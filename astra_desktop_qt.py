"""Astra Quiet Orbit Qt desktop UI. Runtime and security contracts stay unchanged."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import html
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time

from PySide6.QtCore import QDateTime, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QCloseEvent, QCursor, QGuiApplication, QIcon, QKeySequence,
    QPainter, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFileDialog,
    QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSlider, QSplashScreen, QStackedWidget,
    QSystemTrayIcon, QTextBrowser, QVBoxLayout, QWidget,
)

from src.action_audit import record_action
from src.action_policy import ALL_SCOPES, capability_catalog
from src.desktop_bridge import DesktopBridge
from src.desktop_settings import AIProfile, AVATAR_PROFILES, DEFAULT_AVATAR_ID, DesktopSettings
from src.desktop_tray import microphone_tooltip
from src.file_transactions import FileTransactions
from src.file_workspace import FileWorkspace
from src.onboarding_state import OnboardingState
from src.personal_memory import PersonalMemory
from src.profile_backup import export_profile, import_profile
from src.qt_dialogs import (
    ActionAuditDialog, CommandCatalogDialog, FileOperationsDialog,
    FilePlanDialog, FilePreviewDialog, FileQuestionDialog, OnboardingDialog,
    PassphraseDialog,
)
from src.qt_theme import ACCENT, CYAN, MUTED, STYLE
from src.qt_voice_files import QtVoiceFileController
from src.qt_widgets import CharacterStage, OrbitalLogo
from src.reminders import ReminderStore, ReminderWorker
from src.version import DISPLAY_VERSION

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstraVoiceAssistant"

SCOPE_LABELS = {
    "apps": "Приложения из разрешённого списка", "browser": "Браузер и поиск",
    "folders": "Открытие известных папок", "media": "Медиа и громкость",
    "windows": "Управление окнами", "typing": "Ввод текста и клавиши",
    "system": "Сведения о системе и скриншоты", "vpn": "Заданный VPN",
    "routines": "Пользовательские режимы", "reminders": "Создание напоминаний",
    "memory": "Голосовое управление личными заметками",
    "files": "Поиск файлов в выбранной папке", "open_files": "Открытие файлов голосом",
    "read_files": "Чтение выбранных документов вслух", "ask_files": "Вопросы по выбранным файлам",
}
SCOPE_DESCRIPTIONS = {
    "apps": "Запуск приложений, которые Astra распознаёт по имени.",
    "browser": "Открытие браузера, поиск и переход к запрошенной странице.",
    "folders": "Открытие известных папок Windows и выбранных пользователем папок.",
    "media": "Управление воспроизведением и системной громкостью.",
    "windows": "Сворачивание, разворачивание и переключение окон.",
    "typing": "Ввод подготовленного текста и поддерживаемые сочетания клавиш.",
    "system": "Чтение ограниченных сведений о системе и создание скриншотов.",
    "vpn": "Управление только VPN-подключением, заданным в настройках Astra.",
    "routines": "Запуск пользовательских режимов; каждое действие режима проверяется отдельно.",
    "reminders": "Создание, просмотр и отметка локальных напоминаний.",
    "memory": "Запись, поиск и удаление заметок по голосовой команде; нужен локальный Ollama и включённая личная память.",
    "files": "Поиск только имён в явно выбранной папке; доступ заканчивается при отзыве или закрытии Astra.",
    "open_files": "Открывает одно точное совпадение для безопасного документа или медиа; исполняемые файлы и ссылки запрещены.",
    "read_files": "Озвучивает отрывки поддерживаемых документов локальным Windows SAPI; текст не добавляется в чат.",
    "ask_files": "Передаёт вопрос и ограниченные цитаты только локальному Ollama после явного разрешения.",
}


def card():
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def label(text, role=""):
    widget = QLabel(text)
    widget.setObjectName(role)
    widget.setWordWrap(True)
    return widget


def button(text, callback, role=""):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if role:
        widget.setObjectName(role)
    widget.clicked.connect(callback)
    return widget


def _voice_label(voice):
    name = str(getattr(voice, "name", "Голос Windows"))
    details = []
    languages = getattr(voice, "languages", None) or []
    if languages:
        details.append(" · ".join(str(language) for language in languages))
    gender = str(getattr(voice, "gender", "") or "").strip().lower()
    if gender in {"male", "female"}:
        details.append("мужской" if gender == "male" else "женский")
    return name + (" — " + ", ".join(details) if details else "")


def page_title(title, subtitle):
    layout = QVBoxLayout()
    layout.setSpacing(5)
    layout.addWidget(label(title, "title"))
    layout.addWidget(label(subtitle, "subtitle"))
    return layout


class CharacterFullscreenDialog(QDialog):
    def __init__(self, parent, source_stage):
        super().__init__(parent)
        self.setWindowTitle("Astra · персонаж во весь экран")
        self.setModal(False)
        self.setMinimumSize(480, 640)
        self._source_stage = source_stage
        self.stage = CharacterStage(reduced_motion=source_stage.reduced_motion)
        self.sync_from(source_stage)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        actions = QHBoxLayout()
        actions.addWidget(label("2D-персонаж · Esc — выход из полноэкранного режима", "muted"))
        actions.addStretch(1)
        actions.addWidget(button("Выход · Esc", self.close))
        layout.addLayout(actions)
        layout.addWidget(self.stage, 1)
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(120)
        self.sync_timer.timeout.connect(lambda: self.sync_from(self._source_stage))

    def sync_from(self, source_stage):
        image_path = str(source_stage.image_path)
        speaking_path = str(source_stage.speaking_path) if source_stage.speaking_path else None
        if self.stage.image_path != image_path or self.stage.speaking_path != speaking_path:
            self.stage.reload(image_path, source_stage.name, speaking_path=speaking_path)
        self.stage.reduced_motion = source_stage.reduced_motion
        self.stage.set_state(source_stage.state)

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer.start()

    def done(self, result):
        self.sync_timer.stop()
        super().done(result)

    def closeEvent(self, event):
        self.sync_timer.stop()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class DesktopCharacterWindow(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnBottomHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(360, 610)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.stage = CharacterStage(reduced_motion=owner.profile.reduced_motion, desktop_mode=True, transparent_background=True)
        self.stage.fullscreen_requested.connect(owner.show_character_fullscreen)
        layout.addWidget(self.stage, 1)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            self.move(geometry.right() - self.width() - 28, geometry.bottom() - self.height() - 18)

    def sync_character(self):
        self.stage.reload(self.owner.character.image_path, self.owner.assistant_name, speaking_path=self.owner.character.speaking_path)
        self.stage.reduced_motion = self.owner.character.reduced_motion
        self.stage.set_state(self.owner.character.state)

    def set_state(self, text):
        self.stage.set_state(text)


class AstraQtDesktop(QMainWindow):
    file_results_ready = Signal(object)
    file_preview_ready = Signal(object)
    audio_ready = Signal(object)
    audio_status = Signal(str)
    profile_backup_ready = Signal(object)

    def __init__(self, reminder_store=None):
        super().__init__()
        self.bridge = DesktopBridge(ROOT)
        self.voice_files = QtVoiceFileController(self.bridge)
        self.store = DesktopSettings()
        try:
            self.profile = self.store.load()
        except Exception:
            self.profile = AIProfile()
        self.reminder_store = reminder_store
        self.reminder_worker = None
        if reminder_store is not None:
            self.reminder_worker = ReminderWorker(reminder_store, self.bridge.emit)
            self.reminder_worker.start()
        self.memory = PersonalMemory(LOCAL / "memory.sqlite")
        self.workspace = None
        self.transactions = None
        self.preview_session = None
        self.character_fullscreen = None
        self.desktop_character = None
        self.force_exit = False
        self.tray = None
        self.tray_menu = None
        self.tray_mode_action = None
        self.home_status = None
        self.voice_status = None
        self.busy = False
        self.mode_pending = False
        self.pending_mode = None
        self.pending_texts = []
        self.closing = False
        self.audio_busy = False
        self.file_search_generation = 0
        self.voice_map = {"Системный голос Windows": ""}
        self.microphone_map = {"Системный выбор Windows": None}
        self.character_draft = {key: dict(value) for key, value in self.profile.character_profiles.items()}
        self.onboarding_state = OnboardingState()
        try:
            self.onboarding_available = not self.store.path.exists() and not self.onboarding_state.dismissed()
        except Exception:
            self.onboarding_available = not self.store.path.exists()
        self.onboarding_banner = None
        self.setWindowTitle(f"Astra {DISPLAY_VERSION} · личный ассистент")
        self.setWindowIcon(QIcon(str(ROOT / "assets" / "branding" / "astra.ico")))
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(STYLE)
            if self.profile.ui_scale != 100:
                font = app.font()
                font.setPointSizeF(font.pointSizeF() * self.profile.ui_scale / 100)
                app.setFont(font)
        self.resize(1440 * self.profile.ui_scale // 100, 900 * self.profile.ui_scale // 100)
        self.setMinimumSize(1120 * self.profile.ui_scale // 100, 720 * self.profile.ui_scale // 100)
        self._build()
        self._load_character()
        self.desktop_character = DesktopCharacterWindow(self)
        self.desktop_character.sync_character()
        if QApplication.instance().platformName() != "offscreen":
            self.desktop_character.show()
        self._refresh_reminders()
        self._refresh_memory()
        self._prepare_intro_animation()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll)
        self.poll_timer.start(60)
        self.switch_mode("text")

    @property
    def assistant_name(self):
        avatar = self.profile.avatar_id if self.profile.avatar_id in AVATAR_PROFILES else DEFAULT_AVATAR_ID
        return self.profile.assistant_name or AVATAR_PROFILES[avatar]["default_name"]

    def _prepare_intro_animation(self):
        self._intro_effect = None
        self._intro_opacity = 1.0
        self._intro_started = False
        self._intro_timer = None
        if self.profile.reduced_motion:
            return
        self._intro_effect = QGraphicsOpacityEffect(self)
        self._intro_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._intro_effect)
        self._intro_opacity = 0.0
        self._intro_timer = QTimer(self)
        self._intro_timer.setInterval(16)
        self._intro_timer.timeout.connect(self._intro_tick)

    def _start_intro_animation(self):
        if self._intro_started or self._intro_timer is None:
            return
        self._intro_started = True
        self._intro_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._start_intro_animation()

    def _intro_tick(self):
        self._intro_opacity = min(1.0, self._intro_opacity + 0.075)
        if self._intro_effect is not None:
            self._intro_effect.setOpacity(self._intro_opacity)
        if self._intro_opacity >= 1.0:
            self._intro_timer.stop()
            self.setGraphicsEffect(None)
            self._intro_effect = None

    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.pages = QStackedWidget()
        header = QFrame()
        header.setObjectName("nav")
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 0, 22, 0)
        header_layout.setSpacing(10)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        brand_row.addWidget(OrbitalLogo(ROOT / "assets" / "branding" / "astra.png", 42, self.profile.reduced_motion))
        brand_column = QVBoxLayout()
        brand_column.setSpacing(0)
        brand_column.addWidget(label("Astra", "brand"))
        brand_column.addWidget(label("CORE", "eyebrow"))
        brand_row.addLayout(brand_column)
        header_layout.addLayout(brand_row)
        header_layout.addSpacing(22)
        self.nav_buttons = []
        nav_row = QHBoxLayout()
        nav_row.setSpacing(2)
        for index, title in enumerate(("Голос", "Задачи", "Файлы", "Память", "Настройки")):
            nav_button = button(title, lambda _checked=False, i=index: self.show_page(i), "navButton")
            nav_button.setCheckable(True)
            nav_row.addWidget(nav_button)
            self.nav_buttons.append(nav_button)
        header_layout.addLayout(nav_row)
        header_layout.addStretch(1)
        self.header_save_button = button("Сохранить", self.save_settings, "primary")
        self.header_save_button.setToolTip("Сохранить настройки и применить выбранного персонажа")
        header_layout.addWidget(self.header_save_button)
        tools_button = button("Ещё", self._open_tools_menu)
        tools_button.setToolTip("Команды, журнал, персонаж на весь экран, новый диалог и полный выход")
        header_layout.addWidget(tools_button)
        outer.addWidget(header)
        outer.addWidget(self.pages, 1)
        self.character = CharacterStage(reduced_motion=self.profile.reduced_motion)
        self.character.fullscreen_requested.connect(self.show_character_fullscreen)
        self._build_chat()
        self._build_tasks()
        self._build_files()
        self._build_memory()
        self._build_settings()
        self.show_page(0)

    def add_page(self, title, subtitle):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("page")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(38, 32, 38, 32)
        layout.setSpacing(20)
        layout.addLayout(page_title(title, subtitle))
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        for position, item in enumerate(self.nav_buttons):
            item.setChecked(position == index)
        if index == 1:
            self._refresh_reminders()
        elif index == 3:
            self._refresh_memory()

    def _open_tools_menu(self):
        menu = QMenu(self)
        menu.addAction("Команды", self.open_command_catalog)
        menu.addAction("Журнал действий", self.open_action_audit)
        menu.addAction("Новый диалог", self.new_dialogue)
        desktop_text = "Скрыть персонаж с рабочего стола" if self.desktop_character is not None and self.desktop_character.isVisible() else "Показать персонажа на рабочем столе"
        menu.addAction(desktop_text, self.toggle_desktop_character)
        menu.addAction("Персонаж на весь экран", self.show_character_fullscreen)
        menu.addSeparator()
        menu.addAction("Мастер первого запуска", self.open_onboarding)
        menu.addAction("Полностью выйти", self.exit_application)
        menu.exec(QCursor.pos())

    def _build_chat(self):
        layout = self.add_page("Голос", "Голос — главный канал, текст остаётся резервным. Микрофон не включается сам.")
        voice_card = card()
        voice_layout = QHBoxLayout(voice_card)
        voice_layout.setContentsMargins(26, 22, 26, 22)
        voice_layout.setSpacing(22)
        self.voice_logo = OrbitalLogo(ROOT / "assets" / "branding" / "astra.png", 96, self.profile.reduced_motion)
        voice_layout.addWidget(self.voice_logo)
        voice_copy = QVBoxLayout()
        voice_copy.addWidget(label("ЛИЧНЫЙ ГОЛОСОВОЙ АССИСТЕНТ", "eyebrow"))
        voice_copy.addWidget(label(self.assistant_name, "section"))
        self.home_status = label("Микрофон выключен · готова к диалогу", "status")
        voice_copy.addWidget(self.home_status)
        voice_copy.addStretch(1)
        voice_layout.addLayout(voice_copy, 1)
        self.voice_button = button("Начать голосовой сеанс", self.toggle_voice_mode, "voice")
        self.voice_button.setMinimumHeight(68)
        self.voice_button.setMinimumWidth(260)
        self.voice_button.setToolTip("Включить или выключить голосовой диалог")
        voice_layout.addWidget(self.voice_button)
        layout.addWidget(voice_card)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.setUndoRedoEnabled(True)
        layout.addWidget(self.chat, 1)
        self.chat.append(f"<span style='color:{CYAN};font-weight:600'>{html.escape(self.assistant_name)}</span><br>Я рядом. Включи голосовой сеанс или напиши сообщение.<br><br>")
        composer = QHBoxLayout()
        composer.setSpacing(10)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Напиши Astra…")
        self.entry.returnPressed.connect(self.send_text)
        composer.addWidget(self.entry, 1)
        composer.addWidget(button("Отправить", self.send_text, "primary"))
        self.cancel_response_button = button("Остановить", self.cancel_response, "secondary")
        self.cancel_response_button.setToolTip("Остановить текущий запрос к ИИ")
        self.cancel_response_button.setVisible(False)
        composer.addWidget(self.cancel_response_button)
        layout.addLayout(composer)
        self.voice_status = label(self.home_status.text(), "status")
        self.chat_copy = QAction("Копировать", self)
        self.chat_copy.setShortcut(QKeySequence.Copy)
        self.chat_copy.triggered.connect(self.chat.copy)
        self.addAction(self.chat_copy)
        self.focus_chat = QAction(self)
        self.focus_chat.setShortcut(QKeySequence("Ctrl+K"))
        self.focus_chat.triggered.connect(lambda: (self.show_page(0), self.entry.setFocus()))
        self.addAction(self.focus_chat)

    def _build_tasks(self):
        layout = self.add_page("Напоминания", "Один компактный список для задач с временем. Действия применяются к выбранной строке.")
        form = card()
        form_layout = QGridLayout(form)
        form_layout.setContentsMargins(18, 16, 18, 16)
        form_layout.setSpacing(10)
        self.reminder_text = QLineEdit()
        self.reminder_text.setPlaceholderText("Что напомнить?")
        self.reminder_due = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.reminder_due.setDisplayFormat("dd.MM.yyyy  HH:mm")
        self.reminder_due.setCalendarPopup(True)
        form_layout.addWidget(self.reminder_text, 0, 0)
        form_layout.addWidget(self.reminder_due, 0, 1)
        add_button = button("Добавить", self.add_reminder, "primary")
        add_button.setFixedHeight(44)
        form_layout.addWidget(add_button, 0, 2)
        form_layout.setColumnStretch(0, 5)
        form_layout.setColumnStretch(1, 2)
        layout.addWidget(form)
        self.reminders_list = QListWidget()
        layout.addWidget(self.reminders_list, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for text, callback in (("Отменить", self.cancel_reminder), ("Прочитано", self.complete_reminder), ("Экспорт", self.export_reminders), ("Импорт", self.import_reminders)):
            action = button(text, callback)
            action.setFixedSize(138, 38)
            actions.addWidget(action)
        actions.addStretch(1)
        layout.addLayout(actions)

    def _build_files(self):
        layout = self.add_page("Файлы", "Доступ только к явно выбранной папке. Права записи и Корзины выдаются отдельно и временно.")
        row = QHBoxLayout()
        row.addWidget(button("Выбрать папку", self.choose_workspace, "primary"))
        row.addWidget(button("Отозвать доступ", self.close_workspace))
        self.workspace_label = label("Папка не выбрана", "muted")
        row.addWidget(self.workspace_label, 1)
        layout.addLayout(row)
        search_row = QHBoxLayout()
        self.file_query = QLineEdit()
        self.file_query.setPlaceholderText("Поиск по имени файла")
        self.file_query.returnPressed.connect(self.search_files)
        search_row.addWidget(self.file_query, 1)
        search_row.addWidget(button("Найти", self.search_files))
        layout.addLayout(search_row)
        self.files_list = QListWidget()
        self.files_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.files_list.itemDoubleClicked.connect(lambda _item: self.open_selected_file())
        layout.addWidget(self.files_list, 1)
        self.files_status = label("Выбери папку. Двойной щелчок открывает локальный preview.", "muted")
        layout.addWidget(self.files_status)
        actions = QHBoxLayout()
        actions.addWidget(button("Открыть выбранный", self.open_selected_file))
        actions.addWidget(button("Операции · права и восстановление", self.open_file_operations))
        actions.addWidget(button("План файловой задачи", self.open_file_plan))
        actions.addWidget(button("Вопрос по выбранным · локальный ИИ", self.ask_selected_files))
        layout.addLayout(actions)
        self.file_results_ready.connect(self._show_file_results)
        self.file_preview_ready.connect(self._show_file_preview)

    def _build_memory(self):
        layout = self.add_page("Память", "Только явно сохранённые заметки. Хранение локальное и зашифрованное для этой учётной записи Windows.")
        form = card()
        form_layout = QGridLayout(form)
        self.memory_title = QLineEdit()
        self.memory_title.setPlaceholderText("Короткое название")
        self.memory_text = QLineEdit()
        self.memory_text.setPlaceholderText("Что запомнить?")
        form_layout.addWidget(self.memory_title, 0, 0)
        form_layout.addWidget(self.memory_text, 0, 1)
        form_layout.addWidget(button("Сохранить заметку", self.add_memory, "primary"), 0, 2)
        layout.addWidget(form)
        self.memory_query = QLineEdit()
        self.memory_query.setPlaceholderText("Поиск по заметкам")
        self.memory_query.textChanged.connect(self._refresh_memory)
        layout.addWidget(self.memory_query)
        self.memory_list = QListWidget()
        layout.addWidget(self.memory_list, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("Забыть выбранную заметку", self.forget_memory))
        actions.addWidget(button("Локальная копия", self.backup_memory))
        actions.addWidget(button("Восстановить локальную", self.restore_memory))
        actions.addWidget(button("Переносимая копия", self.portable_backup_memory))
        actions.addWidget(button("Восстановить переносимую", self.portable_restore_memory))
        layout.addLayout(actions)
        self.memory_status = label("Пароли и API-ключи здесь не храни.", "muted")
        layout.addWidget(self.memory_status)

    def _build_settings(self):
        layout = self.add_page("Настройки", "Изменения записываются в DPAPI только после нажатия «Сохранить».")
        identity = card()
        form = QGridLayout(identity)
        form.addWidget(label("Персонаж и голос", "section"), 0, 0, 1, 2)
        self.avatar_choice = QComboBox()
        self.avatar_labels = {item["label"]: key for key, item in AVATAR_PROFILES.items()}
        self.avatar_choice.addItems(self.avatar_labels)
        self.avatar_choice.setCurrentText(AVATAR_PROFILES[self.profile.avatar_id]["label"])
        self.current_avatar_draft = self.profile.avatar_id
        self.name_edit = QLineEdit(self.assistant_name)
        self.name_edit.setMaxLength(32)
        self.avatar_mode = QComboBox()
        self.avatar_mode.addItem("2D · анимированный полноразмерный портрет", "2d")
        self.avatar_mode.setCurrentIndex(0)
        form.addWidget(label("Образ", "muted"), 1, 0)
        form.addWidget(self.avatar_choice, 1, 1)
        form.addWidget(label("Собственное имя", "muted"), 2, 0)
        form.addWidget(self.name_edit, 2, 1)
        form.addWidget(label("Представление", "muted"), 3, 0)
        form.addWidget(self.avatar_mode, 3, 1)
        form.addWidget(label("3D-режим временно отложен до появления настоящих моделей; сейчас используется анимированный 2D full-body.", "muted"), 4, 0, 1, 2)
        self.microphone_choice = QComboBox()
        self.microphone_choice.addItem("Системный выбор Windows")
        if self.profile.microphone_index is not None:
            saved_microphone = f"Устройство №{self.profile.microphone_index} (последний выбор)"
            self.microphone_map[saved_microphone] = self.profile.microphone_index
            self.microphone_choice.addItem(saved_microphone)
            self.microphone_choice.setCurrentText(saved_microphone)
        form.addWidget(label("Микрофон", "muted"), 5, 0)
        form.addWidget(self.microphone_choice, 5, 1)
        self.voice_choice = QComboBox()
        self.voice_choice.addItem("Системный голос Windows")
        if self.profile.voice_id:
            self.voice_map["Сохранённый голос Windows"] = self.profile.voice_id
            self.voice_choice.addItem("Сохранённый голос Windows")
            self.voice_choice.setCurrentText("Сохранённый голос Windows")
        form.addWidget(label("Голос Windows", "muted"), 6, 0)
        form.addWidget(self.voice_choice, 6, 1)
        voice_hint = label("Нужен ещё голос? Параметры Windows → Время и язык → Речь → «Добавить голоса» (есть русские мужские и женские). Сторонние SAPI-голоса, например RHVoice, тоже появятся в списке после установки и нажатия «Обнаружить».", "muted")
        voice_hint.setWordWrap(True)
        form.addWidget(voice_hint, 6, 2)
        self.voice_rate = QSlider(Qt.Horizontal)
        self.voice_rate.setRange(80, 300)
        self.voice_rate.setValue(self.profile.voice_rate)
        self.voice_rate_label = label(str(self.profile.voice_rate), "muted")
        self.voice_rate.valueChanged.connect(lambda value: self.voice_rate_label.setText(str(value)))
        form.addWidget(label("Скорость речи", "muted"), 7, 0)
        form.addWidget(self.voice_rate, 7, 1)
        form.addWidget(self.voice_rate_label, 7, 2)
        self.voice_volume = QSlider(Qt.Horizontal)
        self.voice_volume.setRange(0, 100)
        self.voice_volume.setValue(round(self.profile.voice_volume * 100))
        self.voice_volume_label = label(f"{round(self.profile.voice_volume * 100)}%", "muted")
        self.voice_volume.valueChanged.connect(lambda value: self.voice_volume_label.setText(f"{value}%"))
        form.addWidget(label("Громкость речи", "muted"), 8, 0)
        form.addWidget(self.voice_volume, 8, 1)
        form.addWidget(self.voice_volume_label, 8, 2)
        audio_actions = QHBoxLayout()
        audio_actions.addWidget(button("Обнаружить локальные устройства и голоса", self.discover_audio))
        audio_actions.addWidget(button("Прослушать выбранный голос", self.preview_voice))
        form.addLayout(audio_actions, 9, 0, 1, 3)
        self.avatar_choice.currentTextChanged.connect(self._avatar_changed)
        layout.addWidget(identity)

        ai = card()
        ai_form = QGridLayout(ai)
        ai_form.addWidget(label("Интеллект", "section"), 0, 0, 1, 2)
        ai_form.addWidget(label("По умолчанию Astra использует параметры проекта. Ollama подключается к уже запущенному локальному серверу; облако требует ключа.", "muted"), 1, 0, 1, 2)
        self.provider_labels = {
            "env": "Авто · параметры проекта",
            "disabled": "Без ИИ",
            "ollama": "Ollama · локально",
            "gemini": "Gemini · облако",
            "compatible": "Совместимый API",
        }
        self.provider_choice = QComboBox()
        self.provider_choice.addItems(self.provider_labels.values())
        self.provider_choice.setCurrentText(self.provider_labels[self.profile.provider])
        self.model_edit = QLineEdit(self.profile.model)
        self.model_edit.setPlaceholderText("Например: qwen3:4b")
        ai_form.addWidget(label("Режим", "muted"), 2, 0)
        ai_form.addWidget(self.provider_choice, 2, 1)
        ai_form.addWidget(label("Модель", "muted"), 3, 0)
        ai_form.addWidget(self.model_edit, 3, 1)
        self.ai_advanced = card()
        advanced_form = QGridLayout(self.ai_advanced)
        self.endpoint_edit = QLineEdit(self.profile.base_url)
        self.endpoint_edit.setPlaceholderText("http://127.0.0.1:11434")
        self.key_edit = QLineEdit(self.profile.api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Ключ не сохраняется в репозиторий")
        advanced_form.addWidget(label("Endpoint", "muted"), 0, 0)
        advanced_form.addWidget(self.endpoint_edit, 0, 1)
        advanced_form.addWidget(label("API-ключ", "muted"), 1, 0)
        advanced_form.addWidget(self.key_edit, 1, 1)
        self.memory_enabled = QCheckBox("Личная память · только с локальным Ollama")
        self.memory_enabled.setChecked(self.profile.memory_enabled)
        advanced_form.addWidget(self.memory_enabled, 2, 0, 1, 2)
        self.ai_advanced_visible = self.profile.provider in {"ollama", "gemini", "compatible"}
        self.ai_advanced.setVisible(self.ai_advanced_visible)
        ai_form.addWidget(self.ai_advanced, 4, 0, 1, 2)
        self.ai_toggle_button = button("Скрыть подключение" if self.ai_advanced_visible else "Показать подключение", self._toggle_ai_advanced)
        ai_form.addWidget(self.ai_toggle_button, 5, 0, 1, 2)
        layout.addWidget(ai)

        appearance = card()
        appearance_layout = QGridLayout(appearance)
        appearance_layout.addWidget(label("Внешний вид и доступность", "section"), 0, 0, 1, 2)
        self.scale_choice = QComboBox()
        for value in (100, 110, 125, 150):
            self.scale_choice.addItem(f"{value}%", value)
        self.scale_choice.setCurrentIndex((100, 110, 125, 150).index(self.profile.ui_scale))
        self.reduced_motion = QCheckBox("Уменьшить движение интерфейса")
        self.reduced_motion.setChecked(self.profile.reduced_motion)
        appearance_layout.addWidget(label("Масштаб после перезапуска", "muted"), 1, 0)
        appearance_layout.addWidget(self.scale_choice, 1, 1)
        appearance_layout.addWidget(self.reduced_motion, 2, 0, 1, 2)
        layout.addWidget(appearance)

        self.scope_checks = {}
        capability_titles = {entry.key: entry.title for entry in capability_catalog()}
        for scope in ALL_SCOPES:
            check = QCheckBox(SCOPE_LABELS.get(scope, capability_titles[scope]))
            check.setChecked(scope in self.profile.allowed_scopes)
            check.setToolTip(scope)
            self.scope_checks[scope] = check
        profile_actions = QHBoxLayout()
        profile_actions.addWidget(button("Мастер первого запуска", self.open_onboarding))
        profile_actions.addWidget(button("Экспорт профиля", self.export_profile))
        profile_actions.addWidget(button("Импорт профиля", self.import_profile))
        layout.addLayout(profile_actions)
        self.settings_status = label("Сетевые проверки и обнаружение устройств запускаются только отдельными кнопками.", "muted")
        layout.addWidget(self.settings_status)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("Отменить несохранённые изменения", self.reset_settings))
        actions.addWidget(button("Сохранить настройки", self.save_settings, "primary"))
        layout.addLayout(actions)
        self.audio_ready.connect(self._audio_discovered)
        self.audio_status.connect(self.settings_status.setText)
        self.profile_backup_ready.connect(self._profile_backup_finished)

    def _toggle_ai_advanced(self):
        self.ai_advanced_visible = not self.ai_advanced_visible
        self.ai_advanced.setVisible(self.ai_advanced_visible)
        self.ai_toggle_button.setText("Скрыть подключение" if self.ai_advanced_visible else "Показать подключение")

    def _load_character(self):
        avatar_id = self.profile.avatar_id if self.profile.avatar_id in AVATAR_PROFILES else DEFAULT_AVATAR_ID
        avatar = AVATAR_PROFILES[avatar_id]
        resource_root = Path(getattr(sys, "_MEIPASS", ROOT))
        portraits = resource_root / "assets" / "avatars"
        self.character.reload(portraits / avatar["asset"], self.assistant_name, speaking_path=portraits / avatar["speaking_asset"])
        if self.desktop_character is not None:
            self.desktop_character.sync_character()

    def toggle_desktop_character(self):
        if self.desktop_character is None:
            return
        self.desktop_character.setVisible(not self.desktop_character.isVisible())

    def show_character_fullscreen(self):
        if self.character_fullscreen is not None and self.character_fullscreen.isVisible():
            self.character_fullscreen.close()
            return
        if self.character_fullscreen is None:
            self.character_fullscreen = CharacterFullscreenDialog(self, self.character)
            self.character_fullscreen.finished.connect(self._character_fullscreen_finished)
        self.character_fullscreen.sync_from(self.character)
        self.character_fullscreen.showFullScreen()
        self.character_fullscreen.raise_()
        self.character_fullscreen.activateWindow()

    def _character_fullscreen_finished(self, _result):
        dialog = self.character_fullscreen
        self.character_fullscreen = None
        if dialog is not None:
            dialog.deleteLater()

    def open_onboarding(self):
        if self.closing:
            return
        dialog = OnboardingDialog(self, self.store)
        if dialog.exec() == QDialog.Accepted and dialog.saved_profile is not None:
            self.profile = dialog.saved_profile
            self.character_draft = {key: dict(value) for key, value in self.profile.character_profiles.items()}
            self.onboarding_available = False
            if self.onboarding_banner is not None:
                self.onboarding_banner.hide()
            self.reset_settings()
            self._load_character()
            self.switch_mode("text")

    def dismiss_onboarding(self):
        try:
            self.onboarding_state.dismiss()
        except Exception as exc:
            self.append_message("Система", "Не удалось сохранить выбор первого запуска: " + str(exc))
            return
        self.onboarding_available = False
        if self.onboarding_banner is not None:
            self.onboarding_banner.hide()

    def open_command_catalog(self):
        dialog = CommandCatalogDialog(self, self.fill_command)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def fill_command(self, phrase):
        self.show_page(0)
        self.entry.setText(f"{self.assistant_name}, {phrase}")
        self.entry.setFocus()

    def open_action_audit(self):
        dialog = ActionAuditDialog(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def run_quick(self, value):
        self.fill_command(value)
        self.send_text()

    def send_text(self):
        text = self.entry.text().strip()
        if not text:
            return
        if not self.bridge.running or self.bridge.mode != "text":
            self.append_message("Ты", text)
            self.entry.clear()
            self.pending_texts.append(text)
            self._set_voice_status("Переключение режима…")
            self.switch_mode("text")
            return
        try:
            self.bridge.send(text)
        except Exception as exc:
            self.append_message("Система", str(exc))
            return
        self.append_message("Ты", text)
        self.entry.clear()

    def cancel_response(self):
        if not self.bridge.cancel_response():
            self.cancel_response_button.setEnabled(False)
            self.append_message("Система", "Сигнал остановки ответа недоступен.")
            return
        self.cancel_response_button.setEnabled(False)
        self._set_voice_status("Останавливаю ответ…")

    def _flush_pending_texts(self):
        if not self.pending_texts or not self.bridge.running or self.bridge.mode != "text":
            return
        texts = list(self.pending_texts)
        self.pending_texts.clear()
        for text in texts:
            try:
                self.bridge.send(text)
            except Exception as exc:
                self.append_message("Система", str(exc))

    def new_dialogue(self):
        if not self.bridge.running or self.bridge.mode != "text":
            self.append_message("Система", f"Для кнопки переключись в текстовый режим. В голосовом режиме скажи: «{self.assistant_name}, начни новый диалог».")
            return
        if QMessageBox.question(self, "Astra · новый диалог", "Очистить контекст текущего разговора? Сохранённые заметки и напоминания останутся.") != QMessageBox.Yes:
            return
        command = f"{self.assistant_name}, начни новый диалог"
        try:
            self.bridge.send(command)
        except Exception as exc:
            self.append_message("Система", str(exc))
            return
        self.append_message("Ты", command)

    def append_message(self, who, text):
        color = ACCENT if who == "Ты" else CYAN if who == self.assistant_name else MUTED
        safe_who = html.escape(who)
        safe_text = html.escape(text).replace("\n", "<br>")
        self.chat.append(f"<span style='color:{color};font-weight:600'>{safe_who}</span><br>{safe_text}<br>")

    def switch_mode(self, mode):
        if self.closing:
            return
        self.voice_files.cancel()
        if self.busy:
            self.pending_mode = mode
            self.mode_pending = True
            return
        self.busy = True
        self._set_voice_status("Переключение режима…")
        def work():
            try:
                self.bridge.stop()
                if mode and not self.closing:
                    self.bridge.start(mode)
                else:
                    self.bridge.emit("status", "Пауза · микрофон выключен")
            except Exception as exc:
                self.bridge.emit("error", str(exc))
            finally:
                self.bridge.emit("ready", "")
        threading.Thread(target=work, name="astra-qt-mode", daemon=True).start()

    def toggle_voice_mode(self):
        active = self.bridge.running and self.bridge.mode == "voice"
        self.switch_mode(None if active else "voice")

    def _set_voice_status(self, text):
        if not text:
            return
        if self.home_status is not None:
            self.home_status.setText(text)
        if self.voice_status is not None:
            self.voice_status.setText(text)
        self.character.set_state(text)
        if self.desktop_character is not None:
            self.desktop_character.set_state(text)
        active = self.bridge.running and self.bridge.mode == "voice"
        self.voice_button.setProperty("active", active)
        self.voice_button.setText("Выключить голос" if active else "Голос")
        self.voice_button.style().unpolish(self.voice_button)
        self.voice_button.style().polish(self.voice_button)
        self._refresh_tray_tooltip()

    def _poll(self):
        for _ in range(120):
            try:
                kind, text = self.bridge.events.get_nowait()
            except queue.Empty:
                break
            if kind == "ready":
                self.busy = False
                if self.home_status.text() == "Переключение режима…":
                    active = self.bridge.running and self.bridge.mode == "voice"
                    self._set_voice_status("Голосовой диалог активен. Можно говорить." if active else "Микрофон выключен. Нажми кнопку, когда будешь готов говорить.")
                self._flush_pending_texts()
                if self.mode_pending and not self.closing:
                    mode = self.pending_mode
                    self.mode_pending = False
                    self.pending_mode = None
                    self.switch_mode(mode)
            elif kind in {"status", "state"}:
                self._set_voice_status(text)
            elif kind == "assistant":
                self.cancel_response_button.setVisible(False)
                self.append_message(self.assistant_name, text)
            elif kind == "activity":
                if text == "thinking:start":
                    available = self.bridge.cancel_response_available
                    self.cancel_response_button.setVisible(available)
                    self.cancel_response_button.setEnabled(available)
                elif text == "thinking:stop":
                    self.cancel_response_button.setVisible(False)
                    self.cancel_response_button.setEnabled(True)
            elif kind == "transcript":
                self.append_message("Ты · голос", text)
            elif kind == "conversation_reset":
                self.chat.clear()
            elif kind in {"file_search_request", "file_open_request", "file_read_request", "file_question_request"}:
                self.voice_files.handle(kind.removeprefix("file_").removesuffix("_request"), text)
            elif kind == "reminder":
                self._deliver_reminder(text)
            elif kind == "reminder_error":
                self.append_message("Система", text)
            elif kind == "reminder_count":
                count = int(text)
                self.setWindowTitle(f"Astra {DISPLAY_VERSION} · личный ассистент" + (f" · напоминаний: {count}" if count else ""))
            elif kind == "error":
                self._set_voice_status("Ошибка · микрофон выключен")
                self.append_message("Система", text)
            elif kind == "exit":
                if not self.busy and not self.bridge.running:
                    self._set_voice_status("Остановлена · микрофон выключен")
            elif kind == "output":
                text = text.removeprefix("Ты: ")
                if text.startswith("Астра: "):
                    self.append_message(self.assistant_name, text[7:])
                elif "|" not in text and text and self.bridge.mode == "voice":
                    self.append_message("Система", text)
                elif "| ERROR" in text or "| WARNING" in text:
                    self.append_message("Система", text)
        if self.preview_session is not None:
            if self.preview_session.poll() is None:
                self.preview_session.set_state(self.avatar_state())
            else:
                self.preview_session = None

    def _deliver_reminder(self, text):
        if self.closing or self.reminder_store is None:
            return
        try:
            item = json.loads(text)
            if self.reminder_store.valid_claim(item["id"], item["token"]):
                if self.reminder_store.acknowledge(item["id"], item["token"]):
                    self.append_message("Напоминание", item["text"])
                    self._set_voice_status("Новое напоминание · открой чат Astra")
                    if self.tray is not None:
                        self.tray.showMessage("Astra", "Есть новое напоминание. Открой Astra.", QSystemTrayIcon.Information, 8000)
                    self._refresh_reminders()
        except Exception:
            self.append_message("Система", "Не удалось доставить напоминание; оно будет повторено после истечения срока доставки.")

    def avatar_state(self):
        text = self.home_status.text().casefold()
        if "ошибка" in text:
            return "error"
        if "говор" in text or "чита" in text:
            return "speaking"
        if "слуш" in text:
            return "listening"
        if "распозн" in text or "дума" in text or self.busy:
            return "recognizing"
        return "idle"

    def add_reminder(self):
        if self.reminder_store is None or not self.reminder_text.text().strip():
            return
        if "reminders" not in self.profile.allowed_scopes:
            QMessageBox.information(self, "Astra · напоминания", "Создание напоминаний отключено в разрешениях навыков")
            return
        try:
            self.reminder_store.add(self.reminder_text.text().strip(), self.reminder_due.dateTime().toSecsSinceEpoch())
        except Exception as exc:
            QMessageBox.warning(self, "Astra · напоминания", str(exc))
            return
        self.reminder_text.clear()
        self._refresh_reminders()

    def _refresh_reminders(self):
        self.reminders_list.clear()
        if self.reminder_store is None:
            self.reminders_list.addItem("Локальное хранилище напоминаний недоступно")
            return
        for item in self.reminder_store.list():
            row = QListWidgetItem(f"{item.state} · {datetime.fromtimestamp(item.due):%d.%m.%Y  %H:%M}   ·   {item.text}")
            row.setData(Qt.UserRole, item.id)
            self.reminders_list.addItem(row)

    def cancel_reminder(self):
        item = self.reminders_list.currentItem()
        if item is not None and self.reminder_store is not None:
            self.reminder_store.cancel(item.data(Qt.UserRole))
            self._refresh_reminders()

    def complete_reminder(self):
        item = self.reminders_list.currentItem()
        if item is not None and self.reminder_store is not None:
            self.reminder_store.complete(item.data(Qt.UserRole))
            self._refresh_reminders()

    def export_reminders(self):
        if self.reminder_store is None:
            return
        chosen, _ = QFileDialog.getSaveFileName(self, "Переносимая копия напоминаний", "reminders.astra-reminders-portable", "Напоминания Astra (*.astra-reminders-portable)")
        if not chosen:
            return
        dialog = PassphraseDialog(self, "Экспорт напоминаний", confirmation=True)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            count = self.reminder_store.create_portable_backup(Path(chosen), dialog.value())
            QMessageBox.information(self, "Astra · напоминания", f"Создана зашифрованная копия: {count} записей")
        except Exception as exc:
            QMessageBox.warning(self, "Astra · напоминания", str(exc))

    def import_reminders(self):
        if self.reminder_store is None:
            return
        chosen, _ = QFileDialog.getOpenFileName(self, "Восстановить напоминания", "", "Напоминания Astra (*.astra-reminders-portable);;Все файлы (*)")
        if not chosen:
            return
        dialog = PassphraseDialog(self, "Импорт напоминаний")
        if dialog.exec() != QDialog.Accepted:
            return
        source = Path(chosen)
        try:
            new_count, conflicts = self.reminder_store.preview_portable_restore(source, dialog.value())
            if QMessageBox.question(self, "Проверка восстановления", f"Новых: {new_count}. Совпадений без перезаписи: {conflicts}. Продолжить?") != QMessageBox.Yes:
                return
            restored, skipped = self.reminder_store.restore_portable_backup(source, dialog.value())
            self._refresh_reminders()
            QMessageBox.information(self, "Astra · напоминания", f"Добавлено: {restored}. Пропущено: {skipped}.")
        except Exception as exc:
            QMessageBox.warning(self, "Astra · напоминания", str(exc))

    def choose_workspace(self):
        selected = QFileDialog.getExistingDirectory(self, "Разрешить папку на эту сессию")
        if not selected:
            return
        try:
            workspace = FileWorkspace(Path(selected))
        except Exception as exc:
            QMessageBox.warning(self, "Astra · файлы", str(exc))
            return
        self.close_workspace()
        self.workspace = workspace
        self.transactions = FileTransactions(workspace, audit=record_action)
        self.voice_files.set_workspace(workspace)
        self.workspace_label.setText(str(workspace.root))
        self.search_files()

    def close_workspace(self):
        self.file_search_generation += 1
        self.voice_files.set_workspace(None)
        if self.transactions is not None:
            self.transactions.grant_write(False)
            self.transactions.grant_trash(False)
        self.workspace = None
        self.transactions = None
        self.files_list.clear()
        self.workspace_label.setText("Папка не выбрана")
        self.files_status.setText("Доступ к папке отозван")

    def search_files(self):
        if self.workspace is None:
            return
        workspace = self.workspace
        query = self.file_query.text()
        self.file_search_generation += 1
        generation = self.file_search_generation
        self.files_list.clear()
        self.files_list.addItem("Поиск…")
        def work():
            try:
                result = workspace.search(query, deadline=time.monotonic() + 8)
                self.file_results_ready.emit((generation, [item.path for item in result]))
            except Exception as exc:
                self.file_results_ready.emit((generation, str(exc)))
        threading.Thread(target=work, name="astra-qt-files", daemon=True).start()

    def _show_file_results(self, message):
        generation, result = message
        if generation != self.file_search_generation:
            return
        self.files_list.clear()
        if isinstance(result, str):
            self.files_status.setText(result)
        elif result:
            self.files_list.addItems(result)
            self.files_status.setText(f"Найдено: {len(result)} · двойной щелчок открывает просмотр")
        else:
            self.files_status.setText("Файлы не найдены")

    def selected_files(self):
        return [item.text() for item in self.files_list.selectedItems()]

    def open_selected_file(self):
        selected = self.selected_files()
        if self.workspace is None or not selected:
            self.files_status.setText("Выбери файл в списке")
            return
        workspace = self.workspace
        relative = selected[0]
        generation = self.file_search_generation
        self.files_status.setText("Безопасное локальное чтение…")
        def work():
            try:
                value = workspace.preview_image(relative) if Path(relative).suffix.casefold() in workspace.IMAGE_SUFFIXES else workspace.read_text(relative, deadline=time.monotonic() + 15)
                self.file_preview_ready.emit((generation, relative, True, value))
            except Exception as exc:
                self.file_preview_ready.emit((generation, relative, False, str(exc)))
        threading.Thread(target=work, name="astra-qt-file-preview", daemon=True).start()

    def _show_file_preview(self, message):
        generation, relative, ok, value = message
        if generation != self.file_search_generation or self.workspace is None:
            return
        if not ok:
            self.files_status.setText(value)
            return
        dialog = FilePreviewDialog(self, relative, value)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()
        self.files_status.setText("Локальный preview открыт")

    def open_file_operations(self):
        if self.workspace is None:
            self.files_status.setText("Сначала выбери папку")
            return
        dialog = FileOperationsDialog(self, self.workspace, self.transactions)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def open_file_plan(self):
        if self.workspace is None:
            self.files_status.setText("Сначала выбери папку")
            return
        dialog = FilePlanDialog(self, self.workspace, self.transactions)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def ask_selected_files(self):
        selected = self.selected_files()
        if self.workspace is None or not selected:
            self.files_status.setText("Выбери от одного до пяти файлов")
            return
        if len(selected) > 5:
            self.files_status.setText("Для одного локального вопроса выбери не больше пяти файлов")
            return
        try:
            dialog = FileQuestionDialog(self, self.workspace, tuple(selected))
            dialog.setAttribute(Qt.WA_DeleteOnClose)
            dialog.show()
        except Exception as exc:
            self.files_status.setText(str(exc))

    def _refresh_memory(self):
        self.memory_list.clear()
        try:
            rows = self.memory.search(self.memory_query.text())
        except Exception:
            self.memory_status.setText("Не удалось расшифровать память этой учётной записью Windows")
            return
        for item in rows:
            row = QListWidgetItem(f"{item.title}\n{item.text}")
            row.setData(Qt.UserRole, item.id)
            self.memory_list.addItem(row)
        self.memory_status.setText(f"Найдено записей: {len(rows)}. Пароли и API-ключи здесь не храни.")

    def add_memory(self):
        if self.memory_title.text().strip() and self.memory_text.text().strip():
            try:
                self.memory.add(self.memory_title.text().strip(), self.memory_text.text().strip())
            except Exception as exc:
                self.memory_status.setText(str(exc))
                return
            self.memory_title.clear()
            self.memory_text.clear()
            self._refresh_memory()

    def forget_memory(self):
        item = self.memory_list.currentItem()
        if item is not None and QMessageBox.question(self, "Забыть запись?", "Удалить выбранную запись из памяти Astra?") == QMessageBox.Yes:
            self.memory.forget(item.data(Qt.UserRole))
            self._refresh_memory()

    def backup_memory(self):
        chosen, _ = QFileDialog.getSaveFileName(self, "Локальная резервная копия памяти", "memory.astra-memory.json", "Память Astra (*.astra-memory.json);;JSON (*.json)")
        if chosen:
            try:
                count = self.memory.create_backup(Path(chosen))
                self.memory_status.setText(f"Локальная копия создана: {count} записей")
            except Exception as exc:
                QMessageBox.warning(self, "Astra · память", str(exc))

    def restore_memory(self):
        chosen, _ = QFileDialog.getOpenFileName(self, "Восстановить локальную память", "", "Память Astra (*.astra-memory.json *.json);;Все файлы (*)")
        if not chosen:
            return
        source = Path(chosen)
        try:
            new_count, conflicts = self.memory.preview_restore(source)
            if QMessageBox.question(self, "Проверка восстановления", f"Новых: {new_count}. Совпадений без перезаписи: {conflicts}. Продолжить?") != QMessageBox.Yes:
                return
            restored, skipped = self.memory.restore_backup(source)
            self._refresh_memory()
            self.memory_status.setText(f"Добавлено: {restored}. Пропущено: {skipped}.")
        except Exception as exc:
            QMessageBox.warning(self, "Astra · память", str(exc))

    def portable_backup_memory(self):
        chosen, _ = QFileDialog.getSaveFileName(self, "Переносимая копия памяти", "memory.astra-memory-portable", "Память Astra (*.astra-memory-portable)")
        if not chosen:
            return
        dialog = PassphraseDialog(self, "Перенос памяти", confirmation=True)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            count = self.memory.create_portable_backup(Path(chosen), dialog.value())
            self.memory_status.setText(f"Переносимая копия создана: {count} записей")
        except Exception as exc:
            QMessageBox.warning(self, "Astra · память", str(exc))

    def portable_restore_memory(self):
        chosen, _ = QFileDialog.getOpenFileName(self, "Восстановить переносимую память", "", "Память Astra (*.astra-memory-portable);;Все файлы (*)")
        if not chosen:
            return
        dialog = PassphraseDialog(self, "Перенос памяти")
        if dialog.exec() != QDialog.Accepted:
            return
        source = Path(chosen)
        try:
            new_count, conflicts = self.memory.preview_portable_restore(source, dialog.value())
            if QMessageBox.question(self, "Проверка восстановления", f"Новых: {new_count}. Совпадений без перезаписи: {conflicts}. Продолжить?") != QMessageBox.Yes:
                return
            restored, skipped = self.memory.restore_portable_backup(source, dialog.value())
            self._refresh_memory()
            self.memory_status.setText(f"Перенесено: {restored}. Пропущено: {skipped}.")
        except Exception as exc:
            QMessageBox.warning(self, "Astra · память", str(exc))

    def _avatar_changed(self):
        selected = self.avatar_labels.get(self.avatar_choice.currentText(), self.profile.avatar_id)
        previous = getattr(self, "current_avatar_draft", selected)
        if selected == previous:
            return
        self.character_draft[previous] = {
            "assistant_name": self.name_edit.text().strip() or AVATAR_PROFILES[previous]["default_name"],
            "voice_id": self.voice_map.get(self.voice_choice.currentText(), self.profile.voice_id),
        }
        character = self.character_draft.get(selected, {
            "assistant_name": AVATAR_PROFILES[selected]["default_name"], "voice_id": "",
        })
        self.name_edit.setText(character["assistant_name"])
        self._select_voice(character["voice_id"])
        self.current_avatar_draft = selected
        self._preview_avatar_selection(selected)

    def _preview_avatar_selection(self, avatar_id):
        avatar = AVATAR_PROFILES[avatar_id]
        display_name = self.name_edit.text().strip() or avatar["default_name"]
        portraits = Path(getattr(sys, "_MEIPASS", ROOT)) / "assets" / "avatars"
        self.character.reload(portraits / avatar["asset"], display_name, speaking_path=portraits / avatar["speaking_asset"])
        self.character.set_state(self.home_status.text())
        if self.desktop_character is not None:
            self.desktop_character.stage.reload(portraits / avatar["asset"], display_name, speaking_path=portraits / avatar["speaking_asset"])
            self.desktop_character.stage.set_state(self.home_status.text())
        self.settings_status.setText("Образ обновлён для предпросмотра. Нажми «Сохранить», чтобы закрепить.")

    def _select_voice(self, voice_id):
        selected = next((name for name, value in self.voice_map.items() if value == voice_id), None)
        if selected is None and voice_id:
            selected = "Сохранённый голос Windows"
            self.voice_map[selected] = voice_id
            self.voice_choice.addItem(selected)
        self.voice_choice.setCurrentText(selected or "Системный голос Windows")

    def current_settings(self):
        provider = next(key for key, value in self.provider_labels.items() if value == self.provider_choice.currentText())
        avatar_id = self.avatar_labels[self.avatar_choice.currentText()]
        characters = {key: dict(value) for key, value in self.character_draft.items()}
        characters[avatar_id] = {
            "assistant_name": self.name_edit.text().strip(),
            "voice_id": self.voice_map.get(self.voice_choice.currentText(), self.profile.voice_id),
        }
        return replace(
            self.profile, provider=provider, model=self.model_edit.text().strip(),
            base_url=self.endpoint_edit.text().strip(), api_key=self.key_edit.text(),
            assistant_name=characters[avatar_id]["assistant_name"], avatar_id=avatar_id,
            voice_id=characters[avatar_id]["voice_id"], character_profiles=characters,
            microphone_index=self.microphone_map.get(self.microphone_choice.currentText()),
            voice_rate=self.voice_rate.value(), voice_volume=self.voice_volume.value() / 100,
            avatar_mode=self.avatar_mode.currentData(), ui_scale=self.scale_choice.currentData(),
            reduced_motion=self.reduced_motion.isChecked(), memory_enabled=self.memory_enabled.isChecked(),
            allowed_scopes=tuple(scope for scope, check in self.scope_checks.items() if check.isChecked()),
        ).validate()

    def save_settings(self):
        try:
            profile = self.current_settings()
            self.store.save(profile)
        except Exception as exc:
            self.settings_status.setText(str(exc))
            return
        self.profile = profile
        self.character_draft = {key: dict(value) for key, value in profile.character_profiles.items()}
        self.onboarding_available = False
        if self.onboarding_banner is not None:
            self.onboarding_banner.hide()
        self.character.reduced_motion = profile.reduced_motion
        self._load_character()
        self.settings_status.setText("Сохранено. Runtime перезапущен в текстовом режиме; микрофон выключен.")
        self.switch_mode("text")

    def reset_settings(self):
        try:
            self.profile = self.store.load()
        except Exception:
            self.profile = AIProfile()
        self.character_draft = {key: dict(value) for key, value in self.profile.character_profiles.items()}
        self.avatar_choice.setCurrentText(AVATAR_PROFILES[self.profile.avatar_id]["label"])
        self.current_avatar_draft = self.profile.avatar_id
        self.name_edit.setText(self.assistant_name)
        self._select_voice(self.profile.voice_id)
        self.avatar_mode.setCurrentIndex(0)
        self.provider_choice.setCurrentText(self.provider_labels[self.profile.provider])
        self.model_edit.setText(self.profile.model)
        self.endpoint_edit.setText(self.profile.base_url)
        self.key_edit.setText(self.profile.api_key)
        self.memory_enabled.setChecked(self.profile.memory_enabled)
        self.ai_advanced_visible = self.profile.provider in {"ollama", "gemini", "compatible"}
        self.ai_advanced.setVisible(self.ai_advanced_visible)
        self.ai_toggle_button.setText("Скрыть подключение" if self.ai_advanced_visible else "Показать подключение")
        self.scale_choice.setCurrentIndex((100, 110, 125, 150).index(self.profile.ui_scale))
        self.reduced_motion.setChecked(self.profile.reduced_motion)
        self.voice_rate.setValue(self.profile.voice_rate)
        self.voice_volume.setValue(round(self.profile.voice_volume * 100))
        microphone = next((name for name, value in self.microphone_map.items() if value == self.profile.microphone_index), None)
        if microphone is None and self.profile.microphone_index is not None:
            microphone = f"Устройство №{self.profile.microphone_index} (последний выбор)"
            self.microphone_map[microphone] = self.profile.microphone_index
            self.microphone_choice.addItem(microphone)
        self.microphone_choice.setCurrentText(microphone or "Системный выбор Windows")
        for scope, check in self.scope_checks.items():
            check.setChecked(scope in self.profile.allowed_scopes)
        self.settings_status.setText("Несохранённые значения сброшены.")

    def discover_audio(self):
        if self.audio_busy:
            return
        self.audio_busy = True
        self.settings_status.setText("Локальное обнаружение устройств и голосов Windows…")
        def work():
            try:
                import speech_recognition as sr
                microphones = [(f"{index}: {name}", index) for index, name in enumerate(sr.Microphone.list_microphone_names())]
            except Exception:
                microphones = None
            try:
                import pyttsx3
                engine = pyttsx3.init("sapi5")
                voices = [(_voice_label(voice), str(getattr(voice, "id", ""))) for voice in engine.getProperty("voices") or []]
                engine.stop()
            except Exception:
                voices = None
            self.audio_ready.emit({"microphones": microphones, "voices": voices})
        threading.Thread(target=work, name="astra-qt-audio", daemon=True).start()

    def _audio_discovered(self, result):
        self.audio_busy = False
        microphones = result["microphones"]
        voices = result["voices"]
        if microphones is not None:
            self.microphone_map = {"Системный выбор Windows": None}
            self.microphone_map.update(microphones)
            self.microphone_choice.clear()
            self.microphone_choice.addItems(self.microphone_map)
            selected = next((name for name, index in self.microphone_map.items() if index == self.profile.microphone_index), "Системный выбор Windows")
            self.microphone_choice.setCurrentText(selected)
        if voices is not None:
            current_voice = self.voice_map.get(self.voice_choice.currentText(), self.profile.voice_id)
            self.voice_map = {"Системный голос Windows": ""}
            self.voice_map.update(voices)
            self.voice_choice.clear()
            self.voice_choice.addItems(self.voice_map)
            self._select_voice(current_voice)
        self.settings_status.setText("Локальные устройства и голоса обновлены" if microphones is not None and voices is not None else "Часть аудиоустройств недоступна; сохранённый выбор не сброшен")

    def preview_voice(self):
        if self.audio_busy:
            return
        try:
            config = self.current_settings()
        except Exception as exc:
            self.settings_status.setText(str(exc))
            return
        self.audio_busy = True
        self.settings_status.setText("Локальное прослушивание выбранного голоса…")
        def work():
            try:
                import pyttsx3
                engine = pyttsx3.init("sapi5")
                if config.voice_id:
                    engine.setProperty("voice", config.voice_id)
                engine.setProperty("rate", config.voice_rate)
                engine.setProperty("volume", config.voice_volume)
                engine.say(f"Привет, я {config.assistant_name or 'Астра'}. Это проверка голоса.")
                engine.runAndWait()
                engine.stop()
                result = "Прослушивание завершено"
            except Exception:
                result = "Системное озвучивание недоступно"
            self.audio_status.emit(result)
            self.audio_busy = False
        threading.Thread(target=work, name="astra-qt-voice-preview", daemon=True).start()

    def _passphrase(self, title, confirmation=False):
        dialog = PassphraseDialog(self, title, confirmation=confirmation)
        return dialog.value() if dialog.exec() == QDialog.Accepted else None

    def export_profile(self):
        chosen, _ = QFileDialog.getSaveFileName(self, "Экспорт профиля Astra", "profile.astra-profile-backup", "Профиль Astra (*.astra-profile-backup)")
        if not chosen:
            return
        passphrase = self._passphrase("Экспорт профиля", confirmation=True)
        if passphrase is None:
            return
        try:
            snapshot = self.current_settings()
        except Exception as exc:
            self.settings_status.setText(str(exc))
            return
        self.settings_status.setText("Создаю зашифрованную копию профиля…")
        def work():
            try:
                export_profile(Path(chosen), snapshot, passphrase)
                self.profile_backup_ready.emit(("export", True, "Профиль экспортирован. Парольную фразу храни отдельно."))
            except Exception:
                self.profile_backup_ready.emit(("export", False, "Не удалось создать профильную копию. Проверь путь и парольную фразу."))
        threading.Thread(target=work, name="astra-qt-profile-export", daemon=True).start()

    def import_profile(self):
        chosen, _ = QFileDialog.getOpenFileName(self, "Импорт профиля Astra", "", "Профиль Astra (*.astra-profile-backup);;Все файлы (*)")
        if not chosen:
            return
        passphrase = self._passphrase("Импорт профиля")
        if passphrase is None:
            return
        self.settings_status.setText("Проверяю и расшифровываю профиль…")
        def work():
            try:
                restored = import_profile(Path(chosen), passphrase)
                self.profile_backup_ready.emit(("import", True, restored))
            except Exception:
                self.profile_backup_ready.emit(("import", False, "Не удалось открыть копию: проверь файл и парольную фразу."))
        threading.Thread(target=work, name="astra-qt-profile-import", daemon=True).start()

    def _profile_backup_finished(self, message):
        operation, ok, value = message
        if not ok or operation == "export":
            self.settings_status.setText(value)
            return
        restored = value
        summary = (f"Импортировать профиль {restored.assistant_name or 'Astra'}?\n\nПровайдер: {restored.provider}\nМодель: {restored.model}\nРазрешений: {len(restored.allowed_scopes)}\n\nТекущий профиль будет заменён. Память и напоминания останутся без изменений. Микрофон нужно проверить на этом компьютере.")
        if QMessageBox.question(self, "Подтверждение импорта профиля", summary) != QMessageBox.Yes:
            self.settings_status.setText("Импорт отменён; текущий профиль не изменён")
            return
        try:
            self.store.save(restored)
        except Exception as exc:
            self.settings_status.setText(str(exc))
            return
        self.profile = restored
        self.reset_settings()
        self._load_character()
        self.settings_status.setText("Профиль импортирован. Runtime перезапущен в текстовом режиме.")
        self.switch_mode("text")

    def _ensure_tray(self):
        if self.tray is not None:
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray_menu = QMenu(self)
        open_action = self.tray_menu.addAction("Открыть Astra", self.show_from_tray)
        self.tray_mode_action = self.tray_menu.addAction("Включить микрофон", self.toggle_tray_microphone)
        self.tray_menu.addAction("Полностью выйти", self.exit_application)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda reason: self.show_from_tray() if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick} else None)
        self._refresh_tray_tooltip()
        self.tray_menu.setDefaultAction(open_action)

    def hide_to_tray(self):
        if self.closing:
            return
        self._move_to_background()

    def _move_to_background(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._set_voice_status("Системный трей недоступен · окно оставлено открытым")
            return False
        self._ensure_tray()
        self.tray.show()
        if self.character_fullscreen is not None and self.character_fullscreen.isVisible():
            self.character_fullscreen.close()
        self.hide()
        self._set_voice_status("Astra работает в фоне · персонаж остаётся на рабочем столе")
        return True

    def show_from_tray(self):
        if not self.closing:
            self.force_exit = False
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def exit_application(self):
        self.force_exit = True
        self.close()

    def toggle_tray_microphone(self):
        active = self.bridge.running and self.bridge.mode == "voice"
        self.switch_mode("text" if active else "voice")

    def _refresh_tray_tooltip(self):
        if self.tray is None:
            return
        mode = self.bridge.mode if self.bridge.running else "text"
        self.tray.setToolTip(microphone_tooltip(mode, self.home_status.text()))
        if self.tray_mode_action is not None:
            self.tray_mode_action.setText("Выключить микрофон" if mode == "voice" else "Включить микрофон")

    def closeEvent(self, event: QCloseEvent):
        if not self.force_exit and not self.closing:
            if self._move_to_background():
                event.ignore()
                return
            event.ignore()
            return
        self.closing = True
        self.voice_files.set_workspace(None)
        if self.transactions is not None:
            self.transactions.grant_write(False)
            self.transactions.grant_trash(False)
        if self.preview_session is not None:
            self.preview_session.close()
        if self.character_fullscreen is not None and self.character_fullscreen.isVisible():
            self.character_fullscreen.close()
        if self.desktop_character is not None:
            self.desktop_character.close()
        if self.tray is not None:
            self.tray.hide()
        self.bridge.prevent_restart()
        self.bridge.stop()
        if self.reminder_worker is not None:
            self.reminder_worker.stop()
        event.accept()


class BootSplash(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.phase = 0.0
        self.stage_index = 0
        self.stage_text = "Пробуждение Astra…"
        self.logo = QPixmap(str(ROOT / "assets" / "branding" / "astra.png"))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def _tick(self):
        self.phase += 0.033
        self.update()

    def set_stage(self, index, text):
        self.stage_index = index
        self.stage_text = text
        self.update()

    def finish(self, _window):
        self.timer.stop()
        self.close()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 52))
        painter.drawRect(rect)
        center = QPointF(rect.center().x(), rect.center().y() - 28)
        intro = min(1.0, self.phase / 0.95)
        ease = 1.0 - (1.0 - intro) ** 3
        glow_radius = min(rect.width(), rect.height()) * (0.20 + 0.10 * ease)
        glow = QRadialGradient(center, glow_radius)
        glow.setColorAt(0.0, QColor(79, 232, 214, int(56 * intro)))
        glow.setColorAt(0.58, QColor(47, 145, 150, int(24 * intro)))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(glow)
        painter.drawEllipse(center, glow_radius, glow_radius)
        logo_size = 54 + 112 * ease + (3.5 * math.sin(self.phase * 2.2) if intro >= 1 else 0)
        painter.setOpacity(intro)
        for index, span in ((0, 120), (1, 86), (2, 58)):
            color = QColor(79, 232, 214, int((132 - index * 36) * intro))
            painter.setPen(QPen(color, 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            radius = logo_size * (0.70 + index * 0.16)
            start = int((self.phase * (36 + index * 15) + index * 118) % 360)
            painter.drawArc(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2), start * 16, span * 16)
        logo_rect = QRectF(center.x() - logo_size / 2, center.y() - logo_size / 2, logo_size, logo_size)
        if not self.logo.isNull():
            painter.drawPixmap(logo_rect.toRect(), self.logo)
        painter.setOpacity(min(1.0, max(0.0, (self.phase - 0.45) / 0.35)))
        painter.setPen(QColor("#F4F8FF"))
        title_font = painter.font()
        title_font.setPointSize(30)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(rect.left(), center.y() + logo_size * 0.62, rect.width(), 44), Qt.AlignCenter, "Astra")
        small_font = painter.font()
        small_font.setPointSize(10)
        small_font.setBold(True)
        painter.setFont(small_font)
        painter.setPen(QColor(CYAN))
        painter.drawText(QRectF(rect.left(), center.y() + logo_size * 0.62 + 48, rect.width(), 22), Qt.AlignCenter, "AUTONOMOUS DESKTOP")
        status_font = painter.font()
        status_font.setPointSize(11)
        status_font.setBold(False)
        painter.setFont(status_font)
        painter.drawText(QRectF(rect.left(), center.y() + logo_size * 0.62 + 82, rect.width(), 26), Qt.AlignCenter, self.stage_text)
        painter.setOpacity(1.0)
        progress_width = min(420.0, rect.width() * 0.32)
        progress_value = progress_width * min(1.0, (self.stage_index + 1) / 5)
        progress_x = center.x() - progress_width / 2
        progress_y = rect.bottom() - 54
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(16, 28, 40, 190))
        painter.drawRoundedRect(QRectF(progress_x, progress_y, progress_width, 4), 2, 2)
        painter.setBrush(QColor(CYAN))
        painter.drawRoundedRect(QRectF(progress_x, progress_y, progress_value, 4), 2, 2)


def create_splash():
    return BootSplash()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Astra")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(ROOT / "assets" / "branding" / "astra.ico")))
    splash = create_splash()
    splash.showFullScreen()
    app.processEvents()
    try:
        reminders = ReminderStore(LOCAL / "reminders.sqlite")
    except Exception:
        reminders = None
    window = AstraQtDesktop(reminders)
    boot_steps = ["Загрузка персонажа…", "Проверка памяти…", "Подготовка команд…", "Запуск runtime…", "Синхронизация интерфейса…"]
    boot_state = {"index": 0}

    def advance_boot():
        boot_state["index"] += 1
        if boot_state["index"] < len(boot_steps):
            splash.set_stage(boot_state["index"] + 1, boot_steps[boot_state["index"]])
            QTimer.singleShot(220, advance_boot)
        else:
            window.show()
            splash.finish(window)

    QTimer.singleShot(220, advance_boot)
    return app.exec()


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
