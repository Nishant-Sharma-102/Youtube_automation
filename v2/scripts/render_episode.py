"""
PHASE 3 — Blender headless render, lip-synced to narration.

Runs on YOUR machine (Blender + Rhubarb required — not in the build sandbox).

  # Test the whole loop with a placeholder character + auto-built scene (no assets):
  blender --background --python scripts/render_episode.py -- --episode 1 --placeholder --audio audio/ep1.mp3

  # Real character:
  blender --background scene_template.blend --python scripts/render_episode.py -- \
      --episode 1 --character /path/to/milo.fbx --audio audio/ep1.mp3 --clip idle_gesture

Steps: scene (template or procedural) -> character (FBX or placeholder) -> Rhubarb
visemes on mouth shape keys -> Mixamo body clip looped -> render length = audio length
-> render epN.mp4 with EXPLICIT AAC audio muxed -> thumbnail epN.jpg -> `npm run attach`
(which guards streams and sets status='ready').
"""
import argparse, json, math, os, subprocess, sys
import bpy

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDERS = os.path.join(PROJECT_ROOT, "renders")
CLIPS_DIR = os.environ.get("MIXAMO_CLIPS_DIR", os.path.join(PROJECT_ROOT, "assets", "mixamo"))
RHUBARB_BIN = os.environ.get("RHUBARB_BIN", "rhubarb")
FPS = int(os.environ.get("RENDER_FPS", "24"))

# Rhubarb (A-H,X) -> Oculus visemes (Ready Player Me names). Edit if your rig differs.
VISEME_TO_SHAPEKEY = {
    "A": "viseme_PP", "B": "viseme_SS", "C": "viseme_E", "D": "viseme_aa",
    "E": "viseme_O", "F": "viseme_U", "G": "viseme_FF", "H": "viseme_nn", "X": "viseme_sil",
}


def log(m): print(f"[render] {m}", flush=True)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--character", default=None)
    p.add_argument("--audio", required=True)
    p.add_argument("--clip", default="idle_gesture")
    p.add_argument("--template", default=None)
    p.add_argument("--placeholder", action="store_true")
    a = p.parse_args(argv)
    if not a.character and not a.placeholder:
        p.error("provide --character <fbx> or --placeholder")
    return a


def find_armature():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def find_face_mesh():
    return next((o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys), None)


def material(name, rgb):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b: b.inputs["Base Color"].default_value = (*rgb, 1.0)
    return m


def build_scene():
    sc = bpy.context.scene
    if sc.world is None: sc.world = bpy.data.worlds.new("World")
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes.get("Background")
    if bg: bg.inputs["Color"].default_value = (0.5, 0.8, 1.0, 1.0)
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0))
    bpy.context.active_object.data.materials.append(material("Grass", (0.3, 0.6, 0.2)))
    bpy.ops.object.light_add(type="SUN", location=(6, -6, 10)); bpy.context.active_object.data.energy = 3.0
    if sc.camera is None:
        cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        sc.collection.objects.link(cam); sc.camera = cam
        cam.location = (0, -4.2, 1.4); cam.rotation_euler = (math.radians(84), 0, 0)
    log("built procedural scene")


def build_placeholder():
    import bmesh
    mesh = bpy.data.meshes.new("PlaceholderHead"); bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=24, radius=1.0)
    bm.to_mesh(mesh); bm.free()
    head = bpy.data.objects.new("Milo_Placeholder", mesh); bpy.context.collection.objects.link(head)
    head.location = (0, 0, 1.2); head.data.materials.append(material("Orange", (1.0, 0.45, 0.1)))
    head.shape_key_add(name="Basis")
    opens = {"viseme_sil": 0, "viseme_PP": 0, "viseme_FF": .15, "viseme_SS": .15,
             "viseme_nn": .25, "viseme_U": .3, "viseme_E": .4, "viseme_O": .5, "viseme_aa": .7}
    for name, amt in opens.items():
        sk = head.shape_key_add(name=name)
        for i, v in enumerate(mesh.vertices):
            if v.co.y < -0.35 and v.co.z < 0: sk.data[i].co.z -= amt * abs(v.co.z)
    log("built placeholder character with visemes")
    return None, head


def add_audio_length(audio):
    sc = bpy.context.scene; sc.render.fps = FPS
    if not sc.sequence_editor: sc.sequence_editor_create()
    strip = sc.sequence_editor.sequences.new_sound("narration", audio, channel=1, frame_start=1)
    sc.frame_start = 1; sc.frame_end = int(strip.frame_final_end)
    log(f"scene length = {sc.frame_end} frames ({sc.frame_end / FPS:.1f}s)")
    return sc.frame_end


def apply_body(arm, clip, frame_end):
    path = os.path.join(CLIPS_DIR, f"{clip}.fbx")
    if not os.path.exists(path): log(f"WARNING clip not found: {path}"); return
    before = set(bpy.data.objects); bpy.ops.import_scene.fbx(filepath=path)
    imported = [o for o in bpy.data.objects if o not in before]
    src = next((o for o in imported if o.type == "ARMATURE"), None)
    act = src.animation_data.action if src and src.animation_data else None
    if act:
        if not arm.animation_data: arm.animation_data_create()
        strip = arm.animation_data.nla_tracks.new().strips.new(act.name, start=1, action=act)
        strip.repeat = max(1.0, frame_end / max(1, act.frame_range[1]))
    for o in imported: bpy.data.objects.remove(o, do_unlink=True)
    log(f"applied body clip {clip}")


def run_rhubarb(audio):
    out = os.path.join(RENDERS, "_rhubarb.json")
    subprocess.run([RHUBARB_BIN, "-f", "json", "-o", out, audio], check=True)
    return json.load(open(out)).get("mouthCues", [])


def apply_visemes(mesh, cues):
    keys = mesh.data.shape_keys.key_blocks
    names = set(VISEME_TO_SHAPEKEY.values())
    missing = [n for n in names if n not in keys]
    if missing: log(f"WARNING shape keys missing on {mesh.name}: {missing} (fix VISEME_TO_SHAPEKEY)")
    for cue in cues:
        f = int(round(cue["start"] * FPS)) + 1
        active = VISEME_TO_SHAPEKEY.get(cue["value"], VISEME_TO_SHAPEKEY["X"])
        for n in names:
            if n in keys:
                keys[n].value = 1.0 if n == active else 0.0
                keys[n].keyframe_insert("value", frame=f)
    log(f"keyframed {len(cues)} visemes")


def render(mp4, jpg, frame_end):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.render.image_settings.file_format = "FFMPEG"; sc.render.filepath = mp4
    ff = sc.render.ffmpeg
    ff.format = "MPEG4"; ff.codec = "H264"; ff.constant_rate_factor = "MEDIUM"
    ff.audio_codec = "AAC"; ff.audio_bitrate = 192   # <-- explicit audio (the mux fix)
    bpy.ops.render.render(animation=True)
    log(f"rendered {mp4}")
    sc.frame_set(max(1, frame_end // 3))
    sc.render.image_settings.file_format = "JPEG"; sc.render.filepath = jpg
    bpy.ops.render.render(write_still=True)
    log(f"thumbnail {jpg}")


def main():
    a = parse_args(); os.makedirs(RENDERS, exist_ok=True)
    mp4 = os.path.join(RENDERS, f"ep{a.episode}.mp4"); jpg = os.path.join(RENDERS, f"ep{a.episode}.jpg")
    if a.template: bpy.ops.wm.open_mainfile(filepath=a.template)
    else: build_scene()
    if a.placeholder: arm, mesh = build_placeholder()
    else:
        if find_armature() is None: bpy.ops.import_scene.fbx(filepath=a.character)
        arm, mesh = find_armature(), find_face_mesh()
    if mesh is None: raise SystemExit("no face mesh with shape keys (need visemes)")
    frame_end = add_audio_length(a.audio)
    if arm is not None: apply_body(arm, a.clip, frame_end)
    apply_visemes(mesh, run_rhubarb(a.audio))
    render(mp4, jpg, frame_end)
    subprocess.run(["npm", "run", "attach", "--", "--video", str(a.episode)], cwd=PROJECT_ROOT, check=True)
    log("done")


if __name__ == "__main__":
    main()
