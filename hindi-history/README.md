# Hindi History Channel — Automated Pipeline

Narrated, illustrated Hindi history storytelling videos (Ken Burns stills + burned-in
Hindi captions). **Separate** from the kids animation channel: its own code, its own
`.env`, its own Google Sheet tab, its own cron slot.

Topic → **script (Phase 1)** → voice (Phase 2) → illustrations (Phase 3) →
video assembly (Phase 4) → publish (Phase 5, reuses the kids channel's YouTube MCP server).

## Setup

```bash
cd hindi-history
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then edit .env — never hardcode keys
```

## Phase 1 — script generation (built)

Reads the next `draft` topic from the Sheet, calls **Gemini 2.5 Flash** for a Hindi
narration package as structured JSON, prints it, and writes it back as `script_ready`.

**Sheet tab `hindi_history`, columns:**
`topic | script_hindi | title_hindi | description_hindi | tags | scene_breakdown | status | scheduled_date`

The model returns this exact JSON shape:

```json
{
  "title": "…", "description": "…", "tags": ["…"],
  "full_script": "…",
  "scenes": [{"scene_number": 1, "text": "…", "image_prompt_hint": "…"}]
}
```

`full_script` is the exact concatenation of the scene texts (verified, and rebuilt
from the scenes if the model drifts) so narration and per-scene illustration timing
stay in sync for Phases 2–4. `image_prompt_hint` is English on purpose.

### Usage

```bash
# Generate for one topic and just print it (no Sheet needed) — the Phase-1 acceptance test:
.venv/bin/python generate_script.py --topic "The Founding of Rome" --no-write

# One-time: create the separate tab + seed the test topic (needs Sheets creds):
.venv/bin/python generate_script.py --init

# Process the next draft row and write results back to the Sheet:
.venv/bin/python generate_script.py

# Plumbing check with no API key:
.venv/bin/python generate_script.py --topic "The Founding of Rome" --no-write --dry-run
```

### Google Sheets credentials (service account — headless/cron friendly)

1. Google Cloud → create a project (or reuse one) → enable the **Google Sheets API**.
2. Create a **service account**, add a **JSON key**, download it, and point
   `GOOGLE_SERVICE_ACCOUNT_JSON` at the file path.
3. Create the spreadsheet, copy its ID into `HISTORY_SHEET_ID`, and **share** the
   spreadsheet (Editor) with the service account's `client_email`.
4. `.venv/bin/python generate_script.py --init` creates the `hindi_history` tab,
   writes the header row, and seeds "The Founding of Rome" as a `draft`.

Range flags (scene count 8–12, tags 5–8, ~700–1000 words, per-scene sentence count)
are checked after generation and printed as **REVIEW FLAGS** rather than hard failures.

Logs: `logs/generate.log`.

## Phase 2 — voice generation, timed per scene (built)

Reads a `script_ready` episode, synthesizes **each scene separately** with Google
Cloud TTS (hi-IN) → `audio/epN_sceneM.mp3`, measures each scene's exact duration
(ffmpeg), concatenates all scenes → `audio/epN_full.mp3`, tracks free-tier character
usage, writes per-scene `duration_seconds` + the audio path back, sets
`status=audio_ready`. Per-scene durations are the source of truth for Phase 3/4 timing.

> **Google Cloud TTS requires a service account** (`GOOGLE_SERVICE_ACCOUNT_JSON` /
> `GOOGLE_APPLICATION_CREDENTIALS`) with the **Text-to-Speech API enabled** — it does
> **not** accept API keys. `ffmpeg` must be on PATH or set `HISTORY_FFMPEG`.
> Voice defaults to `hi-IN-Wavenet-A` (1M chars/mo free); set `HISTORY_TTS_VOICE` to a
> `hi-IN-Standard-*` voice for the 4M/mo tier.

```bash
# Real run from the Sheet:
.venv/bin/python generate_voice.py --episode 1

# Real run from a local Phase-1 dump (no Sheet):
.venv/bin/python generate_voice.py --episode 1 --scenes-file data/ep1.json

# Offline pipeline test — silent placeholder audio, no TTS credential (verifies
# durations/concat/usage/write-back only; NOT real speech):
.venv/bin/python generate_voice.py --episode 1 --scenes-file data/ep1.json --silent
```

Usage log: `logs/tts_usage.jsonl` (per-episode chars by month + tier; warns at 80%
of the free allowance). Voice log: `logs/voice.log`.
