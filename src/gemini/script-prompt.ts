import { bibleAsPrompt } from "../../data/character-bible.js";
import type { ContentRow } from "../types.js";

export type ContentMode = "story" | "rhyme";

/** Build the Gemini/Claude call #1 prompt — screenplay episode OR rhyming song. */
export function buildScriptPrompt(row: ContentRow, mode: ContentMode = "story"): string {
  return mode === "rhyme" ? buildRhymePrompt(row) : buildStoryPrompt(row);
}

/**
 * Rhyme mode: a nursery-rhyme / sing-along song about the topic. Output is plain
 * lyric lines (with occasional MILO:/LULU: speaker labels) so the existing dialogue
 * extraction feeds voice + captions cleanly. Kept short for TTS budget.
 */
function buildRhymePrompt(row: ContentRow): string {
  return [
    `You are the songwriter for the "Made for Kids" channel "Giggle Grove".`,
    `Write a NURSERY-RHYME style sing-along song about the episode topic.`,
    ``,
    `=== CHARACTER BIBLE (follow exactly) ===`,
    bibleAsPrompt(),
    ``,
    `=== THIS EPISODE (song) ===`,
    `Episode #${row.videoNumber} — Topic: ${row.topic}`,
    ``,
    `=== REQUIREMENTS ===`,
    `- Simple, catchy AABB rhymes with a sing-song meter for ages 2–5.`,
    `- Include a short REPEATING CHORUS used 2–3 times.`,
    `- Milo and Lulu trade verses; work in their catchphrases naturally.`,
    `- 250–500 words total (keep it tight for narration).`,
    `- Format: short lyric lines. Prefix a character's verse with "MILO:" or "LULU:"`,
    `  or "BOTH:" on its own line, then the lyric lines under it. No scene headings,`,
    `  no [stage directions], no markdown fences — ONLY the song text.`,
    `- End with the "Giggle Grove Goodbye" wave line.`,
  ].join("\n");
}

/**
 * Story mode — screenplay episode.
 * Target 5–8 minutes of narrated content (~700–1100 words).
 */
function buildStoryPrompt(row: ContentRow): string {
  return [
    `You are the head writer for a "Made for Kids" educational animation channel.`,
    `Write a complete episode script.`,
    ``,
    `=== CHARACTER BIBLE (follow exactly) ===`,
    bibleAsPrompt(),
    ``,
    `=== THIS EPISODE ===`,
    `Episode #${row.videoNumber}`,
    `Topic: ${row.topic}`,
    `Format: ${row.format}`,
    ``,
    `=== REQUIREMENTS ===`,
    `- Length: a 5–8 minute episode (roughly 700–1100 words of spoken content).`,
    `- Structure: a short cold-open hook, the main learning/story beats, a clear`,
    `  reinforcement of the lesson, then the "Giggle Grove Goodbye" sign-off.`,
    `- Write it as a readable screenplay: SCENE headings, CHARACTER cue lines with`,
    `  dialogue, and brief [action / on-screen note] cues an animator can follow.`,
    `- Keep language simple and warm for ages 2–5. Include the participation moments.`,
    `- Output ONLY the script text. No preamble, no explanations, no markdown fences.`,
  ].join("\n");
}
