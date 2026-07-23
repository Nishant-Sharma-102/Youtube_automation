# Documentary channel — daily Hindi documentary auto-upload pipeline.
# Node 22 (upload + MCP publish orchestrator) + Python 3 (script/voice/visuals/music/
# assembly/metadata) + ffmpeg (Ken Burns, multi-image montage, music mix, libass
# captions) + Devanagari/Latin fonts + supercronic (container-friendly cron).
#
# Secrets (.env files, Google service-account JSON) are NEVER baked in — mount them
# at runtime. Output dirs (documentary/{data,renders,audio,images,music,logs}) should
# be mounted as volumes so episodes persist across container restarts.
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Kolkata \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOC_ROOT=/app \
    DOC_FFMPEG=ffmpeg

# --- system deps: python, ffmpeg (w/ libass), fonts, build tools for better-sqlite3 ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      ffmpeg \
      fonts-lohit-deva fonts-dejavu-core fonts-noto-core \
      build-essential ca-certificates curl tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# --- supercronic (runs the crontab in-container, logs to stdout) ---
# Architecture-aware: works on both x86_64 (t3/m5) and ARM64 (t4g/Graviton) EC2.
# A hardcoded amd64 binary is the classic "exec format error" on Graviton hosts.
ARG SUPERCRONIC_VERSION=v0.2.33
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) sc_arch=amd64 ;; \
      arm64) sc_arch=arm64 ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${sc_arch}"; \
    chmod +x /usr/local/bin/supercronic

WORKDIR /app

# --- Node deps (layer-cached on package manifests) ---
# Full install (NOT --omit=dev): the publish orchestrator runs the TypeScript YouTube
# MCP server via node_modules/.bin/tsx, which is a devDependency. Omitting dev deps
# makes every upload fail with a tsx spawn error.
COPY package.json package-lock.json ./
RUN npm ci

# --- Python deps into per-pipeline in-repo venvs ---
# documentary/.venv (cron + dashboard's documentary channel) and hindi-history/.venv
# (dashboard's Hindi History channel via make_episode.sh).
COPY documentary/requirements.txt documentary/requirements.txt
COPY hindi-history/requirements.txt hindi-history/requirements.txt
RUN python3 -m venv /app/documentary/.venv \
    && /app/documentary/.venv/bin/pip install --upgrade pip \
    && /app/documentary/.venv/bin/pip install -r documentary/requirements.txt \
    && python3 -m venv /app/hindi-history/.venv \
    && /app/hindi-history/.venv/bin/pip install --upgrade pip \
    && /app/hindi-history/.venv/bin/pip install -r hindi-history/requirements.txt

# --- application source ---
COPY . .

# Normalize shell scripts to LF + make executable. A CRLF shebang (from a Windows
# checkout) makes the kernel look for "/usr/bin/env bash\r" → "no such file or directory".
RUN sed -i 's/\r$//' scripts/cron-documentary.sh scripts/run-pipeline.sh \
       hindi-history/make_episode.sh docker/entrypoint.sh docker/crontab \
    && chmod +x scripts/cron-documentary.sh scripts/run-pipeline.sh \
       hindi-history/make_episode.sh docker/entrypoint.sh \
    && mkdir -p logs documentary/data documentary/renders documentary/audio \
       documentary/images documentary/music documentary/logs \
       hindi-history/data hindi-history/renders hindi-history/images hindi-history/audio

ENTRYPOINT ["docker/entrypoint.sh"]
# Default: run the scheduler (fires scripts/cron-documentary.sh at 08:00 IST daily).
# Override with `once` to produce+publish immediately, or `shell` for a prompt.
CMD ["cron"]
