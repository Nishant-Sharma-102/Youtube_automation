#!/usr/bin/env python3
"""Phase 1 — documentary topic research + pipeline intake.

Weekly-ish job that:
  1. Reads the topics already in the Sheet (all statuses) for de-duplication.
  2. Asks Claude (web search enabled) for 10 fact-checked topic ideas across the
     four pillars, with a one-line reasoning per topic.
  3. Writes the 10 accepted topics into the Sheet as status='draft' (NOT
     auto-approved — you promote the ones you want to 'approved' by hand).
  4. Logs which candidates were rejected (duplicate / failed fact-check) so the
     reasoning is visible.
  5. Sends a phone-friendly summary via Telegram / email (prints as fallback).

Runs fine with no Google/Telegram creds: it falls back to a local mirror
(data/topics_mirror.json) and prints the summary, so you can test it now and
wire up the Sheet later.

Usage:
  python generate_topics.py            # full run
  python generate_topics.py --dry-run  # generate + show, but do NOT write/notify
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import BATCH_SIZE, PILLAR_TARGETS, PROJECT_DIR, load_config, require_anthropic_key
from notify import build_summary, send
from research import generate_topics
from sheet import TopicQueue

REJECT_LOG = PROJECT_DIR / "logs" / "rejected_topics.log"


def _pillar_counts(accepted: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in accepted:
        counts[t.get("pillar", "?")] = counts.get(t.get("pillar", "?"), 0) + 1
    return counts


def _log_rejected(rejected: list[dict], stamp: str) -> None:
    REJECT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with REJECT_LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n===== {stamp} — {len(rejected)} rejected/considered =====\n")
        for r in rejected:
            f.write(
                f"- [{r.get('pillar', '?')}] {r.get('topic', '').strip()}\n"
                f"    reason: {r.get('reason', '').strip()}\n"
            )


def _print_report(accepted: list[dict], rejected: list[dict], searches: int) -> None:
    print("\n" + "=" * 72)
    print(f"ACCEPTED — {len(accepted)} topics  (web searches run: {searches})")
    print("=" * 72)
    for i, t in enumerate(accepted, 1):
        print(f"\n{i}. [{t.get('pillar', '?')}] {t.get('topic', '').strip()}")
        print(f"   why: {t.get('notes', '').strip()}")
    print("\n" + "-" * 72)
    print(f"Pillar distribution: {_pillar_counts(accepted)}  (targets: {PILLAR_TARGETS})")
    print("-" * 72)
    print(f"\nREJECTED / CONSIDERED — {len(rejected)}")
    for r in rejected:
        print(f"  ✗ [{r.get('pillar', '?')}] {r.get('topic', '').strip()}")
        print(f"      {r.get('reason', '').strip()}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate and display topics, but do not write or notify.")
    args = ap.parse_args()

    cfg = load_config()
    require_anthropic_key(cfg)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    queue = TopicQueue(cfg)
    existing = queue.existing_topics()
    print(f"[{stamp}] backend={queue.backend}  model={cfg.anthropic_model}  "
          f"existing topics in queue: {len(existing)}")

    print(f"Asking Claude for {BATCH_SIZE} fact-checked topics (web search enabled)…",
          flush=True)
    result = generate_topics(cfg, existing)
    accepted = result["accepted"]
    rejected = result["rejected"]

    _print_report(accepted, rejected, result.get("search_count", 0))

    if len(accepted) != BATCH_SIZE:
        print(f"⚠️  Expected {BATCH_SIZE} accepted topics, got {len(accepted)}. "
              "Proceeding with what was returned.")

    if args.dry_run:
        print("--dry-run: nothing written, no notification sent.")
        return 0

    # 1. Log rejected reasoning (always, even if writing fails downstream).
    _log_rejected(rejected, stamp)
    print(f"Logged {len(rejected)} rejected/considered topics -> {REJECT_LOG}")

    # 2. Write accepted topics as draft rows.
    written = queue.append_drafts(accepted)
    dest = "Google Sheet" if queue.backend == "sheet" else \
        f"local mirror ({PROJECT_DIR / 'data' / 'topics_mirror.json'})"
    print(f"Wrote {written} new draft row(s) to {dest}.")

    # 3. Notify.
    summary = build_summary(accepted, dest, written, len(rejected))
    send(cfg, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
