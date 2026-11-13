# LLM provider boundary

Status: implemented as part of the Astra 3.0 Beta candidate. This is an
internal architecture boundary, not a promise of automatic model failover.

## Responsibilities

- `AIClient` owns Astra prompts, bounded local dialogue, memory consent,
  model fallback lists for the explicitly selected compatible provider,
  timing logs, answer cleanup, and the safe parsing of classifier output.
- `TextProvider` exposes answer generation, single-turn classification, and
  optional warmup.
- `OllamaProvider` sends requests only to the configured loopback Ollama
  endpoint. It never downloads models and never falls back to a remote API.
- `OpenAICompatibleProvider` serves the configured compatible endpoint. It
  receives the current question and system prompt only; local conversation
  history and personal memory are not passed to it.
- `DisabledProvider` makes disabled or unconfigured AI explicit and does not
  create a network client.

Providers return text only. Command JSON still passes through Astra's parser,
confidence checks, `ActionPolicy`, permission grants, and typed dispatch. A
provider cannot directly open an application, access files, or call the shell.

## Privacy and failure behavior

The user selects the provider in settings. That choice is not changed after a
failure. In particular, an unavailable local model does not send its prompt to
the cloud. Personal memory is available only to the local provider after the
existing opt-in. A compatible endpoint can be a user-configured service; its
network and data-handling properties depend on that service.

## Still open for later v3 work

- Explicit task-based local/cloud routing with a visible, testable data policy.
- A useful no-network fallback for tasks that do not require a model.
- Evaluation against a representative Russian voice-command and question set.
- Real microphone, model-quality, and wake-to-first-audio latency acceptance.

Do not add implicit cloud fallback or send local dialogue/memory to a remote
provider as part of that future work.
