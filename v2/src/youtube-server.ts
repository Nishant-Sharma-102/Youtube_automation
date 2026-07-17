// PHASE 4 — custom YouTube MCP server (stdio). Tools: upload_video, set_thumbnail,
// get_upload_status, list_recent_uploads. Runs in mock mode without a refresh token.
// NOTE: stdout is the JSON-RPC channel — logs go to stderr only.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { loadConfig } from "./config.js";
import { createYouTubeService, type Privacy } from "./youtube-service.js";

const log = (m: string) => process.stderr.write(`[youtube-mcp] ${m}\n`);
const result = (data: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(data) }],
  structuredContent: data as Record<string, unknown>,
});

async function main(): Promise<void> {
  const cfg = loadConfig();
  const yt = createYouTubeService(cfg);
  log(`starting (mode=${cfg.youtube.mock ? "MOCK" : "LIVE"})`);
  const server = new McpServer({ name: "youtube-publisher", version: "1.0.0" });

  server.registerTool("upload_video", {
    title: "Upload a video",
    description: "Upload a local video with metadata. Returns { videoId }.",
    inputSchema: {
      file_path: z.string(), title: z.string(), description: z.string(),
      tags: z.array(z.string()).default([]),
      made_for_kids: z.boolean().default(true),
      privacy_status: z.enum(["private", "unlisted", "public"]).default("private"), // test uploads private
    },
  }, async (a) => {
    const r = await yt.uploadVideo({
      filePath: a.file_path, title: a.title, description: a.description, tags: a.tags,
      madeForKids: a.made_for_kids, privacyStatus: a.privacy_status as Privacy,
    });
    log(`upload_video -> ${r.videoId} (${a.privacy_status})`);
    return result(r);
  });

  server.registerTool("set_thumbnail", {
    title: "Set thumbnail", description: "Set a video's custom thumbnail from a local image.",
    inputSchema: { video_id: z.string(), thumbnail_path: z.string() },
  }, async (a) => { await yt.setThumbnail(a.video_id, a.thumbnail_path); log(`set_thumbnail -> ${a.video_id}`); return result({ ok: true, video_id: a.video_id }); });

  server.registerTool("get_upload_status", {
    title: "Get upload status", description: "Return upload + processing status for a video id.",
    inputSchema: { video_id: z.string() },
  }, async (a) => result(await yt.getUploadStatus(a.video_id)));

  server.registerTool("list_recent_uploads", {
    title: "List recent uploads", description: "List recent uploads for the authenticated channel.",
    inputSchema: { limit: z.number().int().positive().max(50).default(10) },
  }, async (a) => result({ uploads: await yt.listRecentUploads(a.limit) }));

  await server.connect(new StdioServerTransport());
  log("connected on stdio");
}

main().catch((e) => { process.stderr.write(`[youtube-mcp] fatal: ${e instanceof Error ? e.stack : e}\n`); process.exit(1); });
