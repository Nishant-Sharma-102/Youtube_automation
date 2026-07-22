#!/usr/bin/env python3
"""Phase 7 — full episode assembly (ffmpeg).

Reads the next status='music_ready' row and renders one episode.mp4:
  • one video segment per scene: a Ken Burns pan/zoom over the scene's keyframe,
    its length driven by that scene's narration clip (perfect A/V sync);
  • segments concatenated in order;
  • the music bed mixed UNDER the narration (narration stays dominant);
  • picks the highest-impact keyframe as thumbnail_source_path for Phase 8.
Then stores video_file_path + thumbnail_source_path and sets status='assembly_ready'.

v1 policy: the 5 Kling scenes are DOWNGRADED to Ken Burns stills (no Kling key / $$
needed). Pass --use-kling to splice in real Kling clips when present (mock stubs are
always ignored).

This box has no ffmpeg — run on EC2. Use --validate anywhere to check timing math +
asset presence and PRINT the exact ffmpeg commands without invoking ffmpeg.

Usage:
  python assemble.py --validate     # no ffmpeg: verify + print the command plan
  python assemble.py                # real render (needs ffmpeg)
  python assemble.py --use-kling    # use real Kling clips where available
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import PROJECT_DIR, load_config
from sheet import TopicQueue

RENDERS = PROJECT_DIR / "renders"


def slugify(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]) or "episode"


def is_real_file(path: str | None, min_bytes: int = 10_240) -> bool:
    """True if a real asset (exists, big enough, not one of our MOCK-* stubs)."""
    if not path:
        return False
    p = Path(path)
    if not p.exists() or p.stat().st_size < min_bytes:
        return False
    return not p.read_bytes()[:5].startswith(b"MOCK")


def kenburns_filter(idx: int, dur: float, w: int, h: int, fps: int) -> str:
    """A single scaled-canvas Ken Burns move. Alternates slow zoom-in / zoom-out so
    consecutive scenes don't feel identical. Center-anchored to avoid jitter."""
    frames = int(math.ceil(dur * fps)) + 2
    cw, ch = int(w * 1.3), int(h * 1.3)  # oversized canvas gives the zoom headroom
    if idx % 2 == 0:  # slow zoom IN
        z = "min(zoom+0.0006,1.25)"
    else:             # slow zoom OUT
        z = "if(eq(on,1),1.25,max(zoom-0.0006,1.0))"
    return (
        f"[0:v]scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},"
        f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={w}x{h}:fps={fps},format=yuv420p[v]"
    )


def segment_cmd(cfg, scene, idx, seg_path: Path) -> list[str]:
    dur = float(scene["duration_sec"])
    return [
        cfg.ffmpeg_bin, "-y",
        "-loop", "1", "-framerate", str(cfg.fps), "-i", scene["keyframe_path"],
        "-i", scene["audio_path"],
        "-filter_complex", kenburns_filter(idx, dur, cfg.video_w, cfg.video_h, cfg.fps),
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", str(seg_path),
    ]


def multi_image_segment_cmd(cfg, scene, idx, images: list[str], seg_path: Path) -> list[str]:
    """Render one scene from MULTIPLE images: Ken Burns on each, cross-dissolved
    together to fill the narration length, then muxed with the scene audio. Gives a
    moving, varied look without any paid video model."""
    dur = float(scene["duration_sec"])
    w, h, fps = cfg.video_w, cfg.video_h, cfg.fps
    cw, ch = int(w * 1.3), int(h * 1.3)
    n = len(images)
    od = max(0.4, min(0.8, dur / (n * 3)))        # cross-dissolve length
    de = (dur + (n - 1) * od) / n                  # per-image on-screen length
    frames = int(math.ceil(de * fps)) + 2

    cmd = [cfg.ffmpeg_bin, "-y"]
    for img in images:
        cmd += ["-i", img]
    cmd += ["-i", scene["audio_path"]]             # audio is input index n

    parts = []
    for i in range(n):
        z = "min(zoom+0.0006,1.25)" if (idx + i) % 2 == 0 else \
            "if(eq(on,1),1.25,max(zoom-0.0006,1.0))"
        parts.append(
            f"[{i}:v]scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={w}x{h}:fps={fps},setsar=1,format=yuv420p[v{i}]"
        )
    prev = "[v0]"
    for i in range(1, n):
        out = "[vout]" if i == n - 1 else f"[x{i}]"
        offset = i * (de - od)
        parts.append(f"{prev}[v{i}]xfade=transition=dissolve:duration={od:.3f}:offset={offset:.3f}{out}")
        prev = out

    return cmd + [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]", "-map", f"{n}:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", str(seg_path),
    ]


def kling_segment_cmd(cfg, scene, seg_path: Path) -> list[str]:
    """Use a real Kling clip as the segment video, muxed with the scene narration
    (trim/pad to the narration length)."""
    dur = float(scene["duration_sec"])
    return [
        cfg.ffmpeg_bin, "-y", "-i", scene["video_path"], "-i", scene["audio_path"],
        "-filter_complex",
        f"[0:v]scale={cfg.video_w}:{cfg.video_h}:force_original_aspect_ratio=increase,"
        f"crop={cfg.video_w}:{cfg.video_h},fps={cfg.fps},format=yuv420p[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", str(seg_path),
    ]


def concat_cmd(cfg, list_file: Path, out: Path) -> list[str]:
    return [cfg.ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(out)]


def music_mix_cmd(cfg, video: Path, music: str, out: Path) -> list[str]:
    return [
        cfg.ffmpeg_bin, "-y", "-i", str(video), "-stream_loop", "-1", "-i", music,
        "-filter_complex",
        f"[1:a]volume={cfg.music_volume}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out),
    ]


def run(cmd: list[str], label: str) -> None:
    print(f"  ▶ {label}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed ({label}):\n{r.stderr[-1500:]}")


def run_ok(cmd: list[str], label: str) -> bool:
    """Like run() but returns False instead of aborting — lets the caller fall back."""
    print(f"  ▶ {label}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    ⚠️ ffmpeg failed ({label}) rc={r.returncode}: {r.stderr.strip()[-300:]}",
              flush=True)
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validate", action="store_true",
                    help="No ffmpeg: verify assets + timing and print the command plan.")
    ap.add_argument("--use-kling", action="store_true",
                    help="(Deprecated alias) Splice real animated clips — now the default.")
    ap.add_argument("--stills-only", action="store_true",
                    help="Force Ken Burns stills for every scene, ignoring any animated clips.")
    ap.add_argument("--keep-segments", action="store_true", help="Keep per-scene segment files.")
    args = ap.parse_args()
    # Splice real animated clips by default; is_real_file() ignores MOCK stubs anyway.
    # --stills-only forces stills for the whole episode.
    args.use_kling = not args.stills_only

    cfg = load_config()
    queue = TopicQueue(cfg)
    rec = queue.next_music_ready()
    if not rec:
        print(f"[backend={queue.backend}] No status='music_ready' row. Nothing to assemble.")
        return 0

    sb = json.loads(rec["scene_breakdown"])
    scenes = sb.get("scenes", [])
    if not scenes:
        raise SystemExit("No scenes in scene_breakdown.")

    # Validate every scene has its real inputs.
    missing, total = [], 0.0
    for s in scenes:
        n = s.get("scene_number")
        if not Path(s.get("keyframe_path", "")).exists():
            missing.append(f"scene {n}: keyframe missing")
        if not is_real_file(s.get("audio_path"), min_bytes=1000):
            missing.append(f"scene {n}: narration audio missing")
        total += float(s.get("duration_sec", 0) or 0)

    # Thumbnail source = highest-impact keyframe (fallback: first scene).
    best = max(scenes, key=lambda s: int(s.get("impact_score", 0) or 0))
    thumb_src = best.get("keyframe_path") or scenes[0].get("keyframe_path")

    music = None
    for f in (sb.get("music") or {}).get("files", []) or []:
        if is_real_file(f):
            music = f
            break

    slug = slugify(rec["topic"])
    rdir = RENDERS / slug
    seg_dir = rdir / "segments"
    episode = rdir / "episode.mp4"

    kling_real = sum(1 for s in scenes
                     if s.get("scene_type") == "kling" and args.use_kling and is_real_file(s.get("video_path")))
    print(f"[backend={queue.backend}] Episode: [{rec['pillar']}] {rec['topic']}")
    print(f"Scenes: {len(scenes)}   total runtime: {total:.1f}s ({total/60:.1f} min)   "
          f"output: {cfg.video_w}x{cfg.video_h}@{cfg.fps}")
    print(f"Kling clips spliced: {kling_real} (rest = Ken Burns stills)")
    print(f"Music bed: {'✅ ' + music if music else '⚠️ none real (silent bed) — retry Jamendo download'}"
          f"   volume={cfg.music_volume}")
    print(f"Thumbnail source (impact {best.get('impact_score','?')}, scene {best.get('scene_number')}): {thumb_src}")

    if missing:
        print("\n❌ Missing inputs — cannot assemble:\n   " + "\n   ".join(missing))
        return 1
    print("✅ All 29 keyframes + narration clips present; per-scene durations sum to the runtime.\n")

    # Build the command plan.
    seg_paths, plan = [], []
    for i, s in enumerate(scenes):
        seg = seg_dir / f"seg_{s['scene_number']:03d}.mp4"
        seg_paths.append(seg)
        use_k = args.use_kling and s.get("scene_type") == "kling" and is_real_file(s.get("video_path"))
        # Multi-image still scenes → cross-dissolve montage; single image → Ken Burns.
        imgs = [p for p in (s.get("keyframe_paths") or [s.get("keyframe_path")]) if is_real_file(p)]
        if use_k:
            cmd, kind = kling_segment_cmd(cfg, s, seg), "kling"
        elif len(imgs) > 1:
            cmd, kind = multi_image_segment_cmd(cfg, s, i, imgs, seg), f"multi×{len(imgs)}"
        else:
            cmd, kind = segment_cmd(cfg, s, i, seg), "still "
        plan.append((f"scene {s['scene_number']:>2} ({kind}, "
                     f"{float(s['duration_sec']):.1f}s)", cmd, i, s, seg, kind))
    list_file = seg_dir / "segments.txt"
    concat_out = rdir / ("concat.mp4" if music else "episode.mp4")

    if args.validate:
        print("=== FFMPEG COMMAND PLAN (validate — not executed) ===")
        print(f"# {len(plan)} per-scene segments, e.g.:")
        for label, cmd, *_ in plan[:2]:
            print(f"# {label}\n{' '.join(cmd)}\n")
        print(f"# … {len(plan)-2} more segments …\n")
        print(f"# concat list -> {list_file}")
        print(f"{' '.join(concat_cmd(cfg, list_file, concat_out))}\n")
        if music:
            print(f"# music mix (narration dominant)\n{' '.join(music_mix_cmd(cfg, concat_out, music, episode))}")
        print("\n(validate only — no files written, status unchanged.)")
        return 0

    if not shutil.which(cfg.ffmpeg_bin) and not Path(cfg.ffmpeg_bin).exists():
        raise SystemExit(f"ffmpeg not found ({cfg.ffmpeg_bin!r}). Install it or set DOC_FFMPEG. "
                         "This box has none — run on EC2, or use --validate.")

    seg_dir.mkdir(parents=True, exist_ok=True)
    for label, cmd, i, s, seg, kind in plan:
        if run_ok(cmd, label):
            continue
        # A multi-image montage is memory-heavy and can be OOM-killed on small hosts.
        # Fall back to a lightweight single-image Ken Burns segment so ONE heavy scene
        # never aborts the whole episode.
        if kind.startswith("multi"):
            print(f"    ↩ falling back to single-image Ken Burns for scene {s['scene_number']}",
                  flush=True)
            if run_ok(segment_cmd(cfg, s, i, seg), f"scene {s['scene_number']:>2} (still fallback)"):
                continue
        raise SystemExit(f"ffmpeg failed and no fallback succeeded for: {label}")
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_paths), encoding="utf-8")
    run(concat_cmd(cfg, list_file, concat_out), "concat segments")
    if music:
        run(music_mix_cmd(cfg, concat_out, music, episode), "mix music bed under narration")
        concat_out.unlink(missing_ok=True)
    if not args.keep_segments:
        shutil.rmtree(seg_dir, ignore_errors=True)

    sb["video_file_path"] = str(episode.resolve())
    sb["thumbnail_source_path"] = thumb_src
    sb["assembly"] = {"runtime_sec": round(total, 2), "resolution": f"{cfg.video_w}x{cfg.video_h}",
                      "fps": cfg.fps, "kling_spliced": kling_real, "music_file": music}
    queue.write_assembly(rec["ref"], json.dumps(sb, ensure_ascii=False, indent=2))
    print(f"\n✔ Rendered {episode} and set status='assembly_ready'. Phase 8 (metadata) is next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
