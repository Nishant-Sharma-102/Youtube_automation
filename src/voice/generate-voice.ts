/**
 * Phase 2 — voice generation.
 *
 *   npm run voice -- --video 2     # a specific script_ready episode
 *   npm run voice                  # next script_ready episode without audio yet
 *
 * Reads the episode script from the queue (SQLite), extracts the spoken dialogue,
 * synthesizes narration (ElevenLabs → Google TTS → Gemini TTS fallback), saves
 * audio/epN.mp3, records the audio path on the row (status stays 'script_ready'),
 * and logs which service + character count was used.
 */
import { loadConfig } from "../config.js";
import { logger } from "../logger.js";
import { createRepo } from "../db/index.js";
import type { ContentRow } from "../types.js";
import { extractDialogue } from "../captions/srt.js";
import { durationSeconds } from "./audio.js";
import { generateVoice } from "./index.js";
import { monthToDateChars } from "./usage.js";

function parseVideoArg(argv: string[]): number | null {
  const a = argv.find((x) => x.startsWith("--video"));
  if (!a) return null;
  const raw = a.includes("=") ? a.split("=")[1] : argv[argv.indexOf(a) + 1];
  const n = Number(raw);
  if (!Number.isInteger(n) || n <= 0) throw new Error(`--video requires a positive integer`);
  return n;
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const cfg = loadConfig();
  const repo = createRepo(cfg);
  try {
    const videoNumber = parseVideoArg(argv);
    let row: ContentRow | null;
    if (videoNumber !== null) {
      row = repo.getByVideoNumber(videoNumber);
      if (!row) throw new Error(`No episode with video_number=${videoNumber}`);
    } else {
      row = repo.listByStatus("script_ready").find((r) => !r.audioPath) ?? null;
    }

    if (!row) {
      logger.warn("No 'script_ready' episode without audio to voice. (Generate a script first.)");
      return;
    }
    if (row.status !== "script_ready") {
      logger.warn(`Episode #${row.videoNumber} is '${row.status}', not 'script_ready' — skipping.`);
      return;
    }
    if (!row.script) throw new Error(`Episode #${row.videoNumber} has no script text.`);

    // Narration = spoken dialogue only (no scene headings / action cues).
    const narration = extractDialogue(row.script).join(" ").trim();
    if (!narration) throw new Error(`No spoken dialogue extracted from episode #${row.videoNumber}.`);

    const result = await generateVoice(cfg, row.videoNumber, narration);
    repo.setAudioPath(row.videoNumber, result.outPath); // status stays 'script_ready'

    const monthTotal = monthToDateChars(result.provider, new Date().toISOString().slice(0, 7));
    logger.info("Phase 2 done — audio ready for rendering", {
      videoNumber: row.videoNumber,
      provider: result.provider,
      chars: result.chars,
      monthToDateChars: monthTotal,
      audioPath: result.outPath,
      durationSec: Math.round(durationSeconds(result.outPath)),
    });
  } finally {
    repo.close();
  }
}

main().catch((err) => {
  logger.error("Fatal error in voice generation", {
    error: err instanceof Error ? err.message : String(err),
  });
  process.exit(1);
});
