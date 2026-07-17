#!/usr/bin/env python3
"""Disk cleanup — delete local media for episodes that are safely on YouTube.

Scans data/ep*.json (the local-queue episode records) and, for every episode
that is status=published AND has a youtube_video_id recorded, deletes its LOCAL
media files (audio/epN_*, images/epN_*, renders/epN.mp4 + epN.jpg) — but only
once the newest of those files is older than --days (default 14). The data/
epN.json records themselves are NEVER touched: they are the durable ledger of
what was published and under which video id.

The DEFAULT mode is a dry run: it prints what WOULD be deleted and how many
bytes that would reclaim. Pass --delete to actually remove files.

Unparseable or incomplete JSON files are skipped (logged, never fatal). The
script always exits 0 when there is simply nothing to do.

TODO(sheet-mode): when episodes are driven from the Google Sheet instead of
local data/*.json files, add a --sheet mode here that reads status /
youtube_video_id via sheet.HistorySheet and applies the same rules. Out of
scope for v1, which is deliberately conservative and local-only.

Examples
--------
  # See what would be reclaimed (safe, default):
  python cleanup.py

  # Actually delete media for episodes published >= 30 days ago:
  python cleanup.py --days 30 --delete
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from config import PROJECT_DIR

AUDIO_DIR = PROJECT_DIR / "audio"
IMAGES_DIR = PROJECT_DIR / "images"
RENDERS_DIR = PROJECT_DIR / "renders"
DATA_DIR = PROJECT_DIR / "data"

(PROJECT_DIR / "logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_DIR / "logs" / "cleanup.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("cleanup")


def _episode_media(ep_num: int) -> list[Path]:
    """All local media files belonging to one episode. data/*.json is NOT media."""
    files: list[Path] = []
    files += sorted(AUDIO_DIR.glob(f"ep{ep_num}_*"))
    files += sorted(IMAGES_DIR.glob(f"ep{ep_num}_*"))
    for ext in ("mp4", "jpg"):
        p = RENDERS_DIR / f"ep{ep_num}.{ext}"
        if p.exists():
            files.append(p)
    return files


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


def main() -> int:
    ap = argparse.ArgumentParser(description="Delete local media for published episodes (dry-run by default)")
    ap.add_argument("--days", type=int, default=14,
                    help="Only delete media whose NEWEST file is older than this many days (default 14).")
    ap.add_argument("--delete", action="store_true",
                    help="Actually delete files. Without this flag the script only reports (dry run).")
    args = ap.parse_args()

    mode = "DELETE" if args.delete else "DRY-RUN"
    cutoff = time.time() - args.days * 86400
    log.info("cleanup starting  mode=%s  days=%d", mode, args.days)

    records = sorted(DATA_DIR.glob("ep*.json"))
    if not records:
        log.info("no data/ep*.json records found — nothing to do.")
        return 0

    total_reclaimed = 0
    eligible_eps = 0
    for rec in records:
        stem = rec.stem  # "ep96"
        try:
            ep_num = int(stem[2:])
        except ValueError:
            log.info("skip %s: filename is not epN.json", rec.name)
            continue
        try:
            data = json.loads(rec.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("skip %s: cannot parse (%s)", rec.name, e)
            continue
        if not isinstance(data, dict):
            log.info("skip %s: not a JSON object", rec.name)
            continue

        status = (data.get("status") or "").strip()
        video_id = (data.get("youtube_video_id") or "").strip()
        if status != "published" or not video_id:
            log.info("skip ep%d: status=%r youtube_video_id=%r (must be published with a video id)",
                     ep_num, status, video_id or None)
            continue

        files = _episode_media(ep_num)
        if not files:
            log.info("skip ep%d: published (%s) but no local media left.", ep_num, video_id)
            continue

        newest = max(f.stat().st_mtime for f in files)
        if newest > cutoff:
            age_days = (time.time() - newest) / 86400
            log.info("skip ep%d: newest media file is only %.1f days old (< %d).", ep_num, age_days, args.days)
            continue

        eligible_eps += 1
        ep_bytes = sum(f.stat().st_size for f in files)
        total_reclaimed += ep_bytes
        log.info("ep%d (video %s): %d files, %s", ep_num, video_id, len(files), _human(ep_bytes))
        for f in files:
            if args.delete:
                try:
                    f.unlink()
                    log.info("  deleted %s", f.relative_to(PROJECT_DIR))
                except OSError as e:
                    log.error("  FAILED to delete %s: %s", f, e)
            else:
                log.info("  would delete %s (%s)", f.relative_to(PROJECT_DIR), _human(f.stat().st_size))

    verb = "reclaimed" if args.delete else "would reclaim"
    log.info("cleanup done  mode=%s  episodes=%d  %s=%s", mode, eligible_eps, verb, _human(total_reclaimed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
