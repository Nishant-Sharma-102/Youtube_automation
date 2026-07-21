"""Pollinations.ai key-frame generation (Phase 5).

Free, no key. One key frame per scene from the scene's visual_prompt (which already
carries the episode style descriptor from Phase 3). For 'still' scenes this IS the
final asset; for 'kling' scenes it's the conditioning image Kling animates from.

Anonymous endpoint is rate-limited, so callers space requests out (config
pollinations_delay_sec) and we retry with exponential backoff on failure.
"""
from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

import httpx

from config import Config

BASE = "https://image.pollinations.ai/prompt/"
# Magic bytes so we never save an HTML error page as a ".jpg".
_IMG_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")


def _looks_like_image(data: bytes) -> bool:
    return bool(data) and data.startswith(_IMG_MAGIC) and len(data) > 3000


def generate_keyframe(cfg: Config, prompt: str, out_path: Path, seed: int | None = None) -> None:
    """Generate one key frame to out_path. Retries with backoff; raises on total failure.
    A `seed` yields a distinct image for the same prompt — used for multi-image scenes."""
    params = {
        "width": cfg.pollinations_width,
        "height": cfg.pollinations_height,
        "model": cfg.pollinations_model,
        "nologo": "true",
    }
    if seed is not None:
        params["seed"] = int(seed)
    url = BASE + urllib.parse.quote(prompt, safe="") + "?" + urllib.parse.urlencode(params)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    last_err: Exception | str | None = None
    for attempt in range(cfg.retry_attempts):
        try:
            resp = httpx.get(url, timeout=120.0, follow_redirects=True)
            if resp.status_code == 200 and _looks_like_image(resp.content):
                out_path.write_bytes(resp.content)
                return
            last_err = f"HTTP {resp.status_code}, {len(resp.content)} bytes (not an image)"
        except Exception as e:  # noqa: BLE001 — network hiccup, retry
            last_err = e
        if attempt < cfg.retry_attempts - 1:
            time.sleep(cfg.retry_base_delay * (2 ** attempt))  # 3, 6, 12s …
    raise RuntimeError(f"Pollinations failed after {cfg.retry_attempts} attempts: {last_err}")
