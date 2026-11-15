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
