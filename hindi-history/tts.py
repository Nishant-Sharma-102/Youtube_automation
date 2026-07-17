"""Google Cloud Text-to-Speech client (hi-IN) for Phase 2.

IMPORTANT: Google Cloud TTS does NOT accept API keys — it requires OAuth2 /
service-account credentials. Point GOOGLE_SERVICE_ACCOUNT_JSON (or
GOOGLE_APPLICATION_CREDENTIALS) at a service-account key whose project has the
Text-to-Speech API enabled.
"""
from __future__ import annotations

from pathlib import Path

from config import Config

# Free-tier monthly character allowances.
STANDARD_LIMIT = 4_000_000  # hi-IN-Standard-*
PREMIUM_LIMIT = 1_000_000   # hi-IN-Wavenet-* (and other premium voice classes)


def voice_tier(voice_name: str) -> str:
    """'Standard' (4M/mo) vs 'WaveNet' premium (1M/mo), inferred from the voice name."""
    return "Standard" if "Standard" in voice_name else "WaveNet"


def tier_limit(tier: str) -> int:
    return STANDARD_LIMIT if tier == "Standard" else PREMIUM_LIMIT


class GoogleTTS:
    def __init__(self, cfg: Config):
        from google.cloud import texttospeech

        from google_auth import TTS_SCOPES, load_google_credentials

        # Service account OR OAuth user token. Cloud TTS does NOT accept API keys.
        # gcp_quota=True attaches a billing/quota project when using OAuth creds.
        creds = load_google_credentials(cfg, TTS_SCOPES, gcp_quota=True)
        self._t = texttospeech
        self._client = texttospeech.TextToSpeechClient(credentials=creds)
        self._voice = cfg.tts_voice
        self._lang = "-".join(cfg.tts_voice.split("-")[:2])  # e.g. "hi-IN"

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        resp = self._client.synthesize_speech(
            input=self._t.SynthesisInput(text=text),
            voice=self._t.VoiceSelectionParams(language_code=self._lang, name=self._voice),
            audio_config=self._t.AudioConfig(audio_encoding=self._t.AudioEncoding.MP3),
        )
        Path(out_path).write_bytes(resp.audio_content)
