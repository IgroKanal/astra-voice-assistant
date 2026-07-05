from __future__ import annotations

import ctypes
import logging
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class KeyboardActionResult:
    ok: bool
    message: str


VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_ALT = 0x12

KEYEVENTF_KEYUP = 0x0002

SW_RESTORE = 9

_SHORTCUTS: dict[str, tuple[list[int], int]] = {
    "close_tab": ([VK_CONTROL], ord("W")),
    "new_tab": ([VK_CONTROL], ord("T")),
    "reopen_tab": ([VK_CONTROL, VK_SHIFT], ord("T")),
    "next_tab": ([VK_CONTROL], 0x09),
    "previous_tab": ([VK_CONTROL, VK_SHIFT], 0x09),
    "address_bar": ([VK_CONTROL], ord("L")),
    "find_on_page": ([VK_CONTROL], ord("F")),
    "refresh": ([], 0x74),
    "browser_back": ([VK_ALT], 0x25),
    "browser_forward": ([VK_ALT], 0x27),
    "incognito": ([VK_CONTROL, VK_SHIFT], ord("N")),
    "fullscreen": ([], 0x7A),
    "copy": ([VK_CONTROL], ord("C")),
    "paste": ([VK_CONTROL], ord("V")),
    "select_all": ([VK_CONTROL], ord("A")),
    "save": ([VK_CONTROL], ord("S")),
    "enter": ([], 0x0D),
    "escape": ([], 0x1B),
    "backspace": ([], 0x08),
    "space": ([], 0x20),
    "page_down": ([], 0x22),
    "page_up": ([], 0x21),
    "home": ([], 0x24),
    "end": ([], 0x23),
}

_BROWSER_SHORTCUTS = {
    "close_tab",
    "new_tab",
    "reopen_tab",
    "next_tab",
    "previous_tab",
    "address_bar",
    "find_on_page",
    "refresh",
    "browser_back",
    "browser_forward",
    "incognito",
    "fullscreen",
}

_VOLUME_KEYS = {
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
}

_SHORTCUT_MESSAGES = {
    "close_tab": "Закрываю вкладку.",
    "new_tab": "Открываю новую вкладку.",
    "reopen_tab": "Возвращаю вкладку.",
    "next_tab": "Следующая вкладка.",
    "previous_tab": "Предыдущая вкладка.",
    "address_bar": "Адресная строка.",
    "find_on_page": "Поиск на странице.",
    "refresh": "Обновляю.",
    "browser_back": "Назад.",
    "browser_forward": "Вперёд.",
    "incognito": "Открываю инкогнито.",
    "fullscreen": "Переключаю полный экран.",
    "copy": "Копирую.",
    "paste": "Вставляю.",
    "select_all": "Выделяю.",
    "save": "Сохраняю.",
    "enter": "Нажимаю.",
    "escape": "Нажимаю.",
    "backspace": "Удаляю.",
    "space": "Пробел.",
    "page_down": "Листаю вниз.",
    "page_up": "Листаю вверх.",
    "home": "В начало.",
    "end": "В конец.",
    "volume_up": "Громче.",
    "volume_down": "Тише.",
    "volume_mute": "Переключаю звук.",
}

_TITLE_FALLBACK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "notepad": ("notepad", "блокнот"),
    "telegram": ("telegram", "телеграм"),
    "code": ("visual studio code", "code"),
    "chrome": ("chrome", "google chrome"),
    "msedge": ("edge", "microsoft edge"),
    "firefox": ("firefox", "mozilla firefox"),
    "explorer": ("explorer", "проводник"),
}


class KeyboardController:
    """Безопасные клавиатурные действия для активного окна.

    v0.8.3 hotfix5:
    - targeted typing for Notepad uses title fallback:
      Windows 10/11 Notepad may expose the visible window under another
      process, so searching only ProcessName=notepad is not reliable.
    - shortcuts still use WinAPI, not PowerShell SendKeys.
    - Russian text is inserted through Unicode clipboard + Ctrl+V.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self._configure_ctypes()

    def _configure_ctypes(self) -> None:
        self.kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        self.kernel32.GlobalAlloc.restype = ctypes.c_void_p
        self.kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalLock.restype = ctypes.c_void_p
        self.kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalUnlock.restype = ctypes.c_int
        self.kernel32.GetCurrentThreadId.argtypes = []
        self.kernel32.GetCurrentThreadId.restype = ctypes.c_ulong

        self.user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        self.user32.SetClipboardData.restype = ctypes.c_void_p
        self.user32.GetClipboardData.argtypes = [ctypes.c_uint]
        self.user32.GetClipboardData.restype = ctypes.c_void_p
        self.user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        self.user32.OpenClipboard.restype = ctypes.c_int
        self.user32.CloseClipboard.argtypes = []
        self.user32.CloseClipboard.restype = ctypes.c_int
        self.user32.EmptyClipboard.argtypes = []
        self.user32.EmptyClipboard.restype = ctypes.c_int

        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.user32.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self.user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self.user32.AttachThreadInput.argtypes = [
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
        ]
        self.user32.AttachThreadInput.restype = ctypes.c_int
        self.user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.user32.ShowWindow.restype = ctypes.c_int
        self.user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
        self.user32.BringWindowToTop.restype = ctypes.c_int
        self.user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        self.user32.SetForegroundWindow.restype = ctypes.c_int
        self.user32.SetActiveWindow.argtypes = [ctypes.c_void_p]
        self.user32.SetActiveWindow.restype = ctypes.c_void_p
        self.user32.SetFocus.argtypes = [ctypes.c_void_p]
        self.user32.SetFocus.restype = ctypes.c_void_p

    def send_shortcut(self, name: str) -> KeyboardActionResult:
        if name in _VOLUME_KEYS:
            ok = self._press_virtual_key(_VOLUME_KEYS[name])
            if ok:
                return KeyboardActionResult(True, _SHORTCUT_MESSAGES.get(name, "Готово."))
            return KeyboardActionResult(False, "Не удалось изменить громкость.")

        combo = _SHORTCUTS.get(name)
        if combo is None:
            return KeyboardActionResult(False, "Не знаю такую клавиатурную команду.")

        if name in _BROWSER_SHORTCUTS:
            self.focus_browser_window()
            time.sleep(0.15)

        modifiers, key_code = combo
        ok = self._press_combo(modifiers, key_code)
        if ok:
            return KeyboardActionResult(True, _SHORTCUT_MESSAGES.get(name, "Готово."))

        return KeyboardActionResult(False, "Не удалось выполнить клавиатурную команду.")

    def type_text(self, text: str, app_process_name: str = "") -> KeyboardActionResult:
        text = text.strip()
        if not text:
            return KeyboardActionResult(False, "Что написать?")

        if app_process_name:
            if not self.focus_process(app_process_name):
                return KeyboardActionResult(
                    False,
                    "Не удалось активировать приложение для ввода текста.",
                )
            time.sleep(0.35)

        had_text_clipboard = False
        old_clipboard = ""

        try:
            old_clipboard = self._get_clipboard_text()
            had_text_clipboard = old_clipboard != ""
        except Exception:
            had_text_clipboard = False

        try:
            self._set_clipboard_text(text)
            time.sleep(0.10)
            ok = self._press_combo([VK_CONTROL], ord("V"))
            time.sleep(0.20)

            if had_text_clipboard:
                try:
                    self._set_clipboard_text(old_clipboard)
                except Exception:
                    self.logger.warning("Не удалось восстановить текстовый clipboard.")

            if ok:
                return KeyboardActionResult(True, "Пишу.")

            return KeyboardActionResult(False, "Не удалось напечатать текст.")
        except Exception:
            self.logger.exception("Type text failed")
            return KeyboardActionResult(False, "Не удалось напечатать текст.")

    def focus_browser_window(self) -> bool:
        for process_name in ("msedge", "chrome", "firefox", "browser"):
            if self.focus_process(process_name):
                return True
        return False

    def focus_process(self, process_name: str) -> bool:
        clean = process_name.strip().lower().removesuffix(".exe")
        if not clean:
            return False

        process_info: tuple[int, int] | None = None

        # Give newly opened apps a short window to create MainWindowHandle.
        for _ in range(8):
            process_info = self._find_process_window(clean)
            if process_info is not None:
                break
            time.sleep(0.25)

        if process_info is None:
            self.logger.info("Окно процесса не найдено: %s", clean)
            return False

        pid, hwnd = process_info

        if self._activate_process_by_pid(pid):
            time.sleep(0.15)
            self.logger.info(
                "Focused process by AppActivate: %s pid=%s hwnd=%s",
                clean,
                pid,
                hwnd,
            )
            return True

        if self._force_foreground_window(hwnd):
            time.sleep(0.15)
            self.logger.info(
                "Focused process by WinAPI: %s pid=%s hwnd=%s",
                clean,
                pid,
                hwnd,
            )
            return True

        self.logger.warning(
            "Не удалось сфокусировать окно процесса: %s pid=%s hwnd=%s",
            clean,
            pid,
            hwnd,
        )
        return False

    def _find_process_window(self, process_name: str) -> tuple[int, int] | None:
        safe_name = process_name.replace("'", "''")
        title_keywords = self._title_keywords_for_process(process_name)
        title_conditions = " -or ".join(
            f"$_.MainWindowTitle -like '*{keyword.replace(chr(39), chr(39) + chr(39))}*'"
            for keyword in title_keywords
        )

        # First preference: exact process name. Fallback: visible window title
        # containing app-specific keyword, e.g. "Блокнот" / "Notepad".
        script = f"""
$ErrorActionPreference = 'SilentlyContinue'

$p = Get-Process |
    Where-Object {{
        $_.ProcessName -ieq '{safe_name}' -and
        $_.MainWindowHandle -ne 0
    }} |
    Sort-Object StartTime -Descending |
    Select-Object -First 1

if ($null -eq $p) {{
    $p = Get-Process |
        Where-Object {{
            $_.MainWindowHandle -ne 0 -and
            ({title_conditions})
        }} |
        Sort-Object StartTime -Descending |
        Select-Object -First 1
}}

if ($null -ne $p) {{
    [Console]::Write("$($p.Id)|$($p.MainWindowHandle)")
}}
"""
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            value = (result.stdout or "").strip()
            if not value or "|" not in value:
                return None

            pid_text, hwnd_text = value.split("|", 1)
            return int(pid_text), int(hwnd_text)
        except Exception:
            self.logger.debug("Не удалось найти окно процесса: %s", process_name)
            return None

    def _title_keywords_for_process(self, process_name: str) -> tuple[str, ...]:
        keywords = _TITLE_FALLBACK_KEYWORDS.get(process_name)
        if keywords is not None:
            return keywords

        return (process_name,)

    def _activate_process_by_pid(self, pid: int) -> bool:
        script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$ws = New-Object -ComObject WScript.Shell
$result = $ws.AppActivate([int]{pid})
if ($result) {{ [Console]::Write('1') }} else {{ [Console]::Write('0') }}
"""
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return (result.stdout or "").strip() == "1"
        except Exception:
            return False

    def _force_foreground_window(self, hwnd: int) -> bool:
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
            self.logger.debug("WinAPI focus failed: hwnd=%s", hwnd)
            return False
        finally:
            for source_thread, target_thread in reversed(attached_pairs):
                try:
                    self.user32.AttachThreadInput(source_thread, target_thread, 0)
                except Exception:
                    pass

    def _press_combo(self, modifiers: list[int], key_code: int) -> bool:
        try:
            for modifier in modifiers:
                self._key_down(modifier)
                time.sleep(0.02)

            self._key_down(key_code)
            time.sleep(0.03)
            self._key_up(key_code)

            for modifier in reversed(modifiers):
                time.sleep(0.02)
                self._key_up(modifier)

            return True
        except Exception:
            self.logger.exception(
                "Keyboard combo failed: modifiers=%s key=%s",
                modifiers,
                key_code,
            )
            return False

    def _press_virtual_key(self, key_code: int) -> bool:
        try:
            self._key_down(key_code)
            time.sleep(0.03)
            self._key_up(key_code)
            return True
        except Exception:
            self.logger.exception("Virtual key press failed: %s", key_code)
            return False

    def _key_down(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, 0, 0)

    def _key_up(self, key_code: int) -> None:
        self.user32.keybd_event(key_code, 0, KEYEVENTF_KEYUP, 0)

    def _get_clipboard_text(self) -> str:
        CF_UNICODETEXT = 13

        if not self.user32.OpenClipboard(None):
            raise RuntimeError("OpenClipboard failed")

        pointer = None
        try:
            handle = self.user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""

            pointer = self.kernel32.GlobalLock(handle)
            if not pointer:
                return ""

            return ctypes.wstring_at(pointer)
        finally:
            if pointer:
                self.kernel32.GlobalUnlock(pointer)
            self.user32.CloseClipboard()

    def _set_clipboard_text(self, text: str) -> None:
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        data = text + "\0"
        raw = data.encode("utf-16-le")
        size_bytes = len(raw)

        handle = self.kernel32.GlobalAlloc(GMEM_MOVEABLE, size_bytes)
        if not handle:
            raise RuntimeError("GlobalAlloc failed")

        pointer = self.kernel32.GlobalLock(handle)
        if not pointer:
            raise RuntimeError("GlobalLock failed")

        try:
            ctypes.memmove(pointer, raw, size_bytes)
        finally:
            self.kernel32.GlobalUnlock(handle)

        if not self.user32.OpenClipboard(None):
            raise RuntimeError("OpenClipboard failed")

        try:
            if not self.user32.EmptyClipboard():
                raise RuntimeError("EmptyClipboard failed")

            if not self.user32.SetClipboardData(CF_UNICODETEXT, handle):
                raise RuntimeError("SetClipboardData failed")
            # Windows owns handle after SetClipboardData.
        finally:
            self.user32.CloseClipboard()
