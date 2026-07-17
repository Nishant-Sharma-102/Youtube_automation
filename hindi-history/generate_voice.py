#!/usr/bin/env python3
"""Phase 2 — Hindi voice generation, timed per scene.

Reads a script_ready episode (from the Sheet, or a local scenes JSON for offline
testing), synthesizes EACH scene separately via the voice provider chain
(ElevenLabs → Google Cloud TTS → Gemini TTS → Edge TTS) to
audio/epN_sceneM.mp3, measures each scene's exact duration, concatenates all scenes
into audio/epN_full.mp3, tracks free-tier character usage, writes durations + the
full audio path back, and sets status=audio_ready.

Examples
--------
  # Offline pipeline test (no TTS credential) using a Phase-1 dump; makes silent
  # placeholder audio so durations/concat/usage math can be verified:
  python generate_voice.py --episode 1 --scenes-file data/ep1.json --silent

  # Real run from the Sheet (needs a service-account JSON with TTS enabled):
  python generate_voice.py --episode 1

  # Real run from a local Phase-1 dump (no Sheet needed):
  python generate_voice.py --episode 1 --scenes-file data/ep1.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from audio_utils import concat_mp3, duration_seconds, make_silence
from config import PROJECT_DIR, load_config, require_sheet

AUDIO_DIR = PROJECT_DIR / "audio"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_DIR / "logs" / "voice.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("phase2")


def _estimate_seconds(text: str) -> float:
    """Rough Hindi narration length for silent placeholders (~132 wpm)."""
    words = len([w for w in text.split() if w])
    return max(1.5, words / 2.2)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 2: Hindi per-scene voice generation")
    ap.add_argument("--episode", type=int, default=1, help="Episode number (names output files).")
    ap.add_argument("--scenes-file", help="Local Phase-1 JSON dump to read/write instead of the Sheet.")
    ap.add_argument("--row", type=int, help="Sheet row to process (default: next script_ready row).")
    ap.add_argument("--silent", action="store_true",
                    help="Generate silent placeholder audio (no TTS credential needed) to test the pipeline.")
    ap.add_argument("--no-write", action="store_true", help="Do not write results back to the Sheet.")
    args = ap.parse_args()

    cfg = load_config()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    ep_num = args.episode

    # --- 1. Load scenes ---
    sheet = None
    row_number = None
    file_data = None
    file_path = None
    if args.scenes_file:
        file_path = Path(args.scenes_file)
        file_data = json.loads(file_path.read_text(encoding="utf-8"))
        scenes = file_data["scenes"]
        log.info("Loaded %d scenes from %s", len(scenes), file_path)
    else:
        require_sheet(cfg)
        from sheet import HistorySheet
        sheet = HistorySheet(cfg)
        if args.row:
            row_number, scenes = sheet.get_row_scenes(args.row)
        else:
            got = sheet.get_next_ready_for_audio()
            if not got:
                log.info("No rows with status='script_ready'. Nothing to do.")
                return 0
            row_number, scenes = got
        log.info("Loaded %d scenes from Sheet row %d", len(scenes), row_number)

    scenes = sorted(scenes, key=lambda s: int(s["scene_number"]))

    # --- 2. Set up TTS (real path only) ---
    # Provider chain, tried in priority order: ElevenLabs → Google Cloud TTS →
    # Gemini TTS → Edge TTS. Locks onto the first that works for a consistent voice.
    tts = None
    if not args.silent:
        from tts_providers import build_voice_chain
        tts = build_voice_chain(cfg)

    # --- 3. Per-scene synthesis + duration ---
    total_chars = 0
    part_paths: list[Path] = []
    for sc in scenes:
        n = int(sc["scene_number"])
        text = sc["text"]
        out = AUDIO_DIR / f"ep{ep_num}_scene{n}.mp3"
        if args.silent:
            make_silence(_estimate_seconds(text), out)
        else:
            tts.synthesize_to_file(text, out)
        sc["duration_seconds"] = duration_seconds(out)
        total_chars += len(text)
        part_paths.append(out)
        log.info("scene %d: %s (%.3fs, %d chars) -> %s",
                 n, "silent placeholder" if args.silent else "synthesized",
                 sc["duration_seconds"], len(text), out.name)

    # --- 4. Concatenate full episode track ---
    full_path = AUDIO_DIR / f"ep{ep_num}_full.mp3"
    concat_mp3(part_paths, full_path)
    full_dur = duration_seconds(full_path)
    scene_sum = round(sum(float(s["duration_seconds"]) for s in scenes), 3)
    log.info("Full track: %s (%.3fs; sum of scenes %.3fs)", full_path.name, full_dur, scene_sum)

    # --- 5. Usage tracking ---
    from usage import record
    u = record(ep_num, total_chars, cfg.tts_voice, persist=not args.silent)

    # --- 6. Write back ---
    if args.scenes_file:
        file_data["scenes"] = scenes
        file_data["audio_path"] = str(full_path)
        file_data["scene_audio"] = [str(p) for p in part_paths]
        file_data["status"] = "audio_ready"
        file_path.write_text(json.dumps(file_data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Updated %s (status=audio_ready)", file_path)
    elif not args.no_write and row_number is not None:
        sheet.write_audio_result(row_number, scenes, str(full_path))
        log.info("Wrote durations + audio_path to Sheet row %d (status=audio_ready)", row_number)
    else:
        log.info("Not writing back (--no-write or no target row).")

    # --- Report ---
    bar = "=" * 64
    print(f"\n{bar}\nPHASE 2 RESULT — episode {ep_num}"
          f"{'  [SILENT PLACEHOLDER AUDIO]' if args.silent else ''}\n{bar}")
    provider_used = "silent" if args.silent else tts.provider_name
    print(f"Voice provider: {provider_used}   (voice={cfg.tts_voice}, {u['tier']} tier)")
    print(f"Scenes processed: {len(scenes)}")
    for sc in scenes:
        print(f"  scene {int(sc['scene_number']):>2}: {float(sc['duration_seconds']):6.2f}s   "
              f"{len(sc['text'])} chars")
    mins = int(full_dur // 60)
    print(f"Total episode duration: {full_dur:.2f}s  (~{mins}m {full_dur - mins*60:.0f}s)")
    print(f"  (sum of scene durations: {scene_sum:.2f}s)")
    print(f"Characters this episode: {total_chars:,}")
    label = "would use" if args.silent else "used"
    print(f"Monthly {u['tier']} total {label}: {u['month_total']:,} / {u['limit']:,} "
          f"({u['pct']:.2f}%)  [{u['month']}]")
    if u["warn"]:
        print(f"  ⚠️  Over {int(0.8*100)}% of the free {u['tier']} tier this month — watch usage.")
    if args.silent:
        print("\n⚠️  Audio is SILENCE (placeholder). Real Hindi speech needs a Google Cloud "
              "service-account JSON with the Text-to-Speech API enabled — then re-run without --silent.")
    print(bar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
