# Как загрузить проект на GitHub

## Вариант A — через Git в терминале

### 1. Установи Git

Проверь:

```bash
git --version
```

Если команда не работает, установи Git for Windows.

---

## 2. Открой папку проекта

В PowerShell или терминале VS Code:

```bash
cd путь\к\папке\astra-voice-assistant
```

Пример:

```bash
cd C:\Users\Rei\Desktop\astra-voice-assistant
```

---

## 3. Инициализируй Git

```bash
git init
git add .
git commit -m "Initial commit"
```

---

## 4. Создай пустой репозиторий на GitHub

1. Открой GitHub.
2. Нажми New repository.
3. Название: `astra-voice-assistant`.
4. Выбери Public или Private.
5. Не добавляй README, .gitignore и license, потому что они уже есть в проекте.
6. Нажми Create repository.

---

## 5. Привяжи локальный проект к GitHub

GitHub покажет команды. Обычно они такие:

```bash
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/astra-voice-assistant.git
git push -u origin main
```

Замени `YOUR_USERNAME` на свой ник GitHub.

---

## 6. Следующие обновления

После изменений в коде:

```bash
git status
git add .
git commit -m "Update project"
git push
```

---

## Важно

Файл `.env` не должен попадать на GitHub. Он уже добавлен в `.gitignore`.
На GitHub можно загружать только `.env.example`, потому что там нет настоящего API-ключа.
