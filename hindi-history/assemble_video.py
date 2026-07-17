#!/usr/bin/env python3
"""Phase 4 — video assembly for one episode (ffmpeg, static binary).

images_ready episode -> per-scene Ken Burns clips with burned-in Hindi captions ->
crossfade concat -> explicit audio mux -> renders/epN.mp4 (+ thumbnail) -> status=ready.

Devanagari captions are rendered via libass (HarfBuzz shaping) using an installed
Devanagari font — NOT ffmpeg drawtext, which does not shape complex scripts.

Examples
--------
  python assemble_video.py --episode 1 --scenes-file data/ep1.json
  python assemble_video.py --episode 1                      # from the Sheet
  python assemble_video.py --episode 1 --scenes-file data/ep1.json --thumb-scene 4
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from audio_utils import duration_seconds, ffmpeg_bin, probe_streams
from config import PROJECT_DIR, load_config, require_sheet

RENDERS = PROJECT_DIR / "renders"
AUDIO = PROJECT_DIR / "audio"
FPS = 30
W, H = 1920, 1080
ZOOM = 1.12
CROSSFADE = 0.4  # seconds; user range 0.3-0.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_DIR / "logs" / "video.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("phase4")


def _run(cmd: list[str], what: str) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{what} failed:\n{p.stderr[-1200:]}")


# ---- Ken Burns expressions (alternate so a full episode doesn't feel repetitive) ----
def kenburns(mode: str, total: int) -> tuple[str, str, str]:
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"
    if mode == "zoom_in":
        return f"1+{ZOOM-1:.3f}*on/{total}", cx, cy
    if mode == "zoom_out":
        return f"{ZOOM:.3f}-{ZOOM-1:.3f}*on/{total}", cx, cy
    if mode == "pan_right":
        return f"{ZOOM:.3f}", f"(iw-iw/zoom)*on/{total}", cy
    # pan_left
    return f"{ZOOM:.3f}", f"(iw-iw/zoom)*(1-on/{total})", cy


MODES = ["zoom_in", "pan_right", "zoom_out", "pan_left"]


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass(text: str, end: float, font: str, *, fontsize: int = 44, bold: int = 0,
         margin_v: int = 48) -> str:
    # Predictable semi-transparent lower-third bar comes from drawbox in the video
    # filter; here the text is white with a thin outline for legibility, bottom-center.
    text = text.replace("\n", " ").strip()
    style = (f"Style: Cap,{font},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
             f"{bold},0,0,0,100,100,0,0,1,2,1,2,150,150,{margin_v},1")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,{_ts(end)},Cap,,0,0,0,,{text}
"""


def render_scene(img: Path, text: str, dur: float, mode: str, font: str, out: Path, tmp: Path) -> None:
    length = dur + CROSSFADE  # extra so crossfade overlap doesn't eat narration time
    total = max(1, round(length * FPS))
    z, x, y = kenburns(mode, total)
    ass_path = tmp / (out.stem + ".ass")
    ass_path.write_text(_ass(text, length, font), encoding="utf-8")
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS},"
        f"drawbox=x=0:y={int(H*0.70)}:w={W}:h={int(H*0.30)}:color=black@0.55:t=fill,"
        f"subtitles='{ass_path.as_posix()}':fontsdir=/usr/share/fonts,"
        f"setsar=1,format=yuv420p"
    )
    _run(
        [ffmpeg_bin(), "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{length:.3f}",
         "-i", str(img), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-r", str(FPS), str(out)],
        f"scene render ({img.name})",
    )


def concat_with_audio(scene_clips: list[Path], audio: Path, lengths: list[float], out: Path) -> None:
    """xfade-chain the scene clips and explicitly map the narration audio."""
    cmd = [ffmpeg_bin(), "-y"]
    for c in scene_clips:
        cmd += ["-i", str(c)]
    cmd += ["-i", str(audio)]
    audio_idx = len(scene_clips)

    filt = []
    prev = "[0:v]"
    acc = lengths[0]
    for k in range(1, len(scene_clips)):
        offset = acc - CROSSFADE
        label = "vout" if k == len(scene_clips) - 1 else f"x{k}"
        filt.append(
            f"{prev}[{k}:v]xfade=transition=fade:duration={CROSSFADE}:offset={offset:.3f}[{label}]"
        )
        prev = f"[{label}]"
        acc += lengths[k] - CROSSFADE
    if len(scene_clips) == 1:
        vmap = "0:v"
        filt = []
    else:
        vmap = "[vout]"

    cmd += (["-filter_complex", ";".join(filt)] if filt else [])
    cmd += [
        "-map", vmap, "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", str(out),
    ]
    _run(cmd, "crossfade concat + audio mux")


def make_thumbnail(img: Path, title: str, font: str, out: Path, tmp: Path) -> None:
    # Use the Devanagari part of the title (drop a trailing "| English" segment).
    head = title.split("|")[0].strip()
    ass_path = tmp / "thumb.ass"
    ass_path.write_text(
        _ass(head, 3600, font, fontsize=78, bold=1, margin_v=110), encoding="utf-8"
    )
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"drawbox=x=0:y={int(H*0.62)}:w={W}:h={int(H*0.38)}:color=black@0.5:t=fill,"
        f"subtitles='{ass_path.as_posix()}':fontsdir=/usr/share/fonts"
    )
    _run(
        [ffmpeg_bin(), "-y", "-loop", "1", "-i", str(img), "-vf", vf,
         "-frames:v", "1", "-q:v", "2", str(out)],
        "thumbnail",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 4: video assembly")
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--scenes-file", help="Local JSON dump to read/write instead of the Sheet.")
    ap.add_argument("--row", type=int)
    ap.add_argument("--thumb-scene", type=int, help="Scene number to use for the thumbnail.")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    RENDERS.mkdir(parents=True, exist_ok=True)
    ep = args.episode

    # Disk preflight — a full disk mid-encode fails late (minutes wasted) and can corrupt
    # the queue file during write-back. Refuse up front if headroom is thin.
    import os as _os
    import shutil as _shutil
    need_gb = float(_os.environ.get("HISTORY_MIN_FREE_GB", "2"))
    free_gb = min(_shutil.disk_usage(tempfile.gettempdir()).free,
                  _shutil.disk_usage(RENDERS).free) / 1e9
    if free_gb < need_gb:
        raise SystemExit(f"Only {free_gb:.1f} GB free (need >= {need_gb} GB) — refusing to render.")

    # --- 1. Load scenes + images + audio ---
    sheet = None
    row_number = None
    file_data = None
    file_path = None
    if args.scenes_file:
        file_path = Path(args.scenes_file)
        file_data = json.loads(file_path.read_text(encoding="utf-8"))
        scenes = file_data["scenes"]
        images_map = {int(k): v for k, v in file_data.get("images_json", {}).items()}
    else:
        require_sheet(cfg)
        from sheet import HistorySheet
        sheet = HistorySheet(cfg)
        got = (args.row and sheet.get_row_scenes(args.row)) or sheet.get_next_ready_for_video()
        if not got:
            log.info("No rows with status='images_ready'. Nothing to do.")
            return 0
        row_number, scenes = got
        images_map = {int(s["scene_number"]): s.get("image_path") for s in scenes}

    scenes = sorted(scenes, key=lambda s: int(s["scene_number"]))
    audio = AUDIO / f"ep{ep}_full.mp3"
    if not audio.exists():
        raise SystemExit(f"Narration track not found: {audio} (run Phase 2 first).")
    for s in scenes:
        n = int(s["scene_number"])
        if not images_map.get(n) or not Path(images_map[n]).exists():
            raise SystemExit(f"Scene {n} image missing ({images_map.get(n)}). Run Phase 3 first.")
        if "duration_seconds" not in s:
            raise SystemExit(f"Scene {n} has no duration_seconds. Run Phase 2 first.")
        # Strict decode up front: ffmpeg silently conceals a corrupt/truncated JPEG
        # ("EOI missing, emulating") and renders garbage that still passes the
        # stream/duration sanity gate — so a broken image would be published undetected.
        try:
            from PIL import Image
            with Image.open(images_map[n]) as _im:
                _im.load()
        except Exception as e:
            raise SystemExit(f"Scene {n} image is not decodable ({images_map[n]}): {e}. Regenerate it (Phase 3 --only {n}).")

    log.info("Episode %d: %d scenes, font=%s, audio=%s", ep, len(scenes), cfg.caption_font, audio.name)

    # --- 2. Per-scene Ken Burns + burned-in caption ---
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        clips, lengths = [], []
        for i, s in enumerate(scenes):
            n = int(s["scene_number"])
            mode = MODES[i % len(MODES)]
            dur = float(s["duration_seconds"])
            clip = tmp / f"scene_{n}.mp4"
            log.info("scene %d: %s, %.2fs -> Ken Burns + caption", n, mode, dur)
            render_scene(Path(images_map[n]), s["text"], dur, mode, cfg.caption_font, clip, tmp)
            clips.append(clip)
            lengths.append(dur + CROSSFADE)

        # --- 3+4. Crossfade concat + explicit audio map ---
        body = RENDERS / f"ep{ep}.mp4"
        log.info("Concatenating %d clips with %.1fs crossfades + muxing audio", len(clips), CROSSFADE)
        concat_with_audio(clips, audio, lengths, body)

        # --- 5. Intro / end-card bumpers (optional; you provide them) ---
        if cfg.intro_path or cfg.endcard_path:
            log.warning("intro/end-card provided but bumper stitching is a follow-up step; "
                        "core episode rendered without them for now.")
        else:
            log.info("No intro/end-card configured (HISTORY_INTRO / HISTORY_ENDCARD) — skipped.")

        # --- 6. Thumbnail ---
        title = file_data.get("title") if file_data else ""
        if not title and sheet is not None:
            title = ""  # (title lives in the Sheet's title_hindi; fetched separately if needed)
        thumb_scene = args.thumb_scene or 4  # she-wolf + twins: the iconic founding image
        if thumb_scene not in images_map:
            thumb_scene = int(scenes[0]["scene_number"])
        thumb = RENDERS / f"ep{ep}.jpg"
        log.info("Thumbnail from scene %d -> %s", thumb_scene, thumb.name)
        make_thumbnail(Path(images_map[thumb_scene]), title or "इतिहास की कहानी", cfg.caption_font, thumb, tmp)

    # --- 7. Sanity check ---
    info = probe_streams(body)
    audio_dur = duration_seconds(audio)
    drift = abs((info["duration"] or 0) - audio_dur)
    ok = info["has_video"] and info["has_audio"] and drift <= 2.5
    log.info("Sanity: video=%s audio=%s vdur=%.2fs adur=%.2fs drift=%.2fs -> %s",
             info["has_video"], info["has_audio"], info["duration"] or -1, audio_dur, drift,
             "PASS" if ok else "FAIL")

    # --- 8. Write back (only mark ready if sanity passed) ---
    if args.no_write:
        log.info("--no-write: skipping persistence.")
    elif not ok:
        log.error("Sanity check FAILED — leaving status unchanged. Not marking ready.")
    elif file_data is not None:
        file_data["video_file_path"] = str(body)
        file_data["thumbnail_path"] = str(thumb)
        file_data["status"] = "ready"
        file_path.write_text(json.dumps(file_data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Updated %s (status=ready)", file_path)
    elif row_number is not None:
        sheet.write_video_result(row_number, str(body), str(thumb))
        log.info("Wrote video/thumbnail paths to Sheet row %d (status=ready)", row_number)

    # --- Report ---
    bar = "=" * 66
    print(f"\n{bar}\nPHASE 4 RESULT — episode {ep}\n{bar}")
    print(f"Video:     {body}")
    print(f"Thumbnail: {thumb}  (scene {thumb_scene})")
    print(f"Streams:   video={'yes' if info['has_video'] else 'NO'}  "
          f"audio={'yes' if info['has_audio'] else 'NO'}")
    print(f"Duration:  video {info['duration']:.2f}s vs audio {audio_dur:.2f}s  (drift {drift:.2f}s)")
    print(f"Font:      {cfg.caption_font} (Devanagari via libass)")
    print(f"Sanity:    {'PASS — status=ready' if ok else 'FAIL — status unchanged'}")
    print(bar)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
