"""Configuration for the Hindi history channel pipeline.

All secrets come from environment variables (loaded from a local .env). Nothing
is ever hardcoded. This project is deliberately separate from the kids animation
channel — its own .env, its own Sheet/tab, its own queue.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent

# Load this project's own .env only. We do NOT auto-load the kids project's .env —
# the pipelines are kept separate on purpose. Reuse the same Gemini key if you like,
# but put it in THIS project's .env.
load_dotenv(PROJECT_DIR / ".env")

# The Sheet columns this pipeline reads/writes. Access is by header name (not
# position), so you may reorder columns in the Sheet. audio_path/video_path are
# added for Phases 2 and 4 to store output paths; status flows
# draft -> script_ready -> audio_ready -> ready -> published.
COLUMNS = [
    "topic",
    "script_hindi",
    "title_hindi",
    "description_hindi",
    "tags",
    "scene_breakdown",
    "audio_path",
    "images_json",
    "video_file_path",
    "thumbnail_path",
    "status",
    "scheduled_date",
]


@dataclass
class Config:
    gemini_api_key: str | None
    gemini_model: str
    sheet_id: str | None
    worksheet: str
    service_account_file: str | None
    oauth_client_file: str | None
    oauth_token_file: str | None
    tts_voice: str
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    elevenlabs_model: str
    image_style: str
    caption_font: str
    intro_path: str | None
    endcard_path: str | None


def load_config() -> Config:
    # One service account can serve both Sheets and Text-to-Speech (enable both
    # APIs on it). Accept the standard GOOGLE_APPLICATION_CREDENTIALS too.
    sa = (
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or ""
    ).strip() or None
    return Config(
        gemini_api_key=(os.environ.get("GEMINI_API_KEY") or "").strip() or None,
        gemini_model=(os.environ.get("GEMINI_MODEL") or "").strip() or "gemini-2.5-flash",
        sheet_id=(os.environ.get("HISTORY_SHEET_ID") or "").strip() or None,
        # A NEW tab, separate from the kids channel queue.
        worksheet=(os.environ.get("HISTORY_WORKSHEET") or "").strip() or "hindi_history",
        service_account_file=sa,
        # OAuth client (desktop app) + the token minted from it by auth_setup.py.
        oauth_client_file=(os.environ.get("GOOGLE_OAUTH_CLIENT_JSON") or "").strip()
        or str(PROJECT_DIR / "oauth-client.json"),
        oauth_token_file=(os.environ.get("GOOGLE_OAUTH_TOKEN_JSON") or "").strip()
        or str(PROJECT_DIR / "token.json"),
        # hi-IN. WaveNet = better quality (1M chars/mo free); swap to a
        # hi-IN-Standard-* voice for the 4M/mo tier.
        tts_voice=(os.environ.get("HISTORY_TTS_VOICE") or "").strip() or "hi-IN-Wavenet-A",
        # Primary voice provider. Needs an API key + a voice ID (any multilingual
        # voice renders Hindi via eleven_multilingual_v2). Falls back to Google/
        # Gemini/Edge if unset or if a request fails.
        elevenlabs_api_key=(os.environ.get("ELEVENLABS_API_KEY") or "").strip() or None,
        elevenlabs_voice_id=(os.environ.get("HISTORY_ELEVENLABS_VOICE_ID") or "").strip() or None,
        elevenlabs_model=(os.environ.get("HISTORY_ELEVENLABS_MODEL") or "").strip()
        or "eleven_multilingual_v2",
        # One knob for the whole channel's art style — appended to every scene's
        # image prompt so all episodes look visually consistent. Tweak once here.
        image_style=(os.environ.get("HISTORY_IMAGE_STYLE") or "").strip()
        or (
            "flat illustrated history storytelling style, warm muted color palette, "
            "painterly digital art, cinematic lighting, no text, no watermark, "
            "16:9 widescreen composition"
        ),
        # Devanagari-capable font family (must be installed / fontconfig-visible).
        # Lohit Devanagari ships on this box; swap for "Noto Sans Devanagari" if installed.
        caption_font=(os.environ.get("HISTORY_CAPTION_FONT") or "").strip() or "Lohit Devanagari",
        # Optional reusable bumpers (you provide these). Skipped if unset/missing.
        intro_path=(os.environ.get("HISTORY_INTRO") or "").strip() or None,
        endcard_path=(os.environ.get("HISTORY_ENDCARD") or "").strip() or None,
    )


def require_gemini_key(cfg: Config) -> str:
    if not cfg.gemini_api_key:
        raise SystemExit(
            "GEMINI_API_KEY is not set. Add it to hindi-history/.env, "
            "or run with --dry-run to test the flow without a key."
        )
    return cfg.gemini_api_key


def require_sheet(cfg: Config) -> str:
    """Ensure a Sheet ID and *some* Google credential (service account OR OAuth token)."""
    if not cfg.sheet_id:
        raise SystemExit("HISTORY_SHEET_ID is not set in hindi-history/.env.")
    has_sa = bool(cfg.service_account_file and Path(cfg.service_account_file).exists())
    has_oauth = bool(cfg.oauth_token_file and Path(cfg.oauth_token_file).exists())
    if not (has_sa or has_oauth):
        raise SystemExit(
            "No Google credentials. Either set GOOGLE_SERVICE_ACCOUNT_JSON to a service-account "
            "key, or run `python auth_setup.py` once to create token.json from your OAuth client."
        )
    return cfg.sheet_id
