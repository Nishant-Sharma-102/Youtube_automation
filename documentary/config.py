"""Configuration for the cinematic AI documentary channel (English).

Phase 1 = topic research + pipeline intake. This channel is deliberately SEPARATE
from the kids-animation and Hindi-history pipelines: its own .env, its own Google
Sheet, its own worksheet/tab. Nothing is hardcoded — every secret comes from the
environment (this project's own .env, with a fallback to the repo-root .env so you
can reuse the same ANTHROPIC_API_KEY without copying it around).

Sheet columns (fixed order, but accessed by header NAME so you may reorder them):
    topic | pillar | script | scene_breakdown | status | scheduled_date | notes
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECT_DIR.parent

# Load this project's .env first (wins), then fall back to the repo-root .env for
# anything not set locally (e.g. a shared ANTHROPIC_API_KEY). override=False means
# a value already in the environment / this project's .env is never clobbered.
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(ROOT_DIR / ".env", override=False)

# The Sheet columns this pipeline reads/writes. status flows:
#   draft -> approved (you set this by hand) -> script_ready -> ... -> published
COLUMNS = [
    "topic",
    "pillar",
    "script",
    "scene_breakdown",
    "status",
    "approved",       # human review gate: set to yes/true/y/x/1 after reviewing visuals
    "scheduled_date",
    "notes",
    "title_choice",       # Phase 8: you fill in v1|v2|v3 (or 1/2/3) after review
    "thumbnail_choice",   # Phase 8: you fill in v1|v2|v3 (or 1/2/3) after review
]

# Values (case-insensitive) that count as an affirmative in the `approved` column.
APPROVED_TRUE = {"yes", "y", "true", "1", "x", "approved", "ok", "✓"}

# The four content pillars and their target share of a 10-topic batch. The model
# is asked to hit these counts; we treat them as targets, not hard constraints.
PILLARS = ["History", "Mysteries", "Science & Space", "Alternate History"]
PILLAR_TARGETS = {
    "History": 4,          # 40%
    "Mysteries": 3,        # 25% (2-3)
    "Science & Space": 2,  # 20%
    "Alternate History": 1,  # 15% (1-2)
}
BATCH_SIZE = 10


@dataclass
class Config:
    # --- Claude (topic research with web search) ---
    anthropic_api_key: str | None
    anthropic_model: str
    # --- Google Sheet queue ---
    sheet_id: str | None
    worksheet: str
    service_account_file: str | None
    oauth_client_file: str | None
    oauth_token_file: str | None
    # --- Notifications ---
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_pass: str | None
    email_to: str | None
    # --- Language / localization ---
    # Human-readable language name that steers script + metadata GENERATION (e.g.
    # "Hindi"), and the BCP-47 code stamped on the YouTube upload (e.g. "hi").
    narration_language: str
    language_code: str
    # Captions: BCP-47 codes to ALSO produce as translated subtitle tracks (the
    # narration language is always included as the source track). e.g. ["en"].
    caption_languages: list[str]
    # Music: optional mood override that wins over the per-pillar default (e.g.
    # "suspense") so every episode gets a consistent tense score. None = per-pillar.
    music_mood_override: str | None
    # Kling: default to LIVE (billed) image-to-video when a key is present. Set
    # DOC_KLING_LIVE=0 to force the free mock even with a key.
    kling_live_default: bool
    # Animation provider for Phase 5: "free" (Hugging Face SVD, no cost, needs a free
    # DOC_HF_TOKEN), "kling" (paid), or "mock" (free stills, no motion).
    visuals_provider: str
    hf_token: str | None
    hf_svd_model: str
    # Free richer visuals: generate multiple images per scene (cross-dissolved with
    # motion in assembly) so long scenes aren't one static frame. ~1 image per
    # images_per_scene_sec of narration, capped at images_per_scene_max.
    images_per_scene_max: int
    images_per_scene_sec: float
    # Evergreen channel hashtags merged into every episode's generated set (deduped,
    # capped at 15) so each upload always carries strong broad-discovery tags.
    base_hashtags: list[str]
    # --- Voice (Phase 4): ElevenLabs -> Google Cloud TTS -> Edge ---
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    elevenlabs_model: str
    google_tts_voice: str
    edge_voice: str
    edge_rate: str
    edge_pitch: str
    # Optional: pin the TTS provider ("elevenlabs" | "google" | "edge"). None = use
    # the ElevenLabs -> Google -> Edge fallback chain. A --provider CLI flag overrides.
    voice_provider: str | None
    # --- Visuals (Phase 5): Pollinations key frames + Kling image-to-video ---
    pollinations_model: str
    pollinations_width: int
    pollinations_height: int
    pollinations_delay_sec: float
    kling_api_key: str | None
    kling_base_url: str
    kling_model: str
    kling_mode: str
    kling_cost_per_sec: float
    kling_max_clip_sec: float
    kling_extend_sec: float
    kling_budget_usd: float
    retry_attempts: int
    retry_base_delay: float
    # --- Music (Phase 6) ---
    music_source: str            # "jamendo" | "pixabay"
    pixabay_api_key: str | None
    pixabay_base_url: str
    jamendo_client_id: str | None
    jamendo_base_url: str
    music_require_commercial: bool   # exclude NonCommercial (NC) licenses (monetized channel)
    # --- Phase 8: thumbnails + metadata ---
    metadata_model: str
    thumb_font: str
    upload_schedule: str             # e.g. "new documentaries every Friday"
    # --- Phase 7: assembly (ffmpeg) ---
    ffmpeg_bin: str
    video_w: int
    video_h: int
    fps: int
    music_volume: float              # music bed gain under full-volume narration


def _env(*names: str) -> str | None:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return None


def load_config() -> Config:
    sa = _env("DOC_SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT_JSON",
              "GOOGLE_APPLICATION_CREDENTIALS")
    return Config(
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        # Factual accuracy matters for a documentary channel's credibility, so we
        # default to the strongest model. Override with DOC_ANTHROPIC_MODEL.
        anthropic_model=_env("DOC_ANTHROPIC_MODEL") or "claude-opus-4-8",
        sheet_id=_env("DOC_SHEET_ID"),
        worksheet=_env("DOC_WORKSHEET") or "documentary",
        service_account_file=sa,
        oauth_client_file=_env("DOC_OAUTH_CLIENT_JSON")
        or str(PROJECT_DIR / "oauth-client.json"),
        oauth_token_file=_env("DOC_OAUTH_TOKEN_JSON")
        or str(PROJECT_DIR / "token.json"),
        telegram_bot_token=_env("TELEGRAM_DOC_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_DOC_CHAT_ID"),
        smtp_host=_env("DOC_SMTP_HOST"),
        smtp_port=int(_env("DOC_SMTP_PORT") or "587"),
        smtp_user=_env("DOC_SMTP_USER"),
        smtp_pass=_env("DOC_SMTP_PASS"),
        email_to=_env("DOC_EMAIL_TO"),
        # Language: this channel narrates in Hindi by default. DOC_NARRATION_LANGUAGE
        # steers the Claude-written script + packaging; DOC_LANGUAGE_CODE is the
        # BCP-47 tag stamped on the YouTube upload. Set both to English again to revert.
        narration_language=_env("DOC_NARRATION_LANGUAGE") or "Hindi",
        language_code=_env("DOC_LANGUAGE_CODE") or "hi",
        # Extra caption tracks to translate into (comma-separated codes). Default en.
        caption_languages=[c.strip() for c in (_env("DOC_CAPTION_LANGUAGES") or "en").split(",")
                           if c.strip()],
        music_mood_override=_env("DOC_MUSIC_MOOD") or None,
        kling_live_default=(_env("DOC_KLING_LIVE") or "").lower() in ("1", "true", "yes", "on"),
        # Animation provider: default to the FREE Hugging Face SVD backend.
        visuals_provider=(_env("DOC_VISUALS_PROVIDER") or "free").lower(),
        hf_token=_env("DOC_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN"),
        hf_svd_model=_env("DOC_HF_SVD_MODEL")
        or "stabilityai/stable-video-diffusion-img2vid-xt",
        images_per_scene_max=int(_env("DOC_IMAGES_PER_SCENE_MAX") or "3"),
        images_per_scene_sec=float(_env("DOC_IMAGES_PER_SCENE_SEC") or "8"),
        # Evergreen broad-discovery hashtags (comma-separated). Universal to the
        # channel (language + format), so they fit any pillar; topic-specific tags
        # from Claude still lead. Override with DOC_BASE_HASHTAGS.
        base_hashtags=[h.strip() for h in (_env("DOC_BASE_HASHTAGS")
            or "#documentary,#hindidocumentary,#documentaryinhindi,#hindi,#facts,#educational").split(",")
            if h.strip()],
        # Voice: DOC_-prefixed vars win; fall back to the repo-root shared vars so
        # you can reuse one ElevenLabs account across channels.
        elevenlabs_api_key=_env("DOC_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY"),
        elevenlabs_voice_id=_env("DOC_ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE_ID"),
        # multilingual_v2 renders Hindi (Devanagari) natively — keep it for the Hindi
        # narration. ElevenLabs stays primary; Edge's Hindi voice is the free fallback.
        elevenlabs_model=_env("DOC_ELEVENLABS_MODEL") or "eleven_multilingual_v2",
        # Calm, measured Hindi documentary voices by default (male, native).
        google_tts_voice=_env("DOC_GOOGLE_TTS_VOICE") or "hi-IN-Neural2-B",
        edge_voice=_env("DOC_EDGE_VOICE") or "hi-IN-MadhurNeural",
        voice_provider=(_env("DOC_VOICE_PROVIDER") or "").lower() or None,
        # NOTE: edge_rate/edge_pitch default to a deep, warm, calm, suspenseful tone
        # (slower + pitched down). See DOC_EDGE_RATE / DOC_EDGE_PITCH below.
        edge_rate=_env("DOC_EDGE_RATE") or "-12%",   # calm, unhurried, suspenseful pace
        edge_pitch=_env("DOC_EDGE_PITCH") or "-15Hz",  # deep, warm narrator timbre
        # Pollinations key frames (free). 16:9 by default.
        pollinations_model=_env("DOC_POLLINATIONS_MODEL") or "flux",
        pollinations_width=int(_env("DOC_POLLINATIONS_WIDTH") or "1280"),
        pollinations_height=int(_env("DOC_POLLINATIONS_HEIGHT") or "720"),
        pollinations_delay_sec=float(_env("DOC_POLLINATIONS_DELAY_SEC") or "2.5"),
        # Kling image-to-video (paid). Verify base URL / auth / rate against YOUR
        # Kling plan — cost_per_sec is the single knob the budget guard multiplies by.
        kling_api_key=_env("DOC_KLING_API_KEY", "KLING_API_KEY"),
        kling_base_url=_env("DOC_KLING_BASE_URL") or "https://api.klingai.com",
        kling_model=_env("DOC_KLING_MODEL") or "kling-v1",
        kling_mode=_env("DOC_KLING_MODE") or "std",  # std | pro
        kling_cost_per_sec=float(_env("DOC_KLING_COST_PER_SEC") or "0.14"),
        kling_max_clip_sec=float(_env("DOC_KLING_MAX_CLIP_SEC") or "10"),
        kling_extend_sec=float(_env("DOC_KLING_EXTEND_SEC") or "4.5"),
        kling_budget_usd=float(_env("DOC_KLING_BUDGET_USD") or "25"),
        retry_attempts=int(_env("DOC_RETRY_ATTEMPTS") or "4"),
        retry_base_delay=float(_env("DOC_RETRY_BASE_DELAY") or "3"),
        # Pixabay. NOTE: Pixabay's public API officially documents images + videos
        # only — there is no documented public music/audio search endpoint. Set a
        # key + base URL here if your account has audio API access; otherwise
        # Phase 6 runs in mock mode. See gen_music.py header.
        pixabay_api_key=_env("DOC_PIXABAY_API_KEY", "PIXABAY_API_KEY"),
        pixabay_base_url=_env("DOC_PIXABAY_MUSIC_URL") or "https://pixabay.com/api/",
        # Jamendo (default): documented music API with per-track CC license metadata.
        # Free client_id from https://developer.jamendo.com. Without it, Phase 6 mocks.
        music_source=(_env("DOC_MUSIC_SOURCE") or "jamendo").lower(),
        jamendo_client_id=_env("DOC_JAMENDO_CLIENT_ID", "JAMENDO_CLIENT_ID"),
        jamendo_base_url=_env("DOC_JAMENDO_BASE_URL") or "https://api.jamendo.com/v3.0",
        # Monetized channel: drop any NonCommercial (NC) track. Set to 0/false only
        # for a non-monetized use.
        music_require_commercial=(_env("DOC_MUSIC_REQUIRE_COMMERCIAL") or "true").lower()
        not in ("0", "false", "no"),
        metadata_model=_env("DOC_METADATA_MODEL") or "claude-opus-4-8",
        thumb_font=_env("DOC_THUMB_FONT")
        or "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        upload_schedule=_env("DOC_UPLOAD_SCHEDULE") or "new documentaries every week",
        ffmpeg_bin=_env("DOC_FFMPEG") or "ffmpeg",
        video_w=int(_env("DOC_VIDEO_W") or "1920"),
        video_h=int(_env("DOC_VIDEO_H") or "1080"),
        fps=int(_env("DOC_FPS") or "30"),
        music_volume=float(_env("DOC_MUSIC_VOLUME") or "0.15"),
    )


def require_anthropic_key(cfg: Config) -> str:
    if not cfg.anthropic_api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add it to documentary/.env or the "
            "repo-root .env."
        )
    return cfg.anthropic_api_key


def google_creds_available(cfg: Config) -> str | None:
    if cfg.service_account_file and Path(cfg.service_account_file).exists():
        return "service_account"
    if cfg.oauth_token_file and Path(cfg.oauth_token_file).exists():
        return "oauth"
    return None
