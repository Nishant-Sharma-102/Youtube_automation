"""Phase-2 voice provider chain for the Hindi history channel.

Priority order (spec): ElevenLabs → Google Cloud TTS → Gemini TTS → Edge TTS.
Each provider exposes the same tiny interface so `generate_voice.py` can stay
provider-agnostic:

    provider.name                     # short label for logs/usage
    Provider.is_configured(cfg)       # cheap check, no heavy imports / network
    provider.synthesize_to_file(text, out_path)   # writes an MP3, raises on failure

`build_voice_chain(cfg)` returns a `ChainTTS` that tries configured providers in
priority order. It LOCKS onto the first provider that successfully renders a scene
so a single episode keeps one consistent voice, and only falls through to the next
provider if the locked one later fails. Edge TTS is free and needs no key, so it
sits last as an always-available safety net — the pipeline should never hard-fail
for lack of a paid credential.

All third-party SDKs are imported lazily INSIDE each provider, so a missing package
(or credential) for one provider never breaks the others.
"""
from __future__ import annotations

import logging
from pathlib import Path

from config import Config

log = logging.getLogger("phase2")


# --------------------------------------------------------------------------- #
# 1. ElevenLabs (primary) — REST, needs only ELEVENLABS_API_KEY.
# --------------------------------------------------------------------------- #
class ElevenLabsTTS:
    name = "elevenlabs"

    def __init__(self, cfg: Config):
        self._key = cfg.elevenlabs_api_key
        self._voice_id = cfg.elevenlabs_voice_id
        self._model = cfg.elevenlabs_model

    @staticmethod
    def is_configured(cfg: Config) -> bool:
        return bool(cfg.elevenlabs_api_key and cfg.elevenlabs_voice_id)

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        import json
        import urllib.error
        import urllib.request

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
        body = json.dumps(
            {
                "text": text,
                "model_id": self._model,
                # multilingual_v2 handles Devanagari/Hindi well.
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "xi-api-key": self._key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                audio = resp.read()
        except urllib.error.HTTPError as e:  # surface the API error body for debugging
            detail = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"ElevenLabs HTTP {e.code}: {detail}") from e
        if not audio or len(audio) < 2000:
            raise RuntimeError("ElevenLabs returned empty/too-small audio")
        Path(out_path).write_bytes(audio)


# --------------------------------------------------------------------------- #
# 2. Google Cloud TTS — reuses the existing tts.GoogleTTS client.
# --------------------------------------------------------------------------- #
class GoogleCloudTTS:
    name = "google"

    def __init__(self, cfg: Config):
        from tts import GoogleTTS

        self._impl = GoogleTTS(cfg)

    @staticmethod
    def is_configured(cfg: Config) -> bool:
        # Cloud TTS needs a service-account key OR a minted OAuth token (no API keys).
        has_sa = bool(cfg.service_account_file and Path(cfg.service_account_file).exists())
        has_oauth = bool(cfg.oauth_token_file and Path(cfg.oauth_token_file).exists())
        return has_sa or has_oauth

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        self._impl.synthesize_to_file(text, out_path)


# --------------------------------------------------------------------------- #
# 3. Gemini TTS — reuses GEMINI_API_KEY (same fallback the kids pipeline uses).
# --------------------------------------------------------------------------- #
class GeminiTTS:
    name = "gemini"

    TTS_MODEL = "gemini-2.5-flash-preview-tts"
    VOICE = "Algenib"          # deep, gravelly narrator timbre
    FALLBACK_VOICE = "Charon"  # if the primary voice name is rejected
    SAMPLE_RATE = 24000
    STYLE = (
        "एक गहरी, गर्मजोशी भरी और भारी आवाज़ में, किसी अनुभवी कहानीकार की तरह — "
        "धीमे, नाटकीय और भावुक अंदाज़ में, हर शब्द पर ठहरते हुए हिंदी में सुनाएँ: "
    )

    def __init__(self, cfg: Config):
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=cfg.gemini_api_key)
        self._voice = self.VOICE

    @staticmethod
    def is_configured(cfg: Config) -> bool:
        return bool(cfg.gemini_api_key)

    def _pcm_to_mp3(self, pcm: bytes, out: Path) -> None:
        import subprocess
        import tempfile

        from audio_utils import ffmpeg_bin

        with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
            f.write(pcm)
            raw = f.name
        try:
            subprocess.run(
                [ffmpeg_bin(), "-y", "-f", "s16le", "-ar", str(self.SAMPLE_RATE), "-ac", "1",
                 "-i", raw, "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                capture_output=True, text=True, check=True,
            )
        finally:
            Path(raw).unlink(missing_ok=True)

    def _synth_once(self, text: str, out: Path, voice: str) -> None:
        import base64

        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.TTS_MODEL,
            contents=self.STYLE + text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )
        data = resp.candidates[0].content.parts[0].inline_data.data
        pcm = data if isinstance(data, (bytes, bytearray)) else base64.b64decode(data)
        self._pcm_to_mp3(bytes(pcm), out)

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        out = Path(out_path)
        try:
            self._synth_once(text, out, self._voice)
        except Exception:
            # Voice name may be rejected — lock onto the fallback voice and retry.
            if self._voice != self.FALLBACK_VOICE:
                self._voice = self.FALLBACK_VOICE
                self._synth_once(text, out, self._voice)
            else:
                raise


# --------------------------------------------------------------------------- #
# 4. Edge TTS — FREE, no key, no billing. Always-available safety net (last).
# --------------------------------------------------------------------------- #
class EdgeTTS:
    name = "edge"

    def __init__(self, cfg: Config):
        import os

        self._voice = os.environ.get("HISTORY_EDGE_VOICE") or "hi-IN-MadhurNeural"
        self._rate = os.environ.get("HISTORY_EDGE_RATE") or "+9%"
        self._pitch = os.environ.get("HISTORY_EDGE_PITCH") or "-2Hz"

    @staticmethod
    def is_configured(cfg: Config) -> bool:
        try:
            import edge_tts  # noqa: F401
        except Exception:
            return False
        return True

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        import asyncio

        import edge_tts

        out = Path(out_path)

        async def _run() -> None:
            await edge_tts.Communicate(text, self._voice, rate=self._rate, pitch=self._pitch).save(str(out))

        asyncio.run(_run())
        if not (out.exists() and out.stat().st_size > 2000):
            raise RuntimeError("edge-tts produced empty audio")


# Priority order: ElevenLabs first, then the rest as fallbacks.
PROVIDER_CLASSES = [ElevenLabsTTS, GoogleCloudTTS, GeminiTTS, EdgeTTS]


class ChainTTS:
    """Tries configured providers in priority order, locking onto the first that works."""

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._candidates = [c for c in PROVIDER_CLASSES if c.is_configured(cfg)]
        if not self._candidates:
            raise SystemExit(
                "No TTS provider is configured. Set ELEVENLABS_API_KEY (+ HISTORY_ELEVENLABS_VOICE_ID), "
                "a Google service-account/OAuth token, or GEMINI_API_KEY — or install edge-tts (free)."
            )
        log.info("Voice provider chain: %s", " -> ".join(c.name for c in self._candidates))
        self._locked = None          # instantiated provider currently in use
        self._start = 0              # index into _candidates to try from next

    @property
    def provider_name(self) -> str:
        return self._locked.name if self._locked else "(none)"

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        # Fast path: reuse the locked provider.
        if self._locked is not None:
            try:
                self._locked.synthesize_to_file(text, out_path)
                return
            except Exception as e:  # locked provider failed mid-episode — fall through
                log.warning("Provider %s failed (%s) — falling through to next", self._locked.name, e)
                self._locked = None

        last_err: Exception | None = None
        for i in range(self._start, len(self._candidates)):
            cls = self._candidates[i]
            try:
                provider = cls(self._cfg)
            except Exception as e:  # construction failed (bad creds / missing dep)
                log.warning("Provider %s unavailable (%s) — skipping", cls.name, e)
                last_err = e
                continue
            try:
                provider.synthesize_to_file(text, out_path)
                self._locked = provider
                self._start = i  # stay on this provider for subsequent scenes
                log.info("Voice provider: %s", provider.name)
                return
            except Exception as e:
                log.warning("Provider %s failed (%s) — trying next", cls.name, e)
                last_err = e
        raise RuntimeError(f"All TTS providers failed. Last error: {last_err}")


def build_voice_chain(cfg: Config) -> ChainTTS:
    return ChainTTS(cfg)
