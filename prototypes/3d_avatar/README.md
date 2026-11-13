# Astra 3D avatar renderer spike

This renderer remains a procedural prototype, but Astra 1.4.0-dev.14 now opens it from the Voice settings as a separate preview window. In dev.31 the four original profiles have distinct male/female shoulder, torso, face and eye proportions, plus a simple blink animation. The portable package bundles the official Godot 4.7.2 Windows runtime. No models or third-party character assets are downloaded. The main desktop window still uses its 2D portrait; these proportions are a blockout and need human visual acceptance before any production claim.

## Run

Open this folder with Godot 4.7.2 stable, or run a preview with a selected profile and display name:

```text
Godot_v4.7.2-stable_win64.exe --path prototypes/3d_avatar -- --avatar=female_saya --name=Сая
```

Accepted IDs: `female_miku`, `male_ren`, `female_saya`, `male_kai`. Unknown IDs fall back to `female_saya`. The scene is visual-only; it cannot access the microphone, files, shell, or Astra runtime.

## Validate headlessly

```text
python tools/validate_3d_avatar.py --godot "C:/Path/To/Godot_v4.7.2-stable_win64.exe"
```

This validates project import, startup for all four IDs, five presentation states, custom display names and safe fallbacks, not visual quality or target-GPU performance. A human still needs to inspect the rendered characters.

## Integration boundary

The Voice settings button launches one preview process. The input protocol contains only a built-in avatar ID and bounded display name; the renderer has no microphone, file, shell-command or Astra-runtime access. Keep the integrated 2D portrait as the main-window fallback. Remaining product work: visual/performance acceptance, live-state synchronization, 3D selection as a persisted mode and a renderer integrated into the main window. The portable ZIP includes the engine MIT license and the 4.7.2 third-party copyright list.

Godot engine license: MIT; see `THIRD_PARTY_NOTICES.md`. Character geometry and materials are authored in `avatar_viewer.gd` for this prototype and have no imported model dependency.
