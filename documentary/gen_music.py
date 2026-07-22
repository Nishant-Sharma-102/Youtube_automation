#!/usr/bin/env python3
"""Phase 6 — background music selection for a reviewed episode.

Runs ONLY on rows that are status='visuals_ready' AND have the `approved` column
set (the Phase 5 human review gate — status alone is not enough). Maps the
episode's pillar to a mood, searches Pixabay for commercial-use instrumental
tracks, picks a track (or 2-3, or a loop) to cover the full narration runtime,
logs the license for a per-episode paper trail, downloads the track(s), records a
music plan (with transition points at natural scene breaks), and sets
status='music_ready'.

Pixabay music: see music_pixabay.py — the public Pixabay API does not officially
expose audio, so without DOC_PIXABAY_API_KEY this runs in MOCK mode (sample
candidates, placeholder downloads) to validate the flow. Actual audio
trimming/looping/concatenation happens in Phase 7 (needs ffmpeg); Phase 6 selects,
licenses, downloads, and SCRIPTS the transitions.

Usage:
  python gen_music.py            # select + download + write back
  python gen_music.py --dry-run  # select + report, no download/write-back
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from config import PROJECT_DIR, load_config
from music_jamendo import JamendoSource, attribution_text, description_credit
from music_pixabay import PixabaySource
from sheet import TopicQueue


def get_source(cfg):
    return JamendoSource(cfg) if cfg.music_source == "jamendo" else PixabaySource(cfg)

MUSIC_ROOT = PROJECT_DIR / "music"

# pillar -> (mood label, mock candidate bucket key, search query for a live API)
MOOD = {
    "History": ("epic, orchestral, measured", "epic-orchestral",
                "epic orchestral cinematic instrumental"),
    "Mysteries": ("tense, minimal, unsettling undertones", "tense-minimal",
                  "tense minimal suspense dark instrumental"),
    "Science & Space": ("curious, bright but restrained, subtly building", "curious-bright",
                        "curious ambient hopeful building instrumental"),
    "Alternate History": ("dramatic, speculative, epic + tense blend", "dramatic-speculative",
                          "dramatic cinematic hybrid epic tension instrumental"),
}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "episode"


def scene_break_times(scenes: list[dict]) -> list[tuple[int, float]]:
    """Cumulative end time (sec) at the end of each scene → (scene_number, t)."""
    out, t = [], 0.0
    for s in scenes:
        t += float(s.get("duration_sec", 0) or 0)
        out.append((int(s["scene_number"]), round(t, 2)))
    return out


def nearest_break(breaks: list[tuple[int, float]], target: float) -> tuple[int, float]:
    return min(breaks, key=lambda b: abs(b[1] - target))


def choose_tracks(candidates: list, runtime: float) -> tuple[str, list, str]:
    """Return (strategy, chosen_tracks, rationale). Prefers a single sufficiently
    long track; else 2-3 tracks in the same mood; else loop the longest."""
    by_dur = sorted(candidates, key=lambda t: t.duration_sec, reverse=True)
    if not by_dur:
        raise SystemExit("No candidate tracks returned.")

    longest = by_dur[0]
    if longest.duration_sec >= runtime * 0.95:
        return ("single", [longest],
                f"'{longest.title}' ({longest.duration_sec:.0f}s) ≥ runtime "
                f"({runtime:.0f}s); trim to length.")

    # Multi-track: greedily add distinct tracks until we cover the runtime.
    chosen, total = [], 0.0
    for t in by_dur:
        chosen.append(t)
        total += t.duration_sec
        if total >= runtime and len(chosen) >= 2:
            break
    if total >= runtime and 2 <= len(chosen) <= 3:
        return ("multi", chosen,
                f"No single track spans {runtime:.0f}s; {len(chosen)} same-mood tracks "
                f"({total:.0f}s combined) with transitions at scene breaks — preferred over "
                "a loop artifact in a long piece.")
    if total >= runtime:
        return ("multi", chosen,
                f"{len(chosen)} tracks needed to span {runtime:.0f}s "
                f"({total:.0f}s combined); more than ideal but avoids looping.")
    # Fallback: loop the longest with a crossfade seam.
    return ("loop", [longest],
            f"Candidates too short to span {runtime:.0f}s even combined; loop "
            f"'{longest.title}' ({longest.duration_sec:.0f}s) with a crossfade at the seam.")


def build_plan(strategy: str, tracks: list, runtime: float,
               breaks: list[tuple[int, float]]) -> dict:
    plan = {"strategy": strategy, "runtime_sec": round(runtime, 2), "tracks": []}
    if strategy in ("single", "loop"):
        t = tracks[0]
        plan["tracks"].append({"title": t.title, "duration_sec": t.duration_sec,
                               "page_url": t.page_url})
        plan["instruction"] = ("trim to runtime" if strategy == "single"
                               else f"loop with ~2s crossfade to reach {runtime:.0f}s")
        return plan
    # multi: script transition points snapped to nearest scene breaks
    transitions, cursor = [], 0.0
    for i, t in enumerate(tracks):
        seg_end = cursor + t.duration_sec
        entry = {"order": i + 1, "title": t.title, "duration_sec": t.duration_sec,
                 "page_url": t.page_url, "starts_sec": round(cursor, 2)}
        if i < len(tracks) - 1:  # transition to the next track at a scene break
            sc, at = nearest_break(breaks, seg_end)
            entry["transition_to_next_at_sec"] = at
            entry["transition_at_scene_break"] = sc
            transitions.append({"from_track": i + 1, "to_track": i + 2,
                                "at_sec": at, "at_scene_break": sc})
            cursor = at
        plan["tracks"].append(entry)
    plan["transitions"] = transitions
    plan["instruction"] = "concatenate in order with short crossfades at the scripted scene breaks"
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Select + report, but do not download or write back.")
    args = ap.parse_args()

    cfg = load_config()
    queue = TopicQueue(cfg)
    rec = queue.next_visuals_approved()
    if not rec:
        print(f"[backend={queue.backend}] No status='visuals_ready' row with `approved` set. "
              "Nothing to do. (Approve a reviewed episode in the `approved` column first.)")
        return 0

    sb = json.loads(rec["scene_breakdown"])
    scenes = sb.get("scenes", [])
    runtime = float(sb.get("total_audio_sec") or sum(
        float(s.get("duration_sec", 0) or 0) for s in scenes))
    if runtime <= 0:
        raise SystemExit("Episode runtime unknown — was Phase 4 (voice) run?")

    pillar = rec["pillar"]
    mood_label, bucket, query = MOOD.get(pillar, MOOD["History"])
    # A configured mood override (e.g. "suspense") wins over the per-pillar default so
    # every episode gets a consistent tense, cinematic score. The bucket (used only by
    # the mock source) stays the pillar's nearest mood.
    if cfg.music_mood_override:
        m = cfg.music_mood_override.strip()
        mood_label = f"{m} (override)"
        # Keep it to a few broad tags — Jamendo fuzzytags with many terms returns few
        # or zero tracks. "suspense"->"dark tense cinematic".
        query = "dark tense cinematic instrumental" if m.lower() in ("suspense", "suspenseful") \
            else f"{m} cinematic instrumental"
    source = get_source(cfg)

    print(f"[backend={queue.backend}] Episode: [{pillar}] {rec['topic']}")
    print(f"Runtime to cover: {runtime:.1f}s ({runtime/60:.1f} min)")
    print(f"Mood ({pillar}): {mood_label}   query: {query!r}")
    print(f"Music source: {cfg.music_source} [{'MOCK — no key' if source.mock else 'LIVE'}]   "
          f"commercial-only filter: {'ON' if cfg.music_require_commercial else 'off'}\n")

    candidates = source.search(bucket, query)
    # Broaden if the mood query returned too few — fuzzytags can be sparse, and a
    # monetized channel needs at least a couple of commercial-safe options to pick from.
    if len(candidates) < 2 and not source.mock:
        for alt in ("dark cinematic instrumental", "cinematic instrumental", "ambient instrumental"):
            if alt == query:
                continue
            print(f"  only {len(candidates)} track(s) for {query!r} — broadening → {alt!r}")
            more = source.search(bucket, alt)
            if len(more) >= 2:
                candidates, query = more, alt
                break
            candidates = candidates or more
    if source.mock:
        print("  ⚠️ Jamendo is in MOCK mode (no DOC_JAMENDO_CLIENT_ID) — the music bed will be a\n"
              "     silent placeholder. Set DOC_JAMENDO_CLIENT_ID in .env for real suspense music.")
    dropped = getattr(source, "filtered_out", [])
    if dropped:
        print(f"License guard dropped {len(dropped)} non-commercial/no-derivatives track(s):")
        for d in dropped:
            print(f"   ✗ {d}")
        print()
    if not candidates:
        raise SystemExit("No commercially-usable candidate tracks after license filtering.")
    strategy, tracks, rationale = choose_tracks(candidates, runtime)
    breaks = scene_break_times(scenes)
    plan = build_plan(strategy, tracks, runtime, breaks)

    print(f"Strategy: {strategy.upper()}\nWhy: {rationale}\n")
    print("Selected track(s):")
    any_attribution = False
    for i, t in enumerate(tracks, 1):
        print(f"  {i}. {t.title}" + (f" — {t.author}" if t.author else "") + f"  ({t.duration_sec:.0f}s)")
        print(f"     source: {t.page_url}")
        print(f"     license RAW: '{t.license.get('code','')}'   ccurl: {t.license.get('url','')}")
        print(f"     license: {t.license['name']} — {t.license['summary']}")
        att = attribution_text(t)
        if att:
            any_attribution = True
            print(f"     ATTRIBUTION REQUIRED → credit: {att}")
        if t.is_mock:
            print("     ⚠️ MOCK sample track — not a real licensing record.")
    if any_attribution:
        print("\n📝 Phase 8 video-description credits (auto-included in every episode):")
        for t in tracks:
            print(f"     {description_credit(t)}")
    if strategy == "multi":
        print("\nScripted transitions (at natural scene breaks):")
        for tr in plan["transitions"]:
            print(f"  track {tr['from_track']} → {tr['to_track']} at {tr['at_sec']:.1f}s "
                  f"(end of scene {tr['at_scene_break']})")
    elif strategy == "loop":
        print("\n⚠️ LOOP strategy — a seam crossfade is needed; loop artifacts are more "
              "noticeable in a 10-15 min piece. Prefer adding real longer/multi candidates.")

    if args.dry_run:
        print("\n--dry-run: no download, no write-back.")
        return 0

    # Download the selected track(s).
    music_dir = MUSIC_ROOT / slugify(rec["topic"])
    music_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, t in enumerate(tracks, 1):
        out = music_dir / (f"music.mp3" if len(tracks) == 1 else f"music_{i:02d}.mp3")
        source.download(t, out)
        paths.append(str(out))
        plan["tracks"][i - 1]["file_path"] = str(out)
        print(f"  downloaded → {out}")

    # Record music metadata into the episode JSON blob and advance status.
    sb["music"] = {
        "strategy": strategy,
        "mood": mood_label,
        "music_file_path": paths[0],
        "files": paths,
        "plan": plan,
        "source": cfg.music_source,
        "is_mock": source.mock,
        "commercial_only_filter": cfg.music_require_commercial,
        "attribution_required": any(t.license.get("attribution_required") for t in tracks),
        "attribution_credits": [attribution_text(t) for t in tracks if attribution_text(t)],
        # RAW license string per track, verbatim from the API, on record per episode.
        "license_raw_per_track": [{"title": t.title, "artist": t.author,
                                   "license_code": t.license.get("code", ""),
                                   "ccurl": t.license.get("url", "")} for t in tracks],
        # Phase 8 drops these straight into the video description.
        "description_attribution": [description_credit(t) for t in tracks],
        "tracks_meta": [{"title": t.title, "artist": t.author, "page_url": t.page_url,
                         "duration_sec": t.duration_sec, "license": t.license} for t in tracks],
    }
    queue.write_music(rec["ref"], json.dumps(sb, ensure_ascii=False, indent=2))
    print(f"\n✔ Stored music plan + license and set status='music_ready' "
          f"({'Google Sheet' if queue.backend == 'sheet' else 'local mirror'}).")
    print("🛑 Manual gate: NOT proceeding to Phase 7 — listen to a preview first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
