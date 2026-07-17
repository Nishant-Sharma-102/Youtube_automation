#!/usr/bin/env python3
"""Phase 6 — weekly monitoring summary for BOTH channels in one message.

Reports each pipeline's last-run health so you can answer "did either channel
publish this week?" without SSHing in. Sends via the History channel's Telegram
creds (TELEGRAM_HISTORY_BOT_TOKEN / _CHAT_ID); prints to stdout if unset.

Cron (weekly, Monday 09:00 UTC):
  0 9 * * 1  TZ=UTC  /home/ubuntu/history-channel/.venv/bin/python \
    /home/ubuntu/history-channel/monitor_summary.py >> /var/log/channel-monitor.log 2>&1
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_DIR = Path(__file__).resolve().parent
KIDS_DIR = Path(os.environ.get("KIDS_CHANNEL_DIR", HISTORY_DIR.parent))
WINDOW_DAYS = 7


def _recent(ts: float) -> bool:
    return datetime.now(timezone.utc) - datetime.fromtimestamp(ts, timezone.utc) <= timedelta(days=WINDOW_DAYS)


def history_status() -> str:
    log = HISTORY_DIR / "logs" / "publish.log"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    published = [l for l in lines if "status=published" in l]
    last = published[-1] if published else (lines[-1] if lines else "(no publish log yet)")
    fresh = "✅ published in last 7d" if (log.exists() and _recent(log.stat().st_mtime) and published) \
        else "⚠️ no publish in last 7d"
    fatal = any("FATAL" in l for l in lines[-50:])
    return f"History: {fresh}{'  ⛔ recent FATAL in log' if fatal else ''}\n  last: {last[-140:]}"



def kids_status() -> str:
    # Kids channel uses a SQLite content queue; report its most recent published row.
    db = KIDS_DIR / "data" / "content-queue.db"
    if not db.exists():
        return "Kids: (content-queue.db not found — set KIDS_CHANNEL_DIR)"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = con.execute(
            "SELECT video_number, title, status FROM content_queue "
            "WHERE status='published' ORDER BY video_number DESC LIMIT 1"
        ).fetchone()
        con.close()
    except Exception as e:  # schema differences etc. — don't crash the summary
        return f"Kids: (could not read DB: {e})"
    if not row:
        return "Kids: ⚠️ no published episodes recorded"
    return f"Kids: latest published #{row[0]} — {row[1]!r} ({row[2]})"


def send(text: str) -> None:
    token = os.environ.get("TELEGRAM_HISTORY_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_HISTORY_CHAT_ID")
    if token and chat:
        data = json.dumps({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"content-type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=15)
            print("summary sent via Telegram")
            return
        except Exception as e:
            print(f"Telegram send failed ({e}); printing instead")
    print(text)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = (
        f"📊 Channel pipeline summary — {stamp} (last {WINDOW_DAYS}d)\n\n"
        f"{history_status()}\n\n{kids_status()}"
    )
    send(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
