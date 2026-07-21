#!/usr/bin/env python3
"""Caption/subtitle generation for an episode.

Builds SRT subtitle tracks from the per-scene narration + measured durations that
Phase 4 (voice) already wrote into scene_breakdown. Each scene's narration is split
into sentence-level cues, and the scene's measured audio duration is distributed
across those cues in proportion to their length — so the subtitles track the spoken
audio closely without needing a forced-aligner.

Two tracks are produced:
  • Hindi (hi)   — the narration verbatim (what is actually spoken).
  • English (en) — a translation of each cue via Claude, cue-aligned so timings match.

Used by Phase 8 (gen_metadata) to write renders/<slug>/captions.<lang>.srt, whose
paths are stored in metadata['captions'] for Phase 9 to upload via set_captions.
"""
from __future__ import annotations

import json
import re

import httpx

API = "https://api.anthropic.com/v1/messages"

# BCP-47 code -> human language name (for the translation prompt). Extend as needed.
CODE_TO_LANGUAGE = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French",
    "de": "German", "pt": "Portuguese", "ar": "Arabic", "bn": "Bengali",
    "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "ur": "Urdu",
}


def language_name(code: str) -> str:
    return CODE_TO_LANGUAGE.get(code.lower(), code)

FACT_MARKER_RE = re.compile(r"⟦FACT-CHECK:.*?⟧", re.DOTALL)
# Devanagari danda + standard sentence punctuation as sentence boundaries.
SENT_SPLIT_RE = re.compile(r"(?<=[।?!.])\s+")


def _clean(text: str) -> str:
    return FACT_MARKER_RE.sub("", text or "").strip()


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENT_SPLIT_RE.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:  # rounding spillover
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_cues(scenes: list[dict]) -> list[dict]:
    """Return time-ordered cues [{start, end, text}] in the narration language,
    derived from each scene's narration_text + duration_sec."""
    cues: list[dict] = []
    t = 0.0
    for s in scenes:
        text = _clean(s.get("narration_text", ""))
        dur = float(s.get("duration_sec", 0) or 0)
        if not text or dur <= 0:
            t += dur
            continue
        sents = _split_sentences(text)
        total_chars = sum(len(x) for x in sents) or 1
        start = t
        for sent in sents:
            share = len(sent) / total_chars
            end = start + dur * share
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": sent})
            start = end
        t += dur
    return cues


def cues_to_srt(cues: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}\n{c['text']}\n")
    return "\n".join(blocks)


def translate_cues(api_key: str, model: str, cues: list[dict], target_language: str = "English") -> list[str]:
    """Translate each cue's text to target_language, preserving order and count so
    timings stay aligned. Returns a list of translated strings (same length as cues).
    On any failure, falls back to the original texts (better a Hindi track than none)."""
    if not cues:
        return []
    numbered = "\n".join(f"{i}. {c['text']}" for i, c in enumerate(cues))
    prompt = (
        f"Translate each numbered subtitle line below into natural, concise {target_language} "
        f"suitable for on-screen captions of a documentary. Keep the SAME numbering and the "
        f"SAME number of lines — exactly one translation per input line, in order. Do not merge, "
        f"split, add, or drop lines.\n\n"
        f"Return ONLY a JSON array of strings (the translations in order), nothing else.\n\n"
        f"{numbered}"
    )
    try:
        r = httpx.post(
            API,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 8000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=300.0,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text").strip()
        m = re.search(r"\[.*\]", text, re.DOTALL)
        arr = json.loads(m.group(0) if m else text)
        arr = [str(x) for x in arr]
        if len(arr) == len(cues):
            return arr
        # Length drift — pad/trim defensively so timings still line up.
        if len(arr) < len(cues):
            arr += [c["text"] for c in cues[len(arr):]]
        return arr[:len(cues)]
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Caption translation to {target_language} failed ({e}); using source text.")
        return [c["text"] for c in cues]


def write_caption_tracks(scenes: list[dict], out_dir, *, source_code: str,
                         api_key: str | None, model: str,
                         translate_to: dict[str, str] | None = None) -> dict[str, str]:
    """Write the source (narration-language) SRT plus any requested translations.

    source_code is the BCP-47 code of the spoken narration (e.g. "hi"). translate_to
    maps a BCP-47 code -> language name to translate INTO, e.g. {"en": "English"}.
    Returns {lang_code: srt_path}, ready for Phase 9 to upload via set_captions.
    Returns {} if there are no usable cues."""
    from pathlib import Path

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cues = build_cues(scenes)
    if not cues:
        return {}
    tracks: dict[str, str] = {}

    # 1. Source track — verbatim narration.
    src_path = out_dir / f"captions.{source_code}.srt"
    src_path.write_text(cues_to_srt(cues), encoding="utf-8")
    tracks[source_code] = str(src_path)

    # 2. Translated tracks (cue-aligned so timings match the source).
    for code, lang_name in (translate_to or {}).items():
        if code == source_code:
            continue
        translated = translate_cues(api_key, model, cues, lang_name) if api_key \
            else [c["text"] for c in cues]
        tcues = [{"start": c["start"], "end": c["end"], "text": t}
                 for c, t in zip(cues, translated)]
        path = out_dir / f"captions.{code}.srt"
        path.write_text(cues_to_srt(tcues), encoding="utf-8")
        tracks[code] = str(path)
    return tracks
