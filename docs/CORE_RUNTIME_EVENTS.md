# Core runtime event contract for the Kimi desktop client

This document describes the local stdout event contract between Astra's core runtime and a desktop client. It adds web-source metadata without changing the existing human-readable event path.

## Event framing

Each event is one UTF-8 JSON line prefixed with `@ASTRA_EVENT `:

```json
{"version":1,"type":"assistant","text":"Источники: [1] Документация — https://docs.example/page","data":{"kind":"web_sources","sources":[{"index":1,"title":"Документация","url":"https://docs.example/page"}]}}
```

`version`, `type`, and `text` retain their existing meanings. The optional `data` object is currently supported only for `type: "assistant"` with `kind: "web_sources"`. Source entries contain consecutive integer indices, display titles, and HTTPS URLs. The parser rejects credentials, loopback/private/reserved IPs, local hostnames, controls, malformed links, and extra fields.

## Core APIs

- `src.runtime_events.parse_event(line)` remains the legacy API and returns `(type, text)`, preserving the current Astra Desktop chat.
- `src.runtime_events.parse_event_record(line)` returns a validated `RuntimeEvent(kind, text, data)` for clients that render structured metadata.
- `DesktopBridge.events` is the bounded legacy queue of `(type, text)` pairs.
- `DesktopBridge.typed_events` is a bounded queue of metadata-bearing `RuntimeEvent` records (64 entries). Poll it promptly. If it fills, Astra drops the typed copy while retaining the readable text event in the legacy queue.

The `web_sources` metadata is display data only. A client may render it as a source card and open a link only after the user clicks it; it must never treat a citation as a command or auto-open the URL.

## Web research disclosure

Voice web answers require the separate `web_research` permission, which is off by default, an explicit web-answer command, and the selected local Ollama provider. Astra sends the explicit search query to Bing and sends retrieved page excerpts only to that local Ollama instance. There is no cloud model fallback. If Edge TTS is selected, the answer text also goes to that network speech service; Windows SAPI keeps speech synthesis local. The new client should make this data flow clear and provide a visible way to review or revoke the permission.

## Compatibility

Older clients continue receiving the source list as normal assistant text. New clients can use `parse_event_record` or `DesktopBridge.typed_events` to render structured citations without scraping that text.

## Character and model integration

The core's `Settings.assistant_name` and `Settings.assistant_gender` are separate: the latter is `female` or `male` and governs Russian self-reference, regardless of the custom name. The existing encrypted desktop profile selects gender via the active `avatar_id`: `female_miku` and `female_saya` map to `female`; `male_ren` and `male_kai` map to `male`. Profile settings are applied when the runtime starts; restart the runtime after a profile change. A client using another profile store must explicitly pass both settings to its core instance, or use `ASSISTANT_NAME` and `ASSISTANT_GENDER` with desktop profile loading deliberately disabled. Merely changing a picture does not update core settings.

Human-readable state events remain unchanged. A new client may explicitly set both `ASTRA_DESKTOP_EVENTS=1` and `ASTRA_ACTIVITY_EVENTS=1` when it starts the runtime to opt in to machine-readable events such as `{"version":1,"type":"activity","text":"speaking:start"}` and `speaking:stop`. The allowed activity names are `listening`, `recognizing`, `thinking` and `speaking`; each has `start` and `stop` phases. Activities may overlap (streamed speech can begin while a model is still generating), so track each activity independently rather than treating them as a single exclusive state. Clear all active indicators when the runtime process exits or its connection is lost. The speech activity covers the TTS attempt, including synthesis and possible playback failure; it does not promise audible sound. This protocol does not provide phonemes, lip sync, emotions, animation assets or window lifecycle controls. Without the explicit opt-in, older clients receive no new activity events. Do not infer that a model has performed an action from its text. File and Windows actions remain subject to the core's typed action policy.

`DesktopBridge.events` forwards these opt-in `("activity", "name:phase")` tuples. They do not appear in `DesktopBridge.typed_events`, which currently carries events with structured `data` only. A client reading runtime stdout directly can use `parse_event_record`.

OpenRouter conversation configuration uses the existing `compatible` provider, `https://openrouter.ai/api/v1` and `openai/gpt-6-luna`. The core requests `reasoning.effort=none` for this exact endpoint and model. `openai/gpt-6-luna-decisions` uses a different decision endpoint and is not a conversational model. No key is included here; cloud requests require an independently configured key and send the current user question and system prompt to the selected provider. Local notes and local dialogue history are not sent. This setup has only mock coverage until a real key and network test are available.
