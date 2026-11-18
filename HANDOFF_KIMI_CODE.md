# HANDOFF — продолжение разработки Astra

Дата обновления: 2026-11-14.

## Текущее состояние

Основной desktop entry point — `astra_desktop_qt.py` на PySide6/Qt Widgets. Старый `astra_desktop.pyw` остаётся ручным Tkinter-fallback; runtime, grants, ActionPolicy, DPAPI, STT/TTS/LLM и JSON-схемы не переписывались.

Новая Qt-оболочка теперь содержит шесть разделов: «Главная», «Диалог», «Задачи», «Файлы», «Память», «Настройки», а также отдельные каталог команд и журнал действий. Перенесены и проверены:

- трёхшаговый первый запуск без автоматического включения микрофона;
- выбор микрофона и SAPI-голоса, скорость, громкость и локальное прослушивание по кнопке;
- экспорт и импорт зашифрованного профиля с подтверждением замены;
- человекочитаемые названия и описания всех scopes;
- файловый поиск, текстовый/image preview, временные write/trash grants, операции, undo/recover;
- локальные вопросы по выбранным файлам и bounded file plans;
- voice file search/open/read/question через существующие IPC-схемы;
- `QSystemTrayIcon` с открытием окна, явным переключением микрофона, выходом и generic-уведомлениями;
- общая Qt-тема для главного окна и отдельных диалогов.

Дополнительные Qt-модули:

- `src/qt_theme.py`
- `src/qt_widgets.py`
- `src/qt_dialogs.py`
- `src/qt_voice_files.py`

Синтетические preview без микрофона, сети и личных данных:

- `visual_previews_qt/home.png`
- `visual_previews_qt/dialogue.png`
- `visual_previews_qt/settings.png`
- `visual_previews_qt/launch-animation.png`
- `visual_previews_qt/files.png`
- `visual_previews_qt/file-operations.png`
- `visual_previews_qt/onboarding.png`
- `visual_previews_qt/command-catalog.png`

Фирменная иконка `assets/branding/astra.*` и существующие персонажи не изменялись.

## Packaging

`tools/build_desktop.py` теперь собирает `Astra.exe` только из `astra_desktop_qt.py`; Tk fallback не добавляется вторым интерфейсом. `tools/validate_desktop_package.py` проверяет Qt-модули, `QtCore/QtGui/QtWidgets` и Windows-плагин `qwindows.dll`. `tools/validate_installer.py` и packaged runtime checks требуют bundled Qt LGPL/GPL license texts. `THIRD_PARTY_NOTICES.md` содержит Qt/PySide6 notice и ссылки на upstream source archives; `QT_LGPL_LICENSE.txt` и `QT_GPL_LICENSE.txt` входят в build fingerprint и portable package.

`start_astra_app.vbs` запускает Qt entry point. `tools/run_current_gate.ps1` определяет корень относительно своего расположения, пропускает только repository-only `git status`/`git diff --check` при отсутствии `.git` и компилирует старый fallback, Qt UI и runtime. `.github/workflows/windows-checks.yml` компилирует оба desktop entry point.

Portable ZIP, relocated package, EXE и installer после переключения Qt **не собирались**: пользователь явно запретил сборку без отдельного запроса, а в handoff отсутствует verified Godot 4.7.2 Windows executable для `ASTRA_GODOT_EXECUTABLE`. Packaging-код интегрирован, но package gates не заявляются как пройденные.

## Проверенные результаты

```powershell
.venv/Scripts/python.exe -m unittest tools.test_qt_desktop
```

Результат: 14 Qt-тестов успешно. Проверяются шесть разделов, явный голосовой режим, clipboard shortcuts, DPAPI-профиль, аудио и scopes, onboarding, каталог, журнал, write grant/отзыв, симуляция плана без чтения файлов, отзыв file-question session, explicit preview success flag, voice IPC без workspace и подтверждение импорта профиля.

```powershell
.venv/Scripts/python.exe -m py_compile astra_desktop_qt.py src/qt_theme.py src/qt_widgets.py
```

Результат: успешно. Полный gate дополнительно компилирует `src/qt_dialogs.py`, `src/qt_voice_files.py`, старый fallback и runtime.

```powershell
.venv/Scripts/python.exe tools/capture_qt_preview.py
```

Результат: успешно; восемь PNG обновлены и визуально проверены. Отдельные диалоги используют тёмную тему; стандартной Tk-компоновки в Qt preview нет.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_current_gate.ps1
```

Результат: успешно; 362 unit/integration tests, smoke checks, config validators и Astra Doctor прошли. В текущем handoff нет `.git`, поэтому repository-only git checks были корректно неприменимы; это не заменяет будущий `git diff --check` в репозитории.

Реальный микрофон, Windows TTS, GPU, переносимый relocated runtime, portable ZIP и installer вручную после Qt ещё не проверялись.

## Полная визуальная переделка и персонажи (2026-11-16, после принятия Qt-оболочки)

Реализовано:

- Пользовательские цельные full-body 2D-референсы `Astra_4_Characters_2D_References.zip` сохранены как `assets/avatars/full_*.png`: лица, причёски, костюмы и акценты соответствуют исходным четырём персонажам, фон прозрачный, каждый персонаж показан от головы до обуви. Оригинальные бюст-портреты оставлены как fallback.
- `src/desktop_settings.py`: все четыре профиля по умолчанию используют full-body idle-кадры и отдельные `*_speaking.png` кадры с аккуратно открытым ртом. Генератор `tools/generate_fullbody_speaking_frames.py` воспроизводит speaking-варианты поверх утверждённых full-body лиц.
- `src/qt_widgets.py`: `CharacterStage` разделяет полноразмерный арт на слои «тело/голова» и заметно анимирует их отдельно: голова кивает, поворачивается и реагирует на listening/recognizing/speaking, тело дышит, покачивается и микродвигется при речи. Сцена включает ореол, тройные вращающиеся кольца, пьедестал, отражение, орбитальные частицы, индикаторы состояний, speaking-кадр с открытым ртом и двойную волну речи. Поддержан прозрачный `desktop_mode` без подписей и с drag-and-drop; `reduced_motion` отключает движение без перезапуска.
- `astra_desktop_qt.py` и `src/qt_theme.py`: Qt-интерфейс полностью переведён в минималистичную cyan/glass систему Astra Glass. Убрана боковая колонна и отдельный дублирующий раздел «Персонаж»; сверху остаются «Голос», «Задачи», «Файлы», «Память», «Настройки», всегда видимое «Сохранить» и компактное «Ещё». Главный экран — голосовой центр с transcript и резервным текстом. Раздел напоминаний пересобран компактно, ручные разрешения скрыты из UI. Смена образа сразу обновляет основную и desktop-сцену, а «Сохранить» закрепляет её в DPAPI. Обычный крестик уводит приложение в фон; полный выход — только «Ещё → Полностью выйти» или меню трея. `DesktopCharacterWindow` остаётся единственным визуальным персонажем: безрамочный прозрачный desktop-pet с drag-and-drop и синхронизацией. Boot-анимация заменена полноэкранным прозрачным слоем поверх рабочего стола: масштабирующийся логотип, кольца, стадии и прогресс, затем fade-in окна.
- `prototypes/3d_avatar/scripts/avatar_viewer.gd`: полноразмерный 3D-blockout приведён к full-body 2D-референсам и отдельным 3D-стилевым концептам пользователя. Для всех персонажей обновлены силуэт, цвета и детали костюма: мельче голова, приталенный торс, отдельные лацканы и полы пиджака, светящиеся швы, ремень с пряжкой, пальцы, коленные вставки, массивные ботинки с носами и подошвами. У Мику длинные слоистые пряди, у Рэна семь шипов волос, у Саи каре с фиолетовой прядью, у Кая волнистый пробор. Камера показывает полный рост; персонажный акцентный свет, контурный свет и кольцо на полу используют цвет профиля/состояния. Протокол IPC (token + loopback, пять состояний, CLOSE) не изменён. После непройденной художественной приёмки 3D временно отложен и не открывается из Qt-интерфейса.
- `tools/validate_desktop_package.py`: обязательный список ассетов расширен full-body файлами.
- Тесты: `tools/test_qt_desktop.py` включает 25 проверок: голосовой центр и порядок пяти разделов, полноэкранный boot-слой, фоновое закрытие, desktop-персонаж, мгновенный предпросмотр смены образа, закреплённое сохранение, прозрачные RGBA full-body ассеты, слоистую анимацию, состояния сцены, полноэкранный 2D-режим, reduced motion, сворачиваемое подключение ИИ и `_voice_label`. Старый тест Tk-fallback учитывает новые пропорции full-body изображения. `capture_qt_preview.py` сохраняет `home.png`, `dialogue.png`, `tasks.png`, `desktop-character.png` и `character-speaking.png`.
- Полный текущий gate после визуальной переделки и персонажей: `tools/run_current_gate.ps1` успешно, 373 теста OK.

Архитектурный недочет для следующего ядра/GPT: пользователь правильно указал, что возможности сейчас слишком жёстко зашиты в коде ядра и плохо адаптируются к другому компьютеру. Нужно убрать ручной список разрешений из обычного UX и перейти к модели автоматической адаптации: ядро само обнаруживает приложения, VPN-клиентов, устройства, браузеры и доступные команды на конкретном ПК; включает безопасные возможности автоматически; конфликтные или опасные действия запрашивают подтверждение в момент выполнения; пользовательский override хранится отдельно. Текущий ActionPolicy/grants runtime в этом handoff не менялись, поэтому UI только скрывает ручные чекбоксы, но не решает архитектуру.

Ограничения этапа: speaking-кадры сделаны локальной композицией маленького открытого рта поверх референсов и подлежат художественной приёмке; 3D временно отложен — процедурные OpenGL/Godot-примитивы не прошли художественную приёмку и удалены из пользовательского UI. Для возврата к 3D нужны настоящие модели персонажей (GLB/VRM или аналог), а не новая отрисовка примитивами. Verified Godot 4.7.2 executable в handoff отсутствует, поэтому `tools/validate_3d_avatar.py` и runtime-приёмка Godot не выполнялись. На ПК пользователя обнаружены голоса: Microsoft Irina (ru-RU, женский), Zira и David (en-US), Alan (RHVoice, en-US); русского мужского голоса нет — установка через настройки Windows остаётся ручным шагом пользователя.

## Правила

- Отвечать пользователю по-русски.
- Работать в проекте, не трогать пользовательские данные вне workspace.
- Голосовой режим по умолчанию не должен запускать микрофон автоматически.
- Пользовательский текст должен экранироваться перед вставкой в rich-text/HTML.
- Clipboard shortcuts `Ctrl+C`, `Ctrl+V`, `Ctrl+X`, `Ctrl+A` должны оставаться рабочими.
- Не понижать существующие ограничения безопасности ради удобства.
- Пакеты, portable builds и установщики собирать только после явного запроса пользователя.
- Исходный ZIP `Astra_Kimi_Visual_Handoff_3.1.zip` считать старым снапшотом, а не актуальным состоянием.

## Команды проверки

```powershell
.venv/Scripts/python.exe -m unittest tools.test_qt_desktop
.venv/Scripts/python.exe -m py_compile astra_desktop_qt.py src/qt_theme.py src/qt_widgets.py
.venv/Scripts/python.exe tools/capture_qt_preview.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_current_gate.ps1
```

После `capture_qt_preview.py` обязательно визуально проверить обновлённые PNG в `visual_previews_qt`.
