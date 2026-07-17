# Deploying the daily kids-rhyme auto-upload on EC2 (Docker)

This containerizes the full pipeline — **generate rhyme → ElevenLabs voice → 1080p
render → public upload → add to "Giggle Grove Rhymes" playlist** — and runs it every
morning at **08:00 IST** via an in-container scheduler (supercronic).

Secrets are **never** baked into the image. You mount your `.env` files (and, if used,
the Google service-account JSON) at runtime.

## 1. Launch an EC2 instance

- **AMI:** Amazon Linux 2023 or Ubuntu 22.04+
- **Type:** `t3.small` (2 GB RAM) is enough; ffmpeg encoding is brief. `t3.micro` works
  but is tight.
- **Storage:** 20 GB gp3.
- **Security group:** no inbound ports needed (outbound only — it just calls APIs).

Install Docker:

```bash
# Amazon Linux 2023
sudo dnf install -y docker git && sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user   # re-login after this
# (Ubuntu: sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git)
```

## 2. Get the code + secrets onto the instance

```bash
git clone <your-repo> agentic_ai && cd agentic_ai   # or scp the project up
```

Create the two secret files (they are git-ignored and docker-ignored):

- `./.env` — must contain: `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`,
  `ELEVENLABS_MODEL`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`,
  `YOUTUBE_MOCK=0`, `GEMINI_API_KEY`.
- `./hindi-history/.env` — history-side settings (only needed if you use the Google TTS
  fallback; ElevenLabs is primary). If you set `GOOGLE_SERVICE_ACCOUNT_JSON` there, also
  mount that JSON file (see the commented line in `docker-compose.yml`).

> The YouTube refresh token must belong to the target channel and carry an upload +
> playlist scope. Mint it locally once with `npm run youtube:auth`.

## 3. Build & start the scheduler

```bash
docker compose up -d --build      # builds the image, starts the 08:00 IST daily job
docker compose logs -f            # watch it
```

The container stays up and fires `scripts/cron-kids-rhyme.sh` at 08:00 IST every day
(`restart: unless-stopped` survives reboots).

## 4. Test it right now (optional)

Produce and upload one episode immediately (uses real API quota, publishes publicly):

```bash
docker compose run --rm rhyme once
```

Or a no-cost wiring check (prints topic + next episode #, no generation/upload):

```bash
docker compose run --rm -e DRY_RUN=1 rhyme once
```

## Operations

| Task | Command |
|---|---|
| Watch logs | `docker compose logs -f` (also `./logs/cron-kids-rhyme.log`) |
| Run one now | `docker compose run --rm rhyme once` |
| Change upload privacy | edit `KIDS_PRIVACY` in `docker-compose.yml`, then `up -d` |
| Change schedule/timezone | edit `docker/crontab` (cron time) and/or `TZ`, then rebuild |
| Edit topics | edit `scripts/topics-kids.txt`, then `up -d --build` |
| Stop | `docker compose down` |

## Notes

- **Timezone:** `TZ=Asia/Kolkata` means the `0 8` in `docker/crontab` is 08:00 IST.
  Change `TZ` for another region (the cron time stays "8 AM local").
- **Persistence:** generated episodes, images, renders, audio, and the topic pointer
  live on host-mounted volumes, so they survive `down`/`up` and image rebuilds.
- **Cost:** each run uses ~500 ElevenLabs characters; images are free (Pollinations).
- **COPPA:** uploads are forced `made_for_kids=TRUE`; YouTube disables comments/cards
  on kids content regardless of settings — expected, not a bug.
