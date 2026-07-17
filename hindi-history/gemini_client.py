"""Gemini 2.5 Flash client for Phase 1 script generation.

Uses the google-genai SDK with a Pydantic response schema so the model must return
JSON in the exact shape we need — no brittle prose-scraping.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from config import Config
from prompt import SYSTEM_INSTRUCTION, build_user_prompt


class Scene(BaseModel):
    scene_number: int
    text: str  # Hindi narration for this beat (2-4 sentences)
    image_prompt_hint: str  # English visual description for later image generation


class Episode(BaseModel):
    title: str  # Hindi
    description: str  # Hindi, 2-3 sentences
    tags: list[str] = Field(default_factory=list)  # 5-8, mix of Hindi + English
    full_script: str  # Hindi, = concatenation of scene texts
    scenes: list[Scene] = Field(default_factory=list)  # 8-12 scenes


def _canonical_full_script(scenes: list[Scene]) -> str:
    return "\n\n".join(s.text.strip() for s in scenes).strip()


def _hindi_word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def validate(ep: Episode) -> list[str]:
    """Return a list of human-readable warnings. Non-fatal — the brief wants
    generation to succeed and flag anything out of range for review."""
    warnings: list[str] = []
    n_scenes = len(ep.scenes)
    if not (8 <= n_scenes <= 12):
        warnings.append(f"scene count is {n_scenes} (brief wants 8-12)")
    n_tags = len(ep.tags)
    if not (5 <= n_tags <= 8):
        warnings.append(f"tag count is {n_tags} (brief wants 5-8)")
    for s in ep.scenes:
        sc = len([x for x in re.split(r"(?<=[।.?!])\s+", s.text.strip()) if x])
        if not (2 <= sc <= 4):
            warnings.append(f"scene {s.scene_number} has ~{sc} sentences (brief wants 2-4)")
    wc = _hindi_word_count(ep.full_script)
    if not (650 <= wc <= 1100):
        warnings.append(f"script is ~{wc} Hindi words (brief target 700-1000)")
    # Keep narration and scene timing in sync: full_script must equal the joined scenes.
    if ep.full_script.strip() != _canonical_full_script(ep.scenes):
        warnings.append(
            "full_script did not exactly match the joined scene texts — "
            "rebuilt it from the scenes to guarantee per-scene audio/image sync"
        )
        ep.full_script = _canonical_full_script(ep.scenes)
    return warnings


def generate_episode(cfg: Config, topic: str) -> tuple[Episode, list[str]]:
    """Call Gemini and return (Episode, warnings). Imports the SDK lazily so
    --dry-run works without the package installed."""
    from google import genai
    from google.genai import types

    # Bound network time. Without an explicit timeout the client can hang on a stalled
    # connection (measured 137s on connect failure; unbounded on a read stall) — and on
    # cron that hang holds the shared render flock, starving both channels. 120s/attempt.
    client = genai.Client(api_key=cfg.gemini_api_key,
                          http_options=types.HttpOptions(timeout=120_000))
    resp = client.models.generate_content(
        model=cfg.gemini_model,
        contents=build_user_prompt(topic),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=Episode,
            temperature=0.9,
            max_output_tokens=20000,
            # Structured extraction doesn't need reasoning tokens; disabling keeps
            # output reliable and avoids truncation. Tune up if you want richer prose.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    ep = getattr(resp, "parsed", None)
    if not isinstance(ep, Episode):
        # Fallback: parse the raw text ourselves.
        raw = (resp.text or "").strip()
        if not raw:
            raise RuntimeError(
                "Gemini returned no text. Check the API key, model name, and quota. "
                f"finish info: {getattr(resp, 'candidates', None)}"
            )
        ep = Episode(**json.loads(raw))

    ep.scenes.sort(key=lambda s: s.scene_number)
    warnings = validate(ep)
    return ep, warnings
