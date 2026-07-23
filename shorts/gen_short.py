#!/usr/bin/env python3
"""Shorts pipeline — one self-contained phase that makes a vertical YouTube Short.

Unlike the long-form documentary pipeline (a multi-phase Sheet state machine), a Short
is small enough to build in a single pass:

  1. Claude writes a fresh short-form script from a topic  ->  title + 4-6 beats
     (Hindi narration + an English image prompt each) + description(#Shorts) + tags.
  2. Pollinations renders one VERTICAL (1080x1920) key frame per beat.
  3. The voice chain (ElevenLabs -> Google -> Edge) narrates each beat.
  4. ffmpeg assembles a vertical Ken-Burns video, optional music bed, optional
     burned-in captions (graceful fallback if the font/burn fails).
  5. Everything is written to shorts/data/short_<id>.json with status='ready'.

The uploader (orchestrator_shorts.js) then publishes it to the SAME channel as the
documentary pipeline (its token), tagged as a Short.

It REUSES the documentary building blocks unchanged (config, voice_providers,
visuals_pollinations, the ffmpeg helpers in assemble). Vertical dimensions come from
the DOC_VIDEO_W/H + DOC_POLLINATIONS_WIDTH/HEIGHT env the runner (make_short.sh) sets.

Usage:
  python gen_short.py "topic here"            # make one short from a topic
  python gen_short.py "topic" --id 7          # force the output id (default: next free)
  python gen_short.py "topic" --dry-run       # script only; no images/voice/ffmpeg
  python gen_short.py "topic" --no-captions   # skip burned-in captions
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import httpx

# Reuse the documentary channel's modules unchanged. This file lives in shorts/, the
# modules live in ../documentary and import each other by bare name, so we run with
# that directory on sys.path.
HERE = Path(__file__).resolve().parent
DOC_DIR = HERE.parent / "documentary"
sys.path.insert(0, str(DOC_DIR))

from config import load_config, require_anthropic_key  # noqa: E402
from voice_providers import build_voice_chain  # noqa: E402
from visuals_pollinations import generate_keyframe  # noqa: E402
from assemble import (  # noqa: E402
    concat_cmd,
    music_mix_cmd,
    run,
    run_ok,
    segment_cmd,
    slugify,
)

DATA_DIR = HERE / "data"
RENDERS = HERE.parent / "renders" / "shorts"
AUDIO_ROOT = HERE.parent / "audio" / "shorts"

API = "https://api.anthropic.com/v1/messages"
# A Short is 5 tight beats: a hook, three build beats, and a payoff/CTA. ~9-11s each
# lands the whole thing under a minute — the YouTube Shorts sweet spot.
N_BEATS = int((__import__("os").environ.get("SHORTS_N_BEATS") or "5"))

SYSTEM = (
    "You write punchy, high-retention YouTube SHORTS scripts. A Short is under 60 "
    "seconds: it must hook in the first 2 seconds, keep every line tight, and never "
    "sag. You write narration ONLY — spoken lines, no camera directions, no headers."
)


def build_prompt(topic: str, language: str) -> str:
    return f"""Write a YouTube SHORT (under 60 seconds) on this topic:

TOPIC: {topic}

Return STRICT JSON only (no markdown, no prose around it) with this exact shape:
{{
  "title": "a scroll-stopping title UNDER 90 chars (may include ONE emoji)",
  "beats": [
    {{
      "narration_text": "one or two tight spoken lines in {language}",
      "image_prompt": "a vivid, concrete ENGLISH image description for this beat"
    }}
    // EXACTLY {N_BEATS} beats
  ],
  "description": "2-3 line {language} description; end with 4-6 relevant hashtags",
  "tags": ["8-12 short search tags (mix {language} + English)"]
}}

Rules:
- EXACTLY {N_BEATS} beats. Beat 1 is a hard hook. The last beat pays it off.
- Each narration_text is SHORT — a Short has no room for long sentences.
- image_prompt must be a standalone visual (no text/watermarks), consistent in style
  across beats, and framed for a VERTICAL 9:16 phone screen.
- Narration + title + description are in {language}. image_prompt + tags may mix English.
- Do NOT put the word "shorts" or a #shorts tag in tags — the uploader adds that."""


IMG_STYLE_SUFFIX = (
    ", vertical 9:16 composition, cinematic, dramatic lighting, highly detailed, "
    "photorealistic, no text, no watermark"
)


def _extract_text(content_blocks: list) -> str:
    return "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()


def _parse_json(raw: str) -> dict:
    """Claude usually returns clean JSON, but tolerate a ```json fence or stray prose."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    else:
        # Fall back to the outermost {...} span.
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]
    return json.loads(raw)


def generate_script(cfg, topic: str) -> dict:
    api_key = require_anthropic_key(cfg)
    resp = httpx.post(
        API,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": cfg.anthropic_model,
            "max_tokens": 4000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": build_prompt(topic, cfg.narration_language)}],
        },
        timeout=300.0,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Claude API error {resp.status_code}: {resp.text[:800]}")
    text = _extract_text(resp.json().get("content", []))
    if not text:
        raise SystemExit("Claude returned no script text.")
    try:
        data = _parse_json(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Claude did not return valid JSON: {e}\n---\n{text[:800]}")

    beats = data.get("beats") or []
    if not beats:
        raise SystemExit("Script has no beats.")
    if not data.get("title"):
        raise SystemExit("Script has no title.")
    return data


def clip_duration_sec(path: Path) -> float:
    from mutagen.mp3 import MP3

    return float(MP3(str(path)).info.length)


def next_free_id() -> int:
    n = 0
    for f in DATA_DIR.glob("short_*.json"):
        m = re.match(r"short_(\d+)\.json$", f.name)
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


def _srt_ts(t: float) -> str:
    ms = int(round((t - int(t)) * 1000))
    s = int(t) % 60
    m = (int(t) // 60) % 60
    h = int(t) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(beats: list, path: Path) -> None:
    lines, t = [], 0.0
    for i, b in enumerate(beats, 1):
        dur = float(b["duration_sec"])
        lines.append(f"{i}\n{_srt_ts(t)} --> {_srt_ts(t + dur)}\n{b['narration_text'].strip()}\n")
        t += dur
    path.write_text("\n".join(lines), encoding="utf-8")


def resolve_caption_font() -> str | None:
    """A Devanagari-capable font for burned captions. Reuses thumbnail.py's resolver so
    Hindi renders as real conjunct glyphs (via libass). None -> skip burning."""
    try:
        from thumbnail import _resolve_font_path

        return _resolve_font_path(None)
    except Exception as e:  # noqa: BLE001
        print(f"  (no caption font resolved: {e}) — captions will not be burned")
        return None


def burn_captions_cmd(cfg, video: Path, srt: Path, font_path: str, out: Path) -> list[str]:
    """Burn the SRT over the video with libass (proper Devanagari shaping). We point
    fontsdir at the font's directory and name the family so libass picks it up."""
    font = Path(font_path)
    family = font.stem.replace("-", " ")
    # Big, bottom-anchored, thick outline — legible on a phone with sound off.
    style = (
        f"FontName={family},Fontsize=16,PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
        f"Alignment=2,MarginV=140,Bold=1"
    )
    esc_srt = str(srt).replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{esc_srt}':fontsdir='{font.parent}':force_style='{style}'"
    return [
        cfg.ffmpeg_bin, "-y", "-i", str(video), "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "copy", str(out),
    ]


def find_music() -> str | None:
    """Optional background bed: $SHORTS_MUSIC, else the first file in shorts/assets/."""
    import os

    env = os.environ.get("SHORTS_MUSIC")
    if env and Path(env).exists():
        return env
    assets = HERE / "assets"
    if assets.is_dir():
        for f in sorted(assets.iterdir()):
            if f.suffix.lower() in (".mp3", ".m4a", ".aac", ".wav"):
                return str(f)
    return None


def assemble(cfg, beats: list, slug: str, burn_caps: bool) -> Path:
    rdir = RENDERS / slug
    seg_dir = rdir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    final = rdir / "short.mp4"

    # One Ken-Burns segment per beat (reuses the documentary single-image path).
    seg_paths = []
    for i, b in enumerate(beats):
        seg = seg_dir / f"seg_{i + 1:03d}.mp4"
        scene = {
            "keyframe_path": b["keyframe_path"],
            "audio_path": b["audio_path"],
            "duration_sec": b["duration_sec"],
        }
        run(segment_cmd(cfg, scene, i, seg), f"beat {i + 1} ({b['duration_sec']:.1f}s)")
        seg_paths.append(seg)

    list_file = seg_dir / "segments.txt"
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_paths), encoding="utf-8")

    music = find_music()
    stitched = rdir / ("concat.mp4" if music else "stitched.mp4")
    run(concat_cmd(cfg, list_file, stitched), "concat beats")
    if music:
        mixed = rdir / "stitched.mp4"
        run(music_mix_cmd(cfg, stitched, music, mixed), "mix music bed under narration")
        stitched.unlink(missing_ok=True)
        stitched = mixed
        print(f"  music bed: {music}")

    # Burned captions are a big win on mobile/sound-off, but never let a font/burn
    # problem cost us the whole video: fall back to the uncaptioned cut.
    if burn_caps:
        font = resolve_caption_font()
        if font:
            srt = rdir / "captions.srt"
            write_srt(beats, srt)
            if run_ok(burn_captions_cmd(cfg, stitched, srt, font, final), "burn captions"):
                stitched.unlink(missing_ok=True)
                return final
            print("  ⚠️ caption burn failed — keeping the uncaptioned cut.")
    stitched.rename(final)
    return final


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topic", help="What the Short is about.")
    ap.add_argument("--id", type=int, default=0, help="Output id (default: next free).")
    ap.add_argument("--dry-run", action="store_true", help="Script only; no media or ffmpeg.")
    ap.add_argument("--no-captions", action="store_true", help="Don't burn captions.")
    args = ap.parse_args()

    cfg = load_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sid = args.id or next_free_id()
    out_json = DATA_DIR / f"short_{sid}.json"

    print(f"── Short #{sid}: {args.topic}")
    print(f"   dims={cfg.video_w}x{cfg.video_h}@{cfg.fps}  lang={cfg.narration_language}  model={cfg.anthropic_model}")
    if cfg.video_h <= cfg.video_w:
        print(f"   ⚠️ dimensions are not vertical ({cfg.video_w}x{cfg.video_h}). "
              "Run via make_short.sh (sets DOC_VIDEO_W/H=1080/1920) for a real Short.")

    data = generate_script(cfg, args.topic)
    beats = data["beats"]
    print(f"   title: {data['title']}")
    print(f"   beats: {len(beats)}")

    record = {
        "id": sid,
        "topic": args.topic,
        "title": data["title"],
        "description": data.get("description", ""),
        "tags": data.get("tags", []),
        "language_code": cfg.language_code,
        "status": "draft",
        "youtube_video_id": None,
        "video_file_path": None,
        "beats": beats,
    }

    if args.dry_run:
        out_json.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n--dry-run: wrote script to {out_json} (status=draft, no media).")
        return 0

    slug = f"{sid:03d}-{slugify(args.topic)}"
    img_dir = RENDERS / slug / "images"
    aud_dir = AUDIO_ROOT / slug
    img_dir.mkdir(parents=True, exist_ok=True)
    aud_dir.mkdir(parents=True, exist_ok=True)

    chain = build_voice_chain(cfg)
    total = 0.0
    for i, b in enumerate(beats, 1):
        img = img_dir / f"{i:03d}.jpg"
        generate_keyframe(cfg, b["image_prompt"] + IMG_STYLE_SUFFIX, img, seed=sid * 100 + i)
        clip = aud_dir / f"{i:03d}.mp3"
        chain.synthesize_to_file(b["narration_text"], clip)
        dur = clip_duration_sec(clip)
        b["keyframe_path"] = str(img.resolve())
        b["audio_path"] = str(clip.resolve())
        b["duration_sec"] = round(dur, 2)
        total += dur
        print(f"   beat {i}: {dur:4.1f}s  [{chain.provider_name}]  \"{b['narration_text'][:44]}…\"", flush=True)

    print(f"   total runtime: {total:.1f}s")
    if total > 180:
        print("   ⚠️ over 180s — YouTube may not treat this as a Short. Trim narration.")

    video = assemble(cfg, beats, slug, burn_caps=not args.no_captions)

    record["status"] = "ready"
    record["video_file_path"] = str(video.resolve())
    record["runtime_sec"] = round(total, 2)
    out_json.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✔ Short #{sid} ready: {video}")
    print(f"  metadata -> {out_json}  (status=ready; run orchestrator_shorts.js to publish)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
