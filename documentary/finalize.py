#!/usr/bin/env python3
"""Phase 8 finalize — lock in the chosen title + thumbnail, set status='ready'.

Reads the next status='metadata_ready' row, applies YOUR title_choice /
thumbnail_choice (v1|v2|v3 or 1|2|3), copies the chosen thumbnail to the canonical
final path, records the final title, and sets status='ready' for Phase 9 to pick
up. Refuses (does not advance) if either choice is missing or invalid.

Usage: python finalize.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from config import load_config
from sheet import TopicQueue


def parse_choice(v: str, n: int) -> int | None:
    m = re.search(r"[123]", v or "")
    if not m:
        return None
    idx = int(m.group(0))
    return idx if 1 <= idx <= n else None


def main() -> int:
    cfg = load_config()
    queue = TopicQueue(cfg)
    rec = queue.next_metadata_ready()
    if not rec:
        print(f"[backend={queue.backend}] No status='metadata_ready' row. Nothing to finalize.")
        return 0

    sb = json.loads(rec["scene_breakdown"])
    meta = sb.get("metadata", {})
    titles = meta.get("titles", [])
    thumbs = meta.get("thumbnails", [])

    ti = parse_choice(rec["title_choice"], len(titles))
    thi = parse_choice(rec["thumbnail_choice"], len(thumbs))
    if not ti or not thi:
        print(f"⏸️  Not finalizing '{rec['topic']}'.")
        print(f"    title_choice={rec['title_choice']!r} → {'ok v'+str(ti) if ti else 'MISSING/invalid'}")
        print(f"    thumbnail_choice={rec['thumbnail_choice']!r} → {'ok v'+str(thi) if thi else 'MISSING/invalid'}")
        print(f"    Fill both with v1/v2/v3 (you have {len(titles)} titles, {len(thumbs)} thumbnails).")
        return 1

    final_title = titles[ti - 1]
    chosen_thumb = Path(thumbs[thi - 1])
    final_thumb = chosen_thumb.with_name("thumbnail_final.jpg")
    if chosen_thumb.exists():
        shutil.copyfile(chosen_thumb, final_thumb)
    else:
        print(f"⚠️  chosen thumbnail file not found: {chosen_thumb} (recording path anyway)")

    meta["final_title"] = final_title
    meta["final_thumbnail"] = str(final_thumb)
    sb["metadata"] = meta
    queue.write_ready(rec["ref"], json.dumps(sb, ensure_ascii=False, indent=2))

    print(f"✔ Finalized '{rec['topic']}'")
    print(f"   title  (v{ti}): {final_title}")
    print(f"   thumb  (v{thi}): {final_thumb}")
    print("   status='ready' → Phase 9 will auto-publish this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
