# Astra v1.0 Beta release notes

## Main beta goals

- Wake-only voice runtime.
- Beta safety gate for command execution.
- Local safe PC skills.
- AmneziaWG VPN control.
- Window awareness.
- Browser/folder/system commands.
- Review/release package builders.

## Important defaults

```env
ALLOW_COMMANDS_WITHOUT_WAKE=false
ALLOW_VOICE_CONVERSATION_WITHOUT_WAKE=false
VOICE_RUNTIME_MODE=wake_only
WAKE_ONLY_MODE=true
```

## Final fixes before beta

- Repaired mojibake `WAKE_RESPONSE_TEXT` handling.
- Added common STT wake aliases: `астер`, `астэр`, `астры`.
- Added beta environment repair script.
- Added beta smoke test.
- Guarded short STT fragments like `закрой ок`.
- Kept dangerous local actions blocked from LLM-router.

## Release gate

Before tagging/releasing:

```powershell
python -m compileall main.py src tools
python tools\smoke_test_v09_parser.py
python tools\smoke_test_v10_parser.py
python tools\smoke_test_v11_wake_runtime.py
python tools\smoke_test_v100_beta.py
python tools\validate_v10_config.py
python tools\astra_doctor.py
```
