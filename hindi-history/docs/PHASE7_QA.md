# Phase 7 — QA & Launch Readiness Report

Method: 8 parallel QA agents (7 completed; contention agent re-run inline) doing failure
injection, double-run, credential-isolation, contention, and disk/cleanup audits against
both pipelines on the **dev box** (NOT the production EC2 — no EC2 metadata, no Blender,
and the kids `.env` here carries live YouTube creds). All tests ran in isolated episode
namespaces on copies; the `ep1` golden fixture and the kids DB were left untouched.

**71 findings: 1 critical, 7 high, 12 medium, 19 low, 32 info.**

---

## Fixes applied this pass (verified)

| Sev | Issue | Fix | Verified |
|---|---|---|---|
| CRITICAL | Real Gemini key committed in `ROOT/.env.example` (not git-ignored → future `git add` stages a live secret) | Scrubbed to placeholder + rotate note | grep shows empty value |
| HIGH | Phase 3: corrupt/HTML 200 body written to final path before PIL verify → counted as coverage, episode → `images_ready` with garbage | `fetch_image` writes `.part`, decodes (verify+load), renames only on success, unlinks on failure | unit test: `ok=False`, no file persisted |
| HIGH | Phase 4: corrupt/truncated JPEG silently rendered (ffmpeg "EOI missing, emulating"), passes sanity, → `ready` | Strict PIL decode preflight per scene before any render | corrupt image → fast SystemExit, status unchanged, no render |
| HIGH | Phase 4: no disk-space preflight (stated EC2 worry) | `shutil.disk_usage` check on /tmp + renders/, refuse < `HISTORY_MIN_FREE_GB` (default 2) | code + compile |
| HIGH | Phase 1: no HTTP timeout on Gemini → 137s+ hang (unbounded on read-stall) holding the shared cron flock | `genai.Client(http_options=HttpOptions(timeout=120_000))` | compile |
| HIGH | Phase 5: `set_thumbnail`/`markPublished` failure *after* upload left row `ready` with no id → next run re-uploads a DUPLICATE | Record `video_id` + `status=published` immediately after upload; thumbnail is best-effort after | mock: "guard armed" logs before "thumbnail set" |
| HIGH | `orchestrator_history.js` loaded no `.env` → under cron's bare env it always refuses; history could never publish on EC2 | Self-load `hindi-history/.env` at startup (never overrides real env) | node --check; mock run |

---

## Item-by-item

### 1. Failure injection
- **Gemini (P1):** bogus key → clean 400, fast, exit 1, row stays `draft` ✓. Network-unreachable → errored after 137s (kernel TCP), **no configured timeout** → FIXED. Write-back is a single atomic `batch_update` after success — mid-run death leaves `draft`, no partial state ✓. Gap: tracebacks reach stderr only, not `logs/generate.log` (medium, open — cron `2>&1` captures them in `/var/log`, but README points at the wrong log). Also: a nonsense topic silently produced an unrelated (plausible) episode — no topical-relevance gate (low, open).
- **TTS (P2):** no-creds → clean instructional exit, state untouched ✓. Mid-run SIGXFSZ crash → queue JSON byte-identical, still `script_ready` ✓. Bogus service-account → raw 30-line traceback, no guidance (medium, open). Usage recorded once at end → a mid-episode real-TTS failure spends quota that's never logged (medium, open).
- **Pollinations (P3):** retry/backoff clean (3 attempts, 3s/6s, no hang) ✓. Whole-phase failure → exit 1, stays `audio_ready`, clear `--only N` guidance ✓. **Corrupt-body-as-coverage → FIXED.** Connect timeout hardcoded 15s ignores param (low, open); worst-case read-stall episode ~68 min with no lock file (low, open).
- **Render (P4):** missing audio/image → fast clean exit, no status change ✓. Mid-encode kill → ffmpeg stderr surfaced, temp dir cleaned, status unchanged ✓. Drift gate blocks `ready` on 63s drift ✓ (but leaves 40 MB orphan mp4 — low, see item 5). **Corrupt-image-silently-rendered → FIXED. Disk preflight → FIXED.**
- **YouTube (P5):** bogus token → 4 backoff retries, exit 1, row stays `ready` ✓ (retrying a non-retryable `invalid_grant` wastes ~7s — low, open). **Post-upload-failure duplicate window → FIXED.**
- **Disk full mid-render:** was unguarded → **FIXED** (preflight) + non-atomic queue write remains (medium, open — recommend `os.replace` tmp pattern).

### 2. Double-run safety
- History file-mode & mock: second run skips via `status != ready` + `youtube_video_id` guard ✓. Kids (DB copy): second `--all` selects nothing, real DB untouched ✓.
- **Open (medium):** Phases 2 & 3 in `--scenes-file`/`--row` mode have **no status gate** — re-running a finished episode silently regresses status (P2 → `audio_ready`, re-spends TTS quota; P3 re-fetches all images). Recommend a `status`-precondition + `--force`. Not blocking for the guarded publish step, but risky for unattended re-triggers of upstream phases.

### 3. Credential isolation — VERDICT: SOUND both directions
- kids-token → history-upload: **impossible.** Orchestrator spawns the server with `{...process.env, YOUTUBE_REFRESH_TOKEN: historyToken}` (explicit key wins over spread), refuses if the history token is unset, and the server's `dotenv` (`override:false`) can't re-inject the kids token because the key already exists in the child env.
- history-token → kids-upload: **impossible.** Distinct names; kids reads only `YOUTUBE_REFRESH_TOKEN`; nothing assigns the history var to it; `hindi-history/.env` loads only into Python.
- Only intentionally shared name: `GEMINI_API_KEY` (+ `GEMINI_MODEL`). Telegram names don't collide.
- **Open (high, config not code):** the kids `.env` on this box has `YOUTUBE_MOCK=0` + a live refresh token → `npm run publish` here would attempt a REAL upload. Keep that in mind on the dev box.

### 4. Resource contention — installed crontab differs from DEPLOY.md
Actual `crontab -l`:
```
0 13 * * *          scripts/cron-generate.sh   # kids GENERATE, DAILY, 13:00 UTC  (shared Gemini key!)
30 16 * * 1,3,5,0   scripts/cron-publish.sh    # kids PUBLISH, 16:30 UTC
```
- `flock`, `nice`, `ionice` all present; `flock -n` correctly skips (exit 1) when held ✓.
- **Reconciliation needed (medium/high):** (a) the kids crons use **no `flock`** — the DEPLOY.md shared-lock plan isn't actually installed; add it to both channels. (b) Kids *generate* runs **daily** on the **shared Gemini key** → this is why the history channel hit 429s during testing. Separate keys per channel. (c) DEPLOY.md assumed kids publishes 20:00 — it's really 16:30; history publish at 14:00 UTC is still safely before it, but update the doc. (d) A `flock -n` skip is **silent** — wrap with `|| echo "skipped: lock held"` so the log shows it.
- Quota (not CPU) is the real shared-resource ceiling: one Google Cloud project → YouTube 10k units/day ÷ 1600 per upload ≈ 6 uploads/day headroom (fine for 4+2 videos/wk); but put the two channels on **separate GCP projects** so TTS + YouTube quotas don't interact.
- Day separation (Tue/Sat vs Mon/Wed/Fri/Sun) + `flock` = robust against overlap even if a Blender render runs long.

### 5. Disk / cost cleanup
- Measured: history ~41 MB/episode (the 39 MB mp4 dominates), kids ~5.5 MB/episode → ~104 MB/week combined. **Nothing auto-deletes today** → indefinite growth (a 20 GB volume fills in ~months, faster with orphan failed-render mp4s).
- **Delivered `hindi-history/cleanup.py`** (tested): dry-run by default; `--delete` removes local media only for episodes that are `published` + have a `youtube_video_id` + are older than `--days` (default 14); never touches `data/*.json`; skips unparseable/`ready`/fresh episodes; logs to `logs/cleanup.log`. Add weekly after the monitor: `0 10 * * 1  .../.venv/bin/python cleanup.py --delete --days 14`.
- Not yet covered: orphan mp4/jpg from sanity-FAIL runs (item 1, P4) — recommend a follow-up sweep mode.

### 6. Full back-to-back dry run (measured on the 6-core dev box; real upload is EC2-pending)
| Phase | History — measured | Marginal cost | Notes |
|---|---|---|---|
| 1 Script | ~18 s | $0 (Gemini free tier; 1 request of ~20/day) | live, real key |
| 2 Voice | ~10 s (`--silent`) | $0 (2,944 chars vs 1M/mo free; ≈ $0.05 if paid) | real TTS pending creds |
| 3 Images | ~6 m 45 s (11 Pollinations + delays) | $0 (no key) | real, 1024×576 |
| 4 Assembly | ~3.5 m (1080p, ffmpeg `veryfast`) | $0 | real, drift 1.05 s, sanity PASS |
| 5 Publish | ~1 s (mock) | $0 (YouTube 1600/10k units/day) | real private upload pending token |
| **Total** | **~11 min active/episode** | **~$0 marginal** (all free-tier) | Kids: mock-only here (no Blender); Blender render time unknown on this box |

What needed a manual nudge: nothing in the happy path; the only manual step is credential provisioning. **Kids end-to-end couldn't run here** (Blender not installed) — mock publish is idempotent and correct.

### 7. Launch checklist — see below.

---

## Remaining (recommended before PUBLIC; not blocking a PRIVATE test)
- **medium:** status gate + `--force` on Phase 2/3 re-runs (prevent silent status regression / quota re-spend).
- **medium:** wrap credential/`SystemExit` around bogus-SA tracebacks (P2); incremental TTS usage recording.
- **medium:** `log.exception` in each phase's `main()` so failure reasons land in the phase log, not just stderr.
- **medium:** atomic queue writes (`os.replace` tmp) in generate_script `--out`, generate_voice, assemble_video.
- **medium/high (ops):** add `flock` to the kids crons; separate Gemini keys and GCP projects per channel; update DEPLOY.md cron to the real 16:30 kids time; make `flock` skips log.
- **low:** Pollinations connect-timeout param, dimension-mismatch warning, non-retryable-error classification in retries, FutureWarning suppression (Python 3.11+), commit `run_pipeline.sh`.

---

## LAUNCH CHECKLIST (tested → live public on schedule)

**A. Credentials / accounts (you, one-time)**
1. [ ] Separate **Gemini API key** for the history channel (its own GCP project) — stop sharing the kids key.
2. [ ] **Google Cloud service account** with Sheets API + Text-to-Speech API enabled + **billing on**; `scp` to `history-channel/service-account.json`; `chmod 600`.
3. [ ] **This channel's** YouTube OAuth: mint `YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN` against the *history* channel (browser consent once), store in `history-channel/.env`.
4. [ ] `HISTORY_SHEET_ID` + share the Sheet with the service-account email; run `generate_script.py --init`.
5. [ ] `TELEGRAM_HISTORY_BOT_TOKEN` + `_CHAT_ID` (distinct from kids).
6. [ ] Rotate the leaked Gemini key that was in `.env.example`.

**B. One real PRIVATE end-to-end on EC2 (before any schedule)**
7. [ ] Run §7 of DEPLOY.md: script → voice (real Hindi audio) → images → assembly → `orchestrator_history.js --privacy private`.
8. [ ] In YouTube Studio (history channel) confirm: on the **non-kids** channel · Hindi title/description/tags render correctly · **Made for kids = No** · custom thumbnail set · video **Private** · audio present & in sync.

**C. Instance / ops**
9. [ ] On EC2: `nproc; free -h; df -h` — confirm ≥ 4 vCPU / 16 GB / 20 GB free (size for Blender); upsize or split instances if short.
10. [ ] Add `flock -n /tmp/channel-render.lock ... || echo "skipped: lock held"` to **both** channels' render crons.
11. [ ] Install history crons (Tue/Sat build 11:00 + publish 14:00 UTC) with the `NODE_PATH`/`YOUTUBE_MCP_ROOT` publish line; commit `run_pipeline.sh`.
12. [ ] Install `monitor_summary.py` (weekly) and `cleanup.py --delete --days 14` (weekly).

**D. Go public (only after B passes for a few episodes)**
13. [ ] Flip `HISTORY_PUBLISH_PRIVACY=public` (or `--privacy public`), or leave `unlisted` for a soft launch.
14. [ ] Watch the first scheduled public run's log + Telegram summary; keep the kids channel on its own token/schedule.
