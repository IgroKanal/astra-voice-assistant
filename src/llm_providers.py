"""Small provider adapters for Astra's local and OpenAI-compatible models.

Provider adapters only generate text. They never dispatch desktop actions; the
caller must still validate any structured output through Astra's action policy.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from src.ollama_client import OllamaClient


class UnsupportedConversationModel(ValueError):
    """The configured model has no chat-completions endpoint."""


class ProviderRequestCancelled(RuntimeError):
    """A caller cancelled an in-flight provider response stream."""


class TextProvider(Protocol):
    """The common boundary used by answers and typed command classification."""

    name: str
    is_local: bool

    @property
    def available(self) -> bool: ...

    def answer(
        self,
        *,
        model: str,
        system: str,
        question: str,
        max_tokens: int,
        temperature: float,
        history: list[dict[str, str]] | None = None,
        memory_context: str = "",
        think: bool | None = None,
        timing_callback: Callable[[dict[str, float | None]], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str: ...

    def classify(
        self,
        *,
        model: str,
        system: str,
        request: str,
        response_format: bool = False,
    ) -> str: ...

    def warmup(self, model: str) -> bool: ...


def _message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else ""


class OllamaProvider:
    """Loopback-only provider; never delegates to a remote provider."""

    name = "ollama"
    is_local = True

    def __init__(self, client: OllamaClient):
        self.client = client

    @property
    def available(self) -> bool:
        return True

    def answer(
        self,
        *,
        model: str,
        system: str,
        question: str,
        max_tokens: int,
        temperature: float,
        history: list[dict[str, str]] | None = None,
        memory_context: str = "",
        think: bool | None = None,
        timing_callback: Callable[[dict[str, float | None]], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        arguments = dict(
            max_tokens=max_tokens,
            history=history,
            memory_context=memory_context,
            temperature=temperature,
            think=think,
        )
        if timing_callback is not None:
            arguments["timing_callback"] = timing_callback
        if on_chunk is not None:
            arguments["on_chunk"] = on_chunk
        if cancelled is not None:
            arguments["cancelled"] = cancelled
        return self.client.chat(
            model,
            system,
            question,
            **arguments,
        )

    def classify(
        self,
        *,
        model: str,
        system: str,
        request: str,
        response_format: bool = False,
    ) -> str:
        # The strict JSON requirement is in the system prompt. Ollama gets no
        # conversation, personal memory, or cloud fallback for command routing.
        return self.client.chat(
            model,
            system,
            request,
            max_tokens=500,
            temperature=0,
            think=False,
        )

    def warmup(self, model: str) -> bool:
        return self.client.warmup(model)


class OpenAICompatibleProvider:
    """Adapter for configured cloud or self-hosted OpenAI-compatible APIs."""

    is_local = False

    def __init__(self, client: Any, name: str, base_url: str = "", *, share_dialogue: bool = False):
        self.client = client
        self.name = name
        self.share_dialogue = share_dialogue is True
        try:
            endpoint = urlsplit(base_url)
            self._openrouter = (endpoint.scheme == "https" and endpoint.hostname == "openrouter.ai"
                                and endpoint.port in (None, 443) and endpoint.path.rstrip("/") == "/api/v1"
                                and not endpoint.username and not endpoint.password and not endpoint.query and not endpoint.fragment)
        except ValueError:
            self._openrouter = False

    def _model_options(self, model: str) -> dict:
        if self._openrouter and model == "openai/gpt-6-luna-decisions":
            raise UnsupportedConversationModel("Luna Decisions не предназначена для диалога. Выбери openai/gpt-6-luna.")
        if self._openrouter and model == "openai/gpt-6-luna":
            return {"extra_body": {"reasoning": {"effort": "none"}}}
        return {}

    @property
    def available(self) -> bool:
        return self.client is not None

    def answer(
        self,
        *,
        model: str,
        system: str,
        question: str,
        max_tokens: int,
        temperature: float,
        history: list[dict[str, str]] | None = None,
        memory_context: str = "",
        think: bool | None = None,
        timing_callback: Callable[[dict[str, float | None]], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        # Personal memory is never forwarded. Dialogue is opt-in and comes
        # from a separate, bounded cloud session maintained by AIClient.
        if on_chunk is not None and not callable(on_chunk):
            raise ValueError("Некорректный обработчик потокового ответа")
        if timing_callback is not None and not callable(timing_callback):
            raise ValueError("Некорректный обработчик замеров ответа")
        if cancelled is not None and not callable(cancelled):
            raise ValueError("Некорректный обработчик отмены запроса")

        def is_cancelled() -> bool:
            if cancelled is None:
                return False
            try:
                return bool(cancelled())
            except Exception:
                return True

        if is_cancelled():
            raise ProviderRequestCancelled("Запрос отменён")

        streaming = on_chunk is not None or timing_callback is not None or cancelled is not None
        messages = [{"role": "system", "content": system}]
        if self.share_dialogue and history:
            for item in history[-8:]:
                if (isinstance(item, dict) and set(item) == {"role", "content"}
                        and isinstance(item.get("role"), str)
                        and item.get("role") in {"user", "assistant"}
                        and isinstance(item.get("content"), str)):
                    messages.append({"role": item["role"], "content": item["content"][:2000]})
        messages.append({"role": "user", "content": question})
        arguments = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        arguments.update(self._model_options(model))
        if streaming:
            arguments["stream"] = True

        import time
        started = time.perf_counter()
        first_token_seconds = None
        stream = None
        try:
            response = self.client.chat.completions.create(**arguments)
            if not streaming:
                return _message_content(response)

            stream = response
            content: list[str] = []
            iterator = iter(response)
            truncated = False
            while True:
                if is_cancelled():
                    raise ProviderRequestCancelled("Запрос отменён")
                try:
                    event = next(iterator)
                except StopIteration:
                    if is_cancelled():
                        raise ProviderRequestCancelled("Запрос отменён")
                    break
                # Cancellation may arrive while the iterator waits for a
                # network event. Do not expose a token received after that.
                if is_cancelled():
                    raise ProviderRequestCancelled("Запрос отменён")
                choices = getattr(event, "choices", None) or []
                if not choices:
                    continue
                if getattr(choices[0], "finish_reason", None) == "length":
                    truncated = True
                delta = getattr(choices[0], "delta", None)
                part = getattr(delta, "content", "")
                if not isinstance(part, str) or not part:
                    continue
                content.append(part)
                if first_token_seconds is None:
                    first_token_seconds = time.perf_counter() - started
                if on_chunk is not None:
                    try:
                        on_chunk(part)
                    except Exception:
                        # A playback/UI observer must not abort a valid model response.
                        pass
            if truncated:
                raise ValueError("Облачная модель исчерпала лимит ответа")
            return "".join(content)
        finally:
            if stream is not None and streaming:
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if timing_callback is not None:
                try:
                    timing_callback({
                        "first_token_seconds": first_token_seconds,
                        "elapsed_seconds": time.perf_counter() - started,
                    })
                except Exception:
                    pass

    def classify(
        self,
        *,
        model: str,
        system: str,
        request: str,
        response_format: bool = False,
    ) -> str:
        arguments = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": request},
            ],
            "temperature": 0,
            "max_tokens": 500,
        }
        arguments.update(self._model_options(model))
        if response_format:
            arguments["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(**arguments)
        return _message_content(response)

    def warmup(self, model: str) -> bool:
        return False


class DisabledProvider:
    """Unavailable adapter used when the feature or credentials are disabled."""

    name = "disabled"
    is_local = False

    @property
    def available(self) -> bool:
        return False

    def answer(self, **_kwargs) -> str:
        raise RuntimeError("LLM provider is disabled")

    def classify(self, **_kwargs) -> str:
        raise RuntimeError("LLM provider is disabled")

    def warmup(self, _model: str) -> bool:
        return False


def create_provider(
    settings,
    *,
    openai_factory,
    ollama_factory=OllamaClient,
    can_create_compatible: bool,
) -> TextProvider:
    """Select exactly one configured provider, with no implicit failover."""
    if not settings.llm_enabled:
        return DisabledProvider()
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            ollama_factory(settings.llm_base_url, settings.llm_timeout_seconds)
        )
    if not can_create_compatible:
        return DisabledProvider()
    client = openai_factory(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
    )
    return OpenAICompatibleProvider(client, settings.llm_provider, settings.llm_base_url or "", share_dialogue=getattr(settings, "llm_cloud_dialogue_enabled", False))
