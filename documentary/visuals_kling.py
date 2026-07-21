"""Kling image-to-video generation (Phase 5).

Animates a scene from its Pollinations key frame (image-to-video mode) to a clip
matching the scene's duration_seconds. Kling caps a single generation at
kling_max_clip_sec (5/10s); longer targets are reached by chaining video
EXTENSIONS — flagged, since chaining is where visual drift risk rises.

Cost is billed_seconds × kling_cost_per_sec. estimate_clip() lets the caller
gate on the $ budget BEFORE spending; generate_clip() does the real work (or a
no-spend mock).

⚠️ Kling providers differ. Verify base_url, auth, request/response shape, and the
per-second rate against YOUR Kling account before a live run. Auth here sends
`Authorization: Bearer <DOC_KLING_API_KEY>`; the official Kling open platform uses
a JWT signed from an access-key/secret pair — mint that JWT and pass it as the key,
or adapt _headers() accordingly.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from config import Config


@dataclass
class ClipPlan:
    target_sec: float
    billed_sec: float      # what Kling will actually generate (>= target)
    cost_usd: float
    segments: int          # 1 base generation + N extensions
    chained: bool


def estimate_clip(cfg: Config, target_sec: float) -> ClipPlan:
    """Plan the generation without calling the API — used for the budget gate."""
    base = cfg.kling_max_clip_sec if target_sec > 5 else 5.0
    base = min(base, cfg.kling_max_clip_sec)
    billed = base
    segments = 1
    while billed < target_sec:
        billed += cfg.kling_extend_sec
        segments += 1
    cost = round(billed * cfg.kling_cost_per_sec, 4)
    return ClipPlan(target_sec, round(billed, 2), cost, segments, segments > 1)


def _headers(cfg: Config) -> dict:
    return {"Authorization": f"Bearer {cfg.kling_api_key}", "Content-Type": "application/json"}


def _poll(cfg: Config, url: str) -> dict:
    """Poll a Kling task until succeed/failed. Returns the task_result dict."""
    for _ in range(120):  # up to ~10 min at 5s intervals
        resp = httpx.get(url, headers=_headers(cfg), timeout=60.0)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("task_status")
        if status == "succeed":
            return data.get("task_result", {})
        if status == "failed":
            raise RuntimeError(f"Kling task failed: {data.get('task_status_msg')}")
        time.sleep(5)
    raise RuntimeError("Kling task timed out")


def _submit_image2video(cfg: Config, image_b64: str, prompt: str, duration_s: int) -> str:
    body = {
        "model_name": cfg.kling_model,
        "mode": cfg.kling_mode,
        "duration": str(duration_s),
        "image": image_b64,
        "prompt": prompt,
        "cfg_scale": 0.5,
    }
    resp = httpx.post(f"{cfg.kling_base_url}/v1/videos/image2video",
                      headers=_headers(cfg), json=body, timeout=120.0)
    resp.raise_for_status()
    return resp.json()["data"]["task_id"]


def _submit_extend(cfg: Config, video_id: str, prompt: str) -> str:
    resp = httpx.post(f"{cfg.kling_base_url}/v1/videos/video-extend",
                      headers=_headers(cfg), json={"video_id": video_id, "prompt": prompt},
                      timeout=120.0)
    resp.raise_for_status()
    return resp.json()["data"]["task_id"]


def _download(url: str, out_path: Path) -> None:
    resp = httpx.get(url, timeout=300.0, follow_redirects=True)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)


def _retry(cfg: Config, fn, *, what: str):
    last = None
    for attempt in range(cfg.retry_attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < cfg.retry_attempts - 1:
                time.sleep(cfg.retry_base_delay * (2 ** attempt))
    raise RuntimeError(f"Kling {what} failed after {cfg.retry_attempts} attempts: {last}")


def generate_clip(cfg: Config, image_path: Path, prompt: str, target_sec: float,
                  out_path: Path, *, mock: bool) -> ClipPlan:
    """Generate the clip (or a no-spend mock). Returns the realized ClipPlan."""
    plan = estimate_clip(cfg, target_sec)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if mock:
        # No API call, no spend. Write a clearly-labelled placeholder so the
        # completeness check + write-back path are still exercised end-to-end.
        out_path.write_bytes(
            f"MOCK-KLING-CLIP\ntarget={target_sec}s billed={plan.billed_sec}s "
            f"segments={plan.segments} est_cost=${plan.cost_usd}\n"
            f"conditioning_image={image_path.name}\n".encode()
        )
        return plan

    if not cfg.kling_api_key:
        raise SystemExit("DOC_KLING_API_KEY not set — cannot run a live Kling render.")

    image_b64 = base64.b64encode(image_path.read_bytes()).decode()
    base_dur = int(cfg.kling_max_clip_sec if target_sec > 5 else 5)

    task_id = _retry(cfg, lambda: _submit_image2video(cfg, image_b64, prompt, base_dur),
                     what="image2video submit")
    result = _poll(cfg, f"{cfg.kling_base_url}/v1/videos/image2video/{task_id}")
    video = result["videos"][0]
    video_id, video_url = video["id"], video["url"]

    # Chain extensions until we reach the target length.
    produced = float(base_dur)
    while produced < target_sec:
        ext_id = _retry(cfg, lambda vid=video_id: _submit_extend(cfg, vid, prompt),
                        what="video-extend submit")
        result = _poll(cfg, f"{cfg.kling_base_url}/v1/videos/video-extend/{ext_id}")
        video = result["videos"][0]
        video_id, video_url = video["id"], video["url"]
        produced += cfg.kling_extend_sec

    _retry(cfg, lambda: _download(video_url, out_path), what="download")
    return plan
