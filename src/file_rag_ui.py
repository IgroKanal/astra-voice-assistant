"""Explicit selected-file local Q&A. Worker callbacks never retain Tk objects."""
import queue
import threading
import tkinter as tk

from src.desktop_settings import DesktopSettings
from src.file_rag import FileQuestionSession


def open_file_questions(owner, workspace, relative, button):
    session = FileQuestionSession(workspace, relative)
    relatives = session.relatives
    panel = tk.Toplevel(owner)
    panel.title("Astra · вопрос по выбранному файлу" if len(relatives) == 1 else "Astra · вопрос по выбранным файлам")
    panel.geometry("850x650")
    panel.configure(bg="#101322")
    tk.Label(panel, text="Выбранные файлы:\n" + "\n".join(relatives), bg="#101322", fg="#e9ecff", wraplength=790, justify="left").pack(pady=12)
    tk.Label(panel, text="Только локальный Ollama. Передаются найденные фрагменты выбранных документов (до 5 файлов / 200000 символов).\nРазрешение действует до закрытия окна. Команды из документов не выполняются.", bg="#101322", fg="#a2abc9", wraplength=790).pack(pady=8)
    allowed = tk.BooleanVar(value=False)
    tk.Checkbutton(panel, text="Разрешаю использовать выбранные файлы для локального ответа", variable=allowed, bg="#101322", fg="#e9ecff", selectcolor="#191f34", activebackground="#101322", activeforeground="#e9ecff").pack(pady=8)
    entry = tk.Entry(panel, font=("Segoe UI", 12))
    entry.pack(fill="x", padx=20, ipady=8)
    status = tk.StringVar(value="Задай конкретный вопрос словами из документа")
    tk.Label(panel, textvariable=status, bg="#101322", fg="#a2abc9", wraplength=790).pack(pady=8)
    content = tk.Text(panel, bg="#191f34", fg="#e9ecff", font=("Segoe UI", 11), wrap="word", state="disabled")
    content.pack(fill="both", expand=True, padx=20, pady=8)
    mailbox = queue.Queue(maxsize=2)
    active = [None]
    running = threading.Event()
    generation = [0]
    timer = [None]

    def cancel(*_):
        generation[0] += 1
        if active[0] is not None:
            active[0].set()
        status.set("Запрос отменён. Уже переданные локальной модели данные нельзя отозвать из выполняющегося запроса.")

    def ask():
        if running.is_set():
            status.set("Предыдущий локальный запрос ещё завершается. Дождись его остановки.")
            return
        if not allowed.get():
            status.set("Сначала выдай разрешение на выбранные файлы")
            return
        try:
            profile = DesktopSettings().load()
        except Exception:
            status.set("Не удалось прочитать профиль ИИ")
            return
        question = entry.get().strip()
        generation[0] += 1
        token = generation[0]
        cancelled = threading.Event()
        active[0] = cancelled
        running.set()
        status.set("Читаю выбранные файлы и готовлю локальный ответ…")
        def work():
            try:
                result = session.answer(question, profile, cancelled)
                message = (token, True, result)
            except Exception as exc:
                message = (token, False, str(exc))
            finally:
                running.clear()
            try:
                mailbox.put_nowait(message)
            except queue.Full:
                pass
        threading.Thread(target=work, name="astra-file-question", daemon=True).start()

    def drain():
        for _ in range(2):
            try:
                token, ok, value = mailbox.get_nowait()
            except queue.Empty:
                break
            if token != generation[0]:
                continue
            active[0] = None
            if ok:
                content.configure(state="normal")
                content.delete("1.0", "end")
                content.insert("end", value.text + "\n\nПроверенные источники выборки:\n")
                for index, passage in enumerate(value.passages, 1):
                    content.insert("end", f"[{index}] {passage.file} · строки {passage.start_line}–{passage.end_line}\n{passage.text}\n\n")
                content.configure(state="disabled")
                status.set("Ответ локальной модели может ошибаться. Сверь цитаты ниже.")
            else:
                status.set(value)
        timer[0] = panel.after(100, drain)

    def close():
        session.revoke()
        cancel()
        if timer[0] is not None:
            panel.after_cancel(timer[0])
        panel.destroy()

    panel.protocol("WM_DELETE_WINDOW", close)
    # Parent/root destruction also revokes the grant, even without WM_DELETE_WINDOW.
    def destroyed(event):
        if event.widget == panel:
            session.revoke()
            if active[0] is not None:
                active[0].set()
            if timer[0] is not None:
                panel.after_cancel(timer[0])
                timer[0] = None
    panel.bind("<Destroy>", destroyed)
    allowed.trace_add("write", lambda *_: cancel() if not allowed.get() else None)
    actions = tk.Frame(panel, bg="#101322")
    actions.pack(side="bottom", before=content, pady=10)
    button(actions, "Спросить по файлу", ask).pack(side="left", padx=5)
    button(actions, "Отменить запрос", cancel).pack(side="left", padx=5)
    panel.astra_question_session = session
    panel.astra_question_entry = entry
    panel.astra_question_allowed = allowed
    panel.astra_question_content = content
    panel.astra_question_status = status
    panel.astra_ask = ask
    panel.astra_question_allowed_widget = allowed
    drain()
    return panel
