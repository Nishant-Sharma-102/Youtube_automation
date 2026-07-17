# Giggle Grove — Project Documentation

A fully MCP-based automation pipeline for a kids animation YouTube channel. It
generates episode scripts + SEO metadata with Gemini, stores them in a local
database, generates subtitles, and publishes videos to YouTube through a custom
Model Context Protocol (MCP) server — all runnable on a cron schedule.

> **What the system does NOT do:** create the animated video itself. That creative
> step is manual (see [PRODUCTION_WORKFLOW.md](PRODUCTION_WORKFLOW.md)). Everything
> before and after — scripting, metadata, captions, uploading, scheduling — is automated.

---

## 1. Big picture

```
                 CONTENT GENERATION                        PUBLISHING
   ┌───────────────────────────────────┐   ┌──────────────────────────────────────┐
   │ calendar + character bible         │   │ orchestrator (MCP client)            │
   │        │                           │   │        │                             │
   │        ▼                           │   │        ▼                             │
   │  Gemini 2.5 Flash ── script        │   │  YouTube MCP server ── upload_video  │
   │                  └─ metadata       │   │  (custom, Data API v3) ├ set_thumbnail│
   │        │                           │   │                        ├ set_captions │
   │        ▼                           │   │                        └ get_status…  │
   │   content_queue (SQLite)  ─────────┼───┼──▶ reads 'ready' rows ──▶ YouTube      │
   └───────────────────────────────────┘   └──────────────────────────────────────┘
              status: draft ─▶ script_ready ─▶ ready ─▶ published
```

The **content queue** (a SQLite table) is the backbone. Every episode is one row that
moves through four states:

| Status | Meaning | Set by |
|--------|---------|--------|
| `draft` | seeded from the calendar, nothing generated yet | `db:init` |
| `script_ready` | script + metadata generated | `generate` |
| `ready` | a rendered video file is attached (animator handoff) | `attachRender()` |
| `published` | uploaded to YouTube | `publish` |

---

## 2. Requirements & install

- **Node.js 22+**
- A **Gemini API key** (free tier, Google AI Studio) — for generation
- A **Google Cloud OAuth client** with YouTube Data API v3 — for publishing

```bash
npm install
cp .env.example .env      # then fill in real values in .env
npm run db:init           # create the DB + seed the 17-episode calendar
```

### Environment variables (`.env`)

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Gemini key (not needed for `--dry-run`) |
| `GEMINI_MODEL` | default `gemini-2.5-flash` |
| `DB_DRIVER` / `DB_PATH` | SQLite by default (`./data/content-queue.db`) |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` | from your Google Cloud OAuth client |
| `YOUTUBE_REFRESH_TOKEN` | obtained via `npm run youtube:auth` |
| `YOUTUBE_REDIRECT_URI` | default `http://localhost:5757/oauth2callback` |
| `YOUTUBE_MOCK` | `1` = mock (no real upload); `0` = live |
| `PUBLISH_PRIVACY` | optional default privacy (`public`/`unlisted`/`private`) |
| `PUBLISH_CAPTIONS` | optional; `1` = always upload captions |

> ⚠️ **Never put real secrets in `.env.example`** — it's a template. Only `.env` is
> git-ignored.

---

## 3. Commands reference

### Generate scripts + metadata
```bash
npm run generate                 # next draft episode
npm run generate -- --week       # one week's uploads (next 4 drafts)
npm run generate -- --video 3    # a specific episode
npm run generate -- --all        # every remaining draft
npm run generate -- --limit 4    # cap the batch (stay under daily free-tier quota)
npm run generate -- --dry-run    # no API key; canned output for testing
```

### Generate captions (SRT)
```bash
npm run captions -- --video 3    # write captions/ep3.en.srt from the script
npm run captions -- --all
```

### Publish to YouTube
```bash
npm run publish                       # 'ready' rows scheduled on/before today
npm run publish -- --video 1          # a specific ready episode
npm run publish -- --all              # every ready row, ignoring schedule
npm run publish -- --privacy unlisted # safe first publish (private/unlisted/public)
npm run publish -- --captions         # also generate + upload subtitles
npm run publish -- --dry-run          # force MOCK mode (no real upload)
```

### YouTube auth (one-time)
```bash
npm run youtube:auth       # browser consent flow → prints YOUTUBE_REFRESH_TOKEN
```

### Utilities
```bash
npm run db:init                    # create/seed DB (idempotent)
npm run db:init -- --launch=2026-08-03   # set the launch Monday (scheduled dates)
npm run youtube:server             # run the YouTube MCP server standalone
npm run typecheck                  # tsc --noEmit
```

### Attach a rendered video (animator handoff: script_ready → ready)
```bash
node --import tsx -e "import{loadConfig}from'./src/config.ts';import{createRepo}from'./src/db/index.ts';const r=createRepo(loadConfig());r.attachRender(1,'renders/ep1.mp4','renders/ep1.jpg');r.close()"
```

---

## 4. Code map

| Area | Path | What it does |
|------|------|--------------|
| Calendar | [`data/calendar.ts`](../data/calendar.ts) | 17-episode schedule (topic, format, date offset) |
| Character bible | [`data/character-bible.ts`](../data/character-bible.ts) | channel + Milo/Lulu + sign-off; edit to rebrand |
| Config | [`src/config.ts`](../src/config.ts) | loads/validates `.env` |
| Logging | [`src/logger.ts`](../src/logger.ts) | console + `logs/generate.log` |
| Retry | [`src/retry.ts`](../src/retry.ts) | exponential backoff; skips non-retryable errors |
| Types | [`src/types.ts`](../src/types.ts) | `ContentRow`, `Status`, result types |
| DB interface | [`src/db/repo.ts`](../src/db/repo.ts) | `ContentQueueRepo` — swap-able storage seam |
| DB (SQLite) | [`src/db/sqlite-repo.ts`](../src/db/sqlite-repo.ts) | implementation + auto-migration |
| DB schema | [`src/db/schema.sql`](../src/db/schema.sql) | `content_queue` table |
| Generation | [`src/generate.ts`](../src/generate.ts) | the generation orchestrator (CLI) |
| Generators | [`src/generator.ts`](../src/generator.ts) | Gemini + dry-run implementations |
| Gemini client | [`src/gemini/client.ts`](../src/gemini/client.ts) | wraps `@google/genai`; retry-aware |
| Prompts | [`src/gemini/*-prompt.ts`](../src/gemini/) | script + SEO metadata prompts |
| YouTube auth | [`src/mcp/youtube-auth.ts`](../src/mcp/youtube-auth.ts) | OAuth2 client + scopes |
| Token helper | [`src/mcp/get-refresh-token.ts`](../src/mcp/get-refresh-token.ts) | one-time refresh-token flow |
| YouTube service | [`src/mcp/youtube-service.ts`](../src/mcp/youtube-service.ts) | Data API v3 calls (real + mock) |
| **YouTube MCP server** | [`src/mcp/youtube-server.ts`](../src/mcp/youtube-server.ts) | exposes upload/thumbnail/captions/status/list tools |
| **Publish orchestrator** | [`src/orchestrate/publish.ts`](../src/orchestrate/publish.ts) | MCP client; drives the publish flow |
| Publish schedule | [`src/publish-config.ts`](../src/publish-config.ts) | 11:00 UTC M/W/F/Sun + cron string |
| Captions | [`src/captions/srt.ts`](../src/captions/srt.ts) | screenplay → SRT (estimated timing) |
| Cron scripts | [`scripts/`](../scripts/) | `cron-generate.sh`, `cron-publish.sh` |

---

## 5. The custom YouTube MCP server

Wraps YouTube Data API v3 and exposes these MCP tools (over stdio):

| Tool | Args | Returns | Scope needed |
|------|------|---------|--------------|
| `upload_video` | file_path, title, description, tags, made_for_kids, privacy_status, category_id, language | `{ videoId }` | `youtube.upload` |
| `set_thumbnail` | video_id, thumbnail_path | `{ ok }` | `youtube.upload` |
| `set_captions` | video_id, srt_path, language | `{ ok }` | `youtube.force-ssl` |
| `get_upload_status` | video_id | `{ uploadStatus, processingStatus }` | `youtube.force-ssl` |
| `list_recent_uploads` | limit | `{ uploads[] }` | `youtube.force-ssl` |

Uploads default to `made_for_kids: true`, category `27` (Education), language `en`,
resumable upload. **Mock mode** (`YOUTUBE_MOCK=1`) validates file existence and returns
fake ids so the whole pipeline is testable with no credentials.

The **orchestrator** ([`publish.ts`](../src/orchestrate/publish.ts)) is an MCP *client*:
it spawns the server as a subprocess, finds `ready` rows, and calls the tools. This is
the brief's "pure-MCP, no n8n" design.

---

## 6. Automation (cron)

Two jobs are installed in the user's crontab (tags in comments):

| Job | Schedule | Script | Purpose |
|-----|----------|--------|---------|
| `giggle-grove-generate` | `0 13 * * *` (1 PM IST daily) | `scripts/cron-generate.sh` | backfill scripts under the daily Gemini quota |
| `giggle-grove-publish` | `30 16 * * 1,3,5,0` (4:30 PM IST = 11:00 UTC, M/W/F/Sun) | `scripts/cron-publish.sh` | publish `ready` episodes at the optimal time |

Manage with `crontab -l` / `crontab -e`. Logs: `logs/cron-generate.log`,
`logs/cron-publish.log`.

**Why 11:00 UTC to publish?** Optimized for a global/US kids audience (7 AM US Eastern,
~2 h before the morning viewing peak). See [`src/publish-config.ts`](../src/publish-config.ts).

---

## 7. Reliability & safety features

- **Idempotency** — publishing skips rows that already have a `youtube_video_id`;
  generation skips non-`draft` rows. Re-runs are safe.
- **Quota-aware retry** — transient errors (503) retry with backoff; daily-quota
  errors (429/RESOURCE_EXHAUSTED) fail fast so they don't burn more quota.
- **Warn, don't fail silently** — an empty queue logs a warning instead of erroring.
- **Mock modes** — `--dry-run` (generation and publishing) exercise the full flow with
  no API calls / no uploads.
- **Swap-able DB** — all storage goes through `ContentQueueRepo`; add a Postgres/MySQL
  implementation without touching business logic.

---

## 8. Free-tier limits to know

- **Gemini free tier:** ~20 requests/day for `gemini-2.5-flash`. Each episode = 2
  requests. Generate ≤ ~8 episodes/day (use `--week` or `--limit`).
- **Made for Kids policy (YouTube):** disables comments, personalized ads, end screens,
  cards, and the notification bell — and lowers RPM. This is policy, not a setting.
- **Custom thumbnails** require a phone-verified YouTube account.

---

## 9. Related docs

- [PRODUCTION_WORKFLOW.md](PRODUCTION_WORKFLOW.md) — how to make the actual video
  (script → voice → animation → publish), in plain language.
- [../README.md](../README.md) — quick-start version of this document.
