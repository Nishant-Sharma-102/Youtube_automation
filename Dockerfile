# Giggle Grove — daily kids-rhyme auto-upload pipeline.
# Node 22 (upload + assembly helpers) + Python 3 (generation/voice/images) + ffmpeg
# (libass captions) + Devanagari/Latin fonts + supercronic (container-friendly cron).
#
# Secrets (.env files, Google service-account JSON) are NEVER baked in — mount them
# at runtime. Output dirs (data/renders/audio/images/logs) should be mounted as a
# volume so episodes persist across container restarts.
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Kolkata \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KIDS_ROOT=/app

# --- system deps: python, ffmpeg (w/ libass), fonts, build tools for better-sqlite3 ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      ffmpeg \
      fonts-lohit-deva fonts-dejavu-core fonts-noto-core \
      build-essential ca-certificates curl tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# --- supercronic (runs the crontab in-container, logs to stdout) ---
ARG SUPERCRONIC_VERSION=v0.2.33
RUN curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app

# --- Node deps (layer-cached on package manifests) ---
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# --- Python deps into an in-repo venv (/app/.venv, where the scripts look) ---
COPY hindi-history/requirements.txt hindi-history/requirements.txt
RUN python3 -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install -r hindi-history/requirements.txt

# --- application source ---
COPY . .

RUN chmod +x scripts/cron-kids-rhyme.sh docker/entrypoint.sh \
    && mkdir -p logs renders audio hindi-history/data hindi-history/images hindi-history/logs

ENTRYPOINT ["docker/entrypoint.sh"]
# Default: run the scheduler (fires scripts/cron-kids-rhyme.sh at 08:00 IST daily).
# Override with `once` to produce+upload immediately, or `shell` for a prompt.
CMD ["cron"]
