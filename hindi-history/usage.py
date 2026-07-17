"""Google Cloud TTS free-tier usage tracking.

Appends one record per episode to logs/tts_usage.jsonl and computes the running
monthly total per voice tier, so we can watch the 4M (Standard) / 1M (WaveNet)
monthly free-tier ceilings and warn before hitting them.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import PROJECT_DIR
from tts import tier_limit, voice_tier

USAGE_FILE = PROJECT_DIR / "logs" / "tts_usage.jsonl"
WARN_AT = 0.80  # warn once monthly usage crosses 80% of the tier's free allowance


def month_total(month: str, tier: str) -> int:
    if not USAGE_FILE.exists():
        return 0
    total = 0
    for line in USAGE_FILE.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("month") == month and e.get("tier") == tier:
            total += int(e.get("chars", 0))
    return total


def record(episode: int, chars: int, voice_name: str, *, persist: bool = True) -> dict:
    """Record this episode's real character usage and return a usage summary.

    persist=False (e.g. --silent runs) computes the summary without charging the
    log, since no real quota was consumed."""
    tier = voice_tier(voice_name)
    now = datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    if persist:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": now.isoformat(),
            "month": month,
            "tier": tier,
            "voice": voice_name,
            "episode": episode,
            "chars": chars,
        }
        with USAGE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    total = month_total(month, tier)
    if not persist:
        total += chars  # show what this run WOULD add
    limit = tier_limit(tier)
    pct = (total / limit * 100) if limit else 0.0
    return {
        "tier": tier,
        "month": month,
        "voice": voice_name,
        "episode_chars": chars,
        "month_total": total,
        "limit": limit,
        "pct": round(pct, 2),
        "warn": pct >= WARN_AT * 100,
        "persisted": persist,
    }
