# Giggle Grove — Automated Kids Animation Pipeline (v2)

Clean rebuild. Topic → script → voice → animation render → YouTube, on a SQLite queue.

## Pipeline

```
db:init → generate → voice → render(Blender) → attach → publish
 (seed)   (Phase 1)  (Ph 2)   (Phase 3)         (→ready)  (Phase 5, cron 8PM)
```

| Phase | Command | What it does | Tested |
|---|---|---|---|
| 1 Content | `npm run generate` | Gemini 2.5 Flash (Claude fallback) → 5–8 min script + 3 metadata variants → `script_ready` | ✅ live |
| 2 Voice | `npm run voice` | ElevenLabs → Google TTS fallback; chunking + budget; `audio/epN.mp3` | ✅ live |
| 3 Render | `blender --background --python scripts/render_episode.py -- --episode N --character … --audio … --clip …` | Rhubarb visemes + Mixamo body + explicit AAC mux → `renders/epN.mp4` → `attach` | ⚠️ runs on your machine (needs Blender) |
| 3b Attach | `npm run attach -- --video N` | stream-guard (video+audible audio) → `ready` | ✅ live |
| 4 YouTube MCP | `npm run youtube:server` | MCP server: `upload_video`/`set_thumbnail`/`get_upload_status`/`list_recent_uploads` | ✅ live |
| 5 Publish | `npm run publish [-- --video N] [--privacy …]` | MCP client: ready → upload → thumbnail → `published`; retry/backoff; double-publish guard; notify | ✅ live |
| 6 Deploy | see `docs/DEPLOY.md` | EC2 setup + cron `0 20 * * 1,3,5,0` + logging | ✅ validated |

## Setup

```bash
npm install
cp .env.example .env   # or reuse ../.env — fill keys, never hardcode
npm run db:init
```

## Key facts
- **Queue:** SQLite (`data/queue.db`), columns mirror the brief's Sheet.
- **Fallbacks:** Gemini→Claude (text), ElevenLabs→Google TTS (voice).
- **Safety:** audio-stream guard before `ready`; test uploads default **private**; double-publish guard.
- **Character/rig:** Milo + Oculus visemes (see `../docs/CHARACTER_AND_RIG.md`); Blender render is the one step that needs your machine + a rigged FBX.

Deploy: `docs/DEPLOY.md`. Render details: `scripts/render_episode.py`.
