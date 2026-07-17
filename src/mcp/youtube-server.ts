/**
 * Custom YouTube MCP server (brief §4.3).
 *
 * Exposes upload_video, set_thumbnail, get_upload_status, list_recent_uploads over
 * the Model Context Protocol (stdio). Wraps YouTube Data API v3; runs in mock mode
 * when YOUTUBE_MOCK=1 or no refresh token is configured.
 *
 * Run standalone:  npm run youtube:server
 * Or (typically) spawned as a subprocess by the publish orchestrator.
 *
 * NOTE: stdout is the JSON-RPC channel — never write logs there. We log to stderr.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { loadConfig } from "../config.js";
import { createYouTubeService, type PrivacyStatus } from "./youtube-service.js";

const log = (msg: string) => process.stderr.write(`[youtube-mcp] ${msg}\n`);

function jsonResult(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data) }], structuredContent: data as Record<string, unknown> };
}

async function main(): Promise<void> {
  const cfg = loadConfig();
  const yt = createYouTubeService(cfg);
  log(`starting (mode=${cfg.youtube.mock ? "MOCK" : "LIVE"})`);

  const server = new McpServer({ name: "youtube-publisher", version: "0.1.0" });

  server.registerTool(
    "upload_video",
    {
      title: "Upload a video to YouTube",
      description: "Upload a local video file with metadata. Returns the new video_id.",
      inputSchema: {
        file_path: z.string().describe("Local path to the rendered video file"),
        title: z.string(),
        description: z.string(),
        tags: z.array(z.string()).default([]),
        made_for_kids: z.boolean().default(true),
        privacy_status: z.enum(["private", "unlisted", "public"]).default("private"),
        category_id: z.string().default("27").describe('YouTube category id; "27" = Education'),
        language: z.string().default("en").describe("BCP-47 language, e.g. 'en'"),
      },
    },
    async (args) => {
      const res = await yt.uploadVideo({
        filePath: args.file_path,
        title: args.title,
        description: args.description,
        tags: args.tags,
        madeForKids: args.made_for_kids,
        privacyStatus: args.privacy_status as PrivacyStatus,
        categoryId: args.category_id,
        language: args.language,
      });
      log(`upload_video -> ${res.videoId}`);
      return jsonResult(res);
    },
  );

  server.registerTool(
    "set_thumbnail",
    {
      title: "Set a video thumbnail",
      description: "Set the custom thumbnail for a video from a local image file.",
      inputSchema: {
        video_id: z.string(),
        thumbnail_path: z.string(),
      },
    },
    async (args) => {
      await yt.setThumbnail(args.video_id, args.thumbnail_path);
      log(`set_thumbnail -> ${args.video_id}`);
      return jsonResult({ ok: true, video_id: args.video_id });
    },
  );

  server.registerTool(
    "set_captions",
    {
      title: "Upload a caption track",
      description: "Upload an SRT subtitle file for a video. Requires youtube.force-ssl scope.",
      inputSchema: {
        video_id: z.string(),
        srt_path: z.string(),
        language: z.string().default("en"),
      },
    },
    async (args) => {
      await yt.setCaptions(args.video_id, args.srt_path, args.language);
      log(`set_captions -> ${args.video_id} (${args.language})`);
      return jsonResult({ ok: true, video_id: args.video_id, language: args.language });
    },
  );

  server.registerTool(
    "get_upload_status",
    {
      title: "Get upload/processing status",
      description: "Return the upload and processing status for a video id.",
      inputSchema: { video_id: z.string() },
    },
    async (args) => {
      const status = await yt.getUploadStatus(args.video_id);
      return jsonResult(status);
    },
  );

  server.registerTool(
    "list_recent_uploads",
    {
      title: "List recent uploads",
      description: "List the most recent uploads for the authenticated channel.",
      inputSchema: { limit: z.number().int().positive().max(50).default(10) },
    },
    async (args) => {
      const uploads = await yt.listRecentUploads(args.limit);
      return jsonResult({ uploads });
    },
  );

  await server.connect(new StdioServerTransport());
  log("connected on stdio");
}

main().catch((err) => {
  process.stderr.write(`[youtube-mcp] fatal: ${err instanceof Error ? err.stack : String(err)}\n`);
  process.exit(1);
});
