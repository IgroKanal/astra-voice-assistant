"""Tk UI for previewing and explicitly running bounded file-only plans."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from src.desktop_settings import DesktopSettings
from src.file_workspace import FileWorkspace
from src.file_transactions import FileTransactions
from src.plan_interpreter import PlanInterpreter
from src.skill_executor import ActionPlan, PlanDenied, SkillCall, SkillExecutor


BG = "#101322"
PANEL = "#191f34"
TEXT = "#e9ecff"
MUTED = "#a2abc9"

SKILLS = {
    "Поиск файлов": ("files.search", ("query",), "Слова для поиска"),
    "Чтение документа": ("files.read_text", ("path",), "Относительный путь"),
    "Копирование файла": ("files.copy", ("source", "destination"), "Относительные пути источника и назначения"),
    "Перемещение файла": ("files.move", ("source", "destination"), "Относительные пути источника и назначения"),
    "Переименование файла": ("files.rename", ("source", "destination"), "Относительные пути файла и нового имени в той же папке"),
    "Создание пустой папки": ("files.create_folder", ("path",), "Относительный путь новой папки"),
}


def _step_title(name: str) -> str:
    return {"files.search": "Поиск файлов", "files.read_text": "Чтение документа",
            "files.copy": "Копирование файла", "files.move": "Перемещение файла",
            "files.rename": "Переименование файла", "files.create_folder": "Создание пустой папки"}.get(name, name)


def _step_value(step: SkillCall) -> str:
    if step.name in {"files.copy", "files.move", "files.rename"}:
        return step.arguments["source"] + " → " + step.arguments["destination"]
    return next(iter(step.arguments.values()))


def open_plan_ui(owner, workspace: FileWorkspace, button, transactions: FileTransactions | None = None):
    from src.action_audit import record_action
    executor = SkillExecutor(workspace, transactions, audit=record_action)
    panel = tk.Toplevel(owner)
    panel.title("Astra · план файловой задачи")
    panel.geometry("820x650")
    panel.minsize(680, 520)
    panel.configure(bg=BG)
    panel.astra_file_busy = [False]

    tk.Label(panel, text="План в выбранной папке", bg=BG, fg=TEXT,
             font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=20, pady=(18, 4))
    tk.Label(panel,
             text="До 8 шагов поиска, чтения, копирования и перемещения. Симуляция не обращается к файлам. "
                  "Изменение файлов и создание папок требуют отдельного разрешения записи, точного preview и подтверждения.",
             bg=BG, fg=MUTED, wraplength=770, justify="left").pack(anchor="w", padx=20, pady=(0, 12))

    form = tk.Frame(panel, bg=BG)
    form.pack(fill="x", padx=20)
    skill = ttk.Combobox(form, state="readonly", values=tuple(SKILLS), width=22)
    skill.set(tuple(SKILLS)[0])
    skill.pack(fill="x")
    fields = tk.Frame(panel, bg=BG)
    fields.pack(fill="x", padx=20, pady=(4, 0))
    source_column = tk.Frame(fields, bg=BG)
    source_column.pack(side="left", fill="x", expand=True, padx=(0, 8))
    argument_label = tk.StringVar(value=SKILLS[skill.get()][2])
    tk.Label(source_column, textvariable=argument_label, bg=BG, fg=MUTED).pack(anchor="w")
    argument = tk.Entry(source_column, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                        relief="flat", font=("Segoe UI", 10))
    argument.pack(fill="x", ipady=8)
    destination_column = tk.Frame(fields, bg=BG)
    destination_column.pack(side="left", fill="x", expand=True)
    tk.Label(destination_column, text="Назначение · относительный путь", bg=BG, fg=MUTED).pack(anchor="w")
    destination_argument = tk.Entry(destination_column, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                                    relief="flat", font=("Segoe UI", 10))
    destination_argument.pack(fill="x", ipady=8)
    destination_column.pack_forget()
    steps_view = tk.Listbox(panel, bg=PANEL, fg=TEXT, selectbackground="#514583",
                            relief="flat", font=("Segoe UI", 10), height=7)
    steps_view.pack(fill="x", padx=20, pady=10)

    plan_steps: list[SkillCall] = []
    preview_steps: tuple[SkillCall, ...] | None = None
    generation = [0]
    mailbox: queue.Queue = queue.Queue(maxsize=4)
    worker_running = threading.Event()
    planner_running = threading.Event()
    cancel_event = threading.Event()
    timer = [None]

    status = tk.StringVar(value="Добавь шаги и симулируй план")
    tk.Label(panel, textvariable=status, bg=BG, fg=MUTED,
             wraplength=770, justify="left").pack(anchor="w", padx=20, pady=(2, 6))
    ai_frame = tk.Frame(panel, bg=PANEL)
    ai_frame.pack(fill="x", padx=20, pady=(0, 8))
    tk.Label(ai_frame, text="Преобразовать запрос в план с локальным ИИ", bg=PANEL, fg=TEXT,
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 3))
    ai_request = tk.Entry(ai_frame, bg=BG, fg=TEXT, insertbackground=TEXT,
                          relief="flat", font=("Segoe UI", 10))
    ai_request.pack(fill="x", padx=10, pady=4, ipady=7)
    ai_consent = tk.BooleanVar(value=False)
    tk.Checkbutton(ai_frame,
                   text="Разрешаю передать только этот запрос локальному Ollama; содержимое файлов не отправляется",
                   variable=ai_consent, bg=PANEL, fg=MUTED, selectcolor=BG,
                   activebackground=PANEL, activeforeground=TEXT, wraplength=740,
                   justify="left").pack(anchor="w", padx=8, pady=(2, 4))
    ai_button = button(ai_frame, "Составить предложение локально", lambda: None)
    ai_button.pack(anchor="w", padx=10, pady=(0, 8))
    output = tk.Text(panel, bg=PANEL, fg=TEXT, wrap="word", relief="flat",
                     font=("Consolas", 10), height=10)
    output.pack(fill="both", expand=True, padx=20, pady=(0, 10))
    output.configure(state="disabled")

    controls = tk.Frame(panel, bg=BG)
    controls.pack(fill="x", padx=20, pady=(0, 16))

    def set_output(value: str):
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", value[:100_000])
        if len(value) > 100_000:
            output.insert("end", "\n… показан ограниченный фрагмент результата")
        output.configure(state="disabled")

    def invalidate_preview():
        nonlocal preview_steps
        preview_steps = None
        generation[0] += 1
        run_button.configure(state="disabled")
        status.set("План изменён · симулируй его заново")

    def add_step():
        if planner_running.is_set():
            status.set("Дождись ответа локального планировщика")
            return
        if len(plan_steps) >= SkillExecutor.MAX_STEPS:
            status.set("Лимит: не больше 8 шагов")
            return
        skill_name, keys, label = SKILLS[skill.get()]
        values = [argument.get().strip()]
        if len(keys) == 2:
            values.append(destination_argument.get().strip())
        if any(not value for value in values):
            status.set(f"Укажи оба относительных пути: {label.lower()}" if len(keys) == 2 else f"Укажи значение: {label.lower()}")
            argument.focus_set()
            return
        if any(len(value) > 4096 for value in values):
            status.set("Значение шага слишком длинное (максимум 4096 символов)")
            return
        plan_steps.append(SkillCall(skill_name, dict(zip(keys, values))))
        steps_view.insert("end", f"{len(plan_steps)}. {_step_title(skill_name)}: {_step_value(plan_steps[-1])}")
        argument.delete(0, "end")
        destination_argument.delete(0, "end")
        invalidate_preview()

    def remove_step():
        if planner_running.is_set():
            status.set("Дождись ответа локального планировщика")
            return
        selection = steps_view.curselection()
        if not selection:
            status.set("Выбери шаг для удаления")
            return
        del plan_steps[selection[0]]
        steps_view.delete(0, "end")
        for index, step in enumerate(plan_steps, 1):
            steps_view.insert("end", f"{index}. {_step_title(step.name)}: {_step_value(step)}")
        invalidate_preview()

    def simulate():
        nonlocal preview_steps
        if planner_running.is_set():
            status.set("Дождись ответа локального планировщика")
            return
        try:
            plan = ActionPlan(tuple(plan_steps))
            preview = executor.simulate(plan, budget_seconds=15)
        except (PlanDenied, ValueError) as exc:
            preview_steps = None
            run_button.configure(state="disabled")
            status.set(str(exc))
            return
        preview_steps = tuple(SkillCall(item.name, dict(item.arguments)) for item in plan_steps)
        lines = ["ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР · файлы не читались и не изменялись"]
        for index, step in enumerate(preview.steps, 1):
            value = _step_value(SkillCall(step.name, dict(step.arguments)))
            action = _step_title(step.name)
            lines.append(f"{index}. {action}: {value}\n   Требуется: {step.required_capability}")
        lines.extend((f"Лимит времени при запуске: {preview.max_runtime_seconds:g} секунд",
                      "Этот preview не подтверждает доступ. Запуск спросит отдельное подтверждение."))
        set_output("\n\n".join(lines))
        status.set(f"Симуляция готова · шагов: {len(preview.steps)} · доступ к файлам не использовался")
        run_button.configure(state="normal")

    def cancel():
        if worker_running.is_set():
            cancel_event.set()
            status.set("Отмена запрошена · текущий шаг завершится перед остановкой следующих шагов")

    def propose_plan():
        if planner_running.is_set() or worker_running.is_set():
            status.set("Сначала дождись завершения текущей операции")
            return
        if not ai_consent.get():
            status.set("Отметь отдельное разрешение на отправку запроса локальному Ollama")
            return
        request = ai_request.get().strip()
        if not request:
            status.set("Опиши файловую задачу обычными словами")
            ai_request.focus_set()
            return
        try:
            profile = DesktopSettings().load()
            profile.validate()
            if profile.provider != "ollama":
                raise PlanDenied("Выбери Ollama в настройках ИИ. Запрос не отправлен.")
        except Exception as exc:
            status.set(str(exc))
            return
        invalidate_preview()
        token = generation[0]
        planner_running.set()
        ai_button.configure(state="disabled")
        status.set("Передаю только текст запроса локальной модели…")

        def work():
            try:
                plan = PlanInterpreter(profile).interpret(request)
                mailbox.put((token, "plan", True, plan))
            except Exception as exc:
                mailbox.put((token, "plan", False, str(exc)))
            finally:
                planner_running.clear()

        threading.Thread(target=work, name="astra-local-plan-interpreter", daemon=True).start()

    def execute():
        nonlocal preview_steps
        snapshot = tuple(plan_steps)
        if not snapshot or preview_steps != snapshot:
            status.set("Сначала симулируй актуальный план")
            run_button.configure(state="disabled")
            return
        write_tokens = {}
        details = []
        prepared = []
        try:
            for index, step in enumerate(snapshot):
                title = _step_title(step.name)
                if step.name in SkillExecutor.WRITE_SKILLS:
                    if transactions is None:
                        raise PlanDenied("Открой операции с файлами, включи временное разрешение записи и повтори")
                    operation = SkillExecutor.WRITE_SKILLS[step.name]
                    if step.name == "files.create_folder":
                        preview = transactions.preview(operation, destination=step.arguments["path"])
                    else:
                        preview = transactions.preview(operation, source=step.arguments["source"],
                                                       destination=step.arguments["destination"])
                    prepared.append(preview.token)
                    write_tokens[index] = preview.token
                    if step.name == "files.create_folder":
                        details.append(f"{index + 1}. {title}\n   Путь: {preview.destination}")
                    else:
                        details.append(f"{index + 1}. {title}\n   Источник: {preview.source}\n"
                                       f"   Назначение: {preview.destination}\n   Объём: {preview.size} байт")
                else:
                    details.append(f"{index + 1}. {title}: {_step_value(step)}")
        except Exception as exc:
            if transactions is not None:
                for token in prepared:
                    transactions.discard_preview(token)
            status.set(str(exc))
            return
        warning = "Шаги идут по очереди. При ошибке план остановится; выполненные изменения можно отдельно отменить в журнале."
        if not messagebox.askyesno("Подтвердить план Astra",
                                   "Выполнить только эти шаги?\n\n" + "\n".join(details) + "\n\n" + warning,
                                   parent=panel):
            if transactions is not None:
                for token in prepared:
                    transactions.discard_preview(token)
            status.set("Запуск отменён · файлы не изменены")
            return
        generation[0] += 1
        token = generation[0]
        cancel_event.clear()
        worker_running.set()
        panel.astra_file_busy[0] = True
        run_button.configure(state="disabled")
        status.set("Выполняю разрешённые шаги…")

        def work():
            try:
                result = executor.execute(ActionPlan(snapshot), cancel=cancel_event, budget_seconds=15,
                                          transaction_previews=write_tokens)
                mailbox.put((token, "execute", True, result))
            except Exception as exc:
                mailbox.put((token, "execute", False, str(exc)))
            finally:
                worker_running.clear()

        threading.Thread(target=work, name="astra-plan-execution", daemon=True).start()

    def drain():
        nonlocal preview_steps
        if not panel.winfo_exists():
            return
        for _ in range(2):
            try:
                token, kind, ok, result = mailbox.get_nowait()
            except queue.Empty:
                break
            if token != generation[0]:
                continue
            if kind == "plan":
                ai_button.configure(state="normal")
                if not ok:
                    status.set("Локальный планировщик отказал: " + result)
                    continue
                plan_steps[:] = result.steps
                steps_view.delete(0, "end")
                for index, step in enumerate(plan_steps, 1):
                    steps_view.insert("end", f"{index}. {_step_title(step.name)}: {_step_value(step)}")
                invalidate_preview()
                set_output("Предложение локальной модели · файлы не читались.\n"
                           "Проверь каждый шаг, затем запусти симуляцию. Для изменений включи отдельное разрешение записи и подтверди точный preview.")
                status.set(f"Предложено шагов: {len(plan_steps)} · проверь список и симулируй план")
                continue
            panel.astra_file_busy[0] = False
            if not ok:
                status.set("План не выполнен: " + result)
                continue
            chunks = []
            for item in result:
                if not item.ok:
                    chunks.append(f"{item.name}: ошибка · {item.error}")
                elif item.name == "files.search":
                    chunks.append(f"Поиск · найдено {len(item.value)} файл(ов):\n" +
                                  "\n".join(entry.path for entry in item.value[:100]))
                elif item.name == "files.read_text":
                    value = str(item.value)
                    chunks.append(f"Чтение · {len(value)} символов:\n{value[:30_000]}" +
                                  ("\n… результат сокращён" if len(value) > 30_000 else ""))
                else:
                    chunks.append(str(item.value))
            set_output("\n\n".join(chunks))
            failed = sum(not item.ok for item in result)
            status.set("План остановлен: не все шаги выполнены" if failed else "План завершён · проверь результат")
            preview_steps = None
        timer[0] = panel.after(80, drain)

    def close():
        if worker_running.is_set():
            cancel_event.set()
            status.set("Закрытие после безопасной остановки плана…")
            panel.after(80, close)
            return
        if timer[0] is not None:
            panel.after_cancel(timer[0])
            timer[0] = None
        panel.destroy()

    row2 = tk.Frame(panel, bg=BG)
    row2.pack(fill="x", padx=20, pady=(0, 8))
    button(row2, "Добавить шаг", add_step).pack(side="left", padx=(0, 6))
    button(row2, "Удалить выбранный", remove_step).pack(side="left", padx=(0, 6))
    button(row2, "Симулировать", simulate).pack(side="left", padx=(0, 6))
    run_button = button(controls, "Подтвердить и выполнить", execute)
    run_button.configure(state="disabled")
    run_button.pack(side="left", padx=(0, 6))
    button(controls, "Отменить", cancel).pack(side="left", padx=(0, 6))
    button(controls, "Закрыть", close).pack(side="right")
    def skill_changed(_event=None):
        argument.delete(0, "end")
        destination_argument.delete(0, "end")
        argument_label.set("Источник · относительный путь" if len(SKILLS[skill.get()][1]) == 2 else SKILLS[skill.get()][2])
        if len(SKILLS[skill.get()][1]) == 2:
            destination_column.pack(side="left", fill="x", expand=True)
        else:
            destination_column.pack_forget()
    skill.bind("<<ComboboxSelected>>", skill_changed)
    panel.protocol("WM_DELETE_WINDOW", close)
    def destroyed(event):
        if event.widget == panel and worker_running.is_set():
            cancel_event.set()
    panel.bind("<Destroy>", destroyed)
    argument.bind("<Return>", lambda _event: (destination_argument.focus_set() if len(SKILLS[skill.get()][1]) == 2 else add_step()))
    destination_argument.bind("<Return>", lambda _event: add_step())
    panel.astra_add_step = add_step
    panel.astra_simulate_plan = simulate
    panel.astra_execute_plan = execute
    panel.astra_skill_selector = skill
    panel.astra_argument_entry = argument
    panel.astra_destination_entry = destination_argument
    panel.astra_plan_output = output
    panel.astra_run_button = run_button
    panel.astra_steps_view = steps_view
    panel.astra_close = close
    panel.astra_ai_request = ai_request
    panel.astra_ai_consent = ai_consent
    panel.astra_propose_plan = propose_plan
    panel.astra_status = status
    ai_button.configure(command=propose_plan)
    drain()
    return panel
