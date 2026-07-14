# Astra v1.0.1 — Beta Bugfix & Reliability Update

## Release goal

This patch keeps the v1.0 Beta architecture and safety model while fixing
confirmed wake/STT/TTS and packaging reliability problems.

## Fixed

- Preserved URL paths, query strings, case-sensitive values and percent-encoding
  such as `https://example.com/CaseSensitive?Token=AbC`.
- Prevented truncated key commands such as `отправь нажми` from reaching LLM
  conversation fallback or pressing a key.
- Added `code-insiders` and `powershell_ise` to the terminal typing/Enter guard.
- Limited TTS prewarm by attempted generations, including failed/time-out attempts.
- Reduced beta defaults to one prewarm attempt and an 8-second generation timeout.
- Updated review/release archive names to v1.0.1.
- Added post-build ZIP validation for forbidden files, real `.env` files and API keys.

## Regression coverage

- Functional fake-`VoiceIO` test of the real `run_voice_mode` wake-only loop.
- No-wake command/router isolation.
- Direct and two-turn wake commands plus pending follow-up.
- Wake aliases and false substring matches.
- URL path/query case and percent-encoding preservation.
- Short close fragments `ок/ак/аг`.
- Terminal typing and Enter guards.
- TTS prewarm failed-attempt cap.
- Package secret and forbidden-file detection.

## Safety

- `ALLOW_COMMANDS_WITHOUT_WAKE=false` remains the beta default.
- Shell applications remain outside the whitelist.
- No arbitrary shell execution, Alt+F4, shutdown, reboot, delete, auto-commit or
  auto-push functionality was added.
