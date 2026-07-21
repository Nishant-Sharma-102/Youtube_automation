#!/usr/bin/env python3
"""Phase 5 — visual generation for an audio_ready episode.

For every scene: generate a Pollinations key frame (free) from its visual_prompt.
For 'still' scenes that key frame is the final asset. For 'kling' scenes: animate
the key frame with Kling image-to-video to a clip matching the scene's
duration_seconds (chaining extensions past Kling's single-clip cap, flagged).

Real Kling costs money, so cost is tracked per scene with a running total, and the
run PAUSES + notifies before any spend that would exceed the budget ($25 default).
A completeness check confirms every scene has its required asset before advancing
to status='visuals_ready'. This is a MANUAL REVIEW GATE — it never proceeds to
Phase 6.

Kling defaults to a no-spend MOCK (writes placeholder clips) so the pipeline can be
validated without a key or a bill. Pass --live-kling (with DOC_KLING_API_KEY set)
for the real render.

Usage:
  python gen_visuals.py                 # keyframes (real) + kling (mock), full episode
  python gen_visuals.py --live-kling    # real Kling render (needs DOC_KLING_API_KEY)
  python gen_visuals.py --force         # regenerate assets even if files exist
  python gen_visuals.py --max-kling-usd 40   # raise the budget gate (e.g. after a go-ahead)
  python gen_visuals.py --limit 5       # only the first N scenes (quick check)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from config import PROJECT_DIR, load_config
from notify import send
from sheet import TopicQueue
from visuals_pollinations import generate_keyframe


def resolve_animation_provider(name: str):
    """Return the module implementing estimate_clip/generate_clip for the configured
    animation provider. 'free' = Hugging Face SVD (no cost), 'kling' = paid, 'mock'
    = free stills (handled via the mock path, but still uses the free provider's
    zero-cost planner)."""
    name = (name or "free").lower()
    if name == "kling":
        import visuals_kling as provider
    else:  # "free" and "mock" both use the free provider's interface
        import visuals_free as provider
    return provider

IMAGES_ROOT = PROJECT_DIR / "images"
VIDEOS_ROOT = PROJECT_DIR / "videos"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "episode"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live-kling", action="store_true",
                    help="Make REAL (billed) Kling calls. Default is a no-spend mock.")
    ap.add_argument("--force", action="store_true",
                    help="Regenerate assets even if the files already exist.")
    ap.add_argument("--max-kling-usd", type=float, default=None,
                    help="Override the Kling budget gate (default from config, $25).")
    ap.add_argument("--limit", type=int, default=0, help="Only process the first N scenes.")
    args = ap.parse_args()

    cfg = load_config()
    budget = args.max_kling_usd if args.max_kling_usd is not None else cfg.kling_budget_usd
    provider = resolve_animation_provider(cfg.visuals_provider)
    estimate_clip = provider.estimate_clip
    generate_clip = provider.generate_clip

    # Decide LIVE vs no-spend MOCK per provider. Missing credentials fall back to mock
    # (free stills) rather than crashing — except an explicit --live-kling with no key.
    if cfg.visuals_provider == "mock":
        mock = True
    elif cfg.visuals_provider == "kling":
        want_live = args.live_kling or cfg.kling_live_default
        if want_live and not cfg.kling_api_key:
            raise SystemExit("Live Kling requires DOC_KLING_API_KEY. Aborting (no mock fallback for a live run).")
        mock = not (want_live and bool(cfg.kling_api_key))
    else:  # free (Hugging Face SVD): live whenever a free token is present
        mock = not bool(cfg.hf_token)
        if mock:
            print("⚠️  DOC_VISUALS_PROVIDER=free but no DOC_HF_TOKEN — writing free-still "
                  "MOCK clips (no motion). Add a free HF token to animate.")

    queue = TopicQueue(cfg)
    rec = queue.next_audio_ready()
    if not rec:
        print(f"[backend={queue.backend}] No rows with status='audio_ready'. Nothing to do.")
        return 0

    sb = json.loads(rec["scene_breakdown"])
    scenes = sb.get("scenes", [])
    if not scenes:
        raise SystemExit("scene_breakdown has no scenes.")
    if args.limit:
        scenes_to_do = scenes[:args.limit]
    else:
        scenes_to_do = scenes

    slug = slugify(rec["topic"])
    img_dir = IMAGES_ROOT / slug
    vid_dir = VIDEOS_ROOT / slug

    is_paid = cfg.visuals_provider == "kling"
    print(f"[backend={queue.backend}] Episode: [{rec['pillar']}] {rec['topic']}")
    print(f"Animation provider: {cfg.visuals_provider}   "
          f"mode: {'MOCK (no motion)' if mock else ('LIVE (billed)' if is_paid else 'LIVE (free)')}"
          + (f"   budget gate: ${budget:.2f}   rate: ${cfg.kling_cost_per_sec}/s" if is_paid else ""))
    print(f"Images: {img_dir}\nVideos: {vid_dir}\n")

    total_cost = 0.0
    paused = False
    n_scenes = len(scenes_to_do)

    # Extra framings appended to the scene prompt so multi-image scenes vary the
    # composition instead of repeating one shot. Index 0 is the primary keyframe.
    SHOT_VARIATIONS = [
        "", ", wider cinematic establishing angle", ", closer detail shot, shallow depth of field",
        ", alternate angle, different framing", ", dramatic low angle",
    ]

    def images_for(duration: float) -> int:
        if cfg.images_per_scene_max <= 1 or cfg.images_per_scene_sec <= 0:
            return 1
        n_img = max(1, round(duration / cfg.images_per_scene_sec))
        return min(n_img, cfg.images_per_scene_max, len(SHOT_VARIATIONS))

    for idx, s in enumerate(scenes_to_do):
        n = int(s["scene_number"])
        stype = s.get("scene_type", "still")
        dur = float(s.get("duration_sec", 0) or 0)
        # A real animation provider needs just one conditioning frame for its 'kling'
        # scenes. But when animation is mocked (no real video model available), EVERY
        # scene — kling included — gets the free multi-image cross-dissolve treatment.
        n_imgs = 1 if (stype == "kling" and not mock) else images_for(dur)

        # 1. Key frame(s) for the scene. First one is the canonical keyframe.
        kf_paths = []
        for j in range(n_imgs):
            kf = img_dir / (f"scene_{n:03d}_keyframe.jpg" if j == 0
                            else f"scene_{n:03d}_img{j+1}.jpg")
            if kf.exists() and not args.force:
                print(f"[{n:>2}] {stype:5} image {j+1}/{n_imgs} reuse  {kf.name}")
            else:
                prompt = s["visual_prompt"] + SHOT_VARIATIONS[j]
                generate_keyframe(cfg, prompt, kf, seed=None if j == 0 else 1000 + n * 10 + j)
                print(f"[{n:>2}] {stype:5} image {j+1}/{n_imgs} ✓      {kf.name}")
                if not (idx == n_scenes - 1 and j == n_imgs - 1):
                    time.sleep(cfg.pollinations_delay_sec)  # respect anon rate limit
            kf_paths.append(str(kf))
        s["keyframe_path"] = kf_paths[0]      # canonical (thumbnail + kling conditioning)
        s["keyframe_paths"] = kf_paths        # full list for multi-image assembly

        # 2. Kling video for 'kling' scenes.
        if stype == "kling":
            target = float(s.get("duration_sec", 0) or 0)
            plan = estimate_clip(cfg, target)
            # BUDGET GATE — never spend past the threshold without a go-ahead.
            if total_cost + plan.cost_usd > budget:
                paused = True
                msg = (
                    f"⏸️  Kling budget gate hit on scene {n}. "
                    f"Spent ${total_cost:.2f}; this clip (+${plan.cost_usd:.2f}) would exceed "
                    f"${budget:.2f}. Paused before spending. Re-run with "
                    f"--max-kling-usd <higher> to continue."
                )
                print("\n" + msg)
                send(cfg, "Documentary Phase 5 (visuals) paused:\n" + msg)
                break
            vid = vid_dir / f"scene_{n:03d}.mp4"
            if vid.exists() and not args.force:
                print(f"        video reuse    {vid.name}")
            else:
                plan = generate_clip(cfg, kf, s["visual_prompt"], target, vid, mock=mock)
                flag = "  ⚠️ CHAINED (drift risk)" if plan.chained else ""
                print(f"        kling ✓ {plan.billed_sec:.1f}s ({plan.segments} seg) "
                      f"→ ${plan.cost_usd:.2f}{flag}  {vid.name}")
            s["video_path"] = str(vid)
            s["kling_billed_sec"] = plan.billed_sec
            s["kling_cost_usd"] = plan.cost_usd
            s["kling_chained"] = plan.chained
            total_cost += plan.cost_usd

    # 3. Completeness check (over the scenes we attempted).
    missing = []
    for s in scenes_to_do:
        n = s["scene_number"]
        kf = Path(s.get("keyframe_path", ""))
        if not (kf and kf.exists()):
            missing.append(f"scene {n}: keyframe missing")
        if s.get("scene_type") == "kling":
            vp = s.get("video_path", "")
            if not (vp and Path(vp).exists()):
                missing.append(f"scene {n}: kling video missing")

    kling_scenes = [s for s in scenes_to_do if s.get("scene_type") == "kling"]
    chained = [s["scene_number"] for s in kling_scenes if s.get("kling_chained")]

    print("\n" + "=" * 70)
    print(f"Scenes processed: {n_scenes}   kling: {len(kling_scenes)}")
    print(f"Total Kling spend this episode: ${total_cost:.2f}  "
          f"({'MOCK — estimated, not billed' if mock else 'LIVE — billed'})")
    if chained:
        print(f"⚠️  Chained (extension) clips — higher drift risk: scenes {chained}")
    if missing:
        print(f"❌ INCOMPLETE — regenerate these:\n   " + "\n   ".join(missing))
    else:
        print("✅ Completeness check passed: every scene has its required asset.")
    print("=" * 70)

    if paused:
        print("\n⏸️  PAUSED at budget gate — status NOT advanced. Re-run with a higher "
              "--max-kling-usd after your go-ahead.")
        return 2
    if missing:
        print("\n❌ Incomplete — status NOT advanced. Regenerate the scenes above (re-run "
              "without --force reuses good assets and only redoes missing ones).")
        return 1
    if args.limit and args.limit < len(scenes):
        print("\n(--limit set: partial run, status NOT advanced.)")
        return 0

    sb["scenes"] = scenes
    sb["kling_spend_usd"] = round(total_cost, 2)
    sb["visuals_mock"] = mock
    queue.write_visuals(rec["ref"], json.dumps(sb, ensure_ascii=False, indent=2))
    print(f"\n✔ Wrote per-scene asset paths + kling_spend_usd (${total_cost:.2f}) and set "
          f"status='visuals_ready' ({'Google Sheet' if queue.backend == 'sheet' else 'local mirror'}).")
    print("🛑 Manual review gate: NOT proceeding to Phase 6. Review the keyframes first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
