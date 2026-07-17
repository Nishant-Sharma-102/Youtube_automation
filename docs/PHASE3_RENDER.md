# Phase 3 — Blender Render (Lip-Synced Animation)

Turns an episode's script + `audio/epN.mp3` into a rendered `renders/epN.mp4` with the
character's mouth lip-synced to the narration, then marks the queue row `ready` so the
Phase 5 publish job picks it up.

**This runs on your machine, not in the build sandbox** — it needs Blender, Rhubarb,
and your FBX/Mixamo assets, none of which live in the repo environment. The script and
the DB hand-off are built and the hand-off is tested; you run the actual render.

## Prerequisites

- **Blender** 3.6+ (`blender` on your PATH)
- **Rhubarb Lip Sync** installed — set `RHUBARB_BIN` to its path if not on PATH
- **Rigged character FBX** (Meshy/Tripo) with **mouth shape keys** (visemes/blendshapes)
- **Mixamo clips** retargeted onto that rig, as FBX files in `assets/mixamo/` (e.g.
  `idle_gesture.fbx`, `wave.fbx`)
- A **scene template `.blend`** you set up once: lighting + camera framing (character
  optional — the script imports the FBX if the template has no armature)

## One-time setup

1. **Build the scene template.** In Blender: set your lighting rig and camera framing,
   optionally import the character. Save as e.g. `scene_template.blend`. This is what
   keeps every episode's visual style identical.

2. **Map visemes to YOUR shape keys.** Open [`scripts/render_episode.py`](../scripts/render_episode.py)
   and edit `VISEME_TO_SHAPEKEY` so the right-hand values are the exact shape-key names
   on your character mesh. This is the #1 thing to get right — wrong names = no mouth
   movement (the script warns which keys it couldn't find).

3. **Point at your tools** (env vars, optional):
   ```bash
   export RHUBARB_BIN=/path/to/rhubarb
   export MIXAMO_CLIPS_DIR=/path/to/assets/mixamo
   export RENDER_FPS=24
   export FACE_MESH_NAME=Head   # if auto-detect picks the wrong mesh
   ```

## Fastest test — no assets needed (placeholder character + procedural scene)

Before you have Milo, run the **whole pipeline** (Rhubarb lip-sync → render → mark
ready) with a built-in primitive character and an auto-built scene. This proves the
loop works on your machine end-to-end:

```bash
blender --background --python scripts/render_episode.py -- \
  --episode 2 --placeholder --audio audio/ep2.mp3
```

- `--placeholder` builds a crude head with the Oculus viseme shape keys (so lip-sync
  runs) — it's a stand-in, not pretty.
- With no `--template`, the script **builds the scene procedurally** (sky, grassy
  ground, lighting, framed camera). Add `--no-scene` to skip it.
- Still needs **Rhubarb** installed (`RHUBARB_BIN`).

Once this produces a valid `renders/ep2.mp4` with lip-sync + audio, swap in your real
character (below).

## Run one episode (real character)

```bash
blender --background scene_template.blend \
  --python scripts/render_episode.py -- \
  --episode 2 \
  --character /path/to/character.fbx \
  --audio audio/ep2.mp3 \
  --clip idle_gesture
```

Parameters (`--episode`, `--character`, `--audio`, `--clip`) make it callable
programmatically. What it does, in order:

| Step | Action |
|------|--------|
| 1 | Opens the scene template (lighting + camera) |
| 2 | Ensures the character is present (imports the FBX if missing) |
| 3 | Runs Rhubarb on the audio → viseme timing → keyframes the mouth shape keys |
| 4 | Applies the Mixamo `--clip` as a looped NLA strip for the whole scene |
| 5 | Sets scene length to the audio duration **exactly** (via the sound strip) |
| 6 | Renders `renders/epN.mp4` (H.264 + **explicit AAC audio**) and a `renders/epN.jpg` thumbnail |
| 7 | Runs `npm run attach -- --video N` → marks the row **`ready`** |

## The audio-mux fix (step 5/6)

The earlier "silent video" bug is guarded twice:
- The Blender render sets `ffmpeg.audio_codec = "AAC"` **and** adds the narration as a
  VSE sound strip — audio export is explicit, not default (Blender defaults to
  video-only otherwise).
- Step 7's `attach` runs the **audio-safety guard** (`assertPublishableRender`): if the
  final mp4 has no audio stream or is silent, it **refuses** to mark the episode `ready`
  (verified — a silent render is rejected with a loud error). Override for a
  deliberately silent clip with `ALLOW_SILENT=1`.

## Hand-off to publishing (Phase 5)

Step 7 sets `status = ready` and records `video_file_path` + `thumbnail_path`. The
publish orchestrator ([`src/orchestrate/publish.ts`](../src/orchestrate/publish.ts))
and its cron then pick it up automatically — **no publish step here**, per spec.

> Note on timing: your spec says "8 PM." The installed publish cron currently runs at
> **16:30 IST (= 11:00 UTC)**, which we set earlier for best global-kids reach
> ([`src/publish-config.ts`](../src/publish-config.ts)). If you want a literal 8 PM
> local slot instead, say so and I'll adjust the cron.

## Testing checklist

- Render one episode; open `renders/epN.mp4` — confirm the mouth tracks the narration
  and audio plays.
- If the mouth doesn't move: your `VISEME_TO_SHAPEKEY` names don't match the rig (check
  the script's "shape keys not found" warning).
- If it errors at step 7 with "audio is SILENT": Blender exported video-only — confirm
  the sound strip was added and `audio_codec = AAC` (both are in the script).
- Confirm the row is `ready`: `npm run attach` prints the status, or query the DB.
