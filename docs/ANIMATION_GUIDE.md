# How to Get Real Animated Videos Made

Your pipeline publishes videos automatically. The one thing it can't do is *create the
animation*. This guide covers the realistic ways to get animated episodes made — from
"free but slower" to "costs money but looks like NuNu Tv" — and how each one plugs back
into your pipeline.

## The honest reality first

NuNu Tv / Cocomelon-style content is **studio-grade 3D animation**. A single 3-minute
3D episode can take a professional team days and cost hundreds to thousands of dollars.
**Matching that quality, solo, at 4 videos/week, is not realistic.** So you have three
honest choices:

1. **Lower the visual bar** to clean 2D / motion-graphics (very doable solo, free-ish).
2. **Pay for it** (freelancers or studios) — closest to NuNu quality, costs money per video.
3. **Use AI video tools** — cheap and fast, but character consistency is still weak.

Pick based on your budget and how much the 3D look matters vs. just getting good
educational content out consistently.

---

## Option A — 2D / puppet animation (best for solo creators)

Colorful, clean, kid-friendly — not 3D, but very effective and sustainable to produce.

| Tool | Cost | Why |
|------|------|-----|
| **Adobe Character Animator** | ~$23/mo (Creative Cloud) | Your character's mouth auto-syncs to the voice audio. Build Milo & Lulu **once** as "puppets," then reuse forever — this is the real speed unlock. |
| **Vyond** | ~$49+/mo | Template-based cartoon maker built for educational/explainer content. Drag-drop scenes. |
| **Animaker / Toonly** | ~$20+/mo | Cheaper template cartoon makers, good for beginners. |
| **Canva / CapCut** | Free | Simplest: static characters + text + voice + simple moves. Lowest effort, lowest polish. |

**Workflow:** design Milo & Lulu + one background once → each episode, drop in the new
voice track and swap the words/props → export **MP4 1080p**.

---

## Option B — Hire it out (closest to NuNu Tv quality)

| Where | Cost (per ~3-min video) | Notes |
|-------|-------------------------|-------|
| **Fiverr** (search "3D kids animation", "nursery rhyme animation") | ~$50–500 | Wide range; check reviews + portfolios. Start with one test episode. |
| **Upwork** freelancers | ~$100–800 | Better for an ongoing relationship / recurring cast. |
| **Small animation studios** | $500–3000+ | Highest quality, least sustainable at 4/week. |

💡 Cost-saver: pay once to have the **characters + a reusable template/rig** built, then
pay much less per episode since the assets are reused.

Use the ready-made brief at the bottom of this file.

---

## Option C — AI video generation (cheapest, quality varies)

| Tool | Cost | Notes |
|------|------|-------|
| **Google Veo / Runway / Pika / Kling / Luma** | ~$10–95/mo | Text/image-to-video. Great for backgrounds and B-roll. |
| **Midjourney/DALL·E + image-to-video** | ~$10–30/mo | Generate a character image, then animate it. |

⚠️ **Honest caveat:** AI still struggles to keep the *same* character looking consistent
across many scenes/episodes — the #1 requirement for a recurring cast. Best used for
tests or as a helper, not (yet) as your reliable main look.

---

## Recommended path for you

1. **Voice** every episode with **ElevenLabs** (free tier) — this alone makes content
   feel professional.
2. Start with **Adobe Character Animator** (Option A) to build Milo & Lulu as reusable
   puppets. It's the best balance of quality, cost, and speed for one person.
3. If you have budget and the 3D look is essential, order **one** test episode from a
   **Fiverr/Upwork** freelancer (Option B) using the brief below, and see if the
   economics work before committing to 4/week.
4. Whatever you choose, the output is the same: **`renders/epN.mp4` (1080p) + a
   thumbnail `renders/epN.jpg`** — then your pipeline takes over.

---

## Plugging any render into your pipeline

Once you have a finished `.mp4` **with the voiceover baked in** and a thumbnail:

```bash
# 1. Attach the files (this now checks the video actually has audio, and fails if silent)
node --import tsx -e "import{loadConfig}from'./src/config.ts';import{createRepo}from'./src/db/index.ts';const r=createRepo(loadConfig());r.attachRender(2,'renders/ep2.mp4','renders/ep2.jpg');r.close()"

# 2. Publish (start unlisted to check, then drop --privacy for public)
npm run publish -- --video 2 --privacy unlisted --captions
```

That's it — upload, thumbnail, subtitles, done. The cron handles the schedule after that.

---

## Copy-paste freelancer brief (uses your character bible)

> **Project:** Recurring 3D/2D animated series for a "Made for Kids" YouTube channel
> called **Giggle Grove** (educational, ages 2–5).
>
> **Characters (must stay consistent every episode):**
> - **Milo** — an energetic young fox cub, bright orange fur, blue scarf, bushy tail,
>   big round eyes; curious and enthusiastic. Catchphrase: "Let's find out!"
> - **Lulu** — a calm, wise owl, soft purple feathers, round golden glasses; patient,
>   kind teacher. Catchphrase: "Great thinking!"
>
> **Style:** bright, warm, high-contrast, gentle. Every episode ends with the "Giggle
> Grove Goodbye" — Milo and Lulu wave and sing a short two-line goodbye song.
>
> **Deliverable:** one 3–4 minute 1080p MP4 with the provided voiceover synced, plus a
> reusable character rig/template for future episodes. I will provide the script + voice
> audio.
>
> **Ask:** quote for (a) this first episode and (b) each additional episode reusing the
> assets.

(Generate the script for any episode with `npm run generate`, and the voice with ElevenLabs.)
