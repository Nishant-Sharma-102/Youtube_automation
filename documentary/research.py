"""Topic research via Claude with web search enabled.

Generates a batch of documentary topic ideas distributed across the four content
pillars, each fact-checked with real web searches, and returns BOTH the accepted
topics and the ones considered-but-rejected (duplicates / failed fact-check) so
the reasoning is visible, not just the final list.

Uses the Anthropic Messages API directly over httpx (no SDK dependency, matching
the rest of this repo). Web search is a server-side tool: Claude issues the
searches and Anthropic runs them; we just loop until the turn completes,
resuming on `pause_turn`.
"""
from __future__ import annotations

import json
import re

import httpx

from config import BATCH_SIZE, PILLAR_TARGETS, PILLARS, Config

API = "https://api.anthropic.com/v1/messages"
# Dynamic-filtering web search (supported on Opus 4.8 / Sonnet 5 / etc.).
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 25}
MAX_PAUSE_RESUMES = 8

SYSTEM = (
    "You are a senior researcher and commissioning editor for a cinematic, "
    "long-form documentary YouTube channel in English. The channel covers four "
    "pillars: History, Mysteries, Science & Space, and Alternate History. Each "
    "episode is a 10-15 minute narrated documentary, so topics must have enough "
    "depth and narrative arc to sustain that runtime.\n\n"
    "Editorial standards:\n"
    "- FACTUAL ACCURACY IS NON-NEGOTIABLE. For History and Science topics especially, "
    "the subject must be real and well-documented by reputable sources. The channel's "
    "credibility depends on it. Use web search to verify every candidate before "
    "accepting it — do not rely on memory alone.\n"
    "- Favour EVERGREEN subjects with genuine, durable search interest — not a fleeting "
    "news cycle or passing trend that will be stale in a month.\n"
    "- Each topic should have a clear hook: strong search demand, a fresh/unique angle, "
    "or exceptional story potential.\n"
    "- Alternate History is speculative by design: the topic must be grounded in a REAL, "
    "well-documented historical juncture (the 'what if' pivot point must be factual), even "
    "though the speculation itself is fiction. Make that grounding explicit in the notes.\n"
    "You are rigorous and skeptical: you would rather reject a shaky idea than let a "
    "poorly-sourced or duplicate topic through."
)


def _targets_line() -> str:
    return (
        f"History: aim for {PILLAR_TARGETS['History']} of {BATCH_SIZE} (~40%); "
        f"Mysteries: 2-3 (~25%); "
        f"Science & Space: {PILLAR_TARGETS['Science & Space']} (~20%); "
        f"Alternate History: 1-2 (~15%)."
    )


def build_user_prompt(existing_topics: list[str]) -> str:
    existing_block = (
        "\n".join(f"- {t}" for t in existing_topics)
        if existing_topics
        else "(none yet — this is the first batch)"
    )
    return f"""Generate {BATCH_SIZE} documentary topic ideas for the channel, distributed across the four pillars.

Target distribution across the {BATCH_SIZE} topics:
{_targets_line()}
Pillar values must be EXACTLY one of: {", ".join(PILLARS)}.

Process — do this properly:
1. Brainstorm more candidates than you need across the pillars.
2. For EACH candidate, run a web search to verify it is a real, well-documented subject
   (critical for History and Science & Space) and that it has genuine evergreen search
   interest rather than being a fleeting trend. For Alternate History, verify the underlying
   historical pivot point is factual and well-documented.
3. Reject any candidate that fails the fact-check, or that duplicates / is an extremely
   similar angle to a topic already in the queue (listed below) or to another candidate in
   this same batch. Keep going until you have {BATCH_SIZE} solid ACCEPTED topics that meet
   the distribution targets.

Topics ALREADY in the queue — do NOT repeat any of these or a near-duplicate angle:
{existing_block}

When you are done searching, respond with ONE JSON object and NOTHING else (no prose around
it, no markdown fences). Shape:

{{
  "accepted": [
    {{
      "topic": "concise, specific, compelling documentary title/subject",
      "pillar": "History | Mysteries | Science & Space | Alternate History",
      "notes": "One line: WHY this works — search demand, unique angle, and/or story potential — plus a brief note of what web search confirmed about its factual basis."
    }}
    // exactly {BATCH_SIZE} objects, respecting the distribution targets
  ],
  "rejected": [
    {{
      "topic": "the candidate you rejected",
      "pillar": "one of the four pillars",
      "reason": "duplicate of '<existing/other topic>'  OR  failed fact-check: <what was wrong / unverifiable>  OR  too trend-driven / not evergreen"
    }}
    // include every candidate you seriously considered but did not accept
  ]
}}
"""


def _extract_text(content_blocks: list[dict]) -> str:
    return "".join(
        b.get("text", "") for b in content_blocks if b.get("type") == "text"
    )


def _parse_json(text: str) -> dict:
    """Pull the JSON object out of Claude's final text, tolerant of stray prose
    or markdown fences."""
    t = text.strip()
    # Strip a ```json ... ``` fence if present.
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.DOTALL)
    if fence:
        t = fence.group(1)
    else:
        # Otherwise grab the outermost {...} span.
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1 and end > start:
            t = t[start:end + 1]
    return json.loads(t)


def generate_topics(cfg: Config, existing_topics: list[str]) -> dict:
    """Return {"accepted": [...], "rejected": [...], "search_count": int}.

    Raises SystemExit on API / parsing failure with a readable message.
    """
    headers = {
        "x-api-key": cfg.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    messages = [{"role": "user", "content": build_user_prompt(existing_topics)}]
    search_count = 0

    with httpx.Client(timeout=600.0) as client:
        for _ in range(MAX_PAUSE_RESUMES + 1):
            resp = client.post(
                API,
                headers=headers,
                json={
                    "model": cfg.anthropic_model,
                    "max_tokens": 8000,
                    "system": SYSTEM,
                    "tools": [WEB_SEARCH_TOOL],
                    "messages": messages,
                },
            )
            if resp.status_code != 200:
                raise SystemExit(
                    f"Claude API error {resp.status_code}: {resp.text[:800]}"
                )
            data = resp.json()
            content = data.get("content", [])
            search_count += sum(
                1 for b in content if b.get("type") == "server_tool_use"
            )
            stop = data.get("stop_reason")
            if stop == "pause_turn":
                # Server-tool loop paused; resume by echoing the assistant turn.
                messages.append({"role": "assistant", "content": content})
                continue
            # Terminal turn — parse the final text.
            text = _extract_text(content)
            if not text.strip():
                raise SystemExit(
                    "Claude returned no text block to parse (stop_reason="
                    f"{stop}). Raw: {json.dumps(content)[:600]}"
                )
            try:
                parsed = _parse_json(text)
            except json.JSONDecodeError as e:
                raise SystemExit(
                    f"Could not parse JSON from Claude's response: {e}\n"
                    f"--- text ---\n{text[:1500]}"
                )
            parsed.setdefault("accepted", [])
            parsed.setdefault("rejected", [])
            parsed["search_count"] = search_count
            return parsed

    raise SystemExit(
        f"Web-search turn did not finish after {MAX_PAUSE_RESUMES} resumes."
    )
