# Deploying the daily documentary auto-upload on EC2 (Docker)

This containerizes the full pipeline — **topic → Hindi script → deep-voice narration →
multi-image visuals → suspense music → 1080p render → public upload with Hindi+English
captions** — and runs it every morning at **08:00 IST** via an in-container scheduler
(supercronic).

Secrets are **never** baked into the image. You mount your `.env` files (and, if used,
the Google service-account JSON) at runtime.

## 1. Launch an EC2 instance

- **AMI:** Amazon Linux 2023 or Ubuntu 22.04+
- **Type:** `t3.medium` (4 GB RAM) recommended — a full multi-image episode does a lot of
  ffmpeg work. `t3.small` works but is tight.
- **Storage:** 30 GB gp3 (episodes + images accumulate).
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

- `./.env` — shared secrets: `ANTHROPIC_API_KEY`, `YOUTUBE_CLIENT_ID`,
  `YOUTUBE_CLIENT_SECRET` (Gemini/ElevenLabs optional).
- `./documentary/.env` — the documentary channel's own settings, must contain
  `YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN` (this channel's upload+captions token),
  plus the pipeline knobs (`DOC_NARRATION_LANGUAGE`, `DOC_MUSIC_MOOD`,
  `DOC_CAPTION_LANGUAGES`, `DOC_IMAGES_PER_SCENE_MAX`, etc.). If you set
  `DOC_SERVICE_ACCOUNT_JSON` for the Sheet/Google TTS, also mount that JSON file
  (see the commented line in `docker-compose.yml`).

> The refresh token must belong to the target channel and carry the
> `youtube.upload` + `youtube.force-ssl` scopes (force-ssl is needed for captions).
> Mint it locally once with `npm run youtube:auth`.

> ffmpeg: the image ships system ffmpeg and sets `DOC_FFMPEG=ffmpeg`, which overrides
> any host-specific `DOC_FFMPEG` path in your mounted `.env`.

## 3. Build & start the scheduler

**One command** (pulls latest, preflights `.env`, builds, starts the daily job):

```bash
./scripts/deploy.sh          # or: ./scripts/deploy.sh once   (also publish one now)
docker compose logs -f       # watch it
```

Or manually:

```bash
docker compose up -d --build      # builds the image, starts the 08:00 IST daily job
docker compose logs -f
```

The container stays up and fires `scripts/cron-documentary.sh` at 08:00 IST every day
(`restart: unless-stopped` survives reboots).

## Dashboard — manual trigger for both history channels

`docker compose up -d --build` also starts a **dashboard** service
(`documentary-dashboard`) on port **8080** alongside the daily cron. Open:

```
http://<EC2_IP>:8080
```

- **Channel selector**: Documentary or Hindi History.
- **Category dropdown** (Documentary: History/Mysteries/Science/Alt-History; Hindi
  History: eras/regions like Maurya Empire, Mughal Empire, British Raj…) **or** a
  free-text **topic** (blank topic → uses the category / AI picks one).
- **Run mode**: *Review* (publishes at your chosen privacy so you can check it) or
  *Fast* (auto-runs and uploads **PRIVATE** — never public, enforced server-side).
- **Live jobs table**: channel, topic, status, phase, elapsed, and the published link.

Runs are **serial** — one at a time across both channels and the 08:00 cron (a shared
lock), so heavy ffmpeg jobs never overlap and OOM.

- **Open port 8080** in the EC2 security group (recommend restricting to your own IP),
  or set `DASHBOARD_TOKEN` on the `dashboard` service for a password. Port via
  `DOC_WEBUI_PORT`.
- The Hindi History channel uploads with its own token — put
  `YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN` in your `.env` for that channel to publish.

## 4. Test it right now (optional)

Produce and publish one episode immediately (uses real API quota, publishes publicly):

```bash
docker compose run --rm documentary once
```

## Operations

| Task | Command |
|---|---|
| Watch logs | `docker compose logs -f` (also `./logs/cron-documentary.log`) |
| Run one now | `docker compose run --rm documentary once` |
| Change upload privacy | edit `DOC_PUBLISH_PRIVACY` in `docker-compose.yml`, then `up -d` |
| Change schedule/timezone | edit `docker/crontab` (cron time) and/or `TZ`, then rebuild |
| Tune visuals/music/voice | edit `documentary/.env` (`DOC_IMAGES_PER_SCENE_MAX`, `DOC_MUSIC_MOOD`, `DOC_EDGE_PITCH`…), then `up -d` |
| Stop | `docker compose down` |

## Notes

- **Timezone:** `TZ=Asia/Kolkata` means the `0 8` in `docker/crontab` is 08:00 IST.
  Change `TZ` for another region (the cron time stays "8 AM local").
- **Persistence:** generated episodes, images, renders, audio, music, and the topic
  queue live on host-mounted volumes, so they survive `down`/`up` and image rebuilds.
- **Cost:** narration uses the free Edge voice; images are free (Pollinations); music is
  free (Jamendo CC). Real animation (Kling) is off by default. The main paid call is
  Claude for the script/metadata/caption-translation.
- **Runtime:** a full multi-image episode takes ~45 min at `DOC_IMAGES_PER_SCENE_MAX=2`.
- **Audience:** uploads are `made_for_kids=FALSE` (general-audience documentary).
