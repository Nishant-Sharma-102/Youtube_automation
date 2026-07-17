// PHASE 3 step-7 — attach a rendered episode and mark it 'ready'.
//   npm run attach -- --video 1
//   npm run attach -- --video 1 --video-file renders/ep1.mp4 --thumbnail renders/ep1.jpg
//
// Called by render_episode.py after a successful Blender render (or run manually).
// Confirms BOTH video + audible audio streams (silent-audio guard) BEFORE marking ready.
import { existsSync } from "node:fs";
import { loadConfig } from "./config.js";
import { openDb, setReady } from "./db.js";
import { assertPublishable } from "./media.js";

function arg(flag: string): string | undefined {
  const a = process.argv.find((x) => x.startsWith(flag));
  if (!a) return undefined;
  return a.includes("=") ? a.split("=")[1] : process.argv[process.argv.indexOf(a) + 1];
}

const n = Number(arg("--video"));
if (!Number.isInteger(n) || n <= 0) throw new Error("--video requires a positive integer");
const videoFile = arg("--video-file") ?? `renders/ep${n}.mp4`;
const thumbArg = arg("--thumbnail") ?? `renders/ep${n}.jpg`;
const thumbnail = existsSync(thumbArg) ? thumbArg : null;

if (!existsSync(videoFile)) throw new Error(`Video not found: ${videoFile}`);

const p = assertPublishable(videoFile); // throws loudly if missing/silent audio
console.log(`Streams in ${videoFile}:`);
p.streams.forEach((s) => console.log(`  ${s}`));
console.log(`video: ${p.hasVideo ? "✅" : "❌"} | audio: ${p.hasAudio ? "✅" : "❌"} | max ${p.maxDb} dB`);

const db = openDb(loadConfig().dbPath);
try {
  setReady(db, n, videoFile, thumbnail);
  console.log(`✅ Episode #${n} → status 'ready' (video_file_path + thumbnail set).`);
} finally {
  db.close();
}
