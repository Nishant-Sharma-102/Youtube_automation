#!/usr/bin/env python3
"""Phase 4 — per-scene voice narration for a storyboard_ready episode.

Reads the next status='storyboard_ready' row, synthesizes one audio clip per
scene (voice provider chain: ElevenLabs -> Google Cloud TTS -> Edge), measures
each clip's duration, writes audio_path + duration_sec back into every scene of
the scene_breakdown JSON, and sets status='audio_ready'. Per-scene durations are
what time the Ken Burns pans / kling motion downstream.

Usage:
  python gen_voice.py                     # full episode, provider chain, writes back
  python gen_voice.py --limit 3           # PREVIEW first 3 scenes only, no write-back
  python gen_voice.py --provider edge     # force one provider (elevenlabs|google|edge)
  python gen_voice.py --dry-run           # generate audio + report, but don't write back
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from config import PROJECT_DIR, load_config
from sheet import TopicQueue
from voice_providers import build_voice_chain

AUDIO_ROOT = PROJECT_DIR / "audio"
# Defensive: Phase 3 already strips these, but never voice an editorial marker.
FACT_MARKER_RE = re.compile(r"⟦FACT-CHECK:.*?⟧", re.DOTALL)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "episode"


def clip_duration_sec(path: Path) -> float:
    """MP3 duration via mutagen (pure-Python, no ffmpeg needed)."""
    from mutagen.mp3 import MP3
    return float(MP3(str(path)).info.length)


def fmt(seconds: float) -> str:
    return f"{int(seconds // 60)}m {seconds % 60:04.1f}s"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0,
                    help="Synthesize only the first N scenes as a PREVIEW (no write-back).")
    ap.add_argument("--provider", choices=["elevenlabs", "google", "edge"],
                    help="Force one provider instead of the ElevenLabs->Google->Edge chain.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Synthesize + report, but do not write back to the Sheet.")
    args = ap.parse_args()

    cfg = load_config()
    queue = TopicQueue(cfg)
    rec = queue.next_storyboard_ready()
    if not rec:
        print(f"[backend={queue.backend}] No rows with status='storyboard_ready'. Nothing to do.")
        return 0

    try:
        sb = json.loads(rec["scene_breakdown"])
    except json.JSONDecodeError as e:
        raise SystemExit(f"scene_breakdown is not valid JSON: {e}")
    scenes = sb.get("scenes", [])
    if not scenes:
        raise SystemExit("scene_breakdown has no scenes — run Phase 3 first.")

    chain = build_voice_chain(cfg, force=args.provider)
    out_dir = AUDIO_ROOT / slugify(rec["topic"])
    out_dir.mkdir(parents=True, exist_ok=True)

    preview = args.limit and args.limit < len(scenes)
    todo = scenes[:args.limit] if args.limit else scenes

    print(f"[backend={queue.backend}] {'PREVIEW ' if preview else ''}"
          f"synthesizing {len(todo)}/{len(scenes)} scenes")
    print(f"Episode: [{rec['pillar']}] {rec['topic']}")
    print(f"Output dir: {out_dir}", flush=True)

    total = 0.0
    for s in todo:
        n = int(s["scene_number"])
        text = FACT_MARKER_RE.sub("", s.get("narration_text", "")).strip()
        if not text:
            print(f"  scene {n:>2}: (empty narration, skipped)")
            continue
        clip = out_dir / f"{n:03d}.mp3"
        chain.synthesize_to_file(text, clip)
        dur = clip_duration_sec(clip)
        s["audio_path"] = str(clip)
        s["duration_sec"] = round(dur, 2)
        total += dur
        print(f"  scene {n:>2}: {dur:6.2f}s  [{chain.provider_name}]  {clip.name}  "
              f"\"{text[:52]}{'…' if len(text) > 52 else ''}\"", flush=True)

    print("-" * 68)
    print(f"Voice provider used: {chain.provider_name}")
    print(f"Scenes voiced: {len(todo)}   total audio: {fmt(total)}")
    if not preview and not args.dry_run:
        # Only meaningful for a full render.
        print(f"Full-episode narration runtime: {fmt(total)}")

    if preview:
        print("\nPREVIEW mode (--limit): nothing written back. Run without --limit for the full episode.")
        return 0
    if args.dry_run:
        print("\n--dry-run: nothing written back.")
        return 0

    sb["scenes"] = scenes
    sb["audio_dir"] = str(out_dir)
    sb["total_audio_sec"] = round(total, 2)
    queue.write_audio(rec["ref"], json.dumps(sb, ensure_ascii=False, indent=2))
    print(f"\n✔ Wrote per-scene audio_path + duration_sec and set status='audio_ready' "
          f"({'Google Sheet' if queue.backend == 'sheet' else 'local mirror'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
