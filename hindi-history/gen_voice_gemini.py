#!/usr/bin/env python3
"""One-off: generate REAL Hindi narration for an episode using Gemini TTS.

The production voice path (tts.py) uses Google Cloud Text-to-Speech, which needs a
separate service-account credential. This helper instead reuses the GEMINI_API_KEY
already on the box (the same model the kids pipeline falls back to,
gemini-2.5-flash-preview-tts) so we can put real speech into an episode now.

It writes the SAME artifacts the real Phase-2 produces — audio/epN_sceneK.mp3 +
audio/epN_full.mp3 — and updates each scene's duration_seconds in the scenes JSON
from the real audio, so Phase-4 assembly stays in sync. Then run assemble_video.py.
"""
from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from google import genai
from google.genai import types

from audio_utils import concat_mp3, duration_seconds, ffmpeg_bin
from config import PROJECT_DIR

AUDIO = PROJECT_DIR / "audio"
TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE = "Algenib"        # deep, gravelly — a rich narrator timbre
FALLBACK_VOICE = "Charon"  # used if the primary voice name is rejected
SAMPLE_RATE = 24000
# Deep, warm, resonant, unhurried, dramatic history storyteller.
STYLE = ("एक गहरी, गर्मजोशी भरी और भारी आवाज़ में, किसी अनुभवी कहानीकार की तरह — "
         "धीमे, नाटकीय और भावुक अंदाज़ में, हर शब्द पर ठहरते हुए हिंदी में सुनाएँ: ")


def _load_gemini_key() -> str:
    """GEMINI_API_KEY lives in the ROOT .env (shared), not hindi-history/.env."""
    import os
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    root_env = PROJECT_DIR.parent / ".env"
    for line in root_env.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("GEMINI_API_KEY not found in env or ../.env")


def _pcm_to_mp3(pcm: bytes, out: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
        f.write(pcm)
        raw = f.name
    try:
        subprocess.run(
            [ffmpeg_bin(), "-y", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
             "-i", raw, "-c:a", "libmp3lame", "-q:a", "2", str(out)],
            capture_output=True, text=True, check=True,
        )
    finally:
        Path(raw).unlink(missing_ok=True)


def _synthesize(client: genai.Client, text: str, out: Path, voice: str, retries: int = 12) -> None:
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = client.models.generate_content(
                model=TTS_MODEL,
                contents=STYLE + text,
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
            _pcm_to_mp3(bytes(pcm), out)
            return
        except Exception as e:  # noqa: BLE001 — surface any API/quota error, then retry
            last = e
            print(f"  attempt {attempt}/{retries} failed: {e}", flush=True)
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1) * 3, 120))
    raise SystemExit(f"Gemini TTS failed after {retries} attempts: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--scenes-file", required=True)
    args = ap.parse_args()

    import json
    ep = args.episode
    fp = Path(args.scenes_file)
    data = json.loads(fp.read_text(encoding="utf-8"))
    scenes = sorted(data["scenes"], key=lambda s: int(s["scene_number"]))
    AUDIO.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=_load_gemini_key())

    # Lock the voice on scene 1: try the deep primary, fall back if the name is rejected.
    voice = VOICE
    first = sorted(scenes, key=lambda s: int(s["scene_number"]))[0]
    try:
        _synthesize(client, first["text"].strip(), AUDIO / f"ep{ep}_scene{int(first['scene_number'])}.mp3", voice)
    except SystemExit:
        print(f"voice '{VOICE}' rejected; falling back to '{FALLBACK_VOICE}'", flush=True)
        voice = FALLBACK_VOICE
        _synthesize(client, first["text"].strip(), AUDIO / f"ep{ep}_scene{int(first['scene_number'])}.mp3", voice)
    print(f"Gemini TTS ({TTS_MODEL}, voice={voice}) — {len(scenes)} scenes", flush=True)

    parts = []
    for s in scenes:
        n = int(s["scene_number"])
        out = AUDIO / f"ep{ep}_scene{n}.mp3"
        text = s["text"].strip()
        print(f"scene {n}: {len(text)} chars -> {out.name}", flush=True)
        if not (n == int(first["scene_number"]) and out.exists()):
            _synthesize(client, text, out, voice)
        dur = duration_seconds(out)
        s["duration_seconds"] = dur
        parts.append(out)
        print(f"  ok, {dur:.2f}s", flush=True)
        time.sleep(15)  # pace requests to stay under any per-minute rate limit

    full = AUDIO / f"ep{ep}_full.mp3"
    concat_mp3(parts, full)
    total = duration_seconds(full)
    print(f"full track -> {full.name}  ({total:.2f}s)", flush=True)

    # Persist the real durations back so Phase-4 assembly syncs to them.
    data["scenes"] = scenes
    data["audio_path"] = str(full)
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated {fp} with real scene durations", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
