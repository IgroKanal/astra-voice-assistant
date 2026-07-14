from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process_name: str
    exe_path: str = ""


@dataclass(frozen=True)
class WindowActionResult:
    ok: bool
    message: str


SW_RESTORE = 9
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
VK_LWIN = 0x5B
KEYEVENTF_KEYUP = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class WindowController:
    """Безопасная работа с открытыми окнами Windows.

    v0.10.2:
    - перечисляет видимые окна;
    - показывает активное окно;
    - переключает фокус на окно по названию приложения/процесса/заголовку;
    - не закрывает окна и не нажимает Alt+F4.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        browser_preferred: str = "",
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.browser_preferred = (browser_preferred or "").strip().lower()
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self._previous_hwnd = 0
        self._configure_ctypes()

    def _configure_ctypes(self) -> None:
        self.user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.user32.EnumWindows.restype = ctypes.c_int
        self.user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        self.user32.IsWindowVisible.restype = ctypes.c_int
        self.user32.IsWindow.argtypes = [ctypes.c_void_p]
        self.user32.IsWindow.restype = ctypes.c_int
        self.user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self.user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.user32.ShowWindow.restype = ctypes.c_int
        self.user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
        self.user32.BringWindowToTop.restype = ctypes.c_int
        self.user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        self.user32.SetForegroundWindow.restype = ctypes.c_int
        self.user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]
        self.user32.AttachThreadInput.restype = ctypes.c_int
        self.user32.SetActiveWindow.argtypes = [ctypes.c_void_p]
        self.user32.SetActiveWindow.restype = ctypes.c_void_p
        self.user32.SetFocus.argtypes = [ctypes.c_void_p]
        self.user32.SetFocus.restype = ctypes.c_void_p
        self.user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ulong, ctypes.c_void_p]
        self.user32.keybd_event.restype = None

        self.kernel32.GetCurrentThreadId.argtypes = []
        self.kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
        self.kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        self.kernel32.OpenProcess.restype = ctypes.c_void_p
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32.CloseHandle.restype = ctypes.c_int
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int

    def describe_open_windows(self, limit: int = 5) -> WindowActionResult:
        windows = self.list_windows()
        if not windows:
            return WindowActionResult(True, "Открытых окон не нашёл.")

        labels = [self._short_window_label(item) for item in windows[:limit]]
        more = "" if len(windows) <= limit else f" И ещё {len(windows) - limit}."
        return WindowActionResult(True, "Открыты: " + ", ".join(labels) + "." + more)

    def describe_active_window(self) -> WindowActionResult:
        info = self.active_window()
        if info is None:
            return WindowActionResult(False, "Активное окно не найдено.")

        return WindowActionResult(True, f"Активное окно: {self._short_window_label(info)}.")

    def minimize_active_window(self) -> WindowActionResult:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return WindowActionResult(False, "Активное окно не найдено.")

        self.user32.ShowWindow(ctypes.c_void_p(hwnd), SW_MINIMIZE)
        return WindowActionResult(True, "Сворачиваю окно.")

    def maximize_active_window(self) -> WindowActionResult:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return WindowActionResult(False, "Активное окно не найдено.")

        self.user32.ShowWindow(ctypes.c_void_p(hwnd), SW_MAXIMIZE)
        return WindowActionResult(True, "Разворачиваю окно.")

    def show_desktop(self) -> WindowActionResult:
        try:
            self.user32.keybd_event(VK_LWIN, 0, 0, None)
            self.user32.keybd_event(ord("D"), 0, 0, None)
            self.user32.keybd_event(ord("D"), 0, KEYEVENTF_KEYUP, None)
            self.user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, None)
            return WindowActionResult(True, "Показываю рабочий стол.")
        except Exception:
            self.logger.exception("Show desktop failed")
            return WindowActionResult(False, "Не удалось показать рабочий стол.")

    def focus_target(self, target: str) -> WindowActionResult:
        target = (target or "").strip()
        if not target:
            return WindowActionResult(False, "На какое окно переключиться?")

        info = self.find_window(target)
        if info is None:
            return WindowActionResult(False, "Не нашёл такое открытое окно.")

        foreground = int(self.user32.GetForegroundWindow() or 0)
        if self._activate_window(info.hwnd):
            if foreground and foreground != info.hwnd:
                self._previous_hwnd = foreground
            self.logger.info(
                "Focused window: target=%r hwnd=%s pid=%s process=%s title=%r",
                target,
                info.hwnd,
                info.pid,
                info.process_name,
                info.title,
            )
            return WindowActionResult(True, f"Переключаюсь на {self._short_window_label(info)}.")

        return WindowActionResult(False, "Не удалось переключиться на окно.")

    def focus_previous_window(self) -> WindowActionResult:
        """Return to the window recorded by the last successful focus action."""
        previous = self._previous_hwnd
        if not previous or not self.user32.IsWindow(ctypes.c_void_p(previous)):
            self._previous_hwnd = 0
            return WindowActionResult(False, "Предыдущее окно пока не запомнено.")

        current = int(self.user32.GetForegroundWindow() or 0)
        if not self._activate_window(previous):
            return WindowActionResult(False, "Не удалось вернуться к предыдущему окну.")

        if current and current != previous:
            self._previous_hwnd = current
        self.logger.info("Focused previous window: hwnd=%s", previous)
        return WindowActionResult(True, "Возвращаю предыдущее окно.")

    def active_window(self) -> WindowInfo | None:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None
        return self._window_info(int(hwnd))

    def list_windows(self) -> list[WindowInfo]:
        hwnds: list[int] = []

        CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if self.user32.IsWindowVisible(hwnd):
                title_len = self.user32.GetWindowTextLengthW(hwnd)
                if title_len > 0:
                    hwnds.append(int(hwnd))
            return True

        self.user32.EnumWindows(CALLBACK(enum_proc), None)

        result: list[WindowInfo] = []
        seen: set[tuple[str, str]] = set()
        for hwnd in hwnds:
            info = self._window_info(hwnd)
            if info is None:
                continue
            if not self._is_useful_window(info):
                continue
            key = (info.process_name.lower(), info.title.lower())
            if key in seen:
                continue
            seen.add(key)
            result.append(info)

        return result

    def find_window(self, target: str) -> WindowInfo | None:
        normalized = self._normalize_target(target)
        aliases = self._target_aliases(normalized)
        windows = self.list_windows()

        # 1. Точные совпадения по process_name.
        for info in windows:
            process = info.process_name.lower()
            if process in aliases:
                return info

        # 2. Вхождение alias в title/process/path.
        for info in windows:
            haystack = " ".join(
                [info.title.lower(), info.process_name.lower(), info.exe_path.lower()]
            )
            if any(alias and alias in haystack for alias in aliases):
                return info

        # 3. Мягкое contains по нормализованному target.
        for info in windows:
            haystack = self._normalize_target(f"{info.process_name} {info.title}")
            if normalized and normalized in haystack:
                return info

        return None

    def _window_info(self, hwnd: int) -> WindowInfo | None:
        title_len = self.user32.GetWindowTextLengthW(hwnd)
        if title_len <= 0:
            return None

        buffer = ctypes.create_unicode_buffer(title_len + 1)
        self.user32.GetWindowTextW(hwnd, buffer, title_len + 1)
        title = buffer.value.strip()
        if not title:
            return None

        pid_value = ctypes.c_ulong(0)
        self.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid_value))
        pid = int(pid_value.value)
        exe_path = self._process_path(pid)
        process_name = Path(exe_path).stem if exe_path else str(pid)

        return WindowInfo(
            hwnd=hwnd,
            title=title,
            pid=pid,
            process_name=process_name,
            exe_path=exe_path,
        )

    def _process_path(self, pid: int) -> str:
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not handle:
            return ""

        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            if not ok:
                return ""
            return buffer.value
        except Exception:
            return ""
        finally:
            self.kernel32.CloseHandle(handle)

    def _activate_window(self, hwnd: int) -> bool:
        hwnd_value = ctypes.c_void_p(hwnd)
        attached_pairs: list[tuple[int, int]] = []

        try:
            foreground_hwnd = self.user32.GetForegroundWindow()
            current_thread = self.kernel32.GetCurrentThreadId()
            target_thread = self.user32.GetWindowThreadProcessId(hwnd_value, None)
            foreground_thread = 0
            if foreground_hwnd:
                foreground_thread = self.user32.GetWindowThreadProcessId(
                    ctypes.c_void_p(foreground_hwnd),
                    None,
                )

            if current_thread and target_thread and current_thread != target_thread:
                if self.user32.AttachThreadInput(current_thread, target_thread, 1):
                    attached_pairs.append((current_thread, target_thread))

            if foreground_thread and target_thread and foreground_thread != target_thread:
                if self.user32.AttachThreadInput(foreground_thread, target_thread, 1):
                    attached_pairs.append((foreground_thread, target_thread))

            self.user32.ShowWindow(hwnd_value, SW_RESTORE)
            self.user32.BringWindowToTop(hwnd_value)
            self.user32.SetActiveWindow(hwnd_value)
            self.user32.SetFocus(hwnd_value)
            return bool(self.user32.SetForegroundWindow(hwnd_value))
        except Exception:
            self.logger.exception("Window focus failed: hwnd=%s", hwnd)
            return False
        finally:
            for source_thread, target_thread in reversed(attached_pairs):
                try:
                    self.user32.AttachThreadInput(source_thread, target_thread, 0)
                except Exception:
                    pass

    def _is_useful_window(self, info: WindowInfo) -> bool:
        title = info.title.strip().lower()
        if title in {"program manager", "windows input experience"}:
            return False
        if info.process_name.lower() in {"shellexperiencehost", "searchapp"}:
            return False
        return True

    def _window_label(self, info: WindowInfo) -> str:
        display = self._display_process_name(info.process_name)
        title = info.title.strip()
        if title and title.lower() != display.lower():
            return f"{display} — {title}"
        return display

    def _short_window_label(self, info: WindowInfo) -> str:
        # Голосовой ответ должен быть коротким. Полные заголовки окон
        # часто содержат название страницы/пути и дают TTS-задержку 10–25 секунд.
        return self._display_process_name(info.process_name)

    def _display_process_name(self, process_name: str) -> str:
        normalized = process_name.strip().lower()
        names = {
            "firefox": "Firefox",
            "chrome": "Chrome",
            "msedge": "Edge",
            "code": "VS Code",
            "telegram": "Telegram",
            "notepad": "Блокнот",
            "explorer": "Проводник",
            "powershell": "PowerShell",
            "windowsterminal": "Windows Terminal",
            "cmd": "Командная строка",
            "amneziawg": "AmneziaWG",
        }
        return names.get(normalized, process_name)

    def _normalize_target(self, value: str) -> str:
        return " ".join(value.lower().replace("ё", "е").split()).strip()

    def _target_aliases(self, target: str) -> set[str]:
        aliases = {target}

        groups = {
            "firefox": {"firefox", "фаерфокс", "файрфокс", "fairfax", "браузер"},
            "chrome": {"chrome", "хром", "google chrome"},
            "msedge": {"edge", "эдж", "microsoft edge"},
            "code": {"vs code", "vscode", "visual studio code", "вс код", "код", "vsco"},
            "telegram": {"telegram", "телеграм", "телега", "тг"},
            "notepad": {"notepad", "блокнот", "bloknot", "блакнот"},
            "explorer": {"explorer", "проводник"},
            "amneziawg": {"amneziawg", "amnezia", "амнезия", "впн", "vpn"},
        }

        if target == "браузер" and self.browser_preferred:
            aliases.add(self.browser_preferred)

        for process, values in groups.items():
            if target in values:
                aliases.add(process)
                aliases.update(values)

        return {item for item in aliases if item}
