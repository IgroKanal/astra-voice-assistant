# ADR 0003 — полноценная Qt-оболочка Astra

Дата: 2026-11-14. Статус: Qt является основным desktop entry point; прежний Tk UI сохранён как ручной fallback. Portable/installer после переключения entry point ещё не собирались.

## Контекст

Владелец отклонил косметический Tk-редизайн: стандартные controls, компоновка и текстовое взаимодействие не соответствуют продуктовой цели. Приложение должно быть голосовым пространством с персонажем, а не только чатом. Фирменная иконка сохраняется и становится источником фирменной анимации.

## Решение

Добавить `astra_desktop_qt.py` на PySide6/Qt Widgets и сохранить процессную границу `DesktopBridge` и schema-validated JSON events. Qt Fusion задаёт собственную отрисовку controls через единый style sheet; системный window frame остаётся для предсказуемого Windows window management.

- Главная: full-stage персонажа, отдельная голосовая консоль, явный mic state, пауза и быстрые действия.
- Отдельные страницы: диалог, задачи, файлы, память и настройки.
- `QLineEdit` и `QTextBrowser` обеспечивают platform-standard selection, context menu и Ctrl+C/V/X/A.
- `OrbitalLogo` использует неизменённый PNG знака Astra, вращающиеся дуги и мягкое свечение. Тот же компонент работает на splash и главной; reduced motion отключает движение.
- 2D остаётся fallback. Существующий authenticated Godot preview вызывается явной кнопкой; новые production персонажи — следующий этап.
- Настройки сохраняют существующий AIProfile v1, scopes и DPAPI. Открытие приложения не включает микрофон и не вызывает сеть.
- `src/qt_dialogs.py` переносит onboarding, каталог, журнал, файловые preview/operations/plans/questions и экспорт/импорт профиля на прежние bounded backends; `src/qt_voice_files.py` использует существующие JSON-схемы voice file IPC.
- `tools/build_desktop.py` собирает `Astra.exe` только из `astra_desktop_qt.py`; validator отдельно проверяет Qt Python-модули, бинарные модули и `qwindows.dll`. Tk fallback не удалён.
- Единый application style sheet покрывает отдельные `QDialog`; порядок правил не позволяет прозрачному `QWidget` перекрывать фон диалога.

## Почему Qt, а не WinUI или дальнейший Tk

Tk уже показал ограничение кастомной отрисовки и компоновки. WinUI потребовал бы отдельного .NET IPC host и полного packaging migration. Qt сохраняет Python integration, поддерживает Windows 10/11, high DPI, accessibility и собственные widgets без переноса runtime. Стоимость — новая зависимость PySide6-Essentials и необходимость повторного portable/installer gate.

## Границы

Новый UI не означает готовый full-body rig или lip-sync. До их реализации используются текущие assets без обрезки и честный 3D preview. EXE, installer, реальный микрофон, TTS и GPU остаются отдельными gates. Пользовательский ярлык не переключается.
