# Windows installer preview

The Inno Setup script installs Astra for the current Windows user under
`%LOCALAPPDATA%\Programs\Astra Voice Assistant`; it does not request UAC.
It creates a Start menu shortcut and offers an optional Desktop shortcut.

## Build a preview

1. Build and validate the portable preview with `tools/build_desktop.py`.
2. Install a signed Inno Setup 7 compiler and set `ASTRA_ISCC` to its `ISCC.exe`
   path. Inno Setup 7.1.1 was the compiler used for the current dev.21 preview.
3. Run:

   ```text
   python tools/build_installer.py --source-dir <verified-preview-folder> --output-dir <installer-output-folder>
   ```

4. Validate installation, runtime launch, per-user logs, and data-preserving
   uninstall:

   ```text
   python tools/validate_installer.py <path-to-Astra-Setup.exe>
   ```

The build script rejects a preview whose manifest version differs from the
source, a manifest that does not explicitly exclude personal `.env`, and an
actual `.env` file in the package.

## User data and uninstall

Settings, memory, reminders, TTS cache, and application logs live below
`%LOCALAPPDATA%\AstraVoiceAssistant`, outside the installation directory.
The installer does not delete that directory during uninstall. The validation
script installs under a path with spaces, runs the packaged text runtime,
checks that logs are outside the install root, and verifies a user-data
sentinel survives removal.

The current Setup executable is an unsigned development preview. Signed
updates, rollback, release signing, and a user-facing automatic update flow are
still roadmap work. The Inno Setup 7 compiler reports `Non-commercial use only`;
commercial distribution requires appropriate licensing or a different
installer compiler.
