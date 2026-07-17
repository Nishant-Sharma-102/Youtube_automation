#!/usr/bin/env python3
"""Generate a cheerful English kids rhyme (Giggle Grove / Milo the fox) with Claude,
in the structured scene shape the illustrated pipeline expects. Kid-safe, bouncy,
repetitive, sing-song. Writes data/ep{N}.json with title/description/tags/scenes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from config import PROJECT_DIR

API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-8"
N_SCENES = 8


def _key() -> str:
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    for line in (PROJECT_DIR.parent / ".env").read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ANTHROPIC_API_KEY not found")


SYSTEM = (
    "You are a delightful children's rhyme writer for a preschool YouTube channel "
    "('Giggle Grove', starring Milo, a cheerful little orange fox cub with a blue scarf). "
    "You write simple, bouncy, sing-song rhymes for ages 2-6: short rhyming couplets, "
    "lots of repetition, warm and gentle, easy words, positive and safe. Every line is "
    "friendly and fun — never scary."
)


def prompt(topic: str) -> str:
    return f"""Write a complete kids rhyme video for Giggle Grove. Topic: {topic}

Requirements:
- Exactly {N_SCENES} scenes. Each scene = 1-2 short rhyming lines (sing-song, easy for toddlers, lots of repetition).
- Star Milo the orange fox cub (blue scarf) and friends; bright, happy, safe.
- Scene 1 = a fun welcoming hook; last scene = a happy wave-goodbye + gentle "subscribe" nudge for parents.
- For EACH scene, a cute cartoon image prompt (Milo/friends, meadow/Giggle Grove, bright & adorable).
- A catchy kid-friendly English title UNDER 80 chars, a short warm description (+ 3-4 kid/nursery hashtags), and 10-15 tags.

Return ONLY JSON, exactly this shape (no extra text):
{{"title_hindi":"<English title>","description_hindi":"<English description>","tags":["..."],
"scenes":[{{"scene_number":1,"text":"<rhyme lines>","image_prompt":"<cute cartoon prompt>","duration_seconds":12}}, ...]}}
(Note: the keys are named title_hindi/description_hindi for pipeline compatibility, but WRITE THEM IN ENGLISH.)
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--topic", required=True)
    args = ap.parse_args()

    print(f"Claude ({MODEL}) writing kids rhyme: {args.topic}", flush=True)
    resp = httpx.post(
        API,
        headers={"x-api-key": _key(), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 8000, "system": SYSTEM,
              "messages": [{"role": "user", "content": prompt(args.topic)}]},
        timeout=300.0,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Claude API error {resp.status_code}: {resp.text[:800]}")
    text = "".join(b.get("text", "") for b in resp.json()["content"] if b.get("type") == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text[4:] if text.startswith("json") else text
        text = text.strip()
    ep = json.loads(text)

    scenes = sorted(ep["scenes"], key=lambda s: int(s["scene_number"]))
    title = ep["title_hindi"].strip()
    if len(title) > 100:
        title = title[:100].rsplit(" ", 1)[0].rstrip(" |:-")
    out = {
        "title_hindi": title, "title": title,
        "description_hindi": ep["description_hindi"].strip(),
        "tags": [t.strip() for t in ep["tags"]],
        "status": "draft", "youtube_video_id": "",
        "scenes": [
            {"scene_number": int(s["scene_number"]), "text": s["text"].strip(),
             "image_prompt_hint": s["image_prompt"].strip(),
             "duration_seconds": float(s.get("duration_seconds", 12))}
            for s in scenes
        ],
    }
    fp = PROJECT_DIR / "data" / f"ep{args.episode}.json"
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"title({len(title)}): {title}\nscenes: {len(out['scenes'])} | tags: {len(out['tags'])}\nwrote {fp}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
