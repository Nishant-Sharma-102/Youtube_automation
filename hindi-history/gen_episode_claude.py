#!/usr/bin/env python3
"""Generate a brand-new episode (title, description, tags, scenes) with Claude.

Writes data/ep{N}.json in the shape the rest of the pipeline expects:
title_hindi, description_hindi (with hashtags), tags[], and scenes[] with
scene_number / text (Hindi narration) / image_prompt_hint (English, cinematic) /
duration_seconds (rough estimate; the voice step overwrites it with the real
measured duration). Kept to 9 scenes to fit within the Gemini free-tier TTS cap.
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
N_SCENES = 9


def _key() -> str:
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    for line in (PROJECT_DIR.parent / ".env").read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ANTHROPIC_API_KEY not found")


SYSTEM = (
    "You are a top Hindi YouTube history-storyteller (think the most gripping "
    "history/mystery channels). Your narration is SUSPENSEFUL and cinematic: it opens "
    "with a mystery or shocking hook, keeps raising questions, and holds the viewer on a "
    "knife's edge to the very end. Style: short, punchy spoken-Hindi sentences; frequent "
    "rhetorical questions ('लेकिन क्या आप जानते हैं...?'); dramatic pauses written as '…'; "
    "mini-cliffhangers at the end of most scenes ('...लेकिन असली कहानी अभी बाकी थी।'); "
    "vivid sensory detail. Natural, conversational, never textbook-formal. Build tension, "
    "then pay it off."
)


def prompt(topic: str) -> str:
    return f"""एक हिंदी इतिहास चैनल के लिए पूरा नया एपिसोड लिखो। विषय: {topic}

ज़रूरतें:
- ठीक {N_SCENES} दृश्य (scenes)।
- दृश्य 1: पहले ही वाक्य में रहस्य/चौंकाने वाला hook (सवाल खड़ा करो, जवाब रोक लो)। बीच के दृश्य: लगातार तनाव व उत्सुकता, ज़्यादातर दृश्य एक mini-cliffhanger पर ख़त्म हों। आख़िरी दृश्य: दमदार खुलासा + भावुक समापन + सब्सक्राइब अपील।
- नाटकीय शैली: छोटे-छोटे दमदार वाक्य; बीच-बीच में सवाल; नाटकीय ठहराव के लिए '…' का इस्तेमाल करो (voice इन पर रुकेगी → सस्पेंस)।
- हर दृश्य की हिंदी नैरेशन ~2-4 वाक्य (बोलने में ~25-40 सेकंड)।
- हर दृश्य के लिए एक समृद्ध सिनेमैटिक अंग्रेज़ी image prompt (ancient India, dramatic, historical)।
- एक आकर्षक हिंदी title — **ज़रूरी: 80 अक्षरों से कम** (YouTube की सीमा 100 है), कोई English टेल न जोड़ो अगर लंबा हो। एक अच्छा हिंदी description (हुक + क्या सीखेंगे + सब्सक्राइब CTA + 3-4 hashtags), और 10-15 tags (हिंदी+अंग्रेज़ी)।

सिर्फ़ JSON लौटाओ, बिल्कुल इस रूप में (कोई अतिरिक्त टेक्स्ट नहीं):
{{"title_hindi":"...","description_hindi":"...","tags":["...","..."],
"scenes":[{{"scene_number":1,"text":"<हिंदी नैरेशन>","image_prompt":"<cinematic English prompt>","duration_seconds":30}}, ...]}}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, default=2)
    ap.add_argument("--topic", required=True)
    args = ap.parse_args()

    print(f"Claude ({MODEL}) writing new episode: {args.topic}", flush=True)
    resp = httpx.post(
        API,
        headers={"x-api-key": _key(), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 10000, "system": SYSTEM,
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
    # Hard guard: YouTube rejects titles > 100 chars. Trim at a word boundary if needed.
    title = ep["title_hindi"].strip()
    if len(title) > 100:
        title = title[:100].rsplit(" ", 1)[0].rstrip(" |:-–—")
        print(f"(title trimmed to {len(title)} chars for YouTube limit)", flush=True)
    out = {
        "title_hindi": title,
        "description_hindi": ep["description_hindi"].strip(),
        "tags": [t.strip() for t in ep["tags"]],
        "status": "draft",
        "youtube_video_id": "",
        "scenes": [
            {"scene_number": int(s["scene_number"]),
             "text": s["text"].strip(),
             "image_prompt_hint": s["image_prompt"].strip(),
             "duration_seconds": float(s.get("duration_seconds", 30))}
            for s in scenes
        ],
    }
    fp = PROJECT_DIR / "data" / f"ep{args.episode}.json"
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"title: {out['title_hindi']}", flush=True)
    print(f"scenes: {len(out['scenes'])} | tags: {len(out['tags'])}", flush=True)
    print(f"wrote {fp}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
