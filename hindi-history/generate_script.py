#!/usr/bin/env python3
"""Phase 1 — Hindi history script generation.

Reads the next draft topic from the Google Sheet, asks Gemini 2.5 Flash for a
Hindi narration package (script + 8-12 scene beats + metadata) as structured JSON,
prints the full result, and writes it back to the Sheet as status=script_ready.

Examples
--------
  # Test generation for one topic, print only (no Sheet needed):
  python generate_script.py --topic "The Founding of Rome" --no-write

  # Create/seed the separate tab in the Sheet (needs Sheets creds):
  python generate_script.py --init

  # Process the next draft row in the Sheet and write results back:
  python generate_script.py

  # Exercise the plumbing with no API key:
  python generate_script.py --topic "The Founding of Rome" --no-write --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from config import PROJECT_DIR, load_config, require_gemini_key, require_sheet
from gemini_client import Episode, Scene, validate

TEST_TOPIC = "The Founding of Rome"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_DIR / "logs" / "generate.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("phase1")


def _dry_run_episode(topic: str) -> Episode:
    """Canned, clearly-fake output so the flow is testable with no API key."""
    scenes = [
        Scene(
            scene_number=i,
            text=f"[DRY-RUN दृश्य {i}] '{topic}' विषय पर यह एक नमूना हिंदी वर्णन है। "
            "यह केवल पाइपलाइन जाँचने के लिए है, असली स्क्रिप्ट नहीं।",
            image_prompt_hint=f"[dry-run] flat illustrated history scene {i} for '{topic}'",
        )
        for i in range(1, 9)
    ]
    return Episode(
        title=f"[DRY-RUN] {topic} — हिंदी कहानी",
        description="यह एक ड्राई-रन विवरण है। असली आउटपुट के लिए API की ज़रूरत है।",
        tags=["इतिहास", "history", "कहानी", "ancient", "documentary"],
        full_script="\n\n".join(s.text for s in scenes),
        scenes=scenes,
    )


def print_episode(topic: str, ep: Episode, warnings: list[str]) -> None:
    bar = "=" * 72
    print(f"\n{bar}\nTOPIC: {topic}\n{bar}")
    print(f"\nTITLE (title_hindi):\n  {ep.title}")
    print(f"\nDESCRIPTION (description_hindi):\n  {ep.description}")
    print(f"\nTAGS ({len(ep.tags)}):\n  {', '.join(ep.tags)}")
    print(f"\nSCENES ({len(ep.scenes)}):")
    for s in ep.scenes:
        print(f"\n  [{s.scene_number}] {s.text}")
        print(f"      image_prompt_hint (EN): {s.image_prompt_hint}")
    wc = len(ep.full_script.split())
    print(f"\n{bar}\nFULL SCRIPT (script_hindi) — ~{wc} words:\n{bar}\n{ep.full_script}\n{bar}")
    if warnings:
        print("\n⚠️  REVIEW FLAGS:")
        for w in warnings:
            print(f"   - {w}")
    else:
        print("\n✅ No range warnings — scene/tag/length counts within brief targets.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1: Hindi history script generation")
    ap.add_argument("--topic", help="Generate for this topic directly (skips the Sheet read).")
    ap.add_argument("--row", type=int, help="Process a specific Sheet row number.")
    ap.add_argument("--no-write", action="store_true", help="Print output but do not write to the Sheet.")
    ap.add_argument("--dry-run", action="store_true", help="Use canned output; no API call.")
    ap.add_argument("--init", action="store_true",
                    help=f"Create/seed the '{TEST_TOPIC}' draft row in the separate tab, then exit.")
    ap.add_argument("--out", help="Also dump the full episode JSON to this path (for offline Phase 2 testing).")
    args = ap.parse_args()

    cfg = load_config()

    # --- Sheet setup mode ---
    if args.init:
        require_sheet(cfg)
        from sheet import HistorySheet
        HistorySheet(cfg).ensure_worksheet(seed_topics=[TEST_TOPIC])
        log.info("Initialized worksheet '%s' and seeded draft topic: %s", cfg.worksheet, TEST_TOPIC)
        return 0

    # --- Resolve topic + target row ---
    sheet = None
    row_number: int | None = None
    if args.topic:
        topic = args.topic
        if args.row:
            row_number = args.row
    else:
        # Read the next draft from the Sheet.
        require_sheet(cfg)
        from sheet import HistorySheet
        sheet = HistorySheet(cfg)
        if args.row:
            row_number, topic = args.row, sheet.get_row_topic(args.row)
            if not topic:
                raise SystemExit(f"Row {args.row} has no topic.")
        else:
            nxt = sheet.get_next_draft()
            if not nxt:
                log.info("No rows with status='draft'. Nothing to do.")
                return 0
            row_number, topic = nxt

    log.info("Processing topic: %s", topic)

    # --- Generate ---
    if args.dry_run:
        ep = _dry_run_episode(topic)
        warnings = validate(ep)
    else:
        require_gemini_key(cfg)
        from gemini_client import generate_episode
        ep, warnings = generate_episode(cfg, topic)

    print_episode(topic, ep, warnings)

    # --- Optional local dump (feeds Phase 2 offline testing) ---
    if args.out:
        Path(args.out).write_text(
            json.dumps(ep.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("Wrote episode JSON to %s", args.out)

    # --- Write back ---
    will_write = not args.no_write and row_number is not None
    if not will_write:
        why = "--no-write set" if args.no_write else "no target Sheet row (use the Sheet path or --row)"
        log.info("Not writing to Sheet (%s). Review the output above.", why)
        return 0

    assert row_number is not None  # guaranteed by will_write above; satisfies type-checker
    if sheet is None:
        require_sheet(cfg)
        from sheet import HistorySheet
        sheet = HistorySheet(cfg)
    sheet.write_result(row_number, ep)
    log.info("✅ Wrote results to row %d and set status=script_ready (topic: %s)", row_number, topic)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
