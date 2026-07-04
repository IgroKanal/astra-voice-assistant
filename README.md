# Астра — голосовой ассистент для Windows

MVP голосового ассистента на Python для Windows 10/11.

Ассистент умеет:

- слушать микрофон;
- активироваться по имени `Астра`;
- открывать приложения из `config/apps.json`;
- закрывать приложения из `config/apps.json`;
- отправлять обычные вопросы в LLM через OpenAI-compatible API;
- озвучивать ответы через TTS;
- работать в тестовом текстовом режиме без микрофона.

---

## 1. Требования

- Windows 10/11
- Python 3.10+
- Git, если нужно загрузить проект на GitHub
- Микрофон
- Интернет для Google Web Speech STT
- API-ключ LLM, если нужны ответы на обычные вопросы

---

## 2. Быстрый запуск

### Шаг 1. Создай виртуальное окружение

```bash
python -m venv .venv
```

### Шаг 2. Активируй окружение

PowerShell:

```bash
.\.venv\Scripts\Activate.ps1
```

Если PowerShell запрещает запуск скриптов, выполни:

```bash
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Потом снова:

```bash
.\.venv\Scripts\Activate.ps1
```

### Шаг 3. Установи зависимости

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Шаг 4. Создай `.env`

Скопируй пример:

```bash
copy .env.example .env
```

Открой `.env` и замени:

```env
LLM_API_KEY=your_gemini_api_key_here
```

на свой API-ключ.

Если пока нет ключа, можно отключить LLM:

```env
LLM_ENABLED=false
```

Тогда команды открытия и закрытия приложений будут работать, но обычные вопросы — нет.

---

## 3. Запуск

### Голосовой режим

```bash
python main.py
```

Примеры фраз:

```text
Астра, открой блокнот
Астра, закрой блокнот
Астра, открой калькулятор
Астра, объясни что такое API
Астра, стоп
```

### Текстовый режим без микрофона

```bash
python main.py --text
```

Этот режим нужен для проверки логики, если микрофон или PyAudio ещё не настроены.

---

## 4. Как добавить приложение

Открой файл:

```text
config/apps.json
```

Добавь приложение в блок `apps`:

```json
"vscode": {
  "aliases": ["код", "vs code", "visual studio code"],
  "open_command": ["C:\\Users\\USERNAME\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"],
  "process_name": "Code.exe"
}
```

Правила:

- `aliases` — как ты будешь называть приложение голосом;
- `open_command` — команда запуска;
- `process_name` — имя процесса для закрытия через `taskkill`;
- обратные слэши в JSON-пути надо писать двойными: `\\`.

---

## 5. Настройка имени ассистента

В `.env`:

```env
ASSISTANT_NAME=Астра
WAKE_PHRASES=астра,эй астра,привет астра
```

Можно поменять, например:

```env
ASSISTANT_NAME=Вега
WAKE_PHRASES=вега,эй вега,привет вега
```

---

## 6. Настройка LLM

### Gemini, стартовый вариант

```env
LLM_PROVIDER=gemini
LLM_API_KEY=your_gemini_api_key_here
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.5-flash
```

### OpenAI

```env
LLM_PROVIDER=openai
LLM_API_KEY=your_openai_api_key_here
LLM_BASE_URL=
LLM_MODEL=gpt-4.1-mini
```

### Ollama локально

```env
LLM_PROVIDER=ollama
LLM_API_KEY=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.1
```

---

## 7. Частые проблемы

### `No module named ...`

Зависимости не установлены или виртуальное окружение не активировано.

Решение:

```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

### Ошибка установки PyAudio

Попробуй обновить pip:

```bash
python -m pip install --upgrade pip setuptools wheel
pip install PyAudio
```

Если не получилось, сначала тестируй проект в текстовом режиме:

```bash
python main.py --text
```

---

### Ассистент не слышит микрофон

Проверь:

- разрешение микрофона в Windows;
- выбран ли правильный микрофон по умолчанию;
- работает ли микрофон в других приложениях;
- не занят ли микрофон другим приложением.

---

### LLM не отвечает

Проверь:

- есть ли `.env`;
- правильно ли указан `LLM_API_KEY`;
- не стоит ли `LLM_ENABLED=false`;
- есть ли интернет;
- правильная ли модель указана в `LLM_MODEL`.

---

## 8. GitHub

Инструкция по загрузке проекта на GitHub лежит в файле:

```text
GITHUB_UPLOAD.md
```

---

## 9. Безопасность

- Реальный `.env` не загружается на GitHub.
- API-ключи нельзя писать в коде.
- Ассистент запускает только приложения из `config/apps.json`.
- Произвольные команды пользователя не выполняются.
