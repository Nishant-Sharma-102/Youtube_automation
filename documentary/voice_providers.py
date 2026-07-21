"""Phase-4 voice provider chain for the documentary channel.

Priority: ElevenLabs -> Google Cloud TTS -> Edge TTS (free, always-available net).
Each provider exposes the same tiny interface:

    provider.name
    Provider.is_configured(cfg)
    provider.synthesize_to_file(text, out_path)   # writes an MP3, raises on failure

build_voice_chain(cfg) returns a ChainTTS that tries configured providers in order
and LOCKS onto the first that renders a scene, so one episode keeps one consistent
voice. All heavy SDKs are imported lazily inside each provider so a missing package
or credential for one never breaks the others.
"""
from __future__ import annotations

import logging
from pathlib import Path

from config import Config

log = logging.getLogger("phase4")


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
        body = json.dumps({
            "text": text,
            "model_id": self._model,
            # Calm, measured narration: higher stability, a touch of style restraint.
            "voice_settings": {"stability": 0.6, "similarity_boost": 0.75, "style": 0.0},
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"xi-api-key": self._key, "Content-Type": "application/json",
                     "Accept": "audio/mpeg"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                audio = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"ElevenLabs HTTP {e.code}: {detail}") from e
        if not audio or len(audio) < 2000:
            raise RuntimeError("ElevenLabs returned empty/too-small audio")
        Path(out_path).write_bytes(audio)


class GoogleCloudTTS:
    name = "google"

    def __init__(self, cfg: Config):
        from google.cloud import texttospeech
        from sheet import _load_google_credentials  # reuse the same auth path

        self._tts = texttospeech
        # Cloud TTS needs cloud-platform scope, not just the Sheets scope.
        creds = _load_google_credentials(cfg)  # sheets scope; fine for many SA keys
        self._client = texttospeech.TextToSpeechClient(credentials=creds)
        self._voice = cfg.google_tts_voice

    @staticmethod
    def is_configured(cfg: Config) -> bool:
        try:
            import google.cloud.texttospeech  # noqa: F401
        except Exception:
            return False
        has_sa = bool(cfg.service_account_file and Path(cfg.service_account_file).exists())
        has_oauth = bool(cfg.oauth_token_file and Path(cfg.oauth_token_file).exists())
        return has_sa or has_oauth

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        lang = "-".join(self._voice.split("-")[:2])  # en-US-Neural2-J -> en-US
        resp = self._client.synthesize_speech(
            input=self._tts.SynthesisInput(text=text),
            voice=self._tts.VoiceSelectionParams(language_code=lang, name=self._voice),
            audio_config=self._tts.AudioConfig(
                audio_encoding=self._tts.AudioEncoding.MP3, speaking_rate=0.95),
        )
        Path(out_path).write_bytes(resp.audio_content)


class EdgeTTS:
    name = "edge"

    def __init__(self, cfg: Config):
        self._voice = cfg.edge_voice
        self._rate = cfg.edge_rate
        self._pitch = cfg.edge_pitch

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
            await edge_tts.Communicate(
                text, self._voice, rate=self._rate, pitch=self._pitch
            ).save(str(out))

        asyncio.run(_run())
        if not (out.exists() and out.stat().st_size > 2000):
            raise RuntimeError("edge-tts produced empty audio")


PROVIDER_CLASSES = [ElevenLabsTTS, GoogleCloudTTS, EdgeTTS]
_BY_NAME = {c.name: c for c in PROVIDER_CLASSES}


class ChainTTS:
    def __init__(self, cfg: Config, force: str | None = None):
        self._cfg = cfg
        if force:
            if force not in _BY_NAME:
                raise SystemExit(f"Unknown provider '{force}'. Choose from {list(_BY_NAME)}.")
            self._candidates = [_BY_NAME[force]]
        else:
            self._candidates = [c for c in PROVIDER_CLASSES if c.is_configured(cfg)]
        if not self._candidates:
            raise SystemExit(
                "No TTS provider configured. Set ELEVENLABS_API_KEY (+ voice id), a Google "
                "service-account/OAuth token, or install edge-tts (free)."
            )
        log.info("Voice chain: %s", " -> ".join(c.name for c in self._candidates))
        self._locked = None
        self._start = 0

    @property
    def provider_name(self) -> str:
        return self._locked.name if self._locked else "(none)"

    def synthesize_to_file(self, text: str, out_path: str | Path) -> None:
        if self._locked is not None:
            try:
                self._locked.synthesize_to_file(text, out_path)
                return
            except Exception as e:
                log.warning("Provider %s failed (%s) — falling through", self._locked.name, e)
                self._locked = None

        last_err: Exception | None = None
        for i in range(self._start, len(self._candidates)):
            cls = self._candidates[i]
            try:
                provider = cls(self._cfg)
            except Exception as e:
                log.warning("Provider %s unavailable (%s) — skipping", cls.name, e)
                last_err = e
                continue
            try:
                provider.synthesize_to_file(text, out_path)
                self._locked = provider
                self._start = i
                return
            except Exception as e:
                log.warning("Provider %s failed (%s) — trying next", cls.name, e)
                last_err = e
        raise RuntimeError(f"All TTS providers failed. Last error: {last_err}")


def build_voice_chain(cfg: Config, force: str | None = None) -> ChainTTS:
    # A --provider CLI flag (force) wins; otherwise honor a pinned DOC_VOICE_PROVIDER.
    return ChainTTS(cfg, force=force or getattr(cfg, "voice_provider", None))
