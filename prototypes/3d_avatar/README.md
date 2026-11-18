# Astra 3D avatar renderer spike

This renderer remains a procedural prototype and is temporarily postponed: the Qt UI does not expose it while proper character models are unavailable. The current blockout is matched to the approved full-body 2D references and the four 3D style concepts: Miku has long layered dark-purple hair and purple accents, Ren has seven hair spikes with cyan accents, Saya has a silver bob with a violet streak and teal eyes, and Kai has wavy brown hair with purple accents. All four use smaller heads, fitted uniforms, separate lapels and coat panels, luminous seams, belts with glowing buckles, articulated fingers, knee inserts, chunky boots with toes and soles, distinct male/female proportions, state rim lighting, a colored floor ring and a simple blink animation. The portable package bundles the official Godot 4.7.2 Windows runtime. No models or third-party character assets are downloaded. The main desktop window uses animated full-body 2D portraits; these 3D proportions did not pass human visual acceptance and need true GLB/VRM-style models before product use.

## Run

Open this folder with Godot 4.7.2 stable, or run a preview with a selected profile and display name:

```text
Godot_v4.7.2-stable_win64.exe --path prototypes/3d_avatar -- --avatar=female_saya --name=Сая
Godot_v4.7.2-stable_win64.exe --path prototypes/3d_avatar -- --avatar=male_ren --name=Рэн --fullscreen
```

Accepted IDs: `female_miku`, `male_ren`, `female_saya`, `male_kai`. Unknown IDs fall back to `female_saya`. The optional `--fullscreen` argument opens the preview on the entire screen; F11 toggles fullscreen and Esc exits. The scene is visual-only; it cannot access the microphone, files, shell, or Astra runtime.

## Validate headlessly

```text
python tools/validate_3d_avatar.py --godot "C:/Path/To/Godot_v4.7.2-stable_win64.exe"
```

This validates project import, startup for all four IDs, five presentation states, custom display names and safe fallbacks, not visual quality or target-GPU performance. A human still needs to inspect the rendered characters.

## Integration boundary

The prototype is launched manually for renderer development only; the Qt settings no longer expose a separate preview button. The input protocol contains only a built-in avatar ID and bounded display name; the renderer has no microphone, file, shell-command or Astra-runtime access. The animated 2D portrait is the supported main-window experience. Remaining product work: source or create true GLB/VRM character models, visual/performance acceptance, live-state synchronization and an integrated main-window renderer. The portable ZIP includes the engine MIT license and the 4.7.2 third-party copyright list.

Godot engine license: MIT; see `THIRD_PARTY_NOTICES.md`. Character geometry and materials are authored in `avatar_viewer.gd` for this prototype and have no imported model dependency.
