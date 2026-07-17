# Phase 6 — Deploying the History channel alongside the Kids channel (one EC2)

Goal: run this pipeline on the same EC2 as the existing kids-animation pipeline
**without the two touching each other's credentials, Sheet, logs, or render slots.**

> ⚠️ **This guide was written on a dev box, not your EC2** (no EC2 metadata, Blender not
> installed here). The specs in §5 are commands for *you* to run on the instance. The
> real end-to-end publish (§7) needs credentials that aren't in the dev environment
> (Google Cloud TTS service account, this channel's YouTube refresh token, Sheet access),
> so it's a runbook you execute on EC2 — I verified everything reachable in mock mode.

---

## 1. Folder structure (clean separation)

```
/home/ubuntu/
├── kids-channel/            # existing pipeline (TypeScript, Blender). UNCHANGED.
│   ├── .env                 # kids secrets only
│   ├── src/mcp/youtube-server.ts   # the shared YouTube MCP server (reused, not copied)
│   ├── data/content-queue.db
│   └── logs/
└── history-channel/         # THIS pipeline (Python + one Node orchestrator)
    ├── .env                 # history secrets only — never references kids vars
    ├── .venv/
    ├── *.py                 # generate_script / generate_voice / generate_images / assemble_video
    ├── orchestrator_history.js
    ├── monitor_summary.py
    ├── service-account.json # chmod 600, git-ignored
    ├── data/  audio/  images/  renders/
    └── logs/                # this channel's logs ONLY
```

The two are separate directories with separate `.env` files, so a bug or a bad path in
one can't read the other's secrets or Sheet. The **one** shared component is the kids
channel's YouTube MCP server (your "reuse, don't rebuild" requirement): the history
orchestrator points at it via `YOUTUBE_MCP_ROOT=/home/ubuntu/kids-channel` and injects
its **own** token into the spawned process — see §2.

---

## 2. Environment variables — full inventory + overlap audit

Put these in `history-channel/.env` **only**. Column "vs kids" flags any collision.

| Variable | Purpose | vs kids channel |
|---|---|---|
| `GEMINI_API_KEY` | Phase 1 script generation | ⚠️ **same name — use a DIFFERENT key** (see risk below) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | same value fine (not a secret) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Sheets + Cloud TTS auth (Phase 2, Sheet R/W) | history's **own** service account |
| `GOOGLE_OAUTH_CLIENT_JSON` / `GOOGLE_OAUTH_TOKEN_JSON` | alt. to service account for Sheets+TTS | history only |
| `HISTORY_SHEET_ID` / `HISTORY_WORKSHEET` | this channel's queue tab | history only |
| `HISTORY_TTS_VOICE` | `hi-IN-Wavenet-A` | history only |
| `HISTORY_IMAGE_STYLE` / `HISTORY_CAPTION_FONT` | Phase 3/4 look | history only |
| `YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN` | **this channel's** YouTube token | ✅ distinct name; kids uses `YOUTUBE_REFRESH_TOKEN` |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` | OAuth *app* for the MCP server | may be the same app; the **token** is what differs per channel |
| `YOUTUBE_MCP_ROOT` | path to the kids channel dir (for the shared server) | points AT kids, by design |
| `HISTORY_PUBLISH_PRIVACY` | default `private` | history only |
| `TELEGRAM_HISTORY_BOT_TOKEN` / `TELEGRAM_HISTORY_CHAT_ID` | History-labelled notifications | ✅ distinct from kids `TELEGRAM_*` |
| _Pollinations.ai_ | Phase 3 images | **no key required** (anonymous) |

**No variable *name* overlaps** except `GEMINI_API_KEY` and the YouTube OAuth *app* id/secret.
Because each channel loads only its own `.env`, values stay isolated at runtime. The
orchestrator additionally **overrides** `YOUTUBE_REFRESH_TOKEN` in the spawned MCP
server with the history token, so the kids token is structurally unable to reach it.

> ⚠️ **Risk — the Gemini key is currently shared.** Both channels using one
> `GEMINI_API_KEY` means (a) they draw on the *same* free-tier quota (only ~20
> `gemini-2.5-flash` requests/day — they already collided during testing), and (b) a
> compromised key exposes both. **Create a separate Google AI Studio key/project for
> the history channel.**

---

## 3. Getting credentials onto EC2 securely

```bash
# From your laptop — copy the service-account key to the history dir:
scp ./history-service-account.json ubuntu@<ec2-host>:/home/ubuntu/history-channel/service-account.json

# On EC2 — lock down permissions (owner read/write only):
chmod 600 /home/ubuntu/history-channel/service-account.json
chmod 600 /home/ubuntu/history-channel/.env

# Confirm secrets are git-ignored (they already are in this project's .gitignore):
cd /home/ubuntu/history-channel
grep -E 'service-account.json|token.json|oauth-client.json|\.env$' .gitignore
git check-ignore service-account.json .env token.json 2>/dev/null   # each should echo back
```

Never commit `.env`, `service-account.json`, `oauth-client.json`, or `token.json`.
`.env.example` is the only env file that's committed — it must contain **placeholders only**.

---

## 4. Cron — separate schedule + separate log

`crontab -e` (times in UTC via `TZ=UTC`; flock prevents any render overlap between channels):

```cron
TZ=UTC

# ── Kids channel (existing) — Mon/Wed/Fri/Sun 20:00 UTC ──
0 20 * * 1,3,5,0  flock -n /tmp/channel-render.lock /home/ubuntu/kids-channel/scripts/cron-publish.sh >> /var/log/kids-channel-publish.log 2>&1

# ── History channel — Tue/Sat ──
# Build the next episode a few hours ahead of publish (script→voice→images→video):
0 11 * * 2,6  flock -n /tmp/channel-render.lock /home/ubuntu/history-channel/run_pipeline.sh >> /var/log/history-channel-build.log 2>&1
# Publish the 'ready' episode at 14:00 UTC (7:30 PM IST). Node (not the Python venv);
# NODE_PATH lets the orchestrator resolve its deps + reuse the kids channel's MCP server.
0 14 * * 2,6  NODE_PATH=/home/ubuntu/kids-channel/node_modules YOUTUBE_MCP_ROOT=/home/ubuntu/kids-channel node /home/ubuntu/history-channel/orchestrator_history.js >> /var/log/history-channel-publish.log 2>&1

# ── Weekly health summary (both channels, one message) ──
0 9 * * 1  /home/ubuntu/history-channel/.venv/bin/python /home/ubuntu/history-channel/monitor_summary.py >> /var/log/channel-monitor.log 2>&1
```

- **Distinct days** (History Tue/Sat vs Kids Mon/Wed/Fri/Sun) → they never publish the
  same day. **Distinct log files** per channel so debugging one never means reading the other.
- The **shared `flock`** on the render commands is the key safety net: even if schedules
  are ever edited to overlap, only one heavy render runs at a time (`-n` = skip if locked;
  the skipped one runs next cycle). Publish (light) isn't locked.
- `run_pipeline.sh` is a thin wrapper you add: `generate_script.py && generate_voice.py
  --episode N && generate_images.py --episode N && assemble_video.py --episode N`.

---

## 5. Instance sizing — Blender (kids) + MoviePy/ffmpeg (history) on one box

Run on the **actual EC2** to see what you have:
```bash
nproc; free -h; df -h /; uptime          # cores, RAM, free disk, load
curl -s http://169.254.169.254/latest/meta-data/instance-type   # e.g. t3.large
```

What the workloads need:
- **Kids/Blender headless** is the heavy one — CPU-bound, can peak all cores and several GB
  RAM per render; complex scenes want 8+ vCPU.
- **History/ffmpeg x264 1080p** (Phase 4) is moderate — the Rome episode encoded ~4.5 min
  of 1080p in a couple of minutes at `veryfast` on 6 cores; needs ~1–2 GB RAM + a few GB
  scratch disk per render.
- **Disk:** each history episode is ~40 MB video + images/audio; trivial. Blender project
  assets dominate. 20–30 GB free is a comfortable floor.

**Recommendation:** one instance is fine **if** (a) it's sized for the *Blender* job (the
bottleneck), and (b) you keep the `flock` guard so the two renders never run concurrently.
A `t3.large` (2 vCPU/8 GB) will struggle with Blender; **`t3.xlarge`/`c5.2xlarge` (4–8
vCPU, 16 GB)** is a reasonable starting target — but confirm against your Blender scene
complexity. If cadence grows or you want renders to run in parallel, **split onto two
instances** (or move rendering to a queue), rather than risk one render starving the
other's cron trigger. Add `nice -n 10` / `ionice -c2 -n7` to the render commands to keep
the box responsive.

---

## 6. Monitoring (`monitor_summary.py`)

Weekly (cron above) it posts **one** Telegram message covering *both* channels: History's
last publish + whether it published in the last 7 days + any recent `FATAL`, and the Kids
channel's latest published episode (read read-only from its SQLite queue via
`KIDS_CHANNEL_DIR`). Uses the History Telegram creds; prints to the log if they're unset.
One glance answers "did either channel actually publish this week?"

---

## 7. Full manual dry-run on EC2 (one episode, PRIVATE)

Prerequisites in place first: `history-channel/.env` filled, `service-account.json`
(chmod 600), Sheets API + Cloud TTS API enabled + billing on, and
`YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN` minted for **this** channel.

**Node deps for the orchestrator** — it needs `@modelcontextprotocol/sdk`, `googleapis`,
`google-auth-library`, and the reused MCP server. Either reuse the kids channel's
`node_modules` (as the cron above does, via `NODE_PATH` + `YOUTUBE_MCP_ROOT`), or give
the history dir its own: `cd history-channel && npm init -y && npm install
@modelcontextprotocol/sdk googleapis google-auth-library tsx` (and set
`YOUTUBE_MCP_ROOT=/home/ubuntu/kids-channel` so it still spawns the shared server).

```bash
cd /home/ubuntu/history-channel && source .venv/bin/activate

# Phase 1-4 for one topic (seed the Sheet row's topic, or use --topic):
python generate_script.py                       # draft → script_ready
python generate_voice.py                         # → audio_ready (real Hindi TTS)
python generate_images.py                        # → images_ready
python assemble_video.py                         # → ready (renders/epN.mp4 + .jpg)

# Phase 5 — publish PRIVATE first (real upload, this channel's token):
node orchestrator_history.js --privacy private
```

Then confirm in **YouTube Studio for the history channel** (the log prints the
`video_id`, the URL, `made_for_kids=false`, `privacy=private`, and the channel's most
recent upload so you can eyeball it landed on the *right* channel):
- ✅ it's on the **non-kids** channel
- ✅ title / description / tags are the Hindi values, rendering correctly
- ✅ **Made for kids = No**
- ✅ custom thumbnail set
- ✅ video is **Private**

Only after all five check out, flip to public (`--privacy public`, or YouTube Studio).

> Mock any time without credentials: `node orchestrator_history.js --dry-run --file data/ep1.json`.

---

## Standing risk flags (don't assume these are fine)

1. **Shared Gemini key** — separate it per channel (quota + blast radius). §2.
2. **Two heavy renders, one box** — safe only with the `flock` guard + right sizing; else split instances. §5.
3. **Real E2E is unverified in dev** — no TTS/YouTube/Sheets creds here; §7 is the runbook to prove it on EC2. Audio is still the silent placeholder until the TTS service account is added (Phase 2).
4. **Publish defaults to PRIVATE** and refuses to run live without this channel's token — keep it private until §7's five checks pass.
