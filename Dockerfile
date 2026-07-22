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

# --- Python deps for the documentary pipeline into an in-repo venv ---
# cron-documentary.sh prefers documentary/.venv, so install there.
COPY documentary/requirements.txt documentary/requirements.txt
RUN python3 -m venv /app/documentary/.venv \
    && /app/documentary/.venv/bin/pip install --upgrade pip \
    && /app/documentary/.venv/bin/pip install -r documentary/requirements.txt

# --- application source ---
COPY . .

# Normalize shell scripts to LF + make executable. A CRLF shebang (from a Windows
# checkout) makes the kernel look for "/usr/bin/env bash\r" → "no such file or directory".
RUN sed -i 's/\r$//' scripts/cron-documentary.sh docker/entrypoint.sh docker/crontab \
    && chmod +x scripts/cron-documentary.sh docker/entrypoint.sh \
    && mkdir -p logs documentary/data documentary/renders documentary/audio \
       documentary/images documentary/music documentary/logs

ENTRYPOINT ["docker/entrypoint.sh"]
# Default: run the scheduler (fires scripts/cron-documentary.sh at 08:00 IST daily).
# Override with `once` to produce+publish immediately, or `shell` for a prompt.
CMD ["cron"]
