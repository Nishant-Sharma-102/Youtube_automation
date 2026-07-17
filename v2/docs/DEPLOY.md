# Phase 6 — Deploy on AWS EC2 (Ubuntu)

End-to-end setup to run the pipeline on an EC2 Ubuntu instance, triggered by cron at
**8 PM Mon/Wed/Fri/Sun**. Nothing secret lives in code — all keys are env vars.

## 1. Instance & system packages

A `t3.small`+ is fine for scripting/voice/publish. **Rendering (Phase 3) is heavy** —
if you render on EC2, use a larger instance (or a GPU instance) and expect long renders;
many creators render locally and only publish from EC2.

```bash
sudo apt update && sudo apt install -y git ffmpeg unzip
# Node 22 via nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc && nvm install 22
# Rhubarb Lip Sync (Phase 3) — download the Linux release, then:
#   unzip rhubarb-*.zip && sudo mv rhubarb-*/rhubarb /usr/local/bin/
# Blender headless (only if rendering on EC2):
#   sudo snap install blender --classic     # or download blender.org tarball
```

## 2. Get the code + install

```bash
git clone <your-repo> ~/giggle-grove        # or scp the project up
cd ~/giggle-grove/v2
npm install
```

## 3. Credentials (never in code)

```bash
cp .env.example .env
nano .env      # fill in every key
chmod 600 .env # readable only by you
```
Fill: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY` (+ `GOOGLE_TTS_API_KEY`),
`YOUTUBE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN`, and optionally `TELEGRAM_BOT_TOKEN`/`CHAT_ID`.
Keep `PUBLISH_PRIVACY=private` until you've confirmed a few episodes, then set `public`.

Initialize the queue: `npm run db:init`

## 4. Timezone (so "8 PM" means your 8 PM)

EC2 defaults to UTC. Either set the box timezone:
```bash
sudo timedatectl set-timezone Asia/Kolkata     # your zone
```
…or keep UTC and convert the cron hour yourself (8 PM IST = 14:30 UTC, etc.).

## 5. Cron — the 8 PM Mon/Wed/Fri/Sun trigger

```bash
chmod +x ~/giggle-grove/v2/scripts/cron-publish.sh
mkdir -p ~/giggle-grove/v2/logs
crontab -e
```
Add (edit the node path / `PROJECT_DIR` inside the script first):
```cron
# minute 0, hour 20 (8 PM), Mon(1) Wed(3) Fri(5) Sun(0) — server local time
0 20 * * 1,3,5,0  /home/ubuntu/giggle-grove/v2/scripts/cron-publish.sh >> /home/ubuntu/giggle-grove/v2/logs/publish.log 2>&1
```

**Upstream content** (script → voice → render) should run *before* 8 PM so an episode is
`ready`. Options: run `npm run generate`, `npm run voice`, and the Blender render on a
separate earlier cron (e.g. mornings), or prepare episodes manually. The 8 PM job only
publishes what's already `ready`.

## 6. Logging & debugging (no guessing)

- **`logs/publish.log`** — every cron run appends a timestamped block (job mode, each
  episode, the video URL or the error). `tail -f logs/publish.log`.
- Run the job by hand anytime: `cd ~/giggle-grove/v2 && ./scripts/cron-publish.sh`
- Dry-run (no upload): `npm run publish -- --dry-run`
- Confirm cron fired: `grep CRON /var/log/syslog`
- Rotate logs so they don't grow forever:
  ```
  sudo tee /etc/logrotate.d/giggle-grove >/dev/null <<'EOF'
  /home/ubuntu/giggle-grove/v2/logs/*.log { weekly rotate 8 compress missingok notifempty }
  EOF
  ```

## 7. Go-live checklist

1. `npm run db:init` — queue seeded
2. `npm run generate` → `npm run voice` → render (Phase 3) → episode is `ready`
3. `npm run publish -- --dry-run` — dry-run looks right
4. `./scripts/cron-publish.sh` once by hand → check `logs/publish.log` + YouTube Studio
5. Flip `PUBLISH_PRIVACY=public` in `.env` once quality is confirmed
6. Let cron take over
