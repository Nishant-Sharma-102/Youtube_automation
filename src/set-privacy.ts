/**
 * Change a published video's privacy.
 *
 *   npm run set-privacy -- --video 2 --privacy public      # by queue episode number
 *   npm run set-privacy -- --video-id yYHAdwyXCsg --privacy unlisted
 *
 * Looks up the YouTube video id from the queue when --video is given.
 */
import { loadConfig } from "./config.js";
import { logger } from "./logger.js";
import { createRepo } from "./db/index.js";
import { RealYouTubeService, type PrivacyStatus } from "./mcp/youtube-service.js";

function arg(flag: string): string | undefined {
  const a = process.argv.find((x) => x.startsWith(flag));
  if (!a) return undefined;
  return a.includes("=") ? a.split("=")[1] : process.argv[process.argv.indexOf(a) + 1];
}

async function main(): Promise<void> {
  const cfg = loadConfig();
  const privacy = (arg("--privacy") ?? "public") as PrivacyStatus;
  if (!["public", "unlisted", "private"].includes(privacy)) {
    throw new Error(`--privacy must be public|unlisted|private`);
  }

  let videoId = arg("--video-id");
  if (!videoId) {
    const n = Number(arg("--video"));
    if (!Number.isInteger(n)) throw new Error("Pass --video-id <id> or --video <N>");
    const repo = createRepo(cfg);
    videoId = repo.getByVideoNumber(n)?.youtubeVideoId ?? undefined;
    repo.close();
    if (!videoId) throw new Error(`Episode #${n} has no youtube_video_id (not published yet?)`);
  }

  if (cfg.youtube.mock) throw new Error("YOUTUBE_MOCK is on — set YOUTUBE_MOCK=0 to change real videos.");
  await new RealYouTubeService(cfg).setPrivacy(videoId, privacy);
  logger.info(`✅ Set ${videoId} to ${privacy}`, { url: `https://youtu.be/${videoId}` });
}

main().catch((err) => {
  logger.error("set-privacy failed", { error: err instanceof Error ? err.message : String(err) });
  process.exit(1);
});
