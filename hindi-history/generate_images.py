#!/usr/bin/env python3
"""Phase 3 — illustration generation (one image per scene, via Pollinations.ai).

Reads an audio_ready episode, builds each scene's prompt (hint + configurable style
suffix), downloads a 1920x1080 image per scene with a delay + retries, sanity-checks
that every scene got an image, flags scenes naming real historical entities for
manual review, and writes images_json back with status=images_ready.

Examples
--------
  # Offline (local Phase-1/2 dump, no Sheet):
  python generate_images.py --episode 1 --scenes-file data/ep1.json

  # From the Sheet:
  python generate_images.py --episode 1

  # Regenerate just one scene after a prompt tweak:
  python generate_images.py --episode 1 --scenes-file data/ep1.json --only 7
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from config import PROJECT_DIR, load_config, require_sheet
from images import build_prompt, fetch_image, review_flags

IMAGES_DIR = PROJECT_DIR / "images"
WIDTH, HEIGHT = 1920, 1080

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_DIR / "logs" / "images.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("phase3")


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3: per-scene illustration generation")
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--scenes-file", help="Local JSON dump to read/write instead of the Sheet.")
    ap.add_argument("--row", type=int, help="Sheet row to process (default: next audio_ready row).")
    ap.add_argument("--only", type=int, help="Regenerate only this scene_number.")
    ap.add_argument("--delay", type=float, default=2.5, help="Seconds between requests (rate-limit).")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    ep = args.episode

    # --- 1. Load scenes ---
    sheet = None
    row_number = None
    file_data = None
    file_path = None
    if args.scenes_file:
        file_path = Path(args.scenes_file)
        file_data = json.loads(file_path.read_text(encoding="utf-8"))
        scenes = file_data["scenes"]
    else:
        require_sheet(cfg)
        from sheet import HistorySheet
        sheet = HistorySheet(cfg)
        if args.row:
            row_number, scenes = sheet.get_row_scenes(args.row)
        else:
            got = sheet.get_next_ready_for_images()
            if not got:
                log.info("No rows with status='audio_ready'. Nothing to do.")
                return 0
            row_number, scenes = got

    scenes = sorted(scenes, key=lambda s: int(s["scene_number"]))
    targets = [s for s in scenes if args.only is None or int(s["scene_number"]) == args.only]
    if not targets:
        raise SystemExit(f"--only {args.only}: no such scene.")
    log.info("Style suffix: %s", cfg.image_style)
    log.info("Generating %d image(s) for episode %d", len(targets), ep)

    # --- 2-6. Generate each scene's image, collect flags/failures ---
    ok_scenes: list[int] = []
    failed: list[tuple[int, str]] = []
    flags: dict[int, list[str]] = {}
    for idx, sc in enumerate(targets):
        n = int(sc["scene_number"])
        hint = sc["image_prompt_hint"]
        prompt = build_prompt(hint, cfg.image_style)
        flags[n] = review_flags(hint)
        out = IMAGES_DIR / f"ep{ep}_scene{n}.jpg"
        log.info("scene %d: fetching -> %s", n, out.name)
        success, detail = fetch_image(
            prompt, out, width=WIDTH, height=HEIGHT, seed=n,
            log=lambda m: log.info(m),
        )
        if success:
            sc["image_path"] = str(out)
            ok_scenes.append(n)
            log.info("scene %d: OK (%s)%s", n, detail,
                     f"  ⚑ review: {', '.join(flags[n])}" if flags[n] else "")
        else:
            failed.append((n, detail))
            log.error("scene %d: FAILED (%s)", n, detail)
        if idx < len(targets) - 1:
            time.sleep(args.delay)

    # --- 5. Sanity check: every (targeted) scene has an image file ---
    missing = [int(s["scene_number"]) for s in targets
               if not (IMAGES_DIR / f"ep{ep}_scene{int(s['scene_number'])}.jpg").exists()]

    # --- 7. Write back (only advance to images_ready if the WHOLE episode is covered) ---
    images_map = {
        int(s["scene_number"]): str(IMAGES_DIR / f"ep{ep}_scene{int(s['scene_number'])}.jpg")
        for s in scenes
        if (IMAGES_DIR / f"ep{ep}_scene{int(s['scene_number'])}.jpg").exists()
    }
    all_covered = len(images_map) == len(scenes)

    if args.no_write:
        log.info("--no-write: skipping persistence.")
    elif not all_covered:
        log.warning("Not all scenes have images (%d/%d) — leaving status unchanged. "
                    "Regenerate failures with --only N.", len(images_map), len(scenes))
        if file_data is not None:
            file_data["scenes"] = scenes
            file_data["images_json"] = images_map
            file_path.write_text(json.dumps(file_data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        if file_data is not None:
            file_data["scenes"] = scenes
            file_data["images_json"] = images_map
            file_data["status"] = "images_ready"
            file_path.write_text(json.dumps(file_data, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("Updated %s (status=images_ready)", file_path)
        elif row_number is not None:
            sheet.write_images_result(row_number, scenes, images_map)
            log.info("Wrote images_json to Sheet row %d (status=images_ready)", row_number)

    # --- Report ---
    bar = "=" * 66
    print(f"\n{bar}\nPHASE 3 RESULT — episode {ep}\n{bar}")
    print(f"Scenes generated successfully: {len(ok_scenes)}/{len(targets)}")
    print("\nImage file paths:")
    for n in sorted(images_map):
        print(f"  scene {n:>2}: {images_map[n]}")
    if failed:
        print("\n❌ FAILED (regenerate with --only N):")
        for n, why in failed:
            print(f"  scene {n}: {why}")
    flagged = {n: f for n, f in flags.items() if f}
    print(f"\n⚑ Scenes flagged for manual review ({len(flagged)}/{len(targets)}) — "
          "named real figures/places/events (AI images of these are often inaccurate):")
    if flagged:
        for n in sorted(flagged):
            print(f"  scene {n}: {', '.join(flagged[n])}")
    else:
        print("  (none — all prompts were decorative/scenic)")
    unflagged = [n for n in (int(s["scene_number"]) for s in targets) if not flags.get(n)]
    if unflagged:
        print(f"\nScenes NOT flagged (scenic/decorative): {', '.join(map(str, sorted(unflagged)))}")
    print(f"\nStatus: {'images_ready' if (all_covered and not args.no_write) else 'unchanged (incomplete)'}")
    print(bar)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
