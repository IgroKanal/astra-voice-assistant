# Adaptive capabilities: current implementation and next steps

## Current slice

The core reads the current Windows browser registrations at startup and combines
the discovered executables with `config/apps.json`. It checks both per-user and
machine-wide `App Paths` and `StartMenuInternet` registrations, then reads the
HTTPS `UserChoice` ProgId to find the OS-selected browser. A candidate is kept
only when its registry command resolves to an absolute existing `.exe` path.
The command parser takes the executable token only; spoken text is never added
to that command line.

The live OS default is used when no saved preference names a browser found on
this computer. A per-user preference can be kept separately at
`%LOCALAPPDATA%\AstraVoiceAssistant\capability_overrides.json`; this file is
versioned, size-limited, validated, and written atomically. It contains a
preference, not a permission grant or a discovered system fact. Existing
`BROWSER_PREFERRED` remains a compatibility fallback.
If the HTTPS default browser is not in the built-in browser name table or
`StartMenuInternet`, Astra now accepts its exact existing executable from the
OS `UserChoice` registration as a generic browser candidate. Script hosts and
Windows shell hosts are still excluded, and the handler command arguments are
not retained.

Discovery is read-only. It does not install software, change the Windows
default, enable a capability, or grant access to user files. If registry access
is unavailable, the existing app configuration remains usable.

There is also a bounded inventory of registered `App Paths` entries and local
Start Menu shortcuts. Shortcut names become display aliases; only an existing
absolute `.exe` target is kept, and shortcut arguments are ignored. The scan is
limited to the current-user and machine-wide Start Menu roots, skips linked
directories, and never starts a shortcut or target. Known command interpreters,
shell hosts and script launchers are excluded from discovery; the spoken request
is never used as an executable path or command line. A shortcut alias still
goes through the exact-match, one-time launch confirmation and file identity
recheck used by other discovered applications.
If a local command exactly names an otherwise unknown entry, Astra requests a
one-time confirmation. Confirmation expires after 20 seconds; before launching,
the core verifies the registration and file identity again. The language model
and routines cannot request this launch. Fuzzy recognition, richer application
names and per-application risk classification are still open.
If no exact registration is found in the initial inventory, the core refreshes
the inventory once, allowing newly registered applications to be found without
restarting. A different command cancels a pending confirmation and goes through
the ordinary wake-word and action checks.
Wake-only voice mode supports up to three consecutive follow-ups, so an open
request, application name and confirmation can be spoken in separate turns.
Timeout or failed recognition cancels the pending request.

The wake-only command «что доступно на этом компьютере» takes a fresh, read-only
snapshot of registered applications, browsers and the system default, audio
inputs, and supported AmneziaWG/WireGuard tunnels. It reports counts and
availability without speaking installed application names, executable paths,
or VPN profile names. A failed discovery source is reported as unavailable,
not as proof that the resource does not exist. The snapshot does not grant
permission; launching a newly discovered app and changing VPN state retain
their existing confirmation rules.

At startup, Astra inspects registered AmneziaWG and WireGuard tunnel services.
An explicit per-user choice wins when that service is still present; otherwise
an explicit `.env` choice is kept when present. A stale AmneziaWG/WireGuard
service name can adapt to the single currently discovered tunnel, while an
unknown explicit service name is preserved for a client outside this adapter.
If several supported candidates remain, the resolver does not choose one. The
selected supported service is used by the existing VPN controller, whose
connect/disconnect operations require a one-time confirmation. At action time,
if no configured preference resolves and several supported services remain,
voice asks for an ordinal from 1 to 9, rechecks the exact selected service,
stores that preference separately, and then asks for the action confirmation.
User speech is never used as a service name. The user choice is stored in the
versioned per-user override file, separate from `.env`; version 1 preference
files remain readable. The current detector recognizes only
AmneziaWG/WireGuard tunnel services and does not detect every commercial or
Windows-native VPN client. No VPN state was changed during automated tests.

When a user saves a microphone selection, the encrypted per-user profile stores
a SHA-256 fingerprint of its normalized device name and host API, not the raw
name or machine-local PortAudio index. On startup, the core enumerates input
metadata without opening a recording stream and resolves the fingerprint to
the current index only when there is one unique match. A missing or ambiguous
match skips the stale index and tries the Windows default once, with a status
message. A profile created on an older version still uses its saved index until
the user saves settings again. If the selected device cannot initialize, the
Windows default is tried and reported; if that also fails, voice input remains
unavailable. Automated tests inject fake device inventories and do not open a
real microphone.

The selected built-in character supplies the runtime assistant name and
grammatical gender. Both are included in the answer-model instruction; local
file-search, memory, reminder, dialogue-reset and common controller error
phrases use the selected gender. Other fixed text may still need review; model
compliance and real voice output require user testing. Voice-feedback commands
accept both masculine and feminine forms so the parser remains usable when the
user switches character gender.

## Security boundary

Discovery answers **what appears to exist on this PC**. It does not answer
**whether Astra may perform an action**. The current ActionPolicy still uses
typed action scopes for most actions. Web search and system information are
enabled as specific low-risk actions when user overrides load successfully.
`disabled_auto_scopes` in `capability_overrides.json` can disable either
automatic action (`browser`, `system`). Invalid overrides disable automatic
mode. Screenshots, URL opening, file access and other actions are not granted
by this mode. Runtime confirmation now covers closing an application,
connecting/disconnecting VPN and closing Yandex Music. Replacing the remaining
fixed scope catalog and reviewing risk classification for every action are
still open.

The runtime separately marks closing an application, connecting/disconnecting
VPN, and closing Yandex Music as actions that need one-time confirmation. The
exact typed action is held for at most 20 seconds; a changed command cancels
the pending request, and the action scope is checked again when the user says
yes. VPN status and ordinary media transport controls remain read-only or
reversible and do not ask for confirmation. File changes keep their existing
separate preview-and-confirm transaction.

Do not treat a discovered VPN service, device, executable, or file as an
authorization. Those require their own adapters and risk classification. A
confirmation must be bound to the exact pending action and expire; a general
spoken “yes” must not create a lasting permission.

## Remaining architecture work

1. Extend the typed capability inventory beyond the current application,
   browser, audio-input, and AmneziaWG/WireGuard snapshot to cover other VPN
   adapters and supported Windows features.
2. Separate discovered inventory, per-user overrides, and authorization state.
3. Keep ordinary reversible actions available by default; request confirmation
   immediately before sensitive or irreversible operations.
4. Expand VPN discovery to additional client adapters. The current
   AmneziaWG/WireGuard resolver honors a valid per-user preference, auto-selects
   only a unique discovered tunnel, and asks for an exact numbered voice choice
   when the configured service is stale and several candidates exist.
   Microphone selection uses a per-user hashed name/host-API fingerprint and
   refuses to guess when duplicate devices match; Windows Core Audio endpoint
   IDs remain a stronger option for identical devices.
5. Keep voice state events as the source of character animation state. The Qt
   scene and current 2D art are preserved; production layered art or a real VRM/
   Live2D-compatible model is still required before attempting polished new
   animation. Procedural 3D primitives remain out of the UI.

This is a foundation increment, not completion of version 3.2 or a Beta gate.
