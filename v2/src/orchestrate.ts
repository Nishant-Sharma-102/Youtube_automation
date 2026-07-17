// PHASE 5 — publish orchestrator (MCP client).
//   npm run publish                    # 'ready' rows due on/before today
//   npm run publish -- --video 1       # a specific ready episode
//   npm run publish -- --all           # every ready row, ignore schedule
//   npm run publish -- --privacy public   # default is 'private' (test-safe)
//   npm run publish -- --dry-run       # mock (no real upload)
//
// Finds ready rows (SQLite queue), reads the video+thumbnail from local renders/,
// drives the YouTube MCP server (Phase 4) to upload_video + set_thumbnail, marks the
// row 'published', and sends a confirmation. Retry w/ backoff; skips already-published.
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { loadConfig, type Config } from "./config.js";
import { openDb, readyForPublish, getByNumber, markPublished, type Episode } from "./db.js";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function withRetry<T>(label: string, fn: () => Promise<T>, attempts = 4): Promise<T> {
  let last: unknown;
  for (let i = 1; i <= attempts; i++) {
    try { return await fn(); }
    catch (e) { last = e; if (i < attempts) { const d = Math.min(1000 * 2 ** (i - 1), 15000); console.warn(`  ${label} failed (${i}/${attempts}), retry in ${d}ms`); await sleep(d); } }
  }
  throw last;
}

async function notify(msg: string): Promise<void> {
  const token = process.env.TELEGRAM_BOT_TOKEN, chat = process.env.TELEGRAM_CHAT_ID;
  if (token && chat) {
    try {
      await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chat, text: msg }),
      });
      console.log("  📨 Telegram confirmation sent");
    } catch { console.warn("  Telegram notify failed"); }
  } else {
    console.log(`  📨 [notify] ${msg}  (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to send)`);
  }
}

/** Thin MCP client over the YouTube MCP server. */
class YouTubeMcp {
  private constructor(private client: Client) {}
  static async connect(mock: boolean): Promise<YouTubeMcp> {
    const transport = new StdioClientTransport({
      command: resolve("node_modules/.bin/tsx"),
      args: ["src/youtube-server.ts"],
      env: { ...process.env, YOUTUBE_MOCK: mock ? "1" : "0" } as Record<string, string>,
      stderr: "inherit",
    });
    const client = new Client({ name: "orchestrator", version: "1.0.0" });
    await client.connect(transport);
    return new YouTubeMcp(client);
  }
  private async call<T>(name: string, args: Record<string, unknown>): Promise<T> {
    const res = await this.client.callTool({ name, arguments: args });
    if ((res as { isError?: boolean }).isError) throw new Error(`${name}: ${JSON.stringify(res.content)}`);
    return (res as { structuredContent?: T }).structuredContent as T;
  }
  uploadVideo(p: Record<string, unknown>) { return this.call<{ videoId: string }>("upload_video", p); }
  setThumbnail(videoId: string, path: string) { return this.call("set_thumbnail", { video_id: videoId, thumbnail_path: path }); }
  close() { return this.client.close(); }
}

interface Args { video: number | null; all: boolean; privacy: string; dryRun: boolean; }
function parseArgs(): Args {
  const a = process.argv;
  const g = (f: string) => { const x = a.find((v) => v.startsWith(f)); return x ? (x.includes("=") ? x.split("=")[1] : a[a.indexOf(x) + 1]) : undefined; };
  const v = g("--video");
  const privacy = g("--privacy") ?? "private"; // test-safe default per the rules
  if (!["private", "unlisted", "public"].includes(privacy)) throw new Error("--privacy must be private|unlisted|public");
  return { video: v ? Number(v) : null, all: a.includes("--all"), privacy, dryRun: a.includes("--dry-run") };
}

function select(db: ReturnType<typeof openDb>, args: Args): Episode[] {
  if (args.video !== null) {
    const ep = getByNumber(db, args.video);
    if (!ep) throw new Error(`No episode #${args.video}`);
    if (ep.status !== "ready") { console.warn(`Episode #${args.video} is '${ep.status}', not 'ready' — skipping.`); return []; }
    return [ep];
  }
  return readyForPublish(db, args.all ? undefined : new Date().toISOString().slice(0, 10));
}

async function publishOne(db: ReturnType<typeof openDb>, yt: YouTubeMcp, ep: Episode, privacy: string): Promise<void> {
  if (ep.youtube_video_id) { console.warn(`  #${ep.video_number} already published (${ep.youtube_video_id}) — skipping (double-publish guard).`); return; }
  if (!ep.title || !ep.description) throw new Error(`#${ep.video_number} missing title/description`);
  if (!ep.video_file_path || !existsSync(ep.video_file_path)) throw new Error(`#${ep.video_number} video not found: ${ep.video_file_path}`);

  console.log(`▶ Publishing #${ep.video_number}: ${ep.title} (${privacy})`);
  const { videoId } = await withRetry(`upload_video(#${ep.video_number})`, () =>
    yt.uploadVideo({ file_path: ep.video_file_path, title: ep.title, description: ep.description, tags: ep.tags, made_for_kids: true, privacy_status: privacy }),
  );
  if (ep.thumbnail_url && existsSync(ep.thumbnail_url)) {
    await withRetry(`set_thumbnail(#${ep.video_number})`, () => yt.setThumbnail(videoId, ep.thumbnail_url!));
  }
  markPublished(db, ep.video_number, videoId); // status -> published (also guards future re-runs)
  console.log(`  ✅ published: https://youtu.be/${videoId}`);
  await notify(`Giggle Grove: "${ep.title}" published (${privacy}) → https://youtu.be/${videoId}`);
}

async function main(): Promise<void> {
  const cfg: Config = loadConfig();
  const args = parseArgs();
  const mock = args.dryRun || cfg.youtube.mock;
  const db = openDb(cfg.dbPath);
  const rows = select(db, args);
  if (!rows.length) { console.warn("No 'ready' episodes to publish."); db.close(); return; }

  console.log(`Publish job — mode=${mock ? "MOCK" : "LIVE"}, privacy=${args.privacy}, episodes=[${rows.map((r) => r.video_number).join(",")}]`);
  const yt = await YouTubeMcp.connect(mock);
  let ok = 0;
  try {
    for (const ep of rows) {
      try { await publishOne(db, yt, ep, args.privacy); ok++; }
      catch (e) { console.error(`  ✗ #${ep.video_number} failed: ${e instanceof Error ? e.message : e}`); }
    }
  } finally { await yt.close(); db.close(); }
  console.log(`Done. ${ok}/${rows.length} published.`);
}

main().catch((e) => { console.error("Phase 5 failed:", e instanceof Error ? e.message : e); process.exit(1); });
