"""Qt dialogs for desktop features shared with the existing safe backends."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.action_audit import default_audit
from src.command_catalog import search_command_examples
from src.desktop_settings import AIProfile, AVATAR_PROFILES, DEFAULT_AVATAR_ID, DesktopSettings
from src.file_rag import FileQuestionSession
from src.file_transactions import FileTransactions
from src.plan_interpreter import PlanInterpreter
from src.qt_theme import ACCENT, MUTED
from src.skill_executor import ActionPlan, PlanDenied, SkillCall, SkillExecutor


def _label(text="", role=""):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def _button(text, callback, role=""):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if role:
        widget.setObjectName(role)
    widget.clicked.connect(callback)
    return widget


class PassphraseDialog(QDialog):
    def __init__(self, parent, title, *, confirmation=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Парольная фраза (не короче 12 символов). Восстановить её невозможно."))
        self.passphrase = QLineEdit()
        self.passphrase.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.passphrase)
        self.confirmation = QLineEdit()
        self.confirmation.setEchoMode(QLineEdit.Password)
        self.require_confirmation = confirmation
        if confirmation:
            layout.addWidget(_label("Повтори парольную фразу"))
            layout.addWidget(self.confirmation)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(_button("Отмена", self.reject))
        actions.addWidget(_button("Продолжить", self._accept, "primary"))
        layout.addLayout(actions)

    def _accept(self):
        if self.require_confirmation and self.passphrase.text() != self.confirmation.text():
            QMessageBox.warning(self, "Astra", "Парольные фразы не совпадают")
            return
        self.accept()

    def value(self):
        return self.passphrase.text()


class OnboardingDialog(QDialog):
    OLLAMA_URL = "http://127.0.0.1:11434"
    OLLAMA_MODEL = "qwen3:4b"

    def __init__(self, parent, store=None):
        super().__init__(parent)
        self.store = store or DesktopSettings()
        try:
            self.initial = self.store.load()
        except Exception:
            self.initial = AIProfile(provider="disabled")
        self.saved_profile = None
        self.setWindowTitle("Astra · первый запуск")
        self.setMinimumSize(760, 540)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Добро пожаловать в Astra", "title"))
        layout.addWidget(_label("Три шага. Ничего не сохранится до нажатия «Готово». Микрофон останется выключен.", "muted"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 3)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)

        identity = self.initial.avatar_id if self.initial.avatar_id in AVATAR_PROFILES else DEFAULT_AVATAR_ID
        characters = {key: dict(value) for key, value in self.initial.character_profiles.items()}
        characters.setdefault(identity, {
            "assistant_name": self.initial.assistant_name or AVATAR_PROFILES[identity]["default_name"],
            "voice_id": self.initial.voice_id,
        })
        self.characters = characters
        character = QWidget()
        form = QFormLayout(character)
        self.avatar_choice = QComboBox()
        for key, value in AVATAR_PROFILES.items():
            self.avatar_choice.addItem(value["label"], key)
        self.avatar_choice.setCurrentIndex(self.avatar_choice.findData(identity))
        self.name_edit = QLineEdit(characters[identity]["assistant_name"])
        self.name_edit.setMaxLength(32)
        form.addRow("Образ", self.avatar_choice)
        form.addRow("Имя ассистента", self.name_edit)
        form.addRow(_label("Имя и голос сохраняются отдельно для каждого существующего образа.", "muted"))
        self.pages.addWidget(character)

        ai = QWidget()
        ai_layout = QVBoxLayout(ai)
        ai_layout.addWidget(_label("Искусственный интеллект", "section"))
        self.provider_choice = QComboBox()
        self.provider_choice.addItem("Пока не подключать ИИ · только локальные команды", "disabled")
        self.provider_choice.addItem("Ollama на этом компьютере · без скачивания модели", "ollama")
        self.provider_choice.addItem("Использовать уже настроенные параметры окружения", "env")
        ai_layout.addWidget(self.provider_choice)
        ai_layout.addWidget(_label(f"Локальный адрес: {self.OLLAMA_URL}\nМодель по умолчанию: {self.OLLAMA_MODEL}\n\nМастер не проверяет сервер, не скачивает модели и не обращается к облаку.", "muted"))
        ai_layout.addStretch()
        self.pages.addWidget(ai)

        privacy = QWidget()
        privacy_layout = QVBoxLayout(privacy)
        privacy_layout.addWidget(_label("Запуск и приватность", "section"))
        self.summary = _label("")
        privacy_layout.addWidget(self.summary)
        privacy_layout.addWidget(_label("После сохранения Astra останется в текстовом режиме. Голос включается только отдельной кнопкой в главном окне.", "muted"))
        privacy_layout.addStretch()
        self.pages.addWidget(privacy)

        actions = QHBoxLayout()
        self.back_button = _button("← Назад", lambda: self.show_step(self.pages.currentIndex() - 1))
        self.next_button = _button("Далее →", self.next_step, "primary")
        actions.addWidget(self.back_button)
        actions.addStretch()
        actions.addWidget(_button("Закрыть", self.reject))
        actions.addWidget(self.next_button)
        layout.addLayout(actions)
        self.avatar_choice.currentIndexChanged.connect(self._avatar_changed)
        self.show_step(0)

    def _avatar_changed(self):
        selected = self.avatar_choice.currentData()
        self.characters.setdefault(selected, {
            "assistant_name": AVATAR_PROFILES[selected]["default_name"], "voice_id": "",
        })
        self.name_edit.setText(self.characters[selected]["assistant_name"])

    def show_step(self, index):
        index = max(0, min(2, index))
        self.pages.setCurrentIndex(index)
        self.progress.setValue(index + 1)
        self.back_button.setEnabled(index > 0)
        self.next_button.setText("Готово" if index == 2 else "Далее →")
        if index == 2:
            selected = self.avatar_choice.currentData()
            provider = self.provider_choice.currentData()
            names = {"disabled": "не подключён", "ollama": "Ollama · локально", "env": "настройки окружения"}
            self.summary.setText(f"Персонаж: {self.name_edit.text().strip()} · {AVATAR_PROFILES[selected]['label']}\nИИ: {names[provider]}\nЗапуск: текстовый режим · микрофон выключен")

    def next_step(self):
        if self.pages.currentIndex() == 0:
            try:
                replace(self.initial, assistant_name=self.name_edit.text().strip(), avatar_id=self.avatar_choice.currentData()).validate()
            except ValueError as exc:
                QMessageBox.warning(self, "Astra · имя", str(exc))
                return
        if self.pages.currentIndex() < 2:
            self.show_step(self.pages.currentIndex() + 1)
        else:
            self.finish()

    def finish(self):
        selected = self.avatar_choice.currentData()
        name = self.name_edit.text().strip() or AVATAR_PROFILES[selected]["default_name"]
        provider = self.provider_choice.currentData()
        characters = dict(self.characters)
        characters[selected] = {
            "assistant_name": name,
            "voice_id": characters.get(selected, {}).get("voice_id", ""),
        }
        try:
            profile = replace(
                self.initial, provider=provider,
                model=self.OLLAMA_MODEL if provider == "ollama" else self.initial.model,
                base_url=self.OLLAMA_URL if provider == "ollama" else self.initial.base_url,
                api_key="" if provider in {"disabled", "ollama"} else self.initial.api_key,
                memory_enabled=False, assistant_name=name, avatar_id=selected,
                character_profiles=characters,
            ).validate()
            self.store.save(profile)
        except Exception as exc:
            QMessageBox.warning(self, "Astra · первый запуск", "Не удалось сохранить профиль: " + str(exc))
            return
        self.saved_profile = profile
        self.accept()


class CommandCatalogDialog(QDialog):
    def __init__(self, parent, insert_command):
        super().__init__(parent)
        self.insert_command = insert_command
        self.entries = {}
        self.setWindowTitle("Astra · команды")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Команды Astra", "title"))
        layout.addWidget(_label("Выбранный пример только вставляется в поле чата и не запускается автоматически.", "muted"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию, команде или описанию")
        layout.addWidget(self.search)
        body = QHBoxLayout()
        self.listing = QListWidget()
        body.addWidget(self.listing, 3)
        details = QVBoxLayout()
        self.title = _label("Выбери команду слева", "section")
        self.phrase = _label("")
        self.description = _label("", "muted")
        details.addWidget(self.title)
        details.addWidget(self.phrase)
        details.addWidget(self.description)
        details.addStretch()
        body.addLayout(details, 2)
        layout.addLayout(body, 1)
        self.count = _label("", "muted")
        layout.addWidget(self.count)
        actions = QHBoxLayout()
        actions.addStretch()
        self.insert_button = _button("Вставить в чат", self.insert_selected, "primary")
        self.insert_button.setEnabled(False)
        actions.addWidget(self.insert_button)
        actions.addWidget(_button("Закрыть", self.reject))
        layout.addLayout(actions)
        self.search.textChanged.connect(self.refresh)
        self.listing.currentItemChanged.connect(self.select_item)
        self.listing.itemDoubleClicked.connect(lambda _item: self.insert_selected())
        self.refresh()

    def refresh(self):
        self.listing.clear()
        self.entries.clear()
        matches = search_command_examples(self.search.text())
        for group, example in matches:
            item = QListWidgetItem(f"{group.title} · {example.title}")
            item.setData(Qt.UserRole, example.key)
            self.entries[example.key] = (group, example)
            self.listing.addItem(item)
        self.count.setText(f"Найдено: {len(matches)}")
        self.select_item()

    def select_item(self, *_args):
        item = self.listing.currentItem()
        entry = self.entries.get(item.data(Qt.UserRole)) if item is not None else None
        self.insert_button.setEnabled(entry is not None)
        if entry is None:
            self.title.setText("Выбери команду слева")
            self.phrase.clear()
            self.description.clear()
            return
        _group, example = entry
        self.title.setText(example.title)
        self.phrase.setText(f"«{self.parent().assistant_name}, {example.phrase}»")
        self.description.setText(example.description)

    def insert_selected(self):
        item = self.listing.currentItem()
        entry = self.entries.get(item.data(Qt.UserRole)) if item is not None else None
        if entry is not None:
            phrase = entry[1].phrase
            self.accept()
            self.insert_command(phrase)


class ActionAuditDialog(QDialog):
    OUTCOME_FILTERS = {
        "Все результаты": None, "Передано на исполнение": "dispatch_allowed",
        "Заблокировано": "blocked", "Выполнено": "succeeded",
        "Ошибка": "failed", "Отменено": "cancelled",
    }
    OUTCOME_LABELS = {value: key for key, value in OUTCOME_FILTERS.items() if value}
    ACTION_LABELS = {
        "files.create": "Создание файла", "files.copy": "Копирование файла",
        "files.move": "Перемещение файла", "files.rename": "Переименование файла",
        "files.create_folder": "Создание папки", "files.replace": "Замена файла",
        "files.trash": "Перемещение в корзину", "files.undo": "Отмена изменения",
        "files.recover": "Проверка восстановления", "files.search": "Поиск файлов",
        "files.read_text": "Чтение документа", "get_time": "Текущее время",
        "get_date": "Текущая дата", "open_app": "Открытие приложения",
        "close_app": "Закрытие приложения", "open_url": "Открытие сайта",
        "open_folder": "Открытие папки", "web_search": "Поиск в интернете",
        "keyboard_shortcut": "Сочетание клавиш", "media_control": "Управление музыкой",
        "type_text": "Ввод текста", "screenshot": "Снимок экрана",
        "system_info": "Сведения о системе", "vpn_control": "Управление VPN",
        "window_control": "Управление окном", "voice_feedback": "Голосовой ответ",
        "routine": "Сценарий", "reminder": "Напоминание",
        "clear_dialogue": "Новый диалог", "help": "Справка",
        "ask_llm": "Вопрос ассистенту", "exit": "Завершение работы",
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Astra · журнал действий")
        self.resize(940, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("История действий", "title"))
        layout.addWidget(_label("Текст команд, пути и содержимое файлов не записываются. Передача на исполнение не подтверждает успех действия.", "muted"))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти действие или результат")
        self.outcome = QComboBox()
        self.outcome.addItems(self.OUTCOME_FILTERS)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.outcome)
        layout.addLayout(filters)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("Время", "Действие", "Результат"))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table, 1)
        self.status = _label("", "muted")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addWidget(_button("Очистить историю", self.clear_history))
        actions.addStretch()
        actions.addWidget(_button("Обновить", self.refresh))
        actions.addWidget(_button("Закрыть", self.reject))
        layout.addLayout(actions)
        self.search.textChanged.connect(self.refresh)
        self.outcome.currentTextChanged.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _normalize(value):
        return " ".join(str(value).casefold().replace("ё", "е").split())

    def refresh(self):
        try:
            rows = default_audit().recent(500)
            query = self._normalize(self.search.text())
            outcome = self.OUTCOME_FILTERS[self.outcome.currentText()]
            visible = []
            for created, action, result, _correlation in rows:
                action_label = self.ACTION_LABELS.get(action, action)
                result_label = self.OUTCOME_LABELS.get(result, result)
                if outcome is not None and result != outcome:
                    continue
                if query and query not in self._normalize(f"{action_label} {action} {result_label} {result}"):
                    continue
                visible.append((created, action_label, result_label))
            self.table.setRowCount(len(visible))
            for row, (created, action, result) in enumerate(visible):
                for column, value in enumerate((f"{datetime.fromtimestamp(created):%d.%m %H:%M:%S}", action, result)):
                    self.table.setItem(row, column, QTableWidgetItem(value))
            self.status.setText(f"Показано {len(visible)} из {len(rows)} последних событий")
        except Exception:
            self.status.setText("Не удалось прочитать локальный журнал")

    def clear_history(self):
        if not QMessageBox.question(self, "Очистить историю действий", "Удалить до 5000 локальных записей? Это нельзя отменить.") == QMessageBox.Yes:
            return
        try:
            deleted = default_audit().clear()
            self.refresh()
            self.status.setText(f"История очищена. Удалено записей: {deleted}.")
        except Exception:
            self.status.setText("Не удалось очистить локальную историю")


class FilePreviewDialog(QDialog):
    def __init__(self, parent, relative, value):
        super().__init__(parent)
        self.setWindowTitle("Astra · локальный просмотр · " + relative)
        self.resize(900, 680)
        layout = QVBoxLayout(self)
        if isinstance(value, str):
            layout.addWidget(_label("Документ открыт только для чтения. Содержимое не отправляется в ИИ.", "muted"))
            content = QPlainTextEdit(value)
            content.setReadOnly(True)
            layout.addWidget(content, 1)
        else:
            layout.addWidget(_label(f"{value.image_format} · {value.original_width} × {value.original_height} · локальный preview без метаданных", "muted"))
            image = QLabel()
            pixmap = QPixmap()
            pixmap.loadFromData(value.png, "PNG")
            image.setPixmap(pixmap)
            image.setAlignment(Qt.AlignCenter)
            scroll = QScrollArea()
            scroll.setWidget(image)
            layout.addWidget(scroll, 1)
        layout.addWidget(_button("Закрыть", self.accept))


class FileOperationsDialog(QDialog):
    operation_finished = Signal(bool, str, object)
    OPERATIONS = {
        "create": "Создание файла", "mkdir": "Создание папки",
        "replace": "Замена текста", "copy": "Копирование", "move": "Перемещение / переименование",
    }

    def __init__(self, parent, workspace, transactions=None):
        super().__init__(parent)
        self.workspace = workspace
        self.transactions = transactions or FileTransactions(workspace)
        self.busy = False
        self.setWindowTitle("Astra · файловые операции")
        self.resize(980, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Файловые операции", "title"))
        layout.addWidget(_label(str(workspace.root), "muted"))
        self.write_grant = QCheckBox("Разрешаю создание, копирование, перемещение и замену только в этой папке")
        self.trash_grant = QCheckBox("Отдельно разрешаю отправлять один выбранный файл в Корзину Windows")
        self.write_grant.setChecked(self.transactions.writable)
        self.trash_grant.setChecked(self.transactions.trash_enabled)
        layout.addWidget(self.write_grant)
        layout.addWidget(self.trash_grant)
        self.write_grant.toggled.connect(self.transactions.grant_write)
        self.trash_grant.toggled.connect(self.transactions.grant_trash)
        form = QFormLayout()
        self.source = QLineEdit()
        self.destination = QLineEdit()
        form.addRow("Источник · относительный путь", self.source)
        form.addRow("Назначение · относительный путь", self.destination)
        layout.addLayout(form)
        layout.addWidget(_label("Текст нового содержимого · только для создания или замены", "muted"))
        self.content = QPlainTextEdit()
        self.content.setMaximumHeight(180)
        layout.addWidget(self.content)
        self.history = QListWidget()
        layout.addWidget(self.history, 1)
        self.status = _label("Запись по умолчанию выключена. Каждая операция требует preview и подтверждения.", "muted")
        layout.addWidget(self.status)
        operations = QHBoxLayout()
        for kind, title in self.OPERATIONS.items():
            operations.addWidget(_button(title, lambda _checked=False, value=kind: self.perform(value)))
        operations.addWidget(_button("В Корзину", self.trash_selected))
        layout.addLayout(operations)
        recovery = QHBoxLayout()
        recovery.addWidget(_button("План · симуляция и запуск", self.open_plan))
        recovery.addWidget(_button("Отменить выбранную операцию", self.undo))
        recovery.addWidget(_button("Проверить незавершённую", self.recover))
        recovery.addStretch()
        recovery.addWidget(_button("Закрыть", self.close))
        layout.addLayout(recovery)
        self.operation_finished.connect(self._finished)
        self.refresh_history()

    def refresh_history(self):
        self.history.clear()
        try:
            for record in self.transactions.history():
                item = QListWidgetItem(f"{record['status']} · {record['operation']} → {record['destination']}")
                item.setData(Qt.UserRole, record)
                self.history.addItem(item)
        except Exception as exc:
            self.status.setText(str(exc))

    def _background(self, operation):
        if self.busy:
            return
        self.busy = True
        self.status.setText("Выполняю подтверждённую операцию…")
        def work():
            try:
                result = operation()
            except Exception as exc:
                self.operation_finished.emit(False, str(exc), None)
            else:
                self.operation_finished.emit(True, result, None)
        threading.Thread(target=work, name="astra-qt-file-operation", daemon=True).start()

    def perform(self, kind):
        if self.busy:
            return
        try:
            preview = self.transactions.preview(
                kind,
                self.source.text().strip() if kind in {"copy", "move"} else "",
                self.destination.text().strip(),
                self.content.toPlainText() if kind in {"create", "replace"} else "",
            )
            origin = "новая папка" if kind == "mkdir" else preview.source or "новый текст"
            summary = f"Операция: {self.OPERATIONS[kind]}\nИсточник: {origin}\nНазначение: {preview.destination}\nОбъём: {preview.size} байт\n\nИзменения ограничены выбранной папкой. Выполнить?"
            if QMessageBox.question(self, "Astra · предварительный просмотр", summary) != QMessageBox.Yes:
                self.transactions.discard_preview(preview.token)
                return
            self._background(lambda: "Выполнено · " + self.transactions.execute(preview.token))
        except Exception as exc:
            self.status.setText(str(exc))

    def trash_selected(self):
        try:
            preview = self.transactions.preview("trash", source=self.source.text().strip())
            summary = f"В Корзину Windows будет перемещён файл:\n{preview.source}\nРазмер: {preview.size} байт.\n\nAstra не удаляет его навсегда. Продолжить?"
            if QMessageBox.question(self, "Astra · перемещение в Корзину", summary) != QMessageBox.Yes:
                self.transactions.discard_preview(preview.token)
                return
            self._background(lambda: self.transactions.execute_trash(preview.token))
        except Exception as exc:
            self.status.setText(str(exc))

    def selected_record(self):
        item = self.history.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def undo(self):
        record = self.selected_record()
        if record is None:
            return
        if QMessageBox.question(self, "Восстановление", f"Отменить {record['operation']} → {record['destination']}?\nИзменённый после операции файл не будет перезаписан.") == QMessageBox.Yes:
            self._background(lambda: (self.transactions.undo(record["id"]) or "Операция отменена; созданные данные сохранены в .astra-history"))

    def recover(self):
        record = self.selected_record()
        if record is None:
            return
        if record.get("status") not in {"prepared", "undo_prepared"}:
            self.status.setText("Выбери незавершённую операцию prepared/undo_prepared")
            return
        if QMessageBox.question(self, "Проверка после аварии", "Сверить файлы и обновить только статус журнала? Содержимое не изменится.") == QMessageBox.Yes:
            self._background(lambda: "Состояние проверено: " + self.transactions.recover(record["id"]))

    def _finished(self, ok, message, _unused):
        self.busy = False
        self.status.setText(message)
        if ok:
            self.refresh_history()

    def open_plan(self):
        dialog = FilePlanDialog(self, self.workspace, self.transactions)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def closeEvent(self, event):
        if self.busy:
            self.status.setText("Дождись окончания текущей операции перед закрытием")
            event.ignore()
            return
        self.write_grant.setChecked(False)
        self.trash_grant.setChecked(False)
        self.transactions.grant_write(False)
        self.transactions.grant_trash(False)
        event.accept()

    def reject(self):
        self.close()


class FileQuestionDialog(QDialog):
    result_ready = Signal(object)

    def __init__(self, parent, workspace, relatives):
        super().__init__(parent)
        self.session = FileQuestionSession(workspace, relatives)
        self.generation = 0
        self.cancelled = None
        self.running = False
        self.setWindowTitle("Astra · вопрос по выбранным файлам")
        self.resize(900, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Выбранные файлы:\n" + "\n".join(self.session.relatives), "section"))
        layout.addWidget(_label("Только локальный Ollama. Передаются найденные фрагменты до 5 файлов / 200000 символов. Команды из документов не выполняются.", "muted"))
        self.allowed = QCheckBox("Разрешаю использовать выбранные файлы для локального ответа")
        layout.addWidget(self.allowed)
        self.question = QLineEdit()
        self.question.setMaxLength(1000)
        self.question.setPlaceholderText("Конкретный вопрос словами из документа")
        layout.addWidget(self.question)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        self.status = _label("Разрешение действует только до закрытия окна.", "muted")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addWidget(_button("Спросить по файлам", self.ask, "primary"))
        actions.addWidget(_button("Отменить запрос", self.cancel))
        actions.addStretch()
        actions.addWidget(_button("Закрыть", self.close))
        layout.addLayout(actions)
        self.allowed.toggled.connect(lambda checked: None if checked else self.cancel())
        self.question.returnPressed.connect(self.ask)
        self.result_ready.connect(self._finished)

    def cancel(self):
        self.generation += 1
        if self.cancelled is not None:
            self.cancelled.set()
        self.status.setText("Запрос отменён. Уже переданный локальной модели запрос может завершиться.")

    def ask(self):
        if self.running:
            self.status.setText("Предыдущий локальный запрос ещё завершается")
            return
        if not self.allowed.isChecked():
            self.status.setText("Сначала выдай разрешение на выбранные файлы")
            return
        try:
            profile = DesktopSettings().load()
        except Exception:
            self.status.setText("Не удалось прочитать профиль ИИ")
            return
        question = self.question.text().strip()
        self.generation += 1
        token = self.generation
        cancelled = threading.Event()
        self.cancelled = cancelled
        self.running = True
        self.status.setText("Читаю выбранные файлы и готовлю локальный ответ…")
        def work():
            try:
                result = self.session.answer(question, profile, cancelled)
                self.result_ready.emit((token, True, result))
            except Exception as exc:
                self.result_ready.emit((token, False, str(exc)))
        threading.Thread(target=work, name="astra-qt-file-question", daemon=True).start()

    def _finished(self, message):
        token, ok, value = message
        self.running = False
        self.cancelled = None
        if token != self.generation:
            return
        if not ok:
            self.status.setText(value)
            return
        chunks = [value.text, "Проверенные источники выборки:"]
        for index, passage in enumerate(value.passages, 1):
            chunks.append(f"[{index}] {passage.file} · строки {passage.start_line}–{passage.end_line}\n{passage.text}")
        self.output.setPlainText("\n\n".join(chunks))
        self.status.setText("Ответ локальной модели может ошибаться. Сверь цитаты.")

    def closeEvent(self, event):
        self.session.revoke()
        self.cancel()
        event.accept()

    def reject(self):
        self.close()


class FilePlanDialog(QDialog):
    SKILLS = {
        "Поиск файлов": ("files.search", ("query",), "Слова для поиска"),
        "Чтение документа": ("files.read_text", ("path",), "Относительный путь"),
        "Копирование файла": ("files.copy", ("source", "destination"), "Источник · относительный путь"),
        "Перемещение файла": ("files.move", ("source", "destination"), "Источник · относительный путь"),
        "Переименование файла": ("files.rename", ("source", "destination"), "Файл · относительный путь"),
        "Создание пустой папки": ("files.create_folder", ("path",), "Относительный путь новой папки"),
    }
    STEP_TITLES = {value[0]: key for key, value in SKILLS.items()}
    result_ready = Signal(object)

    def __init__(self, parent, workspace, transactions=None):
        super().__init__(parent)
        from src.action_audit import record_action
        self.executor = SkillExecutor(workspace, transactions, audit=record_action)
        self.transactions = transactions
        self.plan_steps = []
        self.preview_steps = None
        self.generation = 0
        self.worker_running = False
        self.planner_running = False
        self.cancel_event = threading.Event()
        self.setWindowTitle("Astra · план файловой задачи")
        self.resize(940, 780)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("План в выбранной папке", "title"))
        layout.addWidget(_label("До 8 шагов. Симуляция не читает файлы. Изменения требуют временного write grant, точного preview и отдельного подтверждения.", "muted"))
        self.skill = QComboBox()
        self.skill.addItems(self.SKILLS)
        layout.addWidget(self.skill)
        arguments = QHBoxLayout()
        self.argument = QLineEdit()
        self.destination_argument = QLineEdit()
        arguments.addWidget(self.argument)
        arguments.addWidget(self.destination_argument)
        layout.addLayout(arguments)
        self.steps_view = QListWidget()
        self.steps_view.setMaximumHeight(140)
        layout.addWidget(self.steps_view)
        step_actions = QHBoxLayout()
        step_actions.addWidget(_button("Добавить шаг", self.add_step))
        step_actions.addWidget(_button("Удалить выбранный", self.remove_step))
        step_actions.addWidget(_button("Симулировать", self.simulate))
        layout.addLayout(step_actions)
        layout.addWidget(_label("Локальный ИИ · только текст запроса, без содержимого файлов", "section"))
        self.ai_request = QLineEdit()
        self.ai_request.setMaxLength(1500)
        layout.addWidget(self.ai_request)
        self.ai_consent = QCheckBox("Разрешаю передать только этот запрос локальному Ollama")
        layout.addWidget(self.ai_consent)
        self.ai_button = _button("Составить предложение локально", self.propose_plan)
        layout.addWidget(self.ai_button)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        self.status = _label("Добавь шаги и симулируй план", "muted")
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.run_button = _button("Подтвердить и выполнить", self.execute, "primary")
        self.run_button.setEnabled(False)
        controls.addWidget(self.run_button)
        controls.addWidget(_button("Отменить выполнение", self.cancel))
        controls.addStretch()
        controls.addWidget(_button("Закрыть", self.close))
        layout.addLayout(controls)
        self.skill.currentTextChanged.connect(self._skill_changed)
        self.argument.returnPressed.connect(self.add_step)
        self.destination_argument.returnPressed.connect(self.add_step)
        self.result_ready.connect(self._finished)
        self._skill_changed()

    @staticmethod
    def _step_value(step):
        if step.name in {"files.copy", "files.move", "files.rename"}:
            return step.arguments["source"] + " → " + step.arguments["destination"]
        return next(iter(step.arguments.values()))

    def _skill_changed(self):
        _name, keys, hint = self.SKILLS[self.skill.currentText()]
        self.argument.setPlaceholderText(hint)
        self.destination_argument.setVisible(len(keys) == 2)
        self.destination_argument.setPlaceholderText("Назначение · относительный путь")

    def set_output(self, value):
        self.output.setPlainText(value[:100000] + ("\n… показан ограниченный фрагмент" if len(value) > 100000 else ""))

    def invalidate_preview(self):
        self.preview_steps = None
        self.generation += 1
        self.run_button.setEnabled(False)
        self.status.setText("План изменён · симулируй его заново")

    def refresh_steps(self):
        self.steps_view.clear()
        for index, step in enumerate(self.plan_steps, 1):
            self.steps_view.addItem(f"{index}. {self.STEP_TITLES[step.name]}: {self._step_value(step)}")

    def add_step(self):
        if self.planner_running:
            return
        if len(self.plan_steps) >= SkillExecutor.MAX_STEPS:
            self.status.setText("Лимит: не больше 8 шагов")
            return
        skill_name, keys, hint = self.SKILLS[self.skill.currentText()]
        values = [self.argument.text().strip()]
        if len(keys) == 2:
            values.append(self.destination_argument.text().strip())
        if any(not value for value in values):
            self.status.setText("Укажи значение: " + hint.casefold())
            return
        if any(len(value) > 4096 for value in values):
            self.status.setText("Значение шага слишком длинное (максимум 4096 символов)")
            return
        self.plan_steps.append(SkillCall(skill_name, dict(zip(keys, values))))
        self.argument.clear()
        self.destination_argument.clear()
        self.refresh_steps()
        self.invalidate_preview()

    def remove_step(self):
        row = self.steps_view.currentRow()
        if self.planner_running or row < 0:
            return
        del self.plan_steps[row]
        self.refresh_steps()
        self.invalidate_preview()

    def simulate(self):
        try:
            plan = ActionPlan(tuple(self.plan_steps))
            preview = self.executor.simulate(plan, budget_seconds=15)
        except (PlanDenied, ValueError) as exc:
            self.preview_steps = None
            self.run_button.setEnabled(False)
            self.status.setText(str(exc))
            return
        self.preview_steps = tuple(SkillCall(item.name, dict(item.arguments)) for item in self.plan_steps)
        lines = ["ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР · файлы не читались и не изменялись"]
        for index, step in enumerate(preview.steps, 1):
            lines.append(f"{index}. {self.STEP_TITLES[step.name]}: {self._step_value(SkillCall(step.name, dict(step.arguments)))}\n   Требуется: {step.required_capability}")
        lines.extend((f"Лимит времени при запуске: {preview.max_runtime_seconds:g} секунд", "Preview не подтверждает доступ. Запуск потребует отдельного подтверждения."))
        self.set_output("\n\n".join(lines))
        self.status.setText(f"Симуляция готова · шагов: {len(preview.steps)}")
        self.run_button.setEnabled(True)

    def cancel(self):
        if self.worker_running:
            self.cancel_event.set()
            self.status.setText("Отмена запрошена · текущий шаг завершится перед остановкой следующих")

    def propose_plan(self):
        if self.planner_running or self.worker_running:
            return
        if not self.ai_consent.isChecked():
            self.status.setText("Отметь отдельное разрешение на отправку запроса локальному Ollama")
            return
        request = self.ai_request.text().strip()
        if not request:
            self.status.setText("Опиши файловую задачу обычными словами")
            return
        try:
            profile = DesktopSettings().load()
            profile.validate()
            if profile.provider != "ollama":
                raise PlanDenied("Выбери Ollama в настройках ИИ. Запрос не отправлен.")
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.invalidate_preview()
        token = self.generation
        self.planner_running = True
        self.ai_button.setEnabled(False)
        self.status.setText("Передаю только текст запроса локальной модели…")
        def work():
            try:
                result = PlanInterpreter(profile).interpret(request)
                self.result_ready.emit((token, "plan", True, result))
            except Exception as exc:
                self.result_ready.emit((token, "plan", False, str(exc)))
        threading.Thread(target=work, name="astra-qt-local-plan", daemon=True).start()

    def execute(self):
        snapshot = tuple(self.plan_steps)
        if not snapshot or self.preview_steps != snapshot:
            self.status.setText("Сначала симулируй актуальный план")
            self.run_button.setEnabled(False)
            return
        write_tokens = {}
        details = []
        prepared = []
        try:
            for index, step in enumerate(snapshot):
                title = self.STEP_TITLES[step.name]
                if step.name in SkillExecutor.WRITE_SKILLS:
                    if self.transactions is None:
                        raise PlanDenied("Открой операции, включи временное разрешение записи и повтори")
                    operation = SkillExecutor.WRITE_SKILLS[step.name]
                    if step.name == "files.create_folder":
                        preview = self.transactions.preview(operation, destination=step.arguments["path"])
                    else:
                        preview = self.transactions.preview(operation, source=step.arguments["source"], destination=step.arguments["destination"])
                    prepared.append(preview.token)
                    write_tokens[index] = preview.token
                    details.append(f"{index + 1}. {title}\n   Источник: {preview.source}\n   Назначение: {preview.destination}\n   Объём: {preview.size} байт")
                else:
                    details.append(f"{index + 1}. {title}: {self._step_value(step)}")
        except Exception as exc:
            if self.transactions is not None:
                for token in prepared:
                    self.transactions.discard_preview(token)
            self.status.setText(str(exc))
            return
        warning = "Шаги идут по очереди. При ошибке план остановится; изменения можно отменить в журнале."
        if QMessageBox.question(self, "Подтвердить план Astra", "Выполнить только эти шаги?\n\n" + "\n".join(details) + "\n\n" + warning) != QMessageBox.Yes:
            if self.transactions is not None:
                for token in prepared:
                    self.transactions.discard_preview(token)
            self.status.setText("Запуск отменён · файлы не изменены")
            return
        self.generation += 1
        token = self.generation
        self.cancel_event.clear()
        self.worker_running = True
        self.run_button.setEnabled(False)
        self.status.setText("Выполняю разрешённые шаги…")
        def work():
            try:
                result = self.executor.execute(ActionPlan(snapshot), cancel=self.cancel_event, budget_seconds=15, transaction_previews=write_tokens)
                self.result_ready.emit((token, "execute", True, result))
            except Exception as exc:
                self.result_ready.emit((token, "execute", False, str(exc)))
        threading.Thread(target=work, name="astra-qt-plan-execution", daemon=True).start()

    def _finished(self, message):
        token, kind, ok, result = message
        if kind == "plan":
            self.planner_running = False
            self.ai_button.setEnabled(True)
        else:
            self.worker_running = False
        if token != self.generation:
            return
        if kind == "plan":
            if not ok:
                self.status.setText("Локальный планировщик отказал: " + result)
                return
            self.plan_steps[:] = result.steps
            self.refresh_steps()
            self.invalidate_preview()
            self.set_output("Предложение локальной модели · файлы не читались.\nПроверь каждый шаг и запусти симуляцию.")
            self.status.setText(f"Предложено шагов: {len(self.plan_steps)} · проверь список")
            return
        if not ok:
            self.status.setText("План не выполнен: " + result)
            return
        chunks = []
        for item in result:
            if not item.ok:
                chunks.append(f"{item.name}: ошибка · {item.error}")
            elif item.name == "files.search":
                chunks.append(f"Поиск · найдено {len(item.value)} файл(ов):\n" + "\n".join(entry.path for entry in item.value[:100]))
            elif item.name == "files.read_text":
                value = str(item.value)
                chunks.append(f"Чтение · {len(value)} символов:\n{value[:30000]}" + ("\n… результат сокращён" if len(value) > 30000 else ""))
            else:
                chunks.append(str(item.value))
        self.set_output("\n\n".join(chunks))
        failed = sum(not item.ok for item in result)
        self.status.setText("План остановлен: не все шаги выполнены" if failed else "План завершён · проверь результат")
        self.preview_steps = None

    def closeEvent(self, event):
        if self.worker_running:
            self.cancel_event.set()
            self.status.setText("Закрытие после безопасной остановки плана…")
            event.ignore()
            return
        self.cancel_event.set()
        event.accept()

    def reject(self):
        self.close()
