#!/usr/bin/env python3
"""Phase 8 — thumbnail finalization + metadata generation.

Reads the next status='assembly_ready' row, then:
  • generates 3 high-impact thumbnail phrases (grounded in the script's cold-open
    hook) + 3 title variants + a description + 12-15 tags via Claude;
  • renders 3 thumbnail variants (v1/v2/v3) over the chosen keyframe;
  • appends the Phase-6 Jamendo CC-BY attribution to the description automatically;
  • writes it all back and sets status='metadata_ready' (stops short of 'ready');
  • does NOT auto-pick a title/thumbnail — you fill title_choice / thumbnail_choice.

A phone-friendly side-by-side preview (3 thumbnails + 3 titles) is written to
renders/<slug>/preview.html and summarized via notify.

Usage: python gen_metadata.py [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

import httpx

from config import PROJECT_DIR, load_config, require_anthropic_key
from description import music_credits_block
from notify import send
from sheet import TopicQueue
from thumbnail import render_thumbnail

API = "https://api.anthropic.com/v1/messages"
RENDERS = PROJECT_DIR / "renders"
FACT_MARKER_RE = re.compile(r"⟦FACT-CHECK:.*?⟧", re.DOTALL)


def slugify(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]) or "episode"


def normalize_hashtags(raw: list) -> list[str]:
    """Clean hashtags for YouTube: each starts with '#', no internal spaces, unique,
    order preserved. YouTube IGNORES ALL hashtags if a video has more than 15, so we
    hard-cap at 15."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        tag = str(item).strip()
        if not tag:
            continue
        # Collapse internal whitespace ("#fall of constantinople" -> "#fallofconstantinople").
        tag = "#" + re.sub(r"\s+", "", tag.lstrip("#"))
        if tag == "#" or tag.lower() == "#shorts":
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out[:15]


def cold_open(script: str) -> str:
    clean = FACT_MARKER_RE.sub("", script).strip()
    # First ~2 sentences / 400 chars as the hook.
    sents = re.split(r"(?<=[.!?])\s+", clean)
    hook = " ".join(sents[:3])[:400]
    return hook


SYSTEM = (
    "You write YouTube packaging for a cinematic documentary channel. Titles and "
    "thumbnail text must be curiosity-driven but strictly accurate — never promise "
    "anything not actually in the video. No fabricated 'clickbait'. You also know "
    "YouTube SEO: strong hashtags materially widen reach and impressions."
)


def _lang_clause(language: str) -> str:
    if language.strip().lower() in ("english", "en", "en-us"):
        return ""
    return (
        f" Write the titles, thumbnail_texts and description in {language} (native script — "
        f"Devanagari for Hindi), matching the narration language so they reach the right "
        f"audience. Tags and hashtags: include a mix of {language} AND transliterated/English "
        f"terms so the video is discoverable in both. Widely-recognized proper nouns may stay "
        f"in their common form."
    )


def build_prompt(topic, pillar, hook, schedule, language="English") -> str:
    return f"""Episode topic: {topic}
Pillar: {pillar}
The video's actual cold-open hook (ground everything in THIS, don't invent disconnected claims):
\"\"\"{hook}\"\"\"
{_lang_clause(language)}
Return ONE JSON object, nothing else:
{{
  "thumbnail_texts": ["…","…","…"],   // exactly 3. 2-4 WORDS each, ALL-CAPS-worthy, high-impact,
                                        // drawn from the hook/topic (e.g. "THE FINAL HOUR").
  "titles": ["…","…","…"],            // exactly 3. Curiosity-driven, UNDER 60 characters, accurate.
  "description": "…",                  // 150-300 words. Open with a hook like the video's; weave in
                                        // 2-3 relevant search keywords naturally; END with a call to
                                        // subscribe and this upload-schedule note: "{schedule}".
                                        // Do NOT add music credits or hashtags here — both are appended
                                        // automatically.
  "tags": ["…", …],                    // 12-15 tags: mix broad ("history documentary") and specific
                                        // (named people/events/places from this topic).
  "hashtags": ["#…", …]                // 10-15 high-reach hashtags, EACH starting with '#', no spaces
                                        // inside a tag. Order by importance (YouTube surfaces the first
                                        // 3 above the title). Mix broad discovery tags
                                        // (e.g. #documentary #history #itihaas) with 3-5 specific to
                                        // this topic. No duplicates, no '#shorts'.
}}"""


def call_claude(cfg, topic, pillar, hook) -> dict:
    r = httpx.post(API, headers={"x-api-key": cfg.anthropic_api_key,
                                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
                   json={"model": cfg.metadata_model, "max_tokens": 2500, "system": SYSTEM,
                         "messages": [{"role": "user",
                                       "content": build_prompt(topic, pillar, hook, cfg.upload_schedule,
                                                               cfg.narration_language)}]},
                   timeout=300.0)
    if r.status_code != 200:
        raise SystemExit(f"Claude API error {r.status_code}: {r.text[:600]}")
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise SystemExit(f"No JSON in Claude response: {text[:500]}")
    return json.loads(m.group(0))


def build_preview(topic, thumb_paths, titles, description, tags, out_html: Path):
    def uri(p):
        return "data:image/jpeg;base64," + base64.b64encode(Path(p).read_bytes()).decode()
    cards = "".join(
        f'<figure><img src="{uri(p)}" alt="thumbnail v{i}"><figcaption>v{i}</figcaption></figure>'
        for i, p in enumerate(thumb_paths, 1))
    tlist = "".join(f'<li><span>v{i}</span> {html.escape(t)} <em>({len(t)} chars)</em></li>'
                    for i, t in enumerate(titles, 1))
    out_html.write_text(f"""<title>Pick title & thumbnail — {html.escape(topic)}</title>
<style>
 :root{{--bg:#0e0f13;--panel:#181a20;--ink:#ece9e1;--dim:#9fa0a0;--gold:#c9a24b;--line:#2b2f38}}
 body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif;line-height:1.5}}
 header{{padding:2rem clamp(1rem,4vw,3rem) 1rem;border-bottom:1px solid var(--line)}}
 h1{{font-family:Georgia,serif;font-weight:600;margin:.2rem 0;font-size:clamp(1.3rem,3vw,2rem);text-wrap:balance}}
 .eyebrow{{color:var(--gold);letter-spacing:.2em;text-transform:uppercase;font-size:.72rem;margin:0}}
 h2{{font-family:Georgia,serif;font-weight:600;margin:1.6rem 0 .6rem}}
 main{{padding:1rem clamp(1rem,4vw,3rem) 4rem}}
 .thumbs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem}}
 figure{{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
 figure img{{width:100%;display:block;aspect-ratio:16/9;object-fit:cover}}
 figcaption{{padding:.5rem .8rem;color:var(--gold);font-weight:700}}
 ol{{list-style:none;padding:0;display:flex;flex-direction:column;gap:.5rem;max-width:760px}}
 li{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:.7rem .9rem}}
 li span{{color:var(--gold);font-weight:700;margin-right:.4rem}}
 li em{{color:var(--dim);font-style:normal;font-size:.8rem}}
 .desc{{white-space:pre-wrap;background:var(--panel);border:1px solid var(--line);border-radius:10px;
        padding:1rem;max-width:820px;color:#d6d4cd;font-size:.92rem}}
 .tags{{display:flex;flex-wrap:wrap;gap:.4rem;max-width:820px}}
 .tag{{background:#20242c;border:1px solid var(--line);border-radius:999px;padding:.25rem .7rem;font-size:.8rem;color:var(--dim)}}
</style>
<header><p class="eyebrow">Phase 8 · pick title &amp; thumbnail</p>
 <h1>{html.escape(topic)}</h1>
 <p style="color:var(--dim)">Set <b>title_choice</b> and <b>thumbnail_choice</b> (v1/v2/v3) in the Sheet, then run the finalize step.</p></header>
<main>
 <h2>Thumbnails</h2><div class="thumbs">{cards}</div>
 <h2>Titles</h2><ol>{tlist}</ol>
 <h2>Description</h2><div class="desc">{html.escape(description)}</div>
 <h2>Tags</h2><div class="tags">{"".join(f'<span class="tag">{html.escape(t)}</span>' for t in tags)}</div>
</main>""", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    require_anthropic_key(cfg)
    queue = TopicQueue(cfg)
    rec = queue.next_assembly_ready()
    if not rec:
        print(f"[backend={queue.backend}] No status='assembly_ready' row. Nothing to do.")
        return 0

    sb = json.loads(rec["scene_breakdown"])
    thumb_src = sb.get("thumbnail_source_path")
    if not thumb_src or not Path(thumb_src).exists():
        raise SystemExit(f"thumbnail_source_path missing or not found: {thumb_src!r} (Phase 7 sets this).")

    hook = cold_open(rec["script"])
    print(f"[backend={queue.backend}] Episode: [{rec['pillar']}] {rec['topic']}")
    print(f"Model: {cfg.metadata_model}\nThumbnail source: {thumb_src}")
    print(f"Cold-open hook: {hook[:120]}…\n", flush=True)

    meta = call_claude(cfg, rec["topic"], rec["pillar"], hook)
    thumb_texts = meta.get("thumbnail_texts", [])[:3]
    titles = meta.get("titles", [])[:3]
    description = meta.get("description", "").strip()
    tags = meta.get("tags", [])[:15]
    # Topic-specific hashtags from Claude lead (best for relevance + the 3 shown above
    # the title); evergreen channel hashtags fill the rest for broad reach. Capped 15.
    hashtags = normalize_hashtags(list(meta.get("hashtags", [])) + list(cfg.base_hashtags))

    # Build the final description: body → hashtags (drives reach; YouTube shows the
    # first 3 above the title) → Jamendo CC-BY attribution (deterministic, guaranteed).
    credits = music_credits_block(sb)
    hashtag_line = " ".join(hashtags)
    full_description = description
    if hashtag_line:
        full_description += "\n\n" + hashtag_line
    if credits:
        full_description += "\n\n" + credits

    # Render 3 thumbnail variants.
    slug = slugify(rec["topic"])
    rdir = RENDERS / slug
    thumb_paths = []
    for i, txt in enumerate(thumb_texts, 1):
        out = rdir / f"thumbnail_v{i}.jpg"
        if not args.dry_run:
            render_thumbnail(thumb_src, txt, out, cfg.thumb_font)
        thumb_paths.append(str(out))

    # -- report --
    print("THUMBNAIL TEXT VARIANTS:")
    for i, t in enumerate(thumb_texts, 1):
        print(f"  v{i}: {t}   → {thumb_paths[i-1]}")
    print("\nTITLE VARIANTS:")
    for i, t in enumerate(titles, 1):
        flag = "  ⚠️ >60 chars" if len(t) > 60 else ""
        print(f"  v{i}: {t}  ({len(t)} chars){flag}")
    print(f"\nDESCRIPTION ({len(full_description.split())} words):\n{full_description}\n")
    print(f"TAGS ({len(tags)}): {', '.join(tags)}")
    print(f"HASHTAGS ({len(hashtags)}): {hashtag_line}")
    if credits:
        print("\n✅ Jamendo CC-BY attribution auto-included in the description.")

    if args.dry_run:
        print("\n--dry-run: no thumbnails written, no write-back.")
        return 0

    # Caption tracks: source (narration language) + configured translations, built
    # from the per-scene narration + measured durations. Uploaded in Phase 9.
    captions = {}
    try:
        from captions import language_name, write_caption_tracks
        translate_to = {code: language_name(code) for code in cfg.caption_languages
                        if code and code != cfg.language_code}
        captions = write_caption_tracks(
            sb.get("scenes", []), rdir, source_code=cfg.language_code,
            api_key=cfg.anthropic_api_key, model=cfg.metadata_model, translate_to=translate_to)
        if captions:
            print(f"CAPTIONS ({len(captions)}): " + ", ".join(f"{k}→{Path(v).name}"
                                                              for k, v in captions.items()))
    except Exception as e:  # noqa: BLE001 — captions must never block publishing
        print(f"⚠️  Caption generation skipped ({e}).")

    # Store metadata; leave choices blank for the human.
    sb["metadata"] = {
        "thumbnail_texts": thumb_texts, "thumbnails": thumb_paths,
        "titles": titles, "description": full_description, "tags": tags,
        "hashtags": hashtags, "captions": captions,
    }
    queue.write_metadata(rec["ref"], json.dumps(sb, ensure_ascii=False, indent=2))
    print("\n✔ Wrote metadata + set status='metadata_ready' (choices left blank for you).")

    # Preview + notification.
    preview = rdir / "preview.html"
    build_preview(rec["topic"], thumb_paths, titles, full_description, tags, preview)
    print(f"Preview page: {preview}")
    summary = ("🎬 Pick title & thumbnail — " + rec["topic"] + "\n\nTITLES:\n"
               + "\n".join(f"  v{i}. {t}" for i, t in enumerate(titles, 1))
               + "\n\nTHUMBNAILS:\n"
               + "\n".join(f"  v{i}. “{t}”" for i, t in enumerate(thumb_texts, 1))
               + "\n\nSet title_choice + thumbnail_choice, then run finalize.")
    send(cfg, summary)
    print("🛑 Stops at metadata_ready — NOT 'ready'. You choose title/thumbnail first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
