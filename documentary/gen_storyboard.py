#!/usr/bin/env python3
"""Phase 3 — scene-by-scene storyboard for a script_ready episode.

Reads the next status='script_ready' row, breaks its script into 20-40 scenes
with Claude (verbatim narration slices that fully cover the script, plus a
specific visual_prompt and a still/kling type per scene), enforces the kling cap
in code, appends a per-episode style descriptor to every visual_prompt, writes
the scenes JSON to 'scene_breakdown', and sets status='storyboard_ready'.

Model: claude-opus-4-8 (best at the exact-coverage + high-impact judgment this
phase needs). Override with DOC_STORYBOARD_MODEL.

Usage:
  python gen_storyboard.py            # process the next script_ready row
  python gen_storyboard.py --dry-run  # generate + display only, no write-back
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import httpx

from config import PILLARS, load_config, require_anthropic_key
from sheet import TopicQueue

API = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-4-8"

MIN_SCENES, MAX_SCENES = 20, 40
# HARD cap: kling (animated) scenes may not exceed this fraction of total. Raised to
# 0.35 for a more animated, cinematic feel. Override with DOC_KLING_CEILING_PCT.
KLING_CEILING_PCT = float(os.environ.get("DOC_KLING_CEILING_PCT") or "0.35")

# Phase 2 stores editorial fact-check markers inline (⟦FACT-CHECK: …⟧). They are
# NOT narration, so we strip them to get the clean spoken script before slicing.
FACT_MARKER_RE = re.compile(r"⟦FACT-CHECK:.*?⟧", re.DOTALL)
# Claude sometimes inserts markdown section dividers (a line of --- or ***). These
# are structural, not spoken words, so we drop them before slicing/coverage too.
DIVIDER_RE = re.compile(r"^[ \t]*([-*_])\1{2,}[ \t]*$", re.MULTILINE)

# Per-pillar tone hints — the model turns these into ONE concrete style descriptor
# for this specific episode; we then append it to every scene's visual_prompt.
PILLAR_TONE = {
    "History": "brighter, epic, grand in scale, warm golden cinematic light, painterly realism",
    "Alternate History": "epic and cinematic with a subtly uncanny, alternate-timeline mood",
    "Mysteries": "moodier, desaturated, shadowy, cold palette, high contrast, quietly unsettling",
    "Science & Space": "sleek and awe-inspiring, cool blues, cosmic scale, clean modern cinematic",
}

SYSTEM = (
    "You are a documentary storyboard director. You break a finished narration script "
    "into a precise shot list for image/video generation. You are meticulous about two "
    "things: (1) the narration slices you assign to scenes must reproduce the script "
    "EXACTLY and completely — verbatim, in order, no gaps, no overlaps, no paraphrasing; "
    "(2) you reserve motion/animation for genuinely high-impact moments, defaulting "
    "everything else to a still image with a slow Ken Burns pan/zoom."
)


def clean_script(raw: str) -> str:
    return DIVIDER_RE.sub("", FACT_MARKER_RE.sub("", raw)).strip()


def _norm(s: str) -> str:
    """Collapse all whitespace to single spaces for verbatim-coverage comparison."""
    return re.sub(r"\s+", " ", s).strip()


def build_prompt(topic: str, pillar: str, script: str, target: int,
                 feedback: str = "") -> str:
    tone = PILLAR_TONE.get(pillar, PILLAR_TONE["History"])
    fb = f"\n\n{feedback}\n" if feedback else ""
    return f"""Break this documentary narration script into a scene-by-scene storyboard.

TOPIC: {topic}
PILLAR: {pillar}{fb}

First, decide ONE fixed visual style descriptor for THIS episode — a short phrase (art
medium, palette, lighting, mood) that every shot will share so the episode looks visually
consistent. Match it to the pillar and tone: {tone}. Do NOT repeat this style text inside
each scene's visual_prompt — return it once, separately, as "style_descriptor".

Then split the script into scenes:
- Aim for about {target} scenes. HARD LIMITS: no fewer than {MIN_SCENES}, no more than
  {MAX_SCENES}. Roughly one scene per 20-30 seconds of narration (about 45-75 spoken words
  per scene).
- Each scene must cover at least ~40 words of narration. Do NOT give a short punchy sentence
  its own scene — group short lines together with the surrounding narration into one scene
  (the visual_prompt can still emphasize the punchy moment). This keeps you within the count.
- narration_text MUST be the EXACT verbatim substring of the script that this scene covers,
  copied character-for-character. Concatenating every scene's narration_text in scene order
  MUST reproduce the ENTIRE script with no gaps, no overlaps, and no rewording. Split only at
  clean sentence boundaries.
- visual_prompt: a highly specific English description for image/video generation — subject,
  setting, composition, lighting, camera angle. Be concrete ("aerial view of a fog-covered
  medieval battlefield at dawn, dramatic storm clouds, low sun") not vague ("a battle scene").
  Do NOT include the shared style descriptor here — it will be appended automatically.
- scene_type: "kling" ONLY for genuinely high-impact dramatic beats — the cold-open hook, a
  major reveal, a climactic moment, a cliffhanger — where motion meaningfully beats a still.
  Everything else is "still". Do not spread kling evenly; cluster it on the real peaks. Keep
  kling to at most {int(KLING_CEILING_PCT * 100)}% of scenes.
- impact_score: integer 1-10, how cinematically high-impact this beat is (used to rank).
- reasoning: one short phrase on why this scene got its type.

Respond with ONE JSON object and NOTHING else (no prose, no markdown fences):
{{
  "style_descriptor": "…",
  "scenes": [
    {{"scene_number": 1, "narration_text": "…verbatim slice…", "visual_prompt": "…",
      "scene_type": "still|kling", "impact_score": 7, "reasoning": "…"}}
  ]
}}

SCRIPT (verbatim — slice exactly this text):
---
{script}
---"""


def _extract_text(content_blocks: list[dict]) -> str:
    return "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()


def _parse_json(text: str) -> dict:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.DOTALL)
    if fence:
        t = fence.group(1)
    else:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            t = t[start:end + 1]
    return json.loads(t)


def call_claude(api_key: str, model: str, topic: str, pillar: str, script: str,
                target: int, feedback: str = "") -> dict:
    resp = httpx.post(
        API,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={
            "model": model,
            "max_tokens": 16000,
            "system": SYSTEM,
            "messages": [{"role": "user",
                          "content": build_prompt(topic, pillar, script, target, feedback)}],
        },
        timeout=600.0,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Claude API error {resp.status_code}: {resp.text[:800]}")
    text = _extract_text(resp.json().get("content", []))
    if not text:
        raise SystemExit("Claude returned no text to parse.")
    try:
        return _parse_json(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Could not parse storyboard JSON: {e}\n--- text ---\n{text[:1500]}")


def enforce_kling_cap(scenes: list[dict]) -> tuple[int, int]:
    """Hard-cap kling scenes at KLING_CEILING_PCT of the total. Downgrade the
    lowest-impact kling picks to still. Returns (ceiling, num_downgraded)."""
    total = len(scenes)
    ceiling = int(total * KLING_CEILING_PCT)  # floor — e.g. 30*0.20 = 6
    kling = [s for s in scenes if str(s.get("scene_type", "")).lower() == "kling"]
    for s in scenes:
        s["scene_type"] = str(s.get("scene_type", "still")).lower()
        if s["scene_type"] not in ("still", "kling"):
            s["scene_type"] = "still"
    if len(kling) <= ceiling:
        return ceiling, 0
    # Keep the highest-impact `ceiling` kling scenes; downgrade the rest.
    ranked = sorted(kling, key=lambda s: int(s.get("impact_score", 0)), reverse=True)
    downgraded = 0
    for s in ranked[ceiling:]:
        s["scene_type"] = "still"
        s["reasoning"] = (s.get("reasoning", "").strip()
                          + f" [auto-downgraded to still: kling cap ≤{int(KLING_CEILING_PCT*100)}% enforced]").strip()
        downgraded += 1
    return ceiling, downgraded


def verify_coverage(script: str, scenes: list[dict]) -> tuple[bool, str]:
    """Check that concatenated narration slices reproduce the script (whitespace-
    normalized). Returns (ok, message)."""
    joined = _norm(" ".join(s.get("narration_text", "") for s in scenes))
    target = _norm(script)
    if joined == target:
        return True, "exact match (whitespace-normalized): full coverage, no gaps or overlaps."
    # Locate first divergence to help review.
    lo = 0
    while lo < min(len(joined), len(target)) and joined[lo] == target[lo]:
        lo += 1
    ctx_target = target[max(0, lo - 40):lo + 40]
    ctx_joined = joined[max(0, lo - 40):lo + 40]
    return False, (
        f"MISMATCH. joined={len(joined)} chars, script={len(target)} chars. "
        f"First divergence at char {lo}.\n"
        f"    script : …{ctx_target}…\n"
        f"    scenes : …{ctx_joined}…"
    )


def append_style(scenes: list[dict], style: str) -> str:
    """Append the episode style descriptor (+ technical constraints) to every
    visual_prompt. Returns the final full style suffix used."""
    suffix = style.strip().rstrip(".")
    if "16:9" not in suffix:
        suffix += ", 16:9 cinematic composition, no on-screen text, no watermark"
    for s in scenes:
        base = str(s.get("visual_prompt", "")).strip().rstrip(".")
        s["visual_prompt"] = f"{base}. {suffix}"
    return suffix


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate and display, but do not write back to the Sheet.")
    args = ap.parse_args()

    cfg = load_config()
    require_anthropic_key(cfg)
    model = (os.environ.get("DOC_STORYBOARD_MODEL") or "").strip() or DEFAULT_MODEL

    queue = TopicQueue(cfg)
    rec = queue.next_script_ready()
    if not rec:
        print(f"[backend={queue.backend}] No rows with status='script_ready'. Nothing to do.")
        return 0
    if rec["pillar"] not in PILLARS:
        print(f"⚠️  Unknown pillar {rec['pillar']!r}; proceeding with History defaults.")

    script = clean_script(rec["script"])
    if not script:
        raise SystemExit("The row's 'script' column is empty — run Phase 2 first.")

    # Anchor the target scene count to the narration length (~60 words/scene),
    # clamped to the allowed band, so the model doesn't over- or under-segment.
    word_count = len(script.split())
    target = max(MIN_SCENES, min(MAX_SCENES, round(word_count / 60)))

    print(f"[backend={queue.backend}] model={model}")
    print(f"Storyboarding: [{rec['pillar']}] {rec['topic']}  "
          f"({word_count} words → target ~{target} scenes)", flush=True)

    # One-shot auto-retry if the scene count lands outside the 20-40 band.
    feedback = ""
    for attempt in range(2):
        result = call_claude(cfg.anthropic_api_key, model, rec["topic"], rec["pillar"],
                             script, target, feedback)
        style = str(result.get("style_descriptor", "")).strip()
        scenes = result.get("scenes", [])
        if not scenes:
            raise SystemExit("Claude returned no scenes.")
        n = len(scenes)
        if MIN_SCENES <= n <= MAX_SCENES:
            break
        if attempt == 0:
            direction = "too many — MERGE short adjacent scenes" if n > MAX_SCENES \
                else "too few — SPLIT the longest scenes"
            print(f"  ↻ got {n} scenes (outside {MIN_SCENES}-{MAX_SCENES}); "
                  f"retrying once ({direction}).", flush=True)
            feedback = (
                f"Your previous attempt produced {n} scenes, which is {direction} to land "
                f"between {MIN_SCENES} and {MAX_SCENES} (aim for ~{target}). Keep the exact "
                "verbatim coverage of the full script."
            )

    # Renumber defensively so scene_number is contiguous 1..N in order.
    for i, s in enumerate(scenes, 1):
        s["scene_number"] = i

    # Verify coverage BEFORE mutating visual_prompts (compare against raw slices).
    ok, msg = verify_coverage(script, scenes)

    # Enforce the hard kling cap, then append the shared style to every prompt.
    ceiling, downgraded = enforce_kling_cap(scenes)
    full_suffix = append_style(scenes, style)

    total = len(scenes)
    kling = sum(1 for s in scenes if s["scene_type"] == "kling")
    still = total - kling
    pct = (kling / total * 100) if total else 0

    # -- report ----------------------------------------------------------------
    print("\n" + "=" * 74)
    print(f"STORYBOARD — [{rec['pillar']}] {rec['topic']}")
    print("=" * 74)
    print(f"Style descriptor: {full_suffix}\n")
    for s in scenes:
        tag = "🎬 KLING" if s["scene_type"] == "kling" else "🖼  still"
        print(f"[{s['scene_number']:>2}] {tag}  (impact {s.get('impact_score','?')})")
        print(f"     narration: {s['narration_text'].strip()[:150]}"
              + ("…" if len(s['narration_text'].strip()) > 150 else ""))
        print(f"     visual:    {s['visual_prompt'][:150]}…")
        print(f"     why:       {s.get('reasoning','').strip()}")
    print("=" * 74)
    print(f"Scenes: {total}   still: {still}   kling: {kling}  ({pct:.1f}% of total)")
    print(f"Kling cap: ≤{int(KLING_CEILING_PCT*100)}% → ceiling {ceiling} scene(s); "
          f"auto-downgraded {downgraded} lowest-impact kling→still.")
    if not (MIN_SCENES <= total <= MAX_SCENES):
        print(f"⚠️  Scene count {total} outside the {MIN_SCENES}-{MAX_SCENES} target.")
    print(f"Coverage check: {'✅ ' if ok else '❌ '}{msg}")
    print("=" * 74)

    scene_json = json.dumps(
        {"style_descriptor": full_suffix, "scenes": scenes},
        ensure_ascii=False, indent=2,
    )

    if args.dry_run:
        print("\n--dry-run: not written back to the Sheet.")
        return 0
    if not ok:
        print("\n❌ Coverage check failed — NOT advancing status. "
              "Fix/re-run so narration slices exactly cover the script.")
        return 1

    queue.write_storyboard(rec["ref"], scene_json)
    print(f"\n✔ Wrote scene_breakdown and set status='storyboard_ready' "
          f"({'Google Sheet' if queue.backend == 'sheet' else 'local mirror'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
