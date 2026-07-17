# Giggle Grove — Kids YouTube Automation

Automates a "Made for Kids" YouTube channel end-to-end. The repo contains **two
systems** that share a character bible and a YouTube channel:

1. **🎬 Daily rhyme auto-upload (fully automated, live).** Every morning it writes a
   rhyme with Claude, narrates it with **ElevenLabs**, illustrates 8 scenes, renders a
   **1080p** video, and publishes it **public** — then adds it to a playlist. No human
   in the loop. This is the system deployed via Docker/Jenkins.
2. **📝 Content-generation stage (TS).** Uses **Gemini** to write episode scripts +
   metadata into a database and mark them `script_ready` for a separate animator
   (Blender) handoff. This is the original upstream stage.

> ⚠️ **One channel, two pipelines.** Both publish to the *same* YouTube channel. Any
> bulk operation (e.g. deleting videos) affects both — always list before you delete.

## 📚 Documentation map

| Doc | Read it for |
|---|---|
| **[DOCS.md](DOCS.md)** | **Start here** — the daily rhyme system: architecture, stages, config, ops |
| [DOCKER.md](DOCKER.md) | Deploying the daily job on a server / EC2 (Docker + supercronic) |
| [JENKINS.md](JENKINS.md) | CI/CD pipeline: push → build → deploy, with GitHub webhook |
| [docs/PROJECT_DOCS.md](docs/PROJECT_DOCS.md) · [PRODUCTION_WORKFLOW.md](docs/PRODUCTION_WORKFLOW.md) · [ANIMATION_GUIDE.md](docs/ANIMATION_GUIDE.md) · [PHASE3_RENDER.md](docs/PHASE3_RENDER.md) · [CHARACTER_AND_RIG.md](docs/CHARACTER_AND_RIG.md) | The TS content-generation stage + Blender animation path |

## 🎬 Daily rhyme auto-upload (quick reference)

Orchestrated by [scripts/cron-kids-rhyme.sh](scripts/cron-kids-rhyme.sh) →
`gen_kids_rhyme.py` → `generate_voice.py` (ElevenLabs) → `generate_images.py` →
`assemble_video.py` → `kids_upload.mjs`. Topics rotate through
[scripts/topics-kids.txt](scripts/topics-kids.txt).

```bash
scripts/cron-kids-rhyme.sh              # produce + upload one episode now
DRY_RUN=1 scripts/cron-kids-rhyme.sh    # plan only (topic + episode #), no cost
```

Scheduled daily at **08:00 IST** (local crontab tag `# giggle-grove-kids-rhyme`, or the
Docker container's supercronic). Full details, config knobs, and troubleshooting are in
**[DOCS.md](DOCS.md)**.

---

# Content-generation stage (Gemini scripts & metadata)

The **upstream content-generation stage** of the Kids Animation Channel pipeline
(project brief Section 5). Given a topic from the content calendar plus a fixed
character bible, it uses **Gemini 2.5 Flash** to write the episode script and the
YouTube metadata, then stores them in a local database and marks the episode
`script_ready` for the animator.

## Channel & cast (starter — edit freely)

Defined in [`data/character-bible.ts`](data/character-bible.ts):

- **Channel:** Giggle Grove
- **Milo** — energetic fox cub · "Let's find out!"
- **Lulu** — wise owl · "Great thinking!"
- Every episode ends with the **"Giggle Grove Goodbye"** song.

Change the channel name, characters, or sign-off in that one file and every future
generated script follows the new bible.

## Setup

Requires Node 22+.

```bash
npm install
cp .env.example .env      # then edit .env
```

Set in `.env`:

- `GEMINI_API_KEY` — free-tier key from https://aistudio.google.com/app/apikey
  (not needed for `--dry-run`).
- `GEMINI_MODEL` — defaults to `gemini-2.5-flash`.
- `DB_DRIVER` / `DB_PATH` — defaults to SQLite at `./data/content-queue.db`.

## Usage

```bash
# 1. Create the DB and seed the 17-episode calendar (idempotent).
npm run db:init
npm run db:init -- --launch=2026-08-03   # optional: set the launch Monday

# 2. Generate scripts + metadata.
npm run generate                 # next draft episode
npm run generate -- --week       # one week's uploads: the next 4 drafts
npm run generate -- --video 3    # a specific episode
npm run generate -- --all        # every remaining draft
npm run generate -- --limit 4    # cap the batch (stay under the daily free-tier quota)
npm run generate -- --dry-run    # no API key — canned output to test the flow
```

**Cadence:** the channel publishes **4 videos/week** (Mon/Wed/Fri/Sun), each a **3–4
minute** episode. Generate one week at a time with `--week` — 4 episodes = 8 Gemini
requests, comfortably under the free-tier daily cap.

**Publish schedule (for the upcoming publishing stage):** defined in
[`src/publish-config.ts`](src/publish-config.ts) — **11:00 UTC** on Mon/Wed/Fri/Sun
(= 7 AM US Eastern / 4:30 PM IST), optimized for a global/US kids audience. The
publishing orchestrator (not built yet) will read the schedule from that file.

## Publishing (YouTube)

The publishing stage uploads rendered episodes to YouTube via a **custom MCP server**
driven by an orchestrator (MCP client). It runs in **mock mode** until real
credentials + video files exist — so the whole flow is testable now.

### Pipeline handoff

`script_ready` → (animator renders the video) → **attach the render** → `ready` →
(orchestrator uploads) → `published`.

Attach a render (animator handoff) with the repo's `attachRender(videoNumber,
videoFilePath, thumbnailPath?)`, which moves the row to `ready`.

### One-time YouTube setup

1. In Google Cloud: enable **YouTube Data API v3**, create an **OAuth 2.0 client**
   (Desktop app), and add `http://localhost:5757/oauth2callback` as an authorized
   redirect URI. Put the client id/secret in `.env`.
2. Get a refresh token (opens a browser consent flow):
   ```bash
   npm run youtube:auth
   ```
   Copy the printed `YOUTUBE_REFRESH_TOKEN=...` into `.env`, then set `YOUTUBE_MOCK=0`.

### Usage

```bash
npm run publish                 # publish 'ready' rows scheduled on/before today
npm run publish -- --video 3    # a specific ready episode
npm run publish -- --all        # every ready row, ignoring schedule
npm run publish -- --dry-run    # force MOCK mode (no real upload)
```

Uploads are `made_for_kids: true` and `public`. The job is idempotent (skips rows
that already have a `youtube_video_id`), retries transient failures, and logs to
`logs/generate.log`. The MCP server can also be run standalone: `npm run youtube:server`.

## Automation

- **Generation backfill (installed):** `scripts/cron-generate.sh` runs daily at
  1:00 PM IST (crontab tag `# giggle-grove-generate`) to fill the catalog under the
  free-tier quota. Logs to `logs/cron-generate.log`. Remove via `crontab -e` once the
  catalog is complete.
- **Publishing schedule:** `src/publish-config.ts` holds the target time
  (**11:00 UTC** Mon/Wed/Fri/Sun = 7 AM US Eastern) and a ready-to-use cron line
  `PUBLISH_CRON_UTC`. To activate once credentials are live, add a cron entry running
  `npm run publish` — best with `TZ=UTC` so the schedule matches. Not installed yet
  (nothing to publish until real renders exist).

Each run: picks draft episode(s) → Gemini writes the script → Gemini writes
title/description/tags/thumbnail text → saves to the DB and flips the row to
`script_ready`. Already-generated rows are skipped (idempotent). Logs go to the
console and `logs/generate.log`.

## Data model

`content_queue` (see [`src/db/schema.sql`](src/db/schema.sql)) — one row per video:
`video_number, topic, format, scheduled_date, status, title, description, tags,
thumbnail_text, script`. Status flows `draft → script_ready → ready → published`;
this stage owns the `draft → script_ready` transition.

## Architecture

| Concern            | File                                                        |
| ------------------ | ----------------------------------------------------------- |
| Content calendar   | [`data/calendar.ts`](data/calendar.ts)                      |
| Character bible    | [`data/character-bible.ts`](data/character-bible.ts)        |
| Config / env       | [`src/config.ts`](src/config.ts)                            |
| DB seam (swap-able)| [`src/db/repo.ts`](src/db/repo.ts) · [`sqlite-repo.ts`](src/db/sqlite-repo.ts) |
| Gemini client      | [`src/gemini/client.ts`](src/gemini/client.ts)              |
| Prompts            | [`src/gemini/script-prompt.ts`](src/gemini/script-prompt.ts) · [`metadata-prompt.ts`](src/gemini/metadata-prompt.ts) |
| Generators         | [`src/generator.ts`](src/generator.ts) (Gemini + dry-run)   |
| Orchestrator (CLI) | [`src/generate.ts`](src/generate.ts)                        |

The database is accessed only through the `ContentQueueRepo` interface, so swapping
SQLite for Postgres/MySQL later is a single new implementation in `src/db/` — no
changes to the generation logic. The retry/backoff helper
([`src/retry.ts`](src/retry.ts)) is shared and carries forward to the future
publish orchestrator.
# Youtube_automation
# Youtube_automation
# Youtube_automation
# Youtube_automation
