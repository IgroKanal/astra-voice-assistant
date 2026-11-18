# Astra v1.1 — Daily Workflow & Context Update (Beta)

## Release goal

Make common ChatGPT, Telegram, folder, browser, YouTube and music workflows
shorter without expanding Astra into arbitrary PC or shell control.

## Added

- Exact-match safe routines from `config/routines.json`. The default `рабочий
  режим` opens ChatGPT and opens or focuses Telegram.
- Bounded recent-action context for `закрой его` and explicit focus pronouns.
  Context stores one successful local target and expires after 120 seconds by
  default.
- `вернись обратно` for the previous window recorded by Astra's own successful
  focus action.
- Global media play/pause, next, previous and stop commands using fixed Windows
  virtual-key codes.
- Local YouTube search with punctuation-preserving query extraction.
- Ambiguous `включи музыку` follow-up: local Music folder or Yandex Music.
- Russian accusative `Яндекс музыку` resolves to the Yandex Music website.
- Observed STT substitutions `откроется/откроеться` stay in the local open
  path, preventing action-like text from reaching conversation LLM fallback.
- Source-to-ZIP byte comparison in package validation to detect stale builds.

## Safety

- `ALLOW_COMMANDS_WITHOUT_WAKE=false` remains the beta default.
- New no-wake routine, media and context-like commands are blocked before the
  action layer and LLM-router.
- Routines allow only `open_app`, `open_url` and `open_folder`, with at most
  eight steps and exact alias matching.
- Routine URL schemes other than HTTP/HTTPS are rejected; shell app targets and
  unknown config fields are rejected.
- `ROUTINE` remains blocked as an LLM-router action.
- No arbitrary shell, Alt+F4, shutdown, reboot, delete, auto-commit or auto-push
  functionality was added.

## Regression coverage

- All v0.9, v0.10, v0.11, v1.0 and v1.0.1 smoke tests remain in the gate.
- New `smoke_test_v11_daily_workflow.py` covers routine execution, no-wake
  isolation, media parsing, bounded context, previous-window routing, music
  follow-up, YouTube query preservation, unsafe routine rejection and stale ZIP
  detection.

## Deferred

- Telegram contact/message automation and targeted typing.
- File move/delete operations and arbitrary filesystem access.
- Exact volume percentage control.
- Dedicated offline wake-word engine, GUI/tray and Windows Service.
