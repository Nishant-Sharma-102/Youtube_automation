/**
 * Phase 3 step 7 — attach a rendered episode and mark it 'ready'.
 *
 *   npm run attach -- --video 2
 *   npm run attach -- --video 2 --video-file renders/ep2.mp4 --thumbnail renders/ep2.jpg
 *
 * Defaults to renders/epN.mp4 and renders/epN.jpg by convention. Runs the audio-safety
 * guard (rejects a silent / audioless render) and moves the row script_ready → ready,
 * which is what the Phase 5 publish orchestrator watches for.
 *
 * Called by scripts/render_episode.py after a successful Blender render, or run manually.
 */
import { existsSync } from "node:fs";

import { loadConfig } from "./config.js";
import { logger } from "./logger.js";
import { createRepo } from "./db/index.js";
import { probeAudio } from "./media/probe.js";

function parseArgs(argv: string[]): { video: number; videoFile: string; thumbnail: string | null } {
  const get = (flag: string): string | undefined => {
    const a = argv.find((x) => x.startsWith(flag));
    if (!a) return undefined;
    return a.includes("=") ? a.split("=")[1] : argv[argv.indexOf(a) + 1];
  };
  const n = Number(get("--video"));
  if (!Number.isInteger(n) || n <= 0) throw new Error("--video requires a positive integer");
  const videoFile = get("--video-file") ?? `renders/ep${n}.mp4`;
  const thumbArg = get("--thumbnail") ?? `renders/ep${n}.jpg`;
  return { video: n, videoFile, thumbnail: existsSync(thumbArg) ? thumbArg : null };
}

function main(): void {
  const { video, videoFile, thumbnail } = parseArgs(process.argv.slice(2));
  if (!existsSync(videoFile)) throw new Error(`Video file not found: ${videoFile}`);

  // Show the stream summary (ffprobe-style) and confirm BOTH streams before proceeding.
  const probe = probeAudio(videoFile);
  logger.info(`Streams detected in ${videoFile}:`);
  for (const s of probe.streams) logger.info(`  ${s}`);
  logger.info(
    `video stream: ${probe.hasVideoStream ? "✅ present" : "❌ MISSING"} | ` +
      `audio stream: ${probe.hasAudioStream ? "✅ present" : "❌ MISSING"} | ` +
      `audio level: max ${probe.maxVolumeDb ?? "n/a"} dB${probe.isSilent ? " (SILENT)" : ""}`,
  );
  if (!probe.hasVideoStream || !probe.hasAudioStream) {
    throw new Error(
      `Refusing to mark ready: ${videoFile} is missing a ${!probe.hasVideoStream ? "video" : "audio"} stream.`,
    );
  }

  const repo = createRepo(loadConfig());
  try {
    // attachRender re-runs the guard (video + audible-audio) and moves
    // script_ready -> ready. Throws loudly on a silent/audioless render.
    repo.attachRender(video, videoFile, thumbnail);
    const row = repo.getByVideoNumber(video);
    logger.info(`✅ Episode #${video} attached and marked 'ready' for publishing`, {
      videoFile,
      thumbnail: thumbnail ?? "(none)",
      status: row?.status,
    });
  } finally {
    repo.close();
  }
}

main();
