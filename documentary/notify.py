"""Notifications for the documentary channel topic batch.

Sends a phone-friendly summary of the 10 new topics (pillar + one-line reasoning)
so you can review and approve from your phone without opening the Sheet. Tries
Telegram first, then email (SMTP), and always prints to stdout as the final
fallback — so nothing is ever lost even with no channel configured.
"""
from __future__ import annotations

import json
import smtplib
import urllib.request
from email.mime.text import MIMEText

from config import Config


def build_summary(accepted: list[dict], backend: str, written: int,
                  rejected_count: int) -> str:
    lines = [
        "🎬 Documentary channel — 10 new topic ideas (status: DRAFT, awaiting your approval)",
        "",
    ]
    for i, t in enumerate(accepted, 1):
        lines.append(f"{i}. [{t.get('pillar', '?')}] {t.get('topic', '').strip()}")
        note = t.get("notes", "").strip()
        if note:
            lines.append(f"    ↳ {note}")
    lines += [
        "",
        f"Written to {backend}: {written} row(s). Rejected/considered: {rejected_count}.",
        "Review in the Sheet and change status to 'approved' for the ones you want scripted.",
    ]
    return "\n".join(lines)


def _send_telegram(cfg: Config, text: str) -> bool:
    if not (cfg.telegram_bot_token and cfg.telegram_chat_id):
        return False
    payload = json.dumps({"chat_id": cfg.telegram_chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
        data=payload, headers={"content-type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:  # noqa: BLE001 — fall through to the next channel
        print(f"[notify] Telegram send failed: {e}")
        return False


def _send_email(cfg: Config, text: str) -> bool:
    if not (cfg.smtp_host and cfg.smtp_user and cfg.smtp_pass and cfg.email_to):
        return False
    msg = MIMEText(text)
    msg["Subject"] = "Documentary channel — 10 new topic ideas to review"
    msg["From"] = cfg.smtp_user
    msg["To"] = cfg.email_to
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(cfg.smtp_user, cfg.smtp_pass)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[notify] Email send failed: {e}")
        return False


def send(cfg: Config, text: str) -> str:
    """Deliver the summary. Returns the channel used: 'telegram'|'email'|'stdout'."""
    if _send_telegram(cfg, text):
        print("[notify] summary sent via Telegram")
        return "telegram"
    if _send_email(cfg, text):
        print("[notify] summary sent via email")
        return "email"
    print("\n" + text + "\n")
    print("[notify] no Telegram/email configured — printed above")
    return "stdout"
