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
If a network-adapter provider raises unexpectedly, the network counts are
reported as unavailable while the rest of the snapshot remains usable; one
failed discovery source must not stop the voice runtime.

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
inputs and outputs, Windows network adapters, and supported AmneziaWG/WireGuard
tunnels, plus native Windows RAS phonebook profiles. RAS discovery checks that
Remote Access Connection Manager (`RasMan`) is already running before loading
`rasapi32.dll`, because loading that library can start the service. It then
calls the read-only `RasEnumEntriesW` API and retains profile names only in the
transient discovery result; the voice summary includes only a count. RAS
profiles can represent VPN or dial-up connections, so this count is not
reported as a VPN count and does not imply that Astra can manage those
profiles. A second read-only pass asks `RasGetEntryPropertiesW` for the native
entry type and reports a separate count only for entries Windows identifies as
VPN. The code uses the documented `RASENTRYW` layout but reads only `dwType`;
other profile fields are discarded. If a profile cannot be classified, the VPN
count is marked unavailable rather than guessing. Classification is capped at
128 entries per snapshot and rejects remote phonebook paths. No credentials are
queried, no profile names are spoken, and no connection is started or stopped.
Detecting a Windows VPN profile does not yet mean Astra can connect to it.
Audio endpoint
enumeration reads metadata only and does not open a microphone or playback
stream. Network discovery counts Windows components
marked with the NDIS `NCF_VIRTUAL` characteristic (`0x1`); this can include
VPN, virtual-machine and container adapters and does not identify a particular
client. It reports counts and availability
without speaking installed application names, executable paths, adapter names,
or VPN profile names. A failed discovery source is reported as unavailable,
not as proof that the resource does not exist. The snapshot does not grant
permission; launching a newly discovered app and changing VPN state retain
their existing confirmation rules.

System battery status now uses Win32 `GetSystemPowerStatus`, and screenshot
capture uses `GetSystemMetrics` plus Pillow. These core actions no longer start
PowerShell. Screenshot output is limited to the primary display, bounded by a
pixel-count limit, and reported successful only when a non-empty PNG exists.

VPN service status and transitions now use the typed Windows Service Control
Manager API. The service name is passed as a service identifier, never composed
into a shell command. Reads request query access only; start and stop request
only the matching operation rights. State changes poll for at most 60 seconds,
and the existing voice confirmation and exact-service revalidation still run
before a transition. This changes the adapter implementation, not which VPNs
are detected or which operations are authorized.

Window focusing tries native Win32 activation first. The `WScript.Shell` fallback
is optional: if Windows PowerShell is unavailable, focus simply reports failure
when native activation was also denied; it does not block runtime startup or
other commands. The PID passed to that fallback is range-checked, and no spoken
text is included in the script. Windows may deny foreground activation while
the user is interacting with another application.

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
versioned per-user override file, separate from `.env`; preference files from
versions 1 and 2 remain readable. The current detector recognizes only
AmneziaWG/WireGuard tunnel services and does not detect every commercial or
Windows-native VPN client. No VPN state was changed during automated tests.

When a user saves a microphone selection, the encrypted per-user profile stores
a SHA-256 fingerprint of its normalized device name and host API, not the raw
name or machine-local PortAudio index. On Windows, a second hash of the opaque
Core Audio endpoint ID is stored in the separate per-user capability overrides
file. Raw endpoint IDs and friendly names are never persisted. Core Audio is
matched to a PortAudio entry only when the normalized friendly name identifies
one endpoint; identical names remain unresolved. At startup, the endpoint hash
is preferred, then the older label hash is used only for one unique match. This
keeps the selected input stable across PortAudio index changes while allowing
older profiles and systems without Core Audio metadata to fall back safely.
Missing or ambiguous matches skip the stale index and try the Windows default
once, with a status message. A profile created on an older version still uses
its saved index until the user saves settings again. If the selected device
cannot initialize, the Windows default is tried and reported; if that also
fails, voice input remains unavailable. Automated tests inject fake device
inventories; Core Audio discovery reads metadata only and never opens a
recording stream.

The selected built-in character supplies the runtime assistant name and
grammatical gender. Both are included in the answer-model instruction; local
file-search, memory, reminder, dialogue-reset and common controller error
phrases use the selected gender. Other fixed text may still need review; model
compliance and real voice output require user testing. Voice-feedback commands
accept both masculine and feminine forms so the parser remains usable when the
user switches character gender.
Automatic SAPI selection prefers an installed Russian voice whose reported or
recognized gender matches the active character. An unclassified Russian voice
can serve as a neutral fallback, but a known opposite-gender voice is skipped;
an explicitly selected voice remains an intentional override. This avoids
silently using a clearly female local voice for a male character. If no
compatible voice exists, Russian SAPI fallback is unavailable until a suitable
voice is configured or installed. Real audio quality still needs user review.

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
   browser, audio-input/output, network-adapter, and AmneziaWG/WireGuard
   snapshot to cover other VPN adapters and supported Windows features.
2. Separate discovered inventory, per-user overrides, and authorization state.
3. Keep ordinary reversible actions available by default; request confirmation
   immediately before sensitive or irreversible operations.
4. Expand VPN discovery and then add explicitly confirmed adapters. Native
   Windows RAS profiles are classified as VPN or non-VPN using their Windows
   entry type, but RAS profile management is not implemented. The current
   AmneziaWG/WireGuard resolver honors a valid per-user preference,
   auto-selects only a unique discovered tunnel, and asks for an exact numbered
   voice choice when the configured service is stale and several candidates exist.
   Microphone selection uses per-user hashes of the unique Windows Core Audio
   endpoint and the legacy name/host-API fallback. Exact mapping is limited to
   unique normalized friendly names; duplicate names remain ambiguous and use
   the Windows default rather than guessing.
5. Keep voice state events as the source of character animation state. The Qt
   scene and current 2D art are preserved; production layered art or a real VRM/
   Live2D-compatible model is still required before attempting polished new
   animation. Procedural 3D primitives remain out of the UI.

This is a foundation increment, not completion of version 3.2 or a Beta gate.
