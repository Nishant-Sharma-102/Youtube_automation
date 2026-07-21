"""Video-description helpers (Phase 8 hook).

Phase 6 stores a ready-to-use music-attribution block in the episode JSON
(sb['music']['description_attribution']). CC-BY / CC-BY-SA REQUIRE attribution,
so Phase 8's description template calls music_credits_block() and appends it to
every episode's description automatically — the creator never has to remember it.

Phase 8 (video assembly / publish metadata) isn't built yet; this is the single
source of truth for the credits section so it stays consistent when it is.
"""
from __future__ import annotations


def music_credits_lines(sb: dict) -> list[str]:
    """The per-track CC-BY attribution lines for this episode (may be empty)."""
    return list((sb.get("music") or {}).get("description_attribution") or [])


def music_credits_block(sb: dict) -> str:
    """A formatted 'Music' section for the video description, or '' if no
    attribution-required tracks were used."""
    lines = music_credits_lines(sb)
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "Music\n"
        "—————\n"
        f"{body}\n"
        "Licensed under Creative Commons Attribution (CC-BY / CC-BY-SA). "
        "Full license terms: https://creativecommons.org/licenses/"
    )


def render_description(topic: str, summary: str, sb: dict) -> str:
    """Minimal description assembly. Phase 8 will expand this (chapters, links,
    hashtags); the music-credits section is already wired so attribution is never
    dropped."""
    parts = [summary.strip() if summary else topic.strip()]
    credits = music_credits_block(sb)
    if credits:
        parts.append(credits)
    return "\n\n".join(parts)
