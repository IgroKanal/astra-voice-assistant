"""Small provider adapters for Astra's local and OpenAI-compatible models.

Provider adapters only generate text. They never dispatch desktop actions; the
caller must still validate any structured output through Astra's action policy.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol

from src.ollama_client import OllamaClient


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

    def __init__(self, client: Any, name: str):
        self.client = client
        self.name = name

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
    ) -> str:
        # Deliberately do not include local history or memory in this request.
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _message_content(response)

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
    return OpenAICompatibleProvider(client, settings.llm_provider)
