from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import OpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAIError

from src.config_loader import Settings


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    message: str


class AIClient:
    """LLM-клиент через OpenAI-compatible Chat Completions API."""

    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self._client: OpenAI | None = None

        if self._can_create_client():
            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url or None,
                timeout=self.settings.llm_timeout_seconds,
            )

    def _can_create_client(self) -> bool:
        if not self.settings.llm_enabled:
            return False
        if not self.settings.llm_api_key:
            return False
        if self.settings.llm_api_key.startswith("your_"):
            return False
        return True

    def ask(self, question: str) -> LLMResult:
        question = question.strip()
        if not question:
            return LLMResult(False, "Вопрос пустой.")

        if not self.settings.llm_enabled:
            return LLMResult(False, "LLM отключена в настройках.")

        if self._client is None:
            return LLMResult(
                False,
                "LLM API-ключ не настроен. Я могу выполнять локальные команды, но не могу отвечать на вопросы.",
            )

        try:
            self.logger.info("LLM-запрос: provider=%s model=%s", self.settings.llm_provider, self.settings.llm_model)
            response = self._client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self.settings.llm_system_prompt},
                    {"role": "user", "content": question},
                ],
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
            )

            message = response.choices[0].message.content if response.choices else ""
            clean_message = (message or "").strip()
            if not clean_message:
                return LLMResult(False, "Модель вернула пустой ответ.")

            return LLMResult(True, clean_message)
        except APITimeoutError:
            self.logger.exception("LLM timeout")
            return LLMResult(False, "Не удалось получить ответ: превышено время ожидания.")
        except APIConnectionError:
            self.logger.exception("LLM connection error")
            return LLMResult(False, "Не удалось подключиться к LLM. Проверь интернет.")
        except APIStatusError as exc:
            self.logger.exception("LLM API status error")
            return LLMResult(False, f"LLM вернула ошибку API: {exc.status_code}.")
        except OpenAIError:
            self.logger.exception("LLM OpenAI-compatible error")
            return LLMResult(False, "Не удалось получить ответ от LLM.")
        except Exception:
            self.logger.exception("Unexpected LLM error")
            return LLMResult(False, "Произошла непредвиденная ошибка LLM.")
