# How to Make & Publish One Episode (Simple Guide)

Our system does everything **except make the actual cartoon video**. That one step is
manual. This guide shows the easy way to do it, start to finish.

Think of it as 4 steps: **Script → Voice → Video → Publish.**

---

## Step 0 — Get the script (already automated)

The computer already writes the script for you. To create scripts:

```bash
npm run generate -- --week
```

To read episode #1's script (so you can use it):

```bash
npm run captions -- --video 1   # also makes a subtitle file you can reuse
```

Or open the database and copy the `script` text for the episode you want.

---

## Step 1 — Turn the words into a voice (audio)

Kids videos need a friendly narrator voice. Easiest free options:

- **ElevenLabs** (elevenlabs.io) — free tier ~10,000 characters/month. Paste the
  script, pick a warm voice, click generate, download the `.mp3`. Best quality.
- **Google Cloud Text-to-Speech** — also has a free monthly amount, good backup.

👉 Paste each character's lines, download the audio. That's your soundtrack.

---

## Step 2 — Turn it into a video (the cartoon)

Pick ONE tool based on how much effort you want:

### Easiest (drag-and-drop, ~30 min/video)
- **Canva** (canva.com) — free. Use a "Video" project. Add a background, drop in
  your two characters (draw them once, reuse every episode), add the words on screen,
  and drop in the voice audio from Step 1. Export as **MP4, 1080p**.
- **CapCut** (free) — same idea, good for adding simple movement and music.

### Best quality for real animation (steeper learning curve)
- **Adobe Character Animator** — your character moves its mouth to the voice
  automatically. Build the 2 characters once (a "puppet"), then reuse them forever.
- **Moho** or **After Effects** — professional cartoon animation.

### Fully-automatic AI (fastest, quality varies)
- Tools like **Pika**, **Runway**, or **InVideo AI** can generate video from a script.
  Quality for a *consistent recurring cast* is still hit-or-miss, so it's best for
  quick tests, not your main look.

💡 **The big time-saver:** design your 2 characters (Milo & Lulu) and one background
**once**, then just swap the words/voice each episode. That's why the plan uses a
recurring cast — reuse = speed.

**Output you need:** one file, e.g. `renders/ep1.mp4` (1080p or higher).

---

## Step 3 — Make a thumbnail

A bright, simple image with the character's face + one big word (e.g. "COLORS!").
- Make it in **Canva** (there are free YouTube-thumbnail templates), 1280×720.
- Save it as e.g. `renders/ep1.jpg`.

---

## Step 4 — Publish (fully automated — this is us!)

Put your two files in the `renders/` folder, then run **two commands**:

```bash
# 1. Tell the system the video is ready (attach the files)
node --import tsx -e "import{loadConfig}from'./src/config.ts';import{createRepo}from'./src/db/index.ts';const r=createRepo(loadConfig());r.attachRender(1,'renders/ep1.mp4','renders/ep1.jpg');r.close()"

# 2. Publish it (start UNLISTED to check it looks right)
npm run publish -- --video 1 --privacy unlisted --captions
```

Open the video in YouTube Studio and check it. If it looks good:

```bash
# Publish for real (public)
npm run publish -- --video 1 --captions
```

That uploads the video, sets the thumbnail, adds subtitles, and marks it published —
all automatically. After that, the **daily cron** publishes any ready episode on
schedule (Mon/Wed/Fri/Sun) with no commands at all.

---

## Quick recap

| Step | Tool | Output |
|------|------|--------|
| Script | (automated) `npm run generate` | text |
| Voice | ElevenLabs / Google TTS | `.mp3` |
| Video | Canva / CapCut / Character Animator | `renders/epN.mp4` |
| Thumbnail | Canva | `renders/epN.jpg` |
| Publish | (automated) `npm run publish` | live on YouTube |

You only ever do the middle two steps by hand. Everything else runs itself.
