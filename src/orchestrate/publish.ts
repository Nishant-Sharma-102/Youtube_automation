/**
 * Publish orchestrator (brief §4.4) — the scheduled publish job.
 *
 * Acts as an MCP CLIENT: it spawns the custom YouTube MCP server and drives it.
 *   1. Find 'ready' rows due today (or --video N / --all).
 *   2. upload_video() via the YouTube MCP server.
 *   3. set_thumbnail() if a thumbnail is attached.
 *   4. Mark the row 'published' with the returned video_id.
 *   5. Log a confirmation (Telegram/email notify is a later build).
 *
 * Usage:
 *   npm run publish                 # ready rows scheduled on/before today
 *   npm run publish -- --video 3    # a specific ready episode
 *   npm run publish -- --all        # every ready row, ignoring schedule
 *   npm run publish -- --privacy unlisted   # upload unlisted (safe first real publish)
 *   npm run publish -- --dry-run    # force MOCK mode (no real upload)
 *
 * Privacy defaults to 'public' (override via --privacy or PUBLISH_PRIVACY env).
 */
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

import { loadConfig, type Config } from "../config.js";
import { logger } from "../logger.js";
import { withRetry } from "../retry.js";
import { mkdirSync, existsSync, writeFileSync } from "node:fs";

import { createRepo } from "../db/index.js";
import type { ContentQueueRepo } from "../db/repo.js";
import type { ContentRow } from "../types.js";
import { captionPathFor, scriptToSrt } from "../captions/srt.js";

const PROJECT_ROOT = resolve(fileURLToPath(import.meta.url), "../../..");
const TSX_BIN = resolve(PROJECT_ROOT, "node_modules/.bin/tsx");
const SERVER_SCRIPT = resolve(PROJECT_ROOT, "src/mcp/youtube-server.ts");

type Privacy = "private" | "unlisted" | "public";

interface Args {
  dryRun: boolean;
  all: boolean;
  video: number | null;
  privacy: Privacy;
  captions: boolean;
}

function parseArgs(argv: string[]): Args {
  const videoArg = argv.find((a) => a.startsWith("--video"));
  let video: number | null = null;
  if (videoArg) {
    const raw = videoArg.includes("=") ? videoArg.split("=")[1] : argv[argv.indexOf(videoArg) + 1];
    const n = Number(raw);
    if (!Number.isInteger(n) || n <= 0) throw new Error(`--video requires a positive integer`);
    video = n;
  }

  // Privacy: --privacy <v>, else PUBLISH_PRIVACY env, else 'public'.
  const privacyArg = argv.find((a) => a.startsWith("--privacy"));
  const rawPrivacy = privacyArg
    ? privacyArg.includes("=")
      ? privacyArg.split("=")[1]
      : argv[argv.indexOf(privacyArg) + 1]
    : process.env.PUBLISH_PRIVACY?.trim() || "public";
  if (!["private", "unlisted", "public"].includes(rawPrivacy)) {
    throw new Error(`--privacy must be private|unlisted|public, got "${rawPrivacy}"`);
  }

  return {
    dryRun: argv.includes("--dry-run"),
    all: argv.includes("--all"),
    video,
    privacy: rawPrivacy as Privacy,
    captions: argv.includes("--captions") || process.env.PUBLISH_CAPTIONS?.trim() === "1",
  };
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Thin typed wrapper over an MCP client connected to the YouTube server. */
class YouTubeMcp {
  private constructor(private readonly client: Client) {}

  static async connect(cfg: Config): Promise<YouTubeMcp> {
    const transport = new StdioClientTransport({
      command: TSX_BIN,
      args: [SERVER_SCRIPT],
      cwd: PROJECT_ROOT,
      // Pass our environment so the server sees the same YOUTUBE_* config / mock flag.
      env: { ...process.env, YOUTUBE_MOCK: cfg.youtube.mock ? "1" : "0" } as Record<string, string>,
      stderr: "inherit",
    });
    const client = new Client({ name: "publish-orchestrator", version: "0.1.0" });
    await client.connect(transport);
    return new YouTubeMcp(client);
  }

  private async call<T>(name: string, args: Record<string, unknown>): Promise<T> {
    const res = await this.client.callTool({ name, arguments: args });
    if (res.isError) {
      const text = Array.isArray(res.content) && res.content[0] && "text" in res.content[0]
        ? (res.content[0] as { text: string }).text
        : "unknown MCP tool error";
      throw new Error(`${name} failed: ${text}`);
    }
    if (res.structuredContent) return res.structuredContent as T;
    const first = Array.isArray(res.content) ? res.content[0] : undefined;
    const text = first && "text" in first ? (first as { text: string }).text : "{}";
    return JSON.parse(text) as T;
  }

  uploadVideo(p: {
    file_path: string;
    title: string;
    description: string;
    tags: string[];
    made_for_kids: boolean;
    privacy_status: string;
  }): Promise<{ videoId: string }> {
    return this.call("upload_video", p);
  }

  setThumbnail(videoId: string, thumbnailPath: string): Promise<unknown> {
    return this.call("set_thumbnail", { video_id: videoId, thumbnail_path: thumbnailPath });
  }

  setCaptions(videoId: string, srtPath: string, language = "en"): Promise<unknown> {
    return this.call("set_captions", { video_id: videoId, srt_path: srtPath, language });
  }

  close(): Promise<void> {
    return this.client.close();
  }
}

function selectRows(repo: ContentQueueRepo, args: Args): ContentRow[] {
  if (args.video !== null) {
    const row = repo.getByVideoNumber(args.video);
    if (!row) throw new Error(`No episode with video_number=${args.video}`);
    if (row.status !== "ready") {
      logger.warn(`Episode #${row.videoNumber} is '${row.status}', not 'ready' — skipping.`);
      return [];
    }
    return [row];
  }
  return repo.findReadyForPublish(args.all ? undefined : todayIso());
}

/** Ensure an SRT exists for the row (generating from its script if needed); return the path or null. */
function ensureCaptionFile(row: ContentRow): string | null {
  const path = captionPathFor(row.videoNumber);
  if (existsSync(path)) return path;
  if (!row.script) return null;
  mkdirSync("captions", { recursive: true });
  writeFileSync(path, scriptToSrt(row.script));
  logger.info(`Generated caption file`, { videoNumber: row.videoNumber, path });
  return path;
}

async function publishOne(
  repo: ContentQueueRepo,
  yt: YouTubeMcp,
  row: ContentRow,
  privacy: Privacy,
  captions: boolean,
): Promise<void> {
  // Idempotency guard (brief §4.6): never double-publish.
  if (row.youtubeVideoId) {
    logger.warn(`Episode #${row.videoNumber} already has video id ${row.youtubeVideoId} — skipping.`);
    return;
  }
  if (!row.title || !row.description) {
    throw new Error(`Episode #${row.videoNumber} is missing title/description — generate first.`);
  }
  if (!row.videoFilePath) {
    throw new Error(`Episode #${row.videoNumber} has no video_file_path — attach a render first.`);
  }

  logger.info(`Publishing episode #${row.videoNumber}`, { title: row.title });
  const { videoId } = await withRetry(
    () =>
      yt.uploadVideo({
        file_path: row.videoFilePath!,
        title: row.title!,
        description: row.description!,
        tags: row.tags,
        made_for_kids: true,
        privacy_status: privacy,
      }),
    { label: `upload_video(v${row.videoNumber})` },
  );

  if (row.thumbnailPath) {
    await withRetry(() => yt.setThumbnail(videoId, row.thumbnailPath!), {
      label: `set_thumbnail(v${row.videoNumber})`,
    });
  }

  if (captions) {
    const srtPath = ensureCaptionFile(row);
    if (srtPath) {
      await withRetry(() => yt.setCaptions(videoId, srtPath, "en"), {
        label: `set_captions(v${row.videoNumber})`,
      });
      logger.info(`Captions uploaded`, { videoNumber: row.videoNumber });
    } else {
      logger.warn(`No script to build captions for episode #${row.videoNumber} — skipped.`);
    }
  }

  repo.markPublished(row.videoNumber, videoId, new Date().toISOString());
  logger.info(`✅ Episode #${row.videoNumber} published`, {
    videoId,
    url: `https://youtu.be/${videoId}`,
  });
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const cfg = loadConfig();
  if (args.dryRun) cfg.youtube.mock = true;

  const repo = createRepo(cfg);
  const rows = selectRows(repo, args);
  if (rows.length === 0) {
    // Brief §4.6: warn instead of failing silently when there's nothing ready.
    logger.warn("No 'ready' episodes to publish.");
    repo.close();
    return;
  }

  logger.info("Starting publish job", {
    mode: cfg.youtube.mock ? "MOCK" : "LIVE",
    privacy: args.privacy,
    episodes: rows.map((r) => r.videoNumber),
  });

  const yt = await YouTubeMcp.connect(cfg);
  let ok = 0;
  try {
    for (const row of rows) {
      try {
        await publishOne(repo, yt, row, args.privacy, args.captions);
        ok++;
      } catch (err) {
        logger.error(`Failed to publish episode #${row.videoNumber}`, {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }
  } finally {
    await yt.close();
    repo.close();
  }
  logger.info(`Done. ${ok}/${rows.length} episode(s) published.`);
}

main().catch((err) => {
  logger.error("Fatal error in publish job", {
    error: err instanceof Error ? err.message : String(err),
  });
  process.exit(1);
});
