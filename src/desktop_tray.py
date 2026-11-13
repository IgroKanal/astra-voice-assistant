"""Native Windows tray on its own message thread; never calls Tk."""
import queue
import threading
import uuid

import win32api
import win32con
import win32gui


def microphone_tooltip(mode: str, state: str = "") -> str:
    """Return a short, non-content-bearing tray indication for the current mode."""
    if mode != "voice":
        return "Astra · микрофон выключен"
    text = (state or "").casefold()
    if "слушаю" in text:
        activity = "слушает"
    elif "распознаю" in text:
        activity = "распознаёт речь"
    elif "думаю" in text:
        activity = "думает"
    elif "говорю" in text:
        activity = "говорит"
    elif "ошибка" in text:
        activity = "ошибка голосового режима"
    elif "запуск" in text:
        activity = "запускает голосовой режим"
    else:
        activity = "режим включён"
    return "Astra · микрофон включён · " + activity


class DesktopTray:
    CALLBACK = win32con.WM_USER + 21
    DISPATCH = win32con.WM_USER + 22

    def __init__(self, emit):
        self.emit = emit
        self.commands = queue.Queue(maxsize=32)
        self.ready = threading.Event()
        self.thread = None
        self.hwnd = None
        self.error = None
        self.tooltip = "Astra · микрофон выключен"

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="astra-tray", daemon=True)
            self.thread.start()
        if not self.ready.wait(3) or self.error is not None or self.hwnd is None:
            raise RuntimeError("Не удалось создать значок Astra в трее")

    def post(self, kind, value=""):
        if self.hwnd is None:
            return
        try:
            self.commands.put_nowait((kind, value))
            win32gui.PostMessage(self.hwnd, self.DISPATCH, 0, 0)
        except (queue.Full, win32gui.error):
            pass

    def set_tooltip(self, value):
        self.post("tooltip", value[:120])

    def notify(self):
        # Keep personal reminder content off the lock screen/notification center.
        self.post("notify")

    def stop(self):
        if self.hwnd is not None:
            try:
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except win32gui.error:
                pass
        if self.thread is not None:
            self.thread.join(timeout=4)

    def add_icon(self):
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (self.hwnd, 0,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            self.CALLBACK, self.icon, self.tooltip))

    def on_message(self, hwnd, message, wparam, lparam):
        if message == self.taskbar_created:
            self.add_icon()
        elif message == self.CALLBACK:
            if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK, win32con.WM_USER + 5):
                self.emit("tray_show", "")
            elif lparam == win32con.WM_RBUTTONUP:
                menu = win32gui.CreatePopupMenu()
                try:
                    win32gui.AppendMenu(menu, win32con.MF_STRING, 1, "Открыть Astra")
                    voice_on = "микрофон включён" not in self.tooltip.casefold()
                    label = "Включить микрофон" if voice_on else "Выключить микрофон"
                    win32gui.AppendMenu(menu, win32con.MF_STRING, 2, label)
                    win32gui.AppendMenu(menu, win32con.MF_STRING, 3, "Завершить Astra")
                    win32gui.SetForegroundWindow(hwnd)
                    x, y = win32gui.GetCursorPos()
                    choice = win32gui.TrackPopupMenu(menu, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON, x, y, 0, hwnd, None)
                    if choice:
                        if choice == 1:
                            self.emit("tray_show", "")
                        elif choice == 2:
                            self.emit("tray_mode", "voice" if voice_on else "text")
                        elif choice == 3:
                            self.emit("tray_exit", "")
                    win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
                finally:
                    win32gui.DestroyMenu(menu)
        elif message == self.DISPATCH:
            for _ in range(32):
                try:
                    kind, value = self.commands.get_nowait()
                except queue.Empty:
                    break
                if kind == "tooltip":
                    self.tooltip = value
                    win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, (hwnd, 0, win32gui.NIF_TIP, self.CALLBACK, self.icon, self.tooltip))
                elif kind == "notify":
                    win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, (hwnd, 0, win32gui.NIF_INFO,
                        self.CALLBACK, self.icon, self.tooltip, "Есть новое напоминание. Открой Astra.", 8000, "Astra", win32gui.NIIF_INFO))
        elif message == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
        elif message == win32con.WM_DESTROY:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
            win32gui.PostQuitMessage(0)
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def run(self):
        class_name = "AstraTray_" + uuid.uuid4().hex
        instance = win32api.GetModuleHandle(None)
        registered = False
        try:
            self.taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
            self.icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = instance
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = self.on_message
            win32gui.RegisterClass(window_class)
            registered = True
            self.hwnd = win32gui.CreateWindow(class_name, "Astra background notifications", 0, 0, 0, 0, 0, 0, 0, instance, None)
            self.add_icon()
            self.ready.set()
            win32gui.PumpMessages()
        except Exception as exc:
            self.error = exc
            self.ready.set()
            self.emit("tray_error", "Системный трей недоступен. Окно Astra оставлено открытым.")
        finally:
            if self.hwnd is not None and win32gui.IsWindow(self.hwnd):
                win32gui.DestroyWindow(self.hwnd)
            self.hwnd = None
            if registered:
                win32gui.UnregisterClass(class_name, instance)
