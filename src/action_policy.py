"""Single capability check before dispatching existing typed runtime actions."""
from dataclasses import dataclass
import math

from src.task_router import ActionType, AssistantAction


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Stable, UI-neutral metadata for one user-controlled permission."""

    key: str
    title: str
    description: str
    enabled_by_default: bool


CAPABILITY_CATALOG = (
    CapabilityDescriptor("apps", "Приложения", "Открывать и закрывать приложения из каталога Astra.", True),
    CapabilityDescriptor("browser", "Браузер и сайты", "Открывать сайты и управлять разрешёнными командами браузера.", True),
    CapabilityDescriptor("folders", "Папки", "Открывать папки из списка приложений и пользовательских команд.", True),
    CapabilityDescriptor("media", "Медиа", "Управлять воспроизведением, громкостью и локальным плеером.", True),
    CapabilityDescriptor("windows", "Окна", "Сворачивать, разворачивать и переключать окна.", True),
    CapabilityDescriptor("typing", "Ввод текста и клавиши", "Вводить текст и нажимать разрешённые сочетания клавиш.", True),
    CapabilityDescriptor("system", "Системная информация", "Показывать безопасную информацию о компьютере и делать скриншоты.", True),
    CapabilityDescriptor("vpn", "VPN", "Включать и выключать настроенное VPN-подключение.", True),
    CapabilityDescriptor("routines", "Сценарии", "Запускать сохранённые сценарии из разрешённого набора действий.", True),
    CapabilityDescriptor("reminders", "Напоминания", "Создавать, просматривать и удалять напоминания Astra.", True),
    CapabilityDescriptor("memory", "Личная память", "Сохранять и искать заметки в личной памяти Astra.", True),
    CapabilityDescriptor("files", "Поиск файлов", "Искать файлы только в выбранных папках.", False),
    CapabilityDescriptor("open_files", "Открытие файлов", "Открывать точный файл только внутри выбранной папки.", False),
    CapabilityDescriptor("read_files", "Чтение документов", "Читать выбранные документы локально и с ограничением объёма.", False),
    CapabilityDescriptor("ask_files", "Вопросы по документам", "Передавать выбранные фрагменты только явно выбранной локальной модели.", False),
    CapabilityDescriptor("web_research", "Веб-исследование", "Запрос уходит в Bing, страницы получает только локальная Ollama. Если выбран Edge TTS, текст ответа также обрабатывает сетевой синтезатор; SAPI озвучивает его локально.", False),
)
ALL_SCOPES = tuple(item.key for item in CAPABILITY_CATALOG)
DEFAULT_SCOPES = tuple(item.key for item in CAPABILITY_CATALOG if item.enabled_by_default)
# Runtime capability owned by a newer client integration. Keep it out of the
# legacy desktop settings catalog until that client exposes a dedicated toggle.
INTERNAL_SCOPES = frozenset({"modify_files"})


def capability_catalog() -> tuple[CapabilityDescriptor, ...]:
    """Return immutable permission metadata for desktop permission centers."""
    return CAPABILITY_CATALOG


SCOPES = {
    ActionType.OPEN_APP: "apps", ActionType.CLOSE_APP: "apps",
    ActionType.OPEN_URL: "browser", ActionType.WEB_SEARCH: "browser",
    ActionType.WEB_ANSWER: "web_research",
    ActionType.OPEN_FOLDER: "folders", ActionType.MEDIA_CONTROL: "media",
    ActionType.WINDOW_CONTROL: "windows", ActionType.TYPE_TEXT: "typing",
    ActionType.SCREENSHOT: "system", ActionType.SYSTEM_INFO: "system",
    ActionType.VPN_CONTROL: "vpn", ActionType.ROUTINE: "routines",
    ActionType.REMINDER: "reminders",
    ActionType.MEMORY_NOTE: "memory",
    ActionType.FILE_SEARCH: "files",
    ActionType.FILE_OPEN: "open_files",
    ActionType.FILE_READ: "read_files",
    ActionType.FILE_QUESTION: "ask_files",
    ActionType.FILE_MUTATION: "modify_files",
}
# These built-in requests intentionally have no capability grant: they only
# answer, manage the current conversation, or operate bounded local jobs. Keep
# this set explicit so a newly added ActionType cannot silently inherit access.
SCOPE_FREE_ACTIONS = frozenset({
    ActionType.GET_TIME,
    ActionType.GET_DATE,
    ActionType.VOICE_FEEDBACK,
    ActionType.BACKGROUND_ASK,
    ActionType.BACKGROUND_LIST,
    ActionType.BACKGROUND_CANCEL,
    ActionType.BACKGROUND_RESULT,
    ActionType.CLEAR_DIALOGUE,
    ActionType.HELP,
    ActionType.ASK_LLM,
    ActionType.EXIT,
    ActionType.EMPTY,
    ActionType.UNKNOWN,
})
# The exact scope is derived from the requested shortcut, then checked against
# the ordinary capability grants above.
DYNAMIC_SCOPE_ACTIONS = frozenset({ActionType.KEYBOARD_SHORTCUT})
ROUTER_ALLOWED = {ActionType.OPEN_APP, ActionType.CLOSE_APP, ActionType.OPEN_URL, ActionType.OPEN_FOLDER, ActionType.WEB_SEARCH, ActionType.GET_TIME, ActionType.GET_DATE, ActionType.HELP, ActionType.ASK_LLM, ActionType.UNKNOWN, ActionType.EMPTY}
TRUSTED_LOCAL = {
    "local", "local_parser", "pending_followup", "routine",
    "wake_required_guard", "router_unknown_guard", "conversation_fallback", "fallback",
}
BROWSER_KEYS = {"close_tab", "new_tab", "reopen_tab", "next_tab", "previous_tab", "address_bar", "find_on_page", "refresh", "browser_back", "browser_forward", "incognito", "fullscreen", "browser_new_window", "browser_downloads", "browser_history"}
AUTOMATIC_SAFE_ACTIONS = frozenset({ActionType.WEB_SEARCH, ActionType.SYSTEM_INFO})


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    scope: str = ""
    requires_confirmation: bool = False


def action_requires_confirmation(action: AssistantAction) -> bool:
    """Classify reversible-looking commands that can cause an unwanted state change."""
    if action.type == ActionType.CLOSE_APP:
        target = (action.target or action.query).strip()
        return bool(target and not (target.startswith("__") and target.endswith("__")))
    if action.type == ActionType.VPN_CONTROL:
        return (action.target or action.query).strip().casefold() in {"connect", "disconnect"}
    if action.type == ActionType.MEDIA_CONTROL:
        return (action.target or action.query).split(":", 1)[0].strip().casefold() == "shutdown_yandex_music"
    return False


def action_confirmation_prompt(action: AssistantAction) -> str:
    """Describe the exact high-impact action without speaking arbitrary paths."""
    if action.type == ActionType.CLOSE_APP:
        target = " ".join((action.target or action.query).split())[:64]
        if not target or any(char in target for char in "\\/:"):
            target = "выбранное приложение"
        return f"Подтверди закрытие приложения «{target}». Скажи да или нет."
    if action.type == ActionType.VPN_CONTROL:
        operation = (action.target or action.query).strip().casefold()
        verb = "подключение" if operation == "connect" else "отключение"
        return f"Подтверди {verb} VPN. Скажи да или нет."
    if action.type == ActionType.MEDIA_CONTROL:
        return "Подтверди закрытие Яндекс Музыки. Скажи да или нет."
    return "Подтверди это действие. Скажи да или нет."


class ActionPolicy:
    def __init__(self, allowed_scopes=DEFAULT_SCOPES, *, automatic_safe_actions=False, denied_auto_scopes=()):
        if isinstance(allowed_scopes, (str, bytes)) or not isinstance(
            allowed_scopes, (tuple, list, set, frozenset)
        ):
            raise ValueError("Разрешения должны быть явным списком навыков")
        try:
            self.allowed = frozenset(allowed_scopes)
        except TypeError:
            raise ValueError("Разрешения должны быть простыми именами навыков") from None
        if any(
            not isinstance(scope, str)
            or (scope not in ALL_SCOPES and scope not in INTERNAL_SCOPES)
            for scope in self.allowed
        ):
            raise ValueError("Неизвестное разрешение навыка")
        self.automatic_safe_actions = automatic_safe_actions
        self.denied_auto_scopes = frozenset(denied_auto_scopes)

    def check(self, action: AssistantAction) -> PolicyDecision:
        if not isinstance(action, AssistantAction) or not isinstance(action.type, ActionType):
            return PolicyDecision(False, "Некорректный тип действия")
        if (
            not isinstance(action.source, str)
            or len(action.source) > 64
            or not isinstance(action.reason, str)
            or len(action.reason) > 1000
        ):
            return PolicyDecision(False, "Некорректный источник действия")
        for name, limit in (("target", 4096), ("url", 4096), ("query", 8000), ("text", 8000)):
            value = getattr(action, name)
            if not isinstance(value, str) or len(value) > limit:
                return PolicyDecision(False, "Некорректные аргументы действия")
        if type(action.confidence) not in (int, float) or not math.isfinite(action.confidence) or not 0 <= action.confidence <= 1:
            return PolicyDecision(False, "Некорректная уверенность действия")
        if action.source == "llm_router":
            if action.type not in ROUTER_ALLOWED or action.confidence < 0.55:
                return PolicyDecision(False, "Модель не может выполнять это действие")
        elif action.source not in TRUSTED_LOCAL:
            return PolicyDecision(False, "Недоверенный источник действия")
        scope = SCOPES.get(action.type, "")
        if action.type == ActionType.KEYBOARD_SHORTCUT:
            name = action.target or action.query
            scope = "media" if name.startswith(("media_", "volume_")) else "browser" if name in BROWSER_KEYS else "windows" if name == "show_desktop" else "typing"
        if not scope and action.type not in SCOPE_FREE_ACTIONS:
            return PolicyDecision(False, "Для этого действия не настроено разрешение")
        if scope and action.source not in TRUSTED_LOCAL and action.source != "llm_router":
            return PolicyDecision(False, "Недоверенный источник действия", scope)
        if self.automatic_safe_actions and action.type in AUTOMATIC_SAFE_ACTIONS and scope in self.denied_auto_scopes:
            return PolicyDecision(False, "Это действие отключено пользователем", scope)
        auto_allowed = (self.automatic_safe_actions and action.type in AUTOMATIC_SAFE_ACTIONS
                        and scope not in self.denied_auto_scopes)
        if scope and scope not in self.allowed and not auto_allowed:
            return PolicyDecision(False, "Этот навык отключён в разрешениях Astra", scope)
        if action.type == ActionType.MEDIA_CONTROL and (action.target or action.query).split(":", 1)[0] in {"open_play_local", "shutdown_yandex_music"} and "apps" not in self.allowed:
            return PolicyDecision(False, "Открытие/закрытие приложений отключено в разрешениях Astra", "apps")
        return PolicyDecision(
            True,
            scope=scope,
            requires_confirmation=action_requires_confirmation(action),
        )
