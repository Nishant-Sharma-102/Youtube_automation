#!/usr/bin/env python3
"""Rewrite an episode's Hindi narration + image prompts with Claude for a
top-notch, retention-optimized viewer experience.

Claude (text only) does NOT generate audio or images — it rewrites the SCRIPT:
a gripping opening line, momentum through the middle, a strong closing + CTA,
and a richer cinematic English image prompt per scene. Voice (Gemini TTS) and
images (Pollinations) are produced by the other steps from what this writes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from config import PROJECT_DIR

API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-8"  # best quality for creative Hindi narrative writing


def _key() -> str:
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    for line in (PROJECT_DIR.parent / ".env").read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ANTHROPIC_API_KEY not found in env or ../.env")


SYSTEM = (
    "You are an expert Hindi YouTube scriptwriter for a history-storytelling channel. "
    "You write warm, cinematic, emotionally gripping narration that keeps viewers watching "
    "from the first second to the last. Your Hindi is natural, spoken, and vivid — not "
    "textbook-formal. You understand retention: a hook that creates instant curiosity, "
    "momentum and mini-cliffhangers through the middle, and a satisfying, goosebump closing "
    "with a natural subscribe call-to-action."
)

INSTR = """यह एक हिंदी इतिहास चैनल का एपिसोड है: रोम की स्थापना — रोमुलस और रेमुस की कहानी।
नीचे {n} दृश्य (scenes) हैं। हर दृश्य के लिए मौजूदा हिंदी नैरेशन और एक अंग्रेज़ी image hint दिया है।

हर दृश्य को टॉप-नॉच बनाओ:
- दृश्य 1: पहले ही वाक्य में ज़बरदस्त hook — दर्शक रुक ना पाए।
- बीच के दृश्य: गति बनी रहे, हर दृश्य अगले के लिए उत्सुकता छोड़े।
- आख़िरी दृश्य: दमदार, भावुक समापन + स्वाभाविक रूप से चैनल सब्सक्राइब करने की अपील।
- भाषा: गर्म, नाटकीय, बोलचाल की हिंदी। हर दृश्य लगभग उतना ही लंबा रहे जितना अभी है (±1 वाक्य)।
- साथ ही हर दृश्य के लिए एक समृद्ध, सिनेमैटिक अंग्रेज़ी image prompt लिखो (ancient Rome, dramatic).

सिर्फ़ JSON लौटाओ, इस रूप में (कोई अतिरिक्त टेक्स्ट नहीं):
{"scenes":[{"scene_number":1,"text":"<नई हिंदी नैरेशन>","image_prompt":"<rich cinematic English prompt>"}, ...]}

दृश्य:
"""


def main() -> int:
    fp = Path("data/ep1.json")
    d = json.loads(fp.read_text(encoding="utf-8"))
    scenes = sorted(d["scenes"], key=lambda s: int(s["scene_number"]))
    payload_scenes = [
        {"scene_number": int(s["scene_number"]),
         "current_text": s["text"],
         "current_image_hint": s.get("image_prompt_hint", "")}
        for s in scenes
    ]
    user = INSTR.replace("{n}", str(len(scenes))) + json.dumps(payload_scenes, ensure_ascii=False, indent=2)

    print(f"Calling Claude ({MODEL}) to rewrite {len(scenes)} scenes...", flush=True)
    resp = httpx.post(
        API,
        headers={
            "x-api-key": _key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 8000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=300.0,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Claude API error {resp.status_code}: {resp.text[:800]}")
    text = "".join(b.get("text", "") for b in resp.json()["content"] if b.get("type") == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    data = json.loads(text)
    new = {int(s["scene_number"]): s for s in data["scenes"]}
    if set(new) != {int(s["scene_number"]) for s in scenes}:
        raise SystemExit(f"Scene mismatch: got {sorted(new)}")

    for s in scenes:
        n = int(s["scene_number"])
        s["text"] = new[n]["text"].strip()
        s["image_prompt_hint"] = new[n]["image_prompt"].strip()
        print(f"scene {n}: {len(s['text'])} chars | img: {s['image_prompt_hint'][:60]}...", flush=True)

    d["scenes"] = scenes
    fp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print("updated data/ep1.json with Claude-rewritten narration + image prompts", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
