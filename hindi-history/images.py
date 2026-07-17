"""Phase 3 helpers — Pollinations.ai image generation + named-entity review flags.

No API key required. We build each scene's prompt from its English image_prompt_hint
plus one configurable channel-wide style suffix, download a 1920x1080 image, validate
it's a real image, and flag scenes whose hint names a real historical figure/place/
event (those are the ones most worth eyeballing before publishing).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

import requests

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"

# ---- prompt building -------------------------------------------------------
def build_prompt(hint: str, style: str) -> str:
    return f"{hint.strip().rstrip('.')}, {style.strip()}"


# ---- image download with retry/backoff -------------------------------------
def fetch_image(
    prompt: str,
    out_path: str | Path,
    *,
    width: int = 1920,
    height: int = 1080,
    seed: int | None = None,
    retries: int = 3,
    timeout: int = 120,
    log=None,
) -> tuple[bool, str]:
    url = POLLINATIONS.format(prompt=quote(prompt, safe=""))
    params = {"width": width, "height": height, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed
    info = "no attempt"
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=(15, timeout))
            ct = r.headers.get("content-type", "")
            if r.status_code == 200 and ct.startswith("image") and len(r.content) > 2000:
                # Verify BEFORE the file lands at its final path: a 200 with an image/*
                # content-type can still be an HTML error body. Write to a .part temp,
                # decode it, and only then move it into place — so downstream coverage
                # (which is existence-based) can never count a corrupt body as a scene.
                tmp = Path(str(out_path) + ".part")
                tmp.write_bytes(r.content)
                try:
                    from PIL import Image
                    with Image.open(tmp) as im:
                        im.verify()           # structural check
                    with Image.open(tmp) as im:
                        im.load()             # catches truncation verify() misses
                except Exception as e:
                    tmp.unlink(missing_ok=True)
                    raise ValueError(f"response was not a decodable image: {e}")
                tmp.replace(out_path)
                return True, f"{len(r.content)} bytes, {ct}"
            info = f"HTTP {r.status_code}, content-type={ct!r}, {len(r.content)} bytes"
        except Exception as e:  # network, timeout, or invalid image
            info = f"{type(e).__name__}: {e}"
        if log:
            log(f"    attempt {attempt}/{retries} failed ({info})")
        if attempt < retries:
            time.sleep(3.0 * attempt)  # 3s, 6s backoff
    return False, info


# ---- named-entity review flag ----------------------------------------------
def _load_dictionary() -> set[str] | None:
    for p in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
        fp = Path(p)
        if fp.exists():
            return {w.strip().lower() for w in fp.read_text(errors="ignore").splitlines() if w.strip()}
    return None


_DICT = _load_dictionary()

# Capitalized words that are NOT proper names (sentence starters / art descriptors).
# Fallback filter when no system dictionary is available; also trims noise regardless.
_GENERIC = {
    "a", "an", "the", "in", "on", "at", "of", "and", "or", "with", "by", "to", "for",
    "inside", "outside", "near", "behind", "there", "later", "then", "two", "one", "three",
    "simple", "warm", "early", "ancient", "dramatic", "dynamic", "majestic", "grand",
    "rustic", "somber", "chaotic", "cinematic", "flat", "painterly", "muted", "wild",
    "natural", "miraculous", "clear", "active", "strong", "kind", "young", "older",
    "stern", "sad", "distraught", "proud", "conflicted", "emphasize", "no", "action",
    "oriented", "era", "aesthetic", "art", "digital", "storytelling", "history",
    "historical", "scene", "mood", "light", "lighting", "color", "palette", "style",
    "composition", "widescreen", "text", "watermark", "background", "foreground",
    "festival", "temple", "throne", "senate", "palace", "landscape", "sky", "trees",
    "river", "hill", "walls", "boundary", "attire", "clothing", "roman", "italian",
}

_TITLE_RE = re.compile(
    r"\b(?:Emperor|King|Queen|Prince|Princess|General|Battle of|Siege of|Fall of|"
    r"Founding of|Rise of|Empire of|Kingdom of|Republic of|Dynasty of)\s+[A-Z][A-Za-z']+"
)
_CAP_SEQ = re.compile(r"[A-Z][a-z'][A-Za-z']*(?:\s+[A-Z][a-z'][A-Za-z']*)*")
_PAREN = re.compile(r"\(([^)]*)\)")


def _generic(tok: str) -> bool:
    return len(tok) < 3 or tok.lower() in _GENERIC


def _flag_seq(seq: str, hits: set[str], *, sentence_initial: bool) -> None:
    toks = seq.split()
    if len(toks) >= 2:
        # A multi-word capitalized phrase is a proper-noun phrase if any token
        # isn't a generic/style word (e.g. "Alba Longa", "Tiber River", "Vestal Virgin").
        if any(not _generic(t) for t in toks):
            hits.add(seq)
        return
    tok = toks[0]
    if _generic(tok):
        return
    # A single capital that does NOT start its sentence is almost always a proper
    # noun (Romulus, Mars, Rhea). A sentence-initial capital is ambiguous, so only
    # flag it if it is not an ordinary dictionary word.
    if sentence_initial and _DICT is not None and tok.lower() in _DICT:
        return
    hits.add(tok)


def review_flags(hint: str) -> list[str]:
    """Return the specific named entities that make this scene worth manual review
    (empty list => purely decorative/scenic prompt)."""
    hits: set[str] = set()
    for m in _TITLE_RE.finditer(hint):
        hits.add(m.group(0))
    for paren in _PAREN.findall(hint):  # parenthetical names are never sentence-initial
        for seq in _CAP_SEQ.findall(paren):
            _flag_seq(seq, hits, sentence_initial=False)
    for sentence in re.split(r"(?<=[.!?])\s+", hint.strip()):
        for m in _CAP_SEQ.finditer(sentence):
            _flag_seq(m.group(0), hits, sentence_initial=(m.start() == 0))
    return sorted(hits)
