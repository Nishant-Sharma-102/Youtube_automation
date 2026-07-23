# Documentary Channel — Hindi Documentary YouTube Automation

Automates a general-audience Hindi documentary YouTube channel end-to-end. Every
morning at **08:00 IST** the pipeline picks a topic, writes a fact-checked Hindi
script with Claude, narrates it in a **deep, warm, suspenseful** Hindi voice,
generates **multi-image cinematic visuals** with motion, scores it with **suspenseful**
Creative-Commons music, renders **1080p**, and publishes it **public** with **Hindi +
English captions** and reach-optimized hashtags. No human in the loop.

> This repo previously also ran a "Giggle Grove" kids pipeline. That has been retired —
> the project is now focused solely on the documentary/history channel. The old kids
> scripts were removed from automation (see git history if you ever need them).

## 📚 Documentation map

| Doc | Read it for |
|---|---|
| **[documentary/README.md](documentary/README.md)** | **Start here** — the pipeline: phases, config knobs, how to run each stage |
| [DOCKER.md](DOCKER.md) | Deploying the daily job on a server / EC2 (Docker + supercronic) |
| [JENKINS.md](JENKINS.md) | CI/CD pipeline: push → build → deploy, with GitHub webhook |

## 🎬 Daily auto-upload (quick reference)

Orchestrated by [scripts/cron-documentary.sh](scripts/cron-documentary.sh), which runs
the documentary phases in order:

```
generate_topics → gen_script → gen_storyboard → gen_voice → gen_visuals →
gen_music → assemble → gen_metadata → finalize → orchestrator_documentary.js (publish)
```

```bash
scripts/cron-documentary.sh     # produce + publish one episode now (full run)
```

Scheduled daily at **08:00 IST** — local crontab tag `# documentary-daily`, or the
Docker container's supercronic. It auto-refills topics, approves the next one, runs all
phases, auto-picks the v1 title/thumbnail, and publishes.

## 🖥️ Manual-trigger dashboard (Documentary + Hindi History)

Besides the daily cron, a lightweight dashboard lets you kick off a specific
topic/category on demand across both history channels. `docker compose up -d` starts it
on **http://<host>:8080** (service `documentary-dashboard`). Run it locally with:

```bash
documentary/.venv/bin/python dashboard.py     # binds 0.0.0.0:8080
```

Served by [dashboard.py](dashboard.py) (Python stdlib, no extra deps):
- **Channel selector** (Documentary / Hindi History) + per-channel **category** dropdown
  or a free-text **topic**.
- **Review vs Fast** mode — Fast always uploads **PRIVATE** (never public).
- **Serial job queue** (one run at a time) with a **live status** table.

Documentary jobs insert an approved topic and run [scripts/run-pipeline.sh](scripts/run-pipeline.sh);
Hindi History jobs run [hindi-history/make_episode.sh](hindi-history/make_episode.sh). A
shared flock keeps manual runs and the 8 AM cron from overlapping. Access is open by
default — restrict the port to your IP or set `DASHBOARD_TOKEN` for a password.

## ⚙️ Key config (in `documentary/.env`)

| Knob | Purpose |
|---|---|
| `YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN` | this channel's upload + captions token |
| `DOC_NARRATION_LANGUAGE` / `DOC_LANGUAGE_CODE` | narration language (Hindi / `hi`) |
| `DOC_EDGE_VOICE` / `DOC_EDGE_PITCH` / `DOC_EDGE_RATE` | deep, warm, suspenseful voice |
| `DOC_MUSIC_MOOD` | `suspense` — mood-matched background score |
| `DOC_CAPTION_LANGUAGES` | extra caption tracks to translate + upload (e.g. `en`) |
| `DOC_IMAGES_PER_SCENE_MAX` / `DOC_IMAGES_PER_SCENE_SEC` | multi-image visual density |
| `DOC_BASE_HASHTAGS` | evergreen hashtags merged into every upload for reach |
| `DOC_VISUALS_PROVIDER` | `mock` (free stills+motion), `kling` (paid animation) |
| `DOC_FFMPEG` | ffmpeg binary (host: bundled static; container: system `ffmpeg`) |

See [documentary/README.md](documentary/README.md) for the full list and per-phase detail.

> ⚠️ **Channel note:** the kids, history, and documentary pipelines have all historically
> published to the same YouTube channel ("Minimagictvvv"); which channel a run targets is
> decided by the OAuth account behind its refresh token. Verify the target before a bulk
> operation.
