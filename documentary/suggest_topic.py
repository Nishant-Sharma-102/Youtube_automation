#!/usr/bin/env python3
"""Print ONE suggested, fact-checked documentary topic for a given pillar (category).

Thin CLI wrapper around research.suggest_one so the Node dashboard/API can get an
AI-picked topic when the user selects a category but types no specific topic.

  documentary/.venv/bin/python suggest_topic.py --pillar "History"
  -> prints the topic string on stdout (nothing else), or exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import sys

from config import load_config
from sheet import TopicQueue
import research


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pillar", required=True)
    args = ap.parse_args()
    cfg = load_config()
    q = TopicQueue(cfg)
    picked = research.suggest_one(cfg, args.pillar, q.existing_topics())
    topic = (picked.get("topic") or "").strip()
    if not topic:
        print("no topic returned", file=sys.stderr)
        return 1
    print(topic)  # ONLY the topic on stdout
    return 0


if __name__ == "__main__":
    sys.exit(main())
