#!/usr/bin/env python3
"""Phase 2 — documentary script generation for APPROVED topics.

Picks the next Sheet row with status='approved', writes a full 10-15 minute
narrated documentary script with Claude, writes it back to the 'script' column,
and sets status='script_ready'. Reports word count, estimated runtime, and any
factual-confidence flags Claude raised so you can sanity-check before it runs
unattended.

Model: claude-sonnet-4-6 (as specified for this phase). Override with
DOC_SCRIPT_MODEL.

Usage:
  python gen_script.py            # process the next approved row
  python gen_script.py --dry-run  # generate + display only, do NOT write back
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import httpx

from config import load_config, require_anthropic_key
from sheet import TopicQueue

API = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
WORDS_PER_MINUTE = 140  # midpoint of the 130-150 wpm calm-documentary pace
MIN_WORDS, MAX_WORDS = 1800, 2500

# Distinctive, easy-to-parse inline marker for shaky claims (factual pillars only).
FLAG_OPEN, FLAG_CLOSE = "⟦FACT-CHECK:", "⟧"
FLAG_RE = re.compile(re.escape(FLAG_OPEN) + r"\s*(.*?)\s*" + re.escape(FLAG_CLOSE), re.DOTALL)

# Pillars where factual credibility is load-bearing → flag low-confidence claims.
FACT_PILLARS = {"History", "Science & Space", "Alternate History"}

SYSTEM = (
    "You are a scriptwriter for a cinematic, long-form documentary YouTube channel. "
    "You write calm, immersive, measured narration — the register of a high-end "
    "documentary voice-over. NOT dry or academic, NOT hyped-up YouTuber energy. "
    "Every script is engineered for retention: it hooks in the first breath and never "
    "lets the middle sag. You write narration ONLY — continuous spoken prose, no camera "
    "directions, no 'SCENE 1' headers, no music cues."
)

PILLAR_STRUCTURE = {
    "History": (
        "Use a chronological / cause-and-effect arc: set the stakes, move through the "
        "sequence of events with mounting consequence, land on the turning point and its "
        "aftermath."
    ),
    "Alternate History": (
        "Ground the episode in the REAL, well-documented historical pivot point first, then "
        "build the speculative 'what if' forward in a cause-and-effect chain. Keep the factual "
        "pivot and the speculation clearly distinguishable to the listener."
    ),
    "Mysteries": (
        "Build around unresolved tension: establish the puzzle fast, deepen it with evidence "
        "and dead ends, escalate the stakes, and close on either a satisfying resolution or a "
        "deliberately ambiguous, lingering note — whichever the evidence honestly supports."
    ),
    "Science & Space": (
        "Move from a striking hook question, to a clear and vivid explanation a lay viewer can "
        "follow, to the implications and why it matters. Make the abstract concrete."
    ),
}


def _fact_flag_instruction(pillar: str) -> str:
    if pillar not in FACT_PILLARS:
        return ""
    return (
        "\n\nFACTUAL CONFIDENCE (critical for this channel's credibility): this is a "
        f"{pillar} topic. For any specific claim — a date, name, number, quote, causal "
        "assertion — that you are NOT highly confident is factually accurate, do NOT state "
        "it as plain fact. Instead, write the claim and immediately append an inline flag in "
        f"this exact format: {FLAG_OPEN} the claim, and why you're uncertain / what to "
        f"verify {FLAG_CLOSE}. Use this marker and no other. If the whole script is claims "
        "you're confident in, that's fine — use no flags. Prefer flagging a shaky claim now "
        "over stating it plainly; I would rather catch it before publishing."
    )


def _language_instruction(language: str) -> str:
    if language.strip().lower() in ("english", "en", "en-us"):
        return ""
    return (
        f"\n\nLANGUAGE (critical): Write the ENTIRE narration in {language}. Use natural, "
        f"fluent, native {language} in its native script (for Hindi, use Devanagari) — the "
        f"cadence a real {language} documentary narrator would speak, NOT a stiff translation "
        f"of English. Proper nouns (names of people, places, empires) may stay in their "
        f"commonly-recognized form. Numbers and years may be written in digits. Any "
        f"FACT-CHECK marker you add stays in the exact marker format regardless of language."
    )


def build_prompt(topic: str, pillar: str, notes: str, language: str = "English") -> str:
    structure = PILLAR_STRUCTURE.get(pillar, PILLAR_STRUCTURE["History"])
    context = f"\nEditorial note from the topic queue: {notes}\n" if notes else ""
    return f"""Write the full narration script for one documentary episode.

TOPIC: {topic}
PILLAR: {pillar}{context}

Requirements:
- Length: {MIN_WORDS}-{MAX_WORDS} words (targets a 10-15 minute narrated runtime at a calm pace).
- COLD OPEN: the first 10-15 seconds (~30-40 words) must hook immediately — a striking fact,
  a sharp question, or a vivid scene that creates instant curiosity. No slow wind-up, no
  "In this video we'll explore…", no throat-clearing.
- CURIOSITY LOOPS: open a compelling question early and delay its answer; keep at least one
  such loop running at all times so the viewer stays for the payoff.
- PACING: land a cliffhanger, reveal, or tension beat roughly every 30-60 seconds of narration
  (~every 75-150 words) — especially through the MIDDLE THIRD, where documentaries lose viewers.
  The middle must not sag.
- TONE: calm, cinematic, measured, immersive documentary narration.
- STRUCTURE for this pillar: {structure}
- Close with a resonant, memorable ending. A brief, natural note to subscribe is fine but keep
  it understated — no hard sell.{_fact_flag_instruction(pillar)}{_language_instruction(language)}

Output ONLY the narration script text itself — no title line, no headings, no preamble,
no word count, no commentary. Just the words to be spoken."""


def _extract_text(content_blocks: list[dict]) -> str:
    return "".join(
        b.get("text", "") for b in content_blocks if b.get("type") == "text"
    ).strip()


def generate_script(api_key: str, model: str, topic: str, pillar: str, notes: str,
                    language: str = "English") -> str:
    resp = httpx.post(
        API,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 8000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": build_prompt(topic, pillar, notes, language)}],
        },
        timeout=600.0,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Claude API error {resp.status_code}: {resp.text[:800]}")
    text = _extract_text(resp.json().get("content", []))
    if not text:
        raise SystemExit("Claude returned no script text.")
    return text


def narration_word_count(script: str) -> int:
    """Word count of the spoken narration only — fact-check markers stripped out."""
    spoken = FLAG_RE.sub("", script)
    return len(spoken.split())


def extract_flags(script: str) -> list[str]:
    return [m.strip() for m in FLAG_RE.findall(script)]


def runtime_str(words: int) -> str:
    minutes = words / WORDS_PER_MINUTE
    return f"{int(minutes)}m {round((minutes - int(minutes)) * 60):02d}s"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate and display, but do not write back to the Sheet.")
    args = ap.parse_args()

    cfg = load_config()
    require_anthropic_key(cfg)
    model = (os.environ.get("DOC_SCRIPT_MODEL") or "").strip() or DEFAULT_MODEL

    queue = TopicQueue(cfg)
    rec = queue.next_approved()
    if not rec:
        print(f"[backend={queue.backend}] No rows with status='approved'. Nothing to do.")
        return 0

    print(f"[backend={queue.backend}] model={model}  language={cfg.narration_language}")
    print(f"Generating script for: [{rec['pillar']}] {rec['topic']}", flush=True)
    script = generate_script(cfg.anthropic_api_key, model, rec["topic"],
                             rec["pillar"], rec["notes"], cfg.narration_language)

    words = narration_word_count(script)
    flags = extract_flags(script)

    print("\n" + "=" * 72)
    print(f"SCRIPT — [{rec['pillar']}] {rec['topic']}")
    print("=" * 72 + "\n")
    print(script)
    print("\n" + "=" * 72)
    print(f"Word count (narration): {words}")
    print(f"Estimated runtime:      {runtime_str(words)}  (@ {WORDS_PER_MINUTE} wpm)")
    if not (MIN_WORDS <= words <= MAX_WORDS):
        print(f"⚠️  Outside the {MIN_WORDS}-{MAX_WORDS} word target — review length.")
    print(f"Factual-confidence flags raised: {len(flags)}")
    for i, f in enumerate(flags, 1):
        print(f"  {i}. {f}")
    print("=" * 72)

    if args.dry_run:
        print("\n--dry-run: not written back to the Sheet.")
        return 0

    queue.write_script(rec["ref"], script)
    print(f"\n✔ Wrote script to '{rec['topic']}' and set status='script_ready' "
          f"({'Google Sheet' if queue.backend == 'sheet' else 'local mirror'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
