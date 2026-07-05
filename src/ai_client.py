from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai import OpenAIError

from src.config_loader import AppConfig, Settings
from src.task_router import ActionType, AssistantAction, known_site_aliases


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class RouteResult:
    ok: bool
    action: AssistantAction
    raw_message: str = ""


class AIClient:
    """LLM-клиент через OpenAI-compatible Chat Completions API."""

    _JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
    _THOUGHT_RE = re.compile(r"<thought>.*?</thought>", re.DOTALL | re.IGNORECASE)
    _THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self._client: OpenAI | None = None

        if self._can_create_client():
            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url or None,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=0,
            )

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _can_create_client(self) -> bool:
        if not self.settings.llm_enabled:
            return False
        if not self.settings.llm_api_key:
            return False
        if self.settings.llm_api_key.startswith("your_"):
            return False
        if self.settings.llm_api_key.startswith("PASTE_"):
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
                "LLM API-ключ не настроен. Я могу выполнять локальные команды, "
                "но не могу отвечать на вопросы.",
            )

        system_prompt = self._build_answer_system_prompt()
        last_error_message = "Не удалось получить ответ от LLM."

        for model in self._models_to_try():
            try:
                self.logger.info(
                    "LLM-запрос: provider=%s model=%s",
                    self.settings.llm_provider,
                    model,
                )
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    temperature=self.settings.llm_temperature,
                    max_tokens=self.settings.llm_max_tokens,
                )

                message = response.choices[0].message.content if response.choices else ""
                clean_message = self._clean_llm_answer(message or "")
                if clean_message:
                    return LLMResult(True, clean_message)

                self.logger.warning("LLM модель %s вернула пустой ответ", model)
                last_error_message = "Модель вернула пустой ответ."
            except APITimeoutError:
                self.logger.warning("LLM timeout для модели %s", model, exc_info=True)
                last_error_message = "Не удалось получить ответ: превышено время ожидания."
            except APIConnectionError:
                self.logger.warning("LLM connection error для модели %s", model, exc_info=True)
                last_error_message = "Не удалось подключиться к LLM. Проверь интернет."
            except APIStatusError as exc:
                self.logger.warning(
                    "LLM ошибка модели %s: status=%s",
                    model,
                    exc.status_code,
                    exc_info=True,
                )
                last_error_message = f"LLM вернула ошибку API: {exc.status_code}."
            except OpenAIError:
                self.logger.warning(
                    "LLM OpenAI-compatible error для модели %s",
                    model,
                    exc_info=True,
                )
                last_error_message = "Не удалось получить ответ от LLM."
            except Exception:
                self.logger.warning(
                    "Unexpected LLM error для модели %s",
                    model,
                    exc_info=True,
                )
                last_error_message = "Произошла непредвиденная ошибка LLM."

        return LLMResult(False, last_error_message)

    def route_command(
        self,
        user_text: str,
        apps: dict[str, AppConfig],
    ) -> RouteResult:
        """
        Просит LLM классифицировать команду в безопасный JSON.

        LLM ничего не запускает сама. Она только возвращает намерение.
        """
        if self._client is None:
            return RouteResult(
                ok=False,
                action=AssistantAction(
                    type=ActionType.UNKNOWN,
                    text=user_text,
                    confidence=0.0,
                    source="llm_unavailable",
                    reason="LLM client is not configured.",
                ),
            )

        prompt = self._build_router_prompt(apps)
        last_raw_message = ""

        for model in self._models_to_try():
            try:
                self.logger.info("LLM-router запрос: model=%s text=%s", model, user_text)
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_text},
                    ],
                    temperature=0,
                    max_tokens=500,
                    response_format={"type": "json_object"},
                )
                message = response.choices[0].message.content if response.choices else ""
                raw_message = (message or "").strip()
                last_raw_message = raw_message
                data = self._parse_json_object(raw_message)
                action = self._action_from_router_json(data, user_text)
                return RouteResult(ok=True, action=action, raw_message=raw_message)
            except TypeError:
                self.logger.info(
                    "response_format не поддерживается для %s. Повторяю без него.",
                    model,
                )
                result = self._route_command_without_response_format(
                    user_text=user_text,
                    apps=apps,
                    model=model,
                )
                if result.ok:
                    return result
                last_raw_message = result.raw_message
            except Exception:
                self.logger.warning(
                    "Ошибка LLM-router для модели %s",
                    model,
                    exc_info=True,
                )

        return RouteResult(
            ok=False,
            action=AssistantAction(
                type=ActionType.UNKNOWN,
                text=user_text,
                confidence=0.0,
                source="llm_error",
                reason="LLM router failed.",
            ),
            raw_message=last_raw_message,
        )

    def _route_command_without_response_format(
        self,
        user_text: str,
        apps: dict[str, AppConfig],
        model: str,
    ) -> RouteResult:
        if self._client is None:
            return RouteResult(
                ok=False,
                action=AssistantAction(type=ActionType.UNKNOWN, text=user_text),
            )

        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self._build_router_prompt(apps)},
                    {"role": "user", "content": user_text},
                ],
                temperature=0,
                max_tokens=500,
            )
            message = response.choices[0].message.content if response.choices else ""
            raw_message = (message or "").strip()
            data = self._parse_json_object(raw_message)
            action = self._action_from_router_json(data, user_text)
            return RouteResult(ok=True, action=action, raw_message=raw_message)
        except Exception:
            self.logger.warning(
                "Ошибка LLM-router без response_format для модели %s",
                model,
                exc_info=True,
            )
            return RouteResult(
                ok=False,
                action=AssistantAction(
                    type=ActionType.UNKNOWN,
                    text=user_text,
                    confidence=0.0,
                    source="llm_error",
                    reason="LLM router failed.",
                ),
            )

    def _models_to_try(self) -> list[str]:
        primary = getattr(self.settings, "llm_model", "").strip()
        fallback = getattr(self.settings, "llm_fallback_model", "").strip()

        models: list[str] = []
        for model in (primary, fallback):
            if model and model not in models:
                models.append(model)

        return models or ["gemini-3.5-flash"]

    def _build_answer_system_prompt(self) -> str:
        return (
            f"{self.settings.llm_system_prompt}\n"
            "Отвечай только финальным ответом для пользователя.\n"
            "Запрещено выводить <thought>, <think>, Draft, Option, Analysis, "
            "черновики, внутренние рассуждения, проверки и служебные заметки.\n"
            "Не используй markdown без необходимости.\n"
            "Ответ должен быть законченным, коротким и понятным."
        )

    def _build_router_prompt(self, apps: dict[str, AppConfig]) -> str:
        app_lines = []
        for app in apps.values():
            aliases = ", ".join(app.aliases)
            app_lines.append(f"- {app.name}: {aliases}")

        apps_text = "\n".join(app_lines) if app_lines else "- нет приложений"
        sites_text = ", ".join(known_site_aliases())

        return f"""
Ты строгий JSON-классификатор команд Windows-ассистента.
Верни только один валидный JSON-объект. Никакого markdown, текста, списков и пояснений вне JSON.
Запрещено выводить <thought>, <think>, Draft, Analysis и любые внутренние рассуждения.

Разрешённые action:
open_app, close_app, open_url, open_folder, web_search, get_time, get_date, help, ask_llm, exit, unknown

Список разрешённых приложений:
{apps_text}

Известные сайты:
{sites_text}

Правила безопасности:
1. Для open_app и close_app target должен быть только названием или alias из списка приложений.
2. Если пользователь просит открыть сайт или известный сайт, верни open_url.
3. Если пользователь просит найти информацию, верни web_search.
4. Если пользователь спрашивает время, верни get_time.
5. Если пользователь спрашивает дату или число, верни get_date.
6. Если пользователь просит список возможностей, верни help.
7. Не возвращай keyboard_shortcut, type_text, screenshot или system_info. Эти действия обрабатываются только локальным parser-ом.
8. Если пользователь просит нажать клавиши, написать текст, сделать скриншот или показать статус системы, верни unknown.
9. Если пользователь задаёт обычный вопрос, верни ask_llm и положи вопрос в query.
10. Никогда не возвращай shell, cmd, powershell или произвольные команды ОС.
11. Если уверенность ниже 0.55, верни unknown.

Формат ответа строго такой:
{{"action":"unknown","target":"","query":"","url":"","confidence":0.0,"reason":""}}
""".strip()

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        clean = self._strip_hidden_thoughts(text).strip()
        if not clean:
            raise ValueError("LLM router returned empty message.")

        clean = clean.replace("```json", "```")
        if clean.startswith("```"):
            clean = clean.strip("`").strip()

        balanced = self._extract_balanced_json(clean)
        if balanced:
            clean = balanced
        else:
            match = self._JSON_RE.search(clean)
            if match:
                clean = match.group(0)

        data = json.loads(clean)
        if not isinstance(data, dict):
            raise ValueError("LLM router returned non-object JSON.")
        return data

    def _extract_balanced_json(self, text: str) -> str:
        start = text.find("{")
        if start < 0:
            return ""

        depth = 0
        in_string = False
        escape = False

        for index in range(start, len(text)):
            char = text[index]

            if escape:
                escape = False
                continue

            if char == "\\" and in_string:
                escape = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        return ""

    def _action_from_router_json(
        self,
        data: dict[str, Any],
        original_text: str,
    ) -> AssistantAction:
        action_raw = str(data.get("action", "unknown")).strip().lower()
        try:
            action_type = ActionType(action_raw)
        except ValueError:
            action_type = ActionType.UNKNOWN

        confidence = self._safe_float(data.get("confidence", 0.0))
        return AssistantAction(
            type=action_type,
            text=original_text,
            target=str(data.get("target", "") or "").strip().lower(),
            query=str(data.get("query", "") or "").strip(),
            url=str(data.get("url", "") or "").strip(),
            confidence=confidence,
            source="llm_router",
            reason=str(data.get("reason", "") or "").strip(),
        )

    def _clean_llm_answer(self, text: str) -> str:
        clean = self._strip_hidden_thoughts(text).strip()
        if not clean:
            return ""

        clean = self._remove_draft_sections(clean)
        clean = self._remove_final_answer_labels(clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _strip_hidden_thoughts(self, text: str) -> str:
        clean = text.strip()
        clean = self._THOUGHT_RE.sub("", clean)
        clean = self._THINK_RE.sub("", clean)
        return clean.strip()

    def _remove_draft_sections(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        filtered: list[str] = []

        blocked_starts = (
            "*draft",
            "draft",
            "* draft",
            "option ",
            "*option ",
            "* option ",
            "analysis",
            "reasoning",
            "черновик",
            "вариант ",
            "*вариант ",
            "* вариант ",
        )

        for line in lines:
            normalized = line.strip().lower()
            if normalized.startswith(blocked_starts):
                continue
            filtered.append(line)

        return " ".join(filtered).strip()

    def _remove_final_answer_labels(self, text: str) -> str:
        labels = (
            "final answer:",
            "final:",
            "ответ:",
            "финальный ответ:",
        )
        clean = text.strip()
        lowered = clean.lower()

        for label in labels:
            if lowered.startswith(label):
                return clean[len(label) :].strip()

        return clean

    def _safe_float(self, value: Any) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return 0.0

        return max(0.0, min(1.0, result))
