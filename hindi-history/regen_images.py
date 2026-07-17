#!/usr/bin/env python3
"""Regenerate all scene images at 1920x1080 via Pollinations with a cinematic
style, using the Claude-written per-scene image prompts. Free, no API key."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import argparse
import os

from config import PROJECT_DIR
from images import build_prompt, fetch_image

IMAGES = PROJECT_DIR / "images"
# Default = cinematic history style; override via HISTORY_IMG_STYLE (e.g. kids cartoon).
STYLE = os.environ.get("HISTORY_IMG_STYLE") or (
    "cinematic historical illustration, epic and dramatic, dramatic volumetric "
    "lighting, rich detail, painterly digital art, highly detailed, atmospheric, "
    "widescreen composition, no text, no watermark")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, default=1)
    args = ap.parse_args()
    ep = args.episode
    fp = Path(f"data/ep{ep}.json")
    d = json.loads(fp.read_text(encoding="utf-8"))
    scenes = sorted(d["scenes"], key=lambda s: int(s["scene_number"]))
    IMAGES.mkdir(parents=True, exist_ok=True)
    images_json = {}
    for s in scenes:
        n = int(s["scene_number"])
        out = IMAGES / f"ep{ep}_scene{n}.jpg"
        hint = s["image_prompt_hint"]
        # Pollinations sometimes 500s on a specific long/complex prompt. Try the full
        # prompt, then a shortened one with a fresh seed, then a generic historical
        # fallback — so one flaky image can't abort the whole episode.
        short = " ".join(hint.split()[:10])
        attempts = [
            (build_prompt(hint, STYLE), n * 7),
            (build_prompt(short, STYLE), n * 7 + 1000),
            ("ancient historical scene, " + STYLE, n * 7 + 2000),
        ]
        ok = False
        for i, (prompt, seed) in enumerate(attempts, 1):
            print(f"scene {n}: fetch 1920x1080 (variant {i}/{len(attempts)}) -> {out.name}", flush=True)
            ok, info = fetch_image(prompt, out, width=1920, height=1080, seed=seed,
                                   log=lambda m: print(m, flush=True))
            if ok:
                print(f"  ok ({info}){' [fallback prompt]' if i > 1 else ''}", flush=True)
                break
        if not ok:
            raise SystemExit(f"scene {n} image failed after {len(attempts)} prompt variants: {info}")
        images_json[str(n)] = str(out)
        s["image_path"] = str(out)

    d["images_json"] = images_json
    d["scenes"] = scenes
    fp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"regenerated {len(scenes)} images at 1920x1080", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
