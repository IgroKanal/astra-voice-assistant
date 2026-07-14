# Astra Voice Assistant — v1.0.1 Beta

Astra is a Windows-only voice assistant for PC.

Current beta focus:

- wake-only voice runtime: Astra reacts after the wake phrase `Астра`;
- local safe skills for apps, sites, browser tabs, folders, VPN, windows, screenshots and system info;
- Gemini/OpenAI-compatible LLM fallback only for normal questions after wake phrase;
- beta safety gate: no command execution without wake phrase, no whitelisted `cmd.exe`, terminal text/Enter guards.

---

## 1. Requirements

- Windows 10/11
- Python 3.12
- Microphone
- Internet for Google Web Speech STT
- Gemini API key if LLM answers are needed
- Optional: AmneziaWG if VPN control is enabled

---

## 2. Install

```powershell
cd C:\Projects\astra-voice-assistant

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

copy .env.example .env
```

Then edit `.env`:

```env
GEMINI_API_KEY=PASTE_YOUR_GEMINI_KEY_HERE
```

If you want to test without LLM:

```env
LLM_ENABLED=false
```

Apply beta-safe wake settings:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\apply_v101_beta_env.ps1
```

---

## 3. Run modes

### Voice mode

```powershell
python main.py
```

Voice mode is wake-only by default.

Examples:

```text
Астра
открой YouTube
```

or directly:

```text
Астра, открой YouTube
Астра, статус VPN
Астра, переключись на Firefox
Астра, статус интер
Астра, стоп
```

Without wake phrase, commands are ignored in voice mode:

```text
открой YouTube
закрой вкладку
включи VPN
```

### Text mode

```powershell
python main.py --text
```

Text mode is for development and debugging. With beta defaults, command examples should use wake phrase:

```text
Астра, открой блокнот
Астра, открой youtube.com
Астра, статус VPN
Астра, помощь
```

### STT test mode

```powershell
python main.py --stt-test
```

Use this to check how the microphone/STT recognizes wake phrases and commands.

---

## 4. Double-click launchers

For local beta testing:

```text
start_astra_debug.bat
start_astra_text.bat
start_astra_hidden.vbs
```

Recommended order:

1. Test with `python main.py`.
2. Test with `start_astra_debug.bat`.
3. Only then test `start_astra_hidden.vbs`.

Hidden mode writes diagnostics to logs. Do not use hidden mode for the first test after a patch.

---

## 5. Autostart

Install autostart:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1
```

Remove autostart:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\uninstall_autostart.ps1
```

Autostart is optional for v1.0.1 Beta.

---

## 6. Safety model

Astra v1.0.1 Beta intentionally does not support:

- arbitrary shell/cmd/powershell commands from voice;
- shutdown/reboot/delete commands;
- Alt+F4 active-window closing;
- Telegram contact/message automation;
- browser extension control;
- pywinauto UI control.

Important safety defaults:

```env
ALLOW_COMMANDS_WITHOUT_WAKE=false
ALLOW_VOICE_CONVERSATION_WITHOUT_WAKE=false
VOICE_RUNTIME_MODE=wake_only
WAKE_ONLY_MODE=true
```

The LLM-router cannot execute local sensitive actions such as keyboard shortcuts, typing, screenshot, VPN, window or system info actions.

---

## 7. VPN control

Configure `.env`:

```env
VPN_ENABLED=true
VPN_PROVIDER=amneziawg
VPN_TUNNEL_SERVICE_NAME=AmneziaWGTunnel$pc-awg-2
VPN_MANAGER_SERVICE_NAME=AmneziaWGManager
```

Commands:

```text
Астра, статус VPN
Астра, включи VPN
Астра, выключи VPN
```

Starting/stopping Windows services may require administrator rights.

---

## 8. Verification

Run before commit/release:

```powershell
python -m compileall main.py src tools
python tools\smoke_test_v09_parser.py
python tools\smoke_test_v10_parser.py
python tools\smoke_test_v11_wake_runtime.py
python tools\smoke_test_v100_beta.py
python tools\smoke_test_v101_beta.py
python tools\validate_v10_config.py
python tools\astra_doctor.py
```

Manual voice checklist:

```text
открой YouTube
Астра
открой YouTube
Астра, открой YouTube
Астер, стоп
Астэр, стоп
Астры, стоп
Астра, открой https://example.com/CaseSensitive?Token=AbC
Астра, закрой ок
Астра, статус VPN
Астра, переключись на Firefox
Астра, статус интер
Астра, стоп
```

Expected:

- no-wake `открой YouTube` is ignored in voice mode;
- `Астра` opens the command session;
- direct wake commands work;
- VPN/window/browser/system commands stay local;
- no command-like no-wake phrase goes to LLM-router.

---

## 9. Release packaging

Build review package:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_review_package.ps1
```

Build beta release package:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_beta_package.ps1
```

Do not publish real `.env` or API keys.

The build scripts run `tools\validate_package.py` automatically. Expected
archives are `astra-v1.0.1-beta-review-package.zip` and
`astra-v1.0.1-beta-release.zip` in `C:\Projects`.

---

## 10. Known limitations

See `KNOWN_LIMITATIONS.md`.
