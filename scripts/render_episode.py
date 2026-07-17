"""
Phase 3 — Blender headless render, lip-synced to narration.

Run:
  blender --background TEMPLATE.blend --python scripts/render_episode.py -- \
      --episode 2 \
      --character /path/to/character.fbx \
      --audio audio/ep2.mp3 \
      --clip idle_gesture

Or let the script open the template itself (omit TEMPLATE.blend on the CLI and set
--template):
  blender --background --python scripts/render_episode.py -- --episode 2 \
      --character ... --audio ... --clip ... --template scene_template.blend

Pipeline:
  1. Open a reusable scene template (.blend with lighting + camera; character optional).
  2. Ensure the rigged character is present (import the FBX if the template lacks it).
  3. Run Rhubarb Lip Sync on the audio -> viseme timing -> keyframe mouth shape keys.
  4. Apply a Mixamo body-animation clip (looped to fill the audio duration).
  5. Set the scene length to exactly match the audio duration.
  6. Render renders/epN.mp4 with narration muxed in (EXPLICIT AAC audio + sound strip),
     plus a thumbnail renders/epN.jpg.
  7. Hand off to the TS attach CLI, which marks the row 'ready' (audio-guarded).

IMPORTANT: this is rig-specific. Review the CONFIG block and especially
VISEME_TO_SHAPEKEY — the mouth shape-key names MUST match your Meshy/Tripo rig.
"""
import argparse
import json
import os
import subprocess
import sys

import bpy

# ----------------------------------------------------------------------------
# CONFIG — edit to match your machine and rig
# ----------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDERS_DIR = os.path.join(PROJECT_ROOT, "renders")
CLIPS_DIR = os.environ.get("MIXAMO_CLIPS_DIR", os.path.join(PROJECT_ROOT, "assets", "mixamo"))
RHUBARB_BIN = os.environ.get("RHUBARB_BIN", "rhubarb")  # path to the Rhubarb executable
FPS = int(os.environ.get("RENDER_FPS", "24"))

# Rhubarb basic mouth shapes (A-H, X) -> Oculus viseme shape keys.
# These names are the Oculus/Meta viseme standard, which is exactly what Ready Player
# Me characters export (viseme_PP, viseme_aa, ...). If your character uses different
# shape-key names, change the right-hand values to match (the script warns on mismatch).
VISEME_TO_SHAPEKEY = {
    "A": "viseme_PP",   # closed lips: m, b, p
    "B": "viseme_SS",   # slightly open, teeth close: s, t, d, k
    "C": "viseme_E",    # open, unrounded: eh (bet)
    "D": "viseme_aa",   # wide open: ah (father)
    "E": "viseme_O",    # open, slightly rounded: oh
    "F": "viseme_U",    # puckered: oo, w
    "G": "viseme_FF",   # upper teeth on lower lip: f, v
    "H": "viseme_nn",   # tongue-raised: l, n
    "X": "viseme_sil",  # rest / silence
}
# Name of the mesh object that carries the mouth shape keys (None = auto-detect first
# mesh with shape keys).
FACE_MESH_NAME = os.environ.get("FACE_MESH_NAME") or None


# ----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--character", default=None, help="Path to rigged character FBX (omit with --placeholder)")
    p.add_argument("--audio", required=True, help="Path to narration mp3 (audio/epN.mp3)")
    p.add_argument("--clip", default="idle_gesture", help="Mixamo clip name (file in CLIPS_DIR)")
    p.add_argument("--template", default=None, help="Scene template .blend (skips procedural scene)")
    p.add_argument("--no-scene", action="store_true", help="Don't build the procedural scene")
    p.add_argument("--placeholder", action="store_true",
                   help="Use a built-in primitive character with visemes (test the loop before your real model)")
    args = p.parse_args(argv)
    if not args.character and not args.placeholder:
        p.error("provide --character <fbx> or --placeholder")
    return args


def log(msg: str) -> None:
    print(f"[render_episode] {msg}", flush=True)


# ---- scene setup ------------------------------------------------------------
def open_template(template: str | None) -> None:
    if template:
        log(f"opening template {template}")
        bpy.ops.wm.open_mainfile(filepath=template)
    # else: use whatever .blend blender was launched with (or the default scene)


def find_armature():
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            return obj
    return None


def find_face_mesh():
    if FACE_MESH_NAME and FACE_MESH_NAME in bpy.data.objects:
        return bpy.data.objects[FACE_MESH_NAME]
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data.shape_keys:
            return obj
    return None


def ensure_character(character_fbx: str):
    """Import the character FBX if the template doesn't already contain a rig."""
    if find_armature() is None:
        log(f"no armature in scene — importing {character_fbx}")
        bpy.ops.import_scene.fbx(filepath=character_fbx)
    return find_armature(), find_face_mesh()


def _material(name: str, rgb: tuple) -> "bpy.types.Material":
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    return mat


def build_default_scene() -> None:
    """Procedurally build a simple 'grove': sky, ground, lighting, and a framed camera.
    Runs when no --template is given, so you don't have to hand-build scene_template.blend."""
    import math
    scene = bpy.context.scene

    # Sky-blue world
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.5, 0.8, 1.0, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    # Grassy ground
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.data.materials.append(_material("Grass", (0.3, 0.6, 0.2)))

    # Key sun + soft fill
    bpy.ops.object.light_add(type="SUN", location=(6, -6, 10))
    bpy.context.active_object.data.energy = 3.0
    bpy.ops.object.light_add(type="AREA", location=(-4, -4, 6))
    bpy.context.active_object.data.energy = 200.0

    # Camera framed on the character (near origin, ~head height), if none exists
    if scene.camera is None:
        cam_data = bpy.data.cameras.new("Camera")
        cam = bpy.data.objects.new("Camera", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam
        cam.location = (0.0, -4.2, 1.4)
        cam.rotation_euler = (math.radians(84), 0.0, 0.0)  # look toward +Y, slightly down
    log("built procedural scene (sky, ground, lighting, camera)")


def build_placeholder_character():
    """A crude primitive 'Milo' (head + eyes) with Oculus-viseme shape keys, so you can
    test the FULL lip-sync + render loop before your real rigged model exists.
    Returns (armature=None, face_mesh). Not pretty — a stand-in to prove the pipeline."""
    import bmesh
    # Head sphere
    mesh = bpy.data.meshes.new("PlaceholderHead")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=24, radius=1.0)
    bm.to_mesh(mesh)
    bm.free()
    head = bpy.data.objects.new("Milo_Placeholder", mesh)
    bpy.context.collection.objects.link(head)
    head.location = (0, 0, 1.2)
    head.data.materials.append(_material("MiloOrange", (1.0, 0.45, 0.1)))

    # Shape keys: Basis + each viseme. Front-lower verts (front = -Y, lower = -Z)
    # drop to open a "mouth"; more open = bigger vowel.
    head.shape_key_add(name="Basis")
    openness = {
        "viseme_sil": 0.0, "viseme_PP": 0.0, "viseme_FF": 0.15, "viseme_SS": 0.15,
        "viseme_nn": 0.25, "viseme_U": 0.30, "viseme_E": 0.40, "viseme_O": 0.50, "viseme_aa": 0.7,
    }
    for name, amt in openness.items():
        sk = head.shape_key_add(name=name)
        for i, v in enumerate(mesh.vertices):
            if v.co.y < -0.35 and v.co.z < 0.0:  # front-lower cap = mouth region
                sk.data[i].co.z -= amt * abs(v.co.z)

    # Cute eyes (separate objects, no shape keys — ignored by find_face_mesh)
    for x in (-0.35, 0.35):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.16, location=(x, -0.85, 1.45))
        bpy.context.active_object.data.materials.append(_material("Eye", (0.05, 0.05, 0.05)))

    log("built placeholder character with viseme shape keys")
    return None, head


# ---- body animation ---------------------------------------------------------
def apply_body_clip(armature, clip_name: str, frame_end: int) -> None:
    """Import a Mixamo clip FBX, move its action onto our armature, loop to fill."""
    clip_path = os.path.join(CLIPS_DIR, f"{clip_name}.fbx")
    if not os.path.exists(clip_path):
        log(f"WARNING: clip not found ({clip_path}); skipping body animation")
        return
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=clip_path)
    imported = [o for o in bpy.data.objects if o not in before]
    src_arm = next((o for o in imported if o.type == "ARMATURE"), None)
    action = src_arm.animation_data.action if src_arm and src_arm.animation_data else None
    if action:
        if not armature.animation_data:
            armature.animation_data_create()
        # Use an NLA strip so we can loop the clip across the whole scene length.
        track = armature.animation_data.nla_tracks.new()
        strip = track.strips.new(action.name, start=1, action=action)
        strip.repeat = max(1.0, frame_end / max(1, action.frame_range[1]))
        log(f"applied body clip '{clip_name}' (repeat x{strip.repeat:.1f})")
    # remove the imported helper objects (keep only their action, now on our rig)
    for o in imported:
        bpy.data.objects.remove(o, do_unlink=True)


# ---- lip sync ---------------------------------------------------------------
def run_rhubarb(audio_path: str, dialog_text: str | None) -> list[dict]:
    out_json = os.path.join(RENDERS_DIR, "_rhubarb_tmp.json")
    cmd = [RHUBARB_BIN, "-f", "json", "-o", out_json]
    if dialog_text:
        dlg = os.path.join(RENDERS_DIR, "_dialog_tmp.txt")
        with open(dlg, "w") as f:
            f.write(dialog_text)
        cmd += ["--dialogFile", dlg]  # improves accuracy vs pure phonetic
    cmd += [audio_path]
    log(f"running rhubarb: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    with open(out_json) as f:
        return json.load(f).get("mouthCues", [])


def apply_visemes(face_mesh, cues: list[dict]) -> None:
    keys = face_mesh.data.shape_keys.key_blocks
    shapekey_names = set(VISEME_TO_SHAPEKEY.values())
    missing = [n for n in shapekey_names if n not in keys]
    if missing:
        log(f"WARNING: shape keys not found on '{face_mesh.name}': {missing} "
            f"— fix VISEME_TO_SHAPEKEY to match your rig")
    for cue in cues:
        frame = int(round(cue["start"] * FPS)) + 1
        active = VISEME_TO_SHAPEKEY.get(cue["value"], VISEME_TO_SHAPEKEY["X"])
        for name in shapekey_names:
            if name in keys:
                keys[name].value = 1.0 if name == active else 0.0
                keys[name].keyframe_insert("value", frame=frame)
    log(f"keyframed {len(cues)} viseme cues")


# ---- audio + render ---------------------------------------------------------
def add_audio_and_length(audio_path: str) -> int:
    """Add the narration as a VSE sound strip and set scene length to its duration."""
    scene = bpy.context.scene
    scene.render.fps = FPS
    if not scene.sequence_editor:
        scene.sequence_editor_create()
    strip = scene.sequence_editor.sequences.new_sound("narration", audio_path, channel=1, frame_start=1)
    frame_end = int(strip.frame_final_end)
    scene.frame_start = 1
    scene.frame_end = frame_end
    log(f"audio duration -> frame_end={frame_end} ({frame_end / FPS:.1f}s @ {FPS}fps)")
    return frame_end


def configure_render(mp4_path: str) -> None:
    """H.264 video + EXPLICIT AAC audio muxed from the sound strip (the audio-bug fix)."""
    scene = bpy.context.scene
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.filepath = mp4_path
    ff = scene.render.ffmpeg
    ff.format = "MPEG4"
    ff.codec = "H264"
    ff.constant_rate_factor = "MEDIUM"
    # --- audio: explicit, not default. Without these two lines the mux is video-only. ---
    ff.audio_codec = "AAC"
    ff.audio_bitrate = 192
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100


def render_thumbnail(jpg_path: str, frame_end: int) -> None:
    scene = bpy.context.scene
    scene.frame_set(max(1, frame_end // 3))
    scene.render.image_settings.file_format = "JPEG"
    scene.render.filepath = jpg_path
    bpy.ops.render.render(write_still=True)
    log(f"thumbnail -> {jpg_path}")


# ---- step 7 handoff ---------------------------------------------------------
def mark_ready(episode_id: int) -> None:
    """Call the TS attach CLI (single source of truth for the DB + audio guard)."""
    log("marking episode 'ready' via npm run attach")
    subprocess.run(
        ["npm", "run", "attach", "--", "--video", str(episode_id)],
        cwd=PROJECT_ROOT, check=True,
    )


def main() -> None:
    args = parse_args()
    os.makedirs(RENDERS_DIR, exist_ok=True)
    mp4_path = os.path.join(RENDERS_DIR, f"ep{args.episode}.mp4")
    jpg_path = os.path.join(RENDERS_DIR, f"ep{args.episode}.jpg")

    # Scene: open a template, or build one procedurally (unless suppressed).
    open_template(args.template)
    if not args.template and not args.no_scene:
        build_default_scene()

    # Character: real rigged FBX, or a primitive placeholder for testing the loop.
    if args.placeholder:
        armature, face_mesh = build_placeholder_character()
    else:
        armature, face_mesh = ensure_character(args.character)
    if face_mesh is None:
        raise SystemExit("No face mesh with shape keys found — need a character with visemes.")

    frame_end = add_audio_and_length(args.audio)
    if armature is not None:
        apply_body_clip(armature, args.clip, frame_end)  # skipped for placeholder (no rig)

    cues = run_rhubarb(args.audio, dialog_text=None)  # pass script text here for accuracy
    apply_visemes(face_mesh, cues)

    configure_render(mp4_path)
    bpy.ops.render.render(animation=True)  # muxes video + narration audio
    log(f"rendered {mp4_path}")

    render_thumbnail(jpg_path, frame_end)
    mark_ready(args.episode)
    log("done")


if __name__ == "__main__":
    main()
