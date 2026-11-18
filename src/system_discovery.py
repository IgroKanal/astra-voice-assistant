"""Read-only discovery of installed Windows browsers for adaptive app routing.

The registry is treated as an inventory source, never as a speech-controlled
command line. Only registered browser executables that exist on disk become
launch candidates; the executable path is taken from Windows and is not
interpolated with user speech.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Callable

from src.config_loader import AppConfig


_APP_PATHS = (
    r"Software\Microsoft\Windows\CurrentVersion\App Paths",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
)
_START_MENU_INTERNET = r"Software\Clients\StartMenuInternet"
_HTTPS_USER_CHOICE = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
_SERVICE_REGISTRY = r"SYSTEM\CurrentControlSet\Services"
_VPN_TUNNEL_PREFIXES = ("amneziawgtunnel$", "wireguardtunnel$")
_COMMAND_INTERPRETERS = frozenset({
    "cmd", "powershell", "pwsh", "wscript", "cscript", "mshta",
    "bash", "sh", "zsh", "wsl", "python", "pythonw", "py", "node",
    "regsvr32", "rundll32", "msiexec", "dotnet", "java", "javaw", "ruby", "perl",
})
_BROWSER_NAMES = {
    "msedge": ("edge", ("microsoft edge", "edge", "msedge")),
    "chrome": ("chrome", ("google chrome", "chrome", "хром")),
    "firefox": ("firefox", ("mozilla firefox", "firefox", "фаерфокс")),
    "brave": ("brave", ("brave browser", "brave")),
    "opera": ("opera", ("opera browser", "opera")),
    "vivaldi": ("vivaldi", ("vivaldi browser", "vivaldi")),
    "yandex": ("yandex", ("yandex browser", "яндекс браузер", "яндекс")),
}


@dataclass(frozen=True)
class BrowserDiscovery:
    """Installed browser launch entries and the OS-selected default browser."""

    apps: dict[str, AppConfig]
    default_browser: str = ""


@dataclass(frozen=True)
class RegisteredApplication:
    """An inventory record, not permission to launch the executable."""
    name: str
    executable: str


def discover_vpn_tunnel_services(*, registry: Any | None = None) -> tuple[str, ...]:
    """List recognised tunnel service names without starting or stopping them."""
    if registry is None:
        if os.name != "nt":
            return ()
        try:
            import winreg as registry
        except ImportError:
            return ()
    root = getattr(registry, "HKEY_LOCAL_MACHINE", None)
    if root is None:
        return ()
    services = _registry_subkeys(registry, root, _SERVICE_REGISTRY, max_entries=8192)
    return tuple(name for name in services
                 if name.casefold().startswith(_VPN_TUNNEL_PREFIXES)
                 and len(name) <= 256 and not any(ord(char) < 32 for char in name))


def discover_registered_applications(*, registry: Any | None = None,
                                     file_exists: Callable[[str], bool] | None = None,
                                     expandvars: Callable[[str], str] = os.path.expandvars,
                                     limit: int = 512) -> tuple[RegisteredApplication, ...]:
    """Read registered App Paths without launching or authorizing anything."""
    if not 1 <= limit <= 2048:
        raise ValueError("Недопустимый размер списка приложений")
    if registry is None:
        if os.name != "nt":
            return ()
        try:
            import winreg as registry
        except ImportError:
            return ()
    if file_exists is None:
        file_exists = lambda value: Path(value).is_file()
    found: dict[str, RegisteredApplication] = {}
    for root_name in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        root = getattr(registry, root_name, None)
        if root is None:
            continue
        for base in _APP_PATHS:
            for key in _registry_subkeys(registry, root, base, max_entries=2048):
                if len(found) >= limit:
                    return tuple(found.values())
                if Path(key).name != key or not key.casefold().endswith('.exe'):
                    continue
                if not re.fullmatch(r'[\w .-]{1,100}\.exe', key, re.IGNORECASE):
                    continue
                raw = _registry_value(registry, root, base + "\\" + key)
                executable = _parse_registered_executable(raw or "", expandvars, app_path=True)
                if not executable:
                    continue
                if Path(executable).stem.casefold() in _COMMAND_INTERPRETERS or Path(key).stem.casefold() in _COMMAND_INTERPRETERS:
                    continue
                try:
                    exists = file_exists(executable)
                except OSError:
                    exists = False
                if exists:
                    found.setdefault(key.casefold(), RegisteredApplication(Path(key).stem, executable))
    return tuple(found.values())


def _close_key(registry: Any, key: Any) -> None:
    try:
        registry.CloseKey(key)
    except OSError:
        pass


def _registry_value(registry: Any, root: Any, key_path: str, name: str = "") -> str | None:
    try:
        key = registry.OpenKey(root, key_path)
    except OSError:
        return None
    try:
        value = registry.QueryValueEx(key, name)[0]
    except OSError:
        return None
    finally:
        _close_key(registry, key)
    return value if isinstance(value, str) else None


def _registry_subkeys(registry: Any, root: Any, key_path: str, max_entries: int = 2048) -> list[str]:
    try:
        key = registry.OpenKey(root, key_path)
    except OSError:
        return []
    names: list[str] = []
    try:
        index = 0
        while index < max_entries:
            try:
                names.append(registry.EnumKey(key, index))
            except OSError:
                break
            index += 1
    finally:
        _close_key(registry, key)
    return names


def _parse_registered_executable(command: str, expandvars: Callable[[str], str] = os.path.expandvars, *, app_path: bool = False) -> str | None:
    """Extract only a quoted or unquoted ``.exe`` token from a registry command."""
    if not isinstance(command, str) or len(command) > 4096:
        return None
    expanded = expandvars(command.strip())
    if app_path and not expanded.startswith('"') and expanded.casefold().endswith('.exe'):
        # App Paths stores an executable path, unlike shell open commands.
        # It is commonly unquoted even when the path contains spaces.
        match = re.fullmatch(r'([^"\r\n]+?\.exe)', expanded, re.IGNORECASE)
    elif expanded.startswith('"'):
        match = re.match(r'^"([^"\r\n]+?\.exe)"(?=\s|$)', expanded, re.IGNORECASE)
    else:
        match = re.match(r'^([^\s"\r\n]+?\.exe)(?=\s|$)', expanded, re.IGNORECASE)
    if match is None:
        return None
    executable = match.group(1).strip()
    if (
        not executable
        or Path(executable).suffix.casefold() != ".exe"
        or not Path(executable).is_absolute()
    ):
        return None
    return executable


def _browser_app(display_name: str, executable: str) -> AppConfig:
    stem = Path(executable).stem.casefold()
    if stem in _BROWSER_NAMES:
        name, known_aliases = _BROWSER_NAMES[stem]
        aliases = set(known_aliases)
    else:
        cleaned = re.sub(r"[^a-z0-9а-яё]+", "_", display_name.casefold()).strip("_")
        name = "browser_" + (cleaned or stem)
        aliases = {display_name.casefold(), stem}
    aliases.update({display_name.casefold(), stem})
    return AppConfig(
        name=name,
        aliases=sorted(alias for alias in aliases if alias),
        open_command=[executable],
        process_name=Path(executable).name,
    )


def discover_windows_browsers(
    *,
    registry: Any | None = None,
    file_exists: Callable[[str], bool] | None = None,
    expandvars: Callable[[str], str] = os.path.expandvars,
) -> BrowserDiscovery:
    """Discover installed browser launchers and the current HTTPS default.

    ``registry``, ``file_exists`` and ``expandvars`` are injectable so registry
    behaviour can be regression-tested without changing a machine's defaults.
    Discovery is read-only and returns an empty result outside Windows.
    """
    if registry is None:
        if os.name != "nt":
            return BrowserDiscovery({})
        try:
            import winreg as registry  # type: ignore[no-redef]
        except ImportError:
            return BrowserDiscovery({})
    if file_exists is None:
        file_exists = lambda value: Path(value).is_file()

    roots = tuple(
        getattr(registry, name)
        for name in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE")
        if hasattr(registry, name)
    )
    apps: dict[str, AppConfig] = {}

    def add_candidate(display_name: str, command: str | None, *, app_path: bool = False) -> None:
        if not command:
            return
        executable = _parse_registered_executable(command, expandvars, app_path=app_path)
        if executable is None:
            return
        if Path(executable).stem.casefold() in _COMMAND_INTERPRETERS:
            return
        try:
            if not file_exists(executable):
                return
        except OSError:
            return
        app = _browser_app(display_name, executable)
        # Per-user registrations appear first and take precedence over the
        # machine-wide registration for the same browser.
        apps.setdefault(app.name, app)

    for root in roots:
        for base in _APP_PATHS:
            for executable_key in _registry_subkeys(registry, root, base):
                stem = Path(executable_key).stem.casefold()
                if stem not in _BROWSER_NAMES:
                    continue
                command = _registry_value(registry, root, base + "\\" + executable_key)
                add_candidate(_BROWSER_NAMES[stem][0], command, app_path=True)

        for client in _registry_subkeys(registry, root, _START_MENU_INTERNET):
            command_key = _START_MENU_INTERNET + "\\" + client + r"\shell\open\command"
            command = _registry_value(registry, root, command_key)
            add_candidate(Path(client).stem, command)

    default_browser = ""
    user_root = getattr(registry, "HKEY_CURRENT_USER", None)
    user_choice = _registry_value(registry, user_root, _HTTPS_USER_CHOICE, "ProgId")
    classes_root = getattr(registry, "HKEY_CLASSES_ROOT", None)
    if user_choice and classes_root is not None:
        command_key = user_choice + r"\shell\open\command"
        command = _registry_value(registry, classes_root, command_key)
        executable = _parse_registered_executable(command or "", expandvars)
        try:
            executable_exists = bool(executable and file_exists(executable))
        except OSError:
            executable_exists = False
        if executable and executable_exists:
            for app in apps.values():
                if os.path.normcase(app.open_command[0]) == os.path.normcase(executable):
                    default_browser = app.name
                    break
            else:
                stem = Path(executable).stem.casefold()
                # An unrecognized protocol handler is not promoted to an
                # executable candidate merely because it owns the registry key.
                if stem in _BROWSER_NAMES:
                    app = _browser_app(_BROWSER_NAMES[stem][0], executable)
                    apps[app.name] = app
                    default_browser = app.name

    if default_browser and default_browser in apps:
        default = apps[default_browser]
        apps[default_browser] = AppConfig(
            name=default.name,
            aliases=sorted(set(default.aliases) | {"браузер", "browser"}),
            open_command=list(default.open_command),
            process_name=default.process_name,
        )
    return BrowserDiscovery(apps, default_browser)


def merge_discovered_browsers(configured_apps: dict[str, AppConfig], discovered: BrowserDiscovery) -> dict[str, AppConfig]:
    """Prefer current OS paths for browsers while preserving other user apps."""
    merged = dict(configured_apps)
    for name, app in discovered.apps.items():
        old = merged.get(name)
        if old is not None:
            app = AppConfig(app.name, sorted(set(app.aliases) | set(old.aliases)), app.open_command, app.process_name)
        merged[name] = app
    return merged


def resolve_browser_preference(
    configured_preference: str,
    override_preference: str,
    discovered: BrowserDiscovery,
) -> str:
    """Choose a present browser, preferring a separate user override.

    Stale preference strings are ignored. The operating-system default is used
    when neither preference names a browser in the live discovery snapshot.
    """
    if not discovered.apps:
        return (override_preference or configured_preference or "").casefold().strip().removesuffix(".exe")
    known_names = set(discovered.apps)
    for app in discovered.apps.values():
        known_names.update(alias.casefold().strip() for alias in app.aliases)
    for candidate in (override_preference, configured_preference, discovered.default_browser):
        clean = (candidate or "").casefold().strip().removesuffix(".exe")
        if clean in known_names:
            for name, app in discovered.apps.items():
                if clean == name.casefold() or clean in {alias.casefold().strip() for alias in app.aliases}:
                    return name
    return ""
