"""Single capability check before dispatching existing typed runtime actions."""
from dataclasses import dataclass
import math

from src.task_router import ActionType, AssistantAction

ALL_SCOPES = ("apps", "browser", "folders", "media", "windows", "typing", "system", "vpn", "routines", "reminders", "memory", "files", "open_files")
DEFAULT_SCOPES = tuple(scope for scope in ALL_SCOPES if scope not in {"files", "open_files"})
SCOPES = {
    ActionType.OPEN_APP: "apps", ActionType.CLOSE_APP: "apps",
    ActionType.OPEN_URL: "browser", ActionType.WEB_SEARCH: "browser",
    ActionType.OPEN_FOLDER: "folders", ActionType.MEDIA_CONTROL: "media",
    ActionType.WINDOW_CONTROL: "windows", ActionType.TYPE_TEXT: "typing",
    ActionType.SCREENSHOT: "system", ActionType.SYSTEM_INFO: "system",
    ActionType.VPN_CONTROL: "vpn", ActionType.ROUTINE: "routines",
    ActionType.REMINDER: "reminders",
    ActionType.MEMORY_NOTE: "memory",
    ActionType.FILE_SEARCH: "files",
    ActionType.FILE_OPEN: "open_files",
}
ROUTER_ALLOWED = {ActionType.OPEN_APP, ActionType.CLOSE_APP, ActionType.OPEN_URL, ActionType.OPEN_FOLDER, ActionType.WEB_SEARCH, ActionType.GET_TIME, ActionType.GET_DATE, ActionType.HELP, ActionType.ASK_LLM, ActionType.UNKNOWN, ActionType.EMPTY}
TRUSTED_LOCAL = {"local", "local_parser", "pending_followup", "routine"}
BROWSER_KEYS = {"close_tab", "new_tab", "reopen_tab", "next_tab", "previous_tab", "address_bar", "find_on_page", "refresh", "browser_back", "browser_forward", "incognito", "fullscreen", "browser_new_window", "browser_downloads", "browser_history"}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    scope: str = ""


class ActionPolicy:
    def __init__(self, allowed_scopes=DEFAULT_SCOPES):
        self.allowed = frozenset(allowed_scopes)

    def check(self, action: AssistantAction) -> PolicyDecision:
        if not isinstance(action, AssistantAction) or not isinstance(action.type, ActionType):
            return PolicyDecision(False, "Некорректный тип действия")
        for name, limit in (("target", 4096), ("url", 4096), ("query", 8000), ("text", 8000)):
            value = getattr(action, name)
            if not isinstance(value, str) or len(value) > limit:
                return PolicyDecision(False, "Некорректные аргументы действия")
        if not isinstance(action.confidence, (int, float)) or not math.isfinite(action.confidence) or not 0 <= action.confidence <= 1:
            return PolicyDecision(False, "Некорректная уверенность действия")
        if action.source == "llm_router":
            if action.type not in ROUTER_ALLOWED or action.confidence < 0.55:
                return PolicyDecision(False, "Модель не может выполнять это действие")
        scope = SCOPES.get(action.type, "")
        if action.type == ActionType.KEYBOARD_SHORTCUT:
            name = action.target or action.query
            scope = "media" if name.startswith(("media_", "volume_")) else "browser" if name in BROWSER_KEYS else "windows" if name == "show_desktop" else "typing"
        if scope and action.source not in TRUSTED_LOCAL and action.source != "llm_router":
            return PolicyDecision(False, "Недоверенный источник действия", scope)
        if scope and scope not in self.allowed:
            return PolicyDecision(False, "Этот навык отключён в разрешениях Astra", scope)
        if action.type == ActionType.MEDIA_CONTROL and (action.target or action.query).split(":", 1)[0] in {"open_play_local", "shutdown_yandex_music"} and "apps" not in self.allowed:
            return PolicyDecision(False, "Открытие/закрытие приложений отключено в разрешениях Astra", "apps")
        return PolicyDecision(True, scope=scope)
