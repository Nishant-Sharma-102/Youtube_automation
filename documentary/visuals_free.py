"""Free image-to-video generation (Phase 5) — a no-cost alternative to Kling.

Mirrors visuals_kling's interface (estimate_clip / generate_clip / ClipPlan) so
gen_visuals can swap providers with a single config knob (DOC_VISUALS_PROVIDER).

Backend: Hugging Face Serverless Inference running Stable Video Diffusion
(stabilityai/stable-video-diffusion-img2vid-xt). This is FREE with a free HF token
(DOC_HF_TOKEN), rate-limited on the free tier. SVD returns a SHORT clip (~2-4s,
1024x576); to fill a scene's narration length we loop it with ffmpeg. That is the
honest trade vs paid Kling: free + automatable, but short source motion and lower
resolution.

⚠️ Free API availability changes. If HF serverless drops SVD, set DOC_VISUALS_PROVIDER
back to 'kling' (paid) or 'mock' (free stills), or point HF_SVD_MODEL at another
image-to-video model your token can reach.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx

from config import Config
# Reuse Kling's ClipPlan so the two providers are drop-in interchangeable.
from visuals_kling import ClipPlan

HF_INFERENCE_BASE = "https://api-inference.huggingface.co/models"


def estimate_clip(cfg: Config, target_sec: float) -> ClipPlan:
    """Free: no spend. We loop one short generation to cover the target, so this is
    always a single (billed_sec = target) plan at $0 — the budget gate never trips."""
    return ClipPlan(target_sec=target_sec, billed_sec=round(target_sec, 2),
                    cost_usd=0.0, segments=1, chained=False)


def _svd_model(cfg: Config) -> str:
    return getattr(cfg, "hf_svd_model", None) or "stabilityai/stable-video-diffusion-img2vid-xt"


def _generate_short_clip(cfg: Config, image_path: Path, out_raw: Path) -> None:
    """Call HF SVD with the keyframe bytes; write the returned mp4 to out_raw."""
    token = getattr(cfg, "hf_token", None)
    if not token:
        raise SystemExit("Free visuals need DOC_HF_TOKEN (a free Hugging Face token). "
                         "Get one at https://huggingface.co/settings/tokens.")
    url = f"{HF_INFERENCE_BASE}/{_svd_model(cfg)}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "video/mp4"}
    last = None
    for attempt in range(cfg.retry_attempts):
        try:
            r = httpx.post(url, headers=headers, content=image_path.read_bytes(), timeout=300.0)
            # 503 = model loading; HF asks us to wait and retry.
            if r.status_code == 503:
                wait = float((r.json() or {}).get("estimated_time", 20)) if r.headers.get(
                    "content-type", "").startswith("application/json") else 20.0
                time.sleep(min(wait, 60))
                continue
            r.raise_for_status()
            if not r.content or len(r.content) < 2000:
                raise RuntimeError("HF returned empty/too-small video")
            out_raw.write_bytes(r.content)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < cfg.retry_attempts - 1:
                time.sleep(cfg.retry_base_delay * (2 ** attempt))
    raise RuntimeError(f"HF SVD generation failed after {cfg.retry_attempts} attempts: {last}")


def _loop_to_length(cfg: Config, raw_clip: Path, out_path: Path, target_sec: float) -> None:
    """Loop the short SVD clip (silently) up to target_sec. Narration is muxed later
    in assemble; here we only produce silent video of the right length."""
    cmd = [
        cfg.ffmpeg_bin, "-y", "-stream_loop", "-1", "-i", str(raw_clip),
        "-t", f"{target_sec:.3f}", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg loop failed: {proc.stderr[-500:]}")


def generate_clip(cfg: Config, image_path: Path, prompt: str, target_sec: float,
                  out_path: Path, *, mock: bool) -> ClipPlan:
    """Generate a free image-to-video clip (or a no-spend mock stub). Returns the
    ClipPlan. `prompt` is accepted for interface parity (SVD is image-conditioned)."""
    plan = estimate_clip(cfg, target_sec)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if mock:
        out_path.write_bytes(
            f"MOCK-FREE-CLIP\ntarget={target_sec}s (free provider, no spend)\n"
            f"conditioning_image={image_path.name}\n".encode()
        )
        return plan

    raw = out_path.with_suffix(".raw.mp4")
    try:
        _generate_short_clip(cfg, image_path, raw)
        _loop_to_length(cfg, raw, out_path, target_sec)
    finally:
        if raw.exists():
            raw.unlink()
    return plan
