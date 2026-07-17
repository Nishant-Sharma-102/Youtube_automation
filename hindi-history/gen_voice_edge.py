#!/usr/bin/env python3
"""Generate episode narration with Microsoft Edge TTS — FREE, no API key, no
billing, no daily cap. hi-IN-MadhurNeural is a warm male Hindi neural voice;
slower rate + lower pitch give it a deeper, storyteller feel.

Writes audio/ep{N}_scene{K}.mp3 + audio/ep{N}_full.mp3 and updates each scene's
duration_seconds from the real audio, so Phase-4 assembly stays in sync.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import edge_tts

from audio_utils import concat_mp3, duration_seconds
from config import PROJECT_DIR

AUDIO = PROJECT_DIR / "audio"
# Defaults = deep Hindi history narrator; override via env for other channels (e.g. kids).
VOICE = os.environ.get("HISTORY_EDGE_VOICE") or "hi-IN-MadhurNeural"
RATE = os.environ.get("HISTORY_EDGE_RATE") or "+9%"
PITCH = os.environ.get("HISTORY_EDGE_PITCH") or "-2Hz"


async def _synth(text: str, out: Path) -> None:
    last = None
    for attempt in range(1, 4):
        try:
            await edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(out))
            if out.exists() and out.stat().st_size > 2000:
                return
            raise RuntimeError("empty audio")
        except Exception as e:  # transient network
            last = e
            await asyncio.sleep(2 * attempt)
    raise SystemExit(f"edge-tts failed after retries: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, default=2)
    ap.add_argument("--scenes-file", required=True)
    args = ap.parse_args()

    ep = args.episode
    fp = Path(args.scenes_file)
    d = json.loads(fp.read_text(encoding="utf-8"))
    scenes = sorted(d["scenes"], key=lambda s: int(s["scene_number"]))
    AUDIO.mkdir(parents=True, exist_ok=True)
    print(f"Edge TTS (voice={VOICE}, rate={RATE}, pitch={PITCH}) — {len(scenes)} scenes", flush=True)

    parts = []
    for s in scenes:
        n = int(s["scene_number"])
        out = AUDIO / f"ep{ep}_scene{n}.mp3"
        text = s["text"].strip()
        print(f"scene {n}: {len(text)} chars -> {out.name}", flush=True)
        asyncio.run(_synth(text, out))
        dur = duration_seconds(out)
        s["duration_seconds"] = dur
        parts.append(out)
        print(f"  ok, {dur:.2f}s", flush=True)

    full = AUDIO / f"ep{ep}_full.mp3"
    from music_bed import add_music_bed, enabled
    if enabled():
        raw = AUDIO / f"ep{ep}_narration_raw.mp3"
        concat_mp3(parts, raw)
        print("mixing cinematic ambient music bed under narration (ducked)...", flush=True)
        add_music_bed(raw, full)
    else:
        concat_mp3(parts, full)
    total = duration_seconds(full)
    d["scenes"] = scenes
    d["audio_path"] = str(full)
    fp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"full track -> {full.name} ({total:.2f}s); updated {fp}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
