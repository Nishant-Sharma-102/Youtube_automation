/**
 * Phase 5 — History-channel publishing orchestrator (SEPARATE from the kids channel).
 *
 * Acts as an MCP CLIENT that REUSES the kids channel's YouTube MCP server unchanged.
 * The server reads a single YOUTUBE_REFRESH_TOKEN from its environment, so we achieve
 * hard channel isolation by SPAWNING it with the history channel's own token injected —
 * the kids token is never placed in the child's environment.
 *
 *   ready row (this channel's Sheet, or a local episode JSON) ->
 *   upload_video(made_for_kids:FALSE, privacy:private) -> set_thumbnail ->
 *   status=published (+ youtube_video_id) -> History-labelled notification.
 *
 * Safety design (this is a DIFFERENT channel from the kids one — easy to get wrong):
 *   - Refresh token comes ONLY from YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN. If it is
 *     absent and we are not in mock mode, we REFUSE — we never fall back to the kids
 *     token, so we can't publish to the wrong channel.
 *   - made_for_kids is a hard-coded FALSE constant with a loud marker (see below).
 *   - Uploads default to PRIVATE; going public is an explicit, separate step.
 *   - Double-publish guard: skip if the row already carries a youtube_video_id.
 *
 * Usage:
 *   node orchestrator_history.js --dry-run --file data/ep1.json     # mock, local JSON
 *   node orchestrator_history.js                                     # from the Sheet
 *   node orchestrator_history.js --privacy unlisted                  # first real publish
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const HERE = dirname(fileURLToPath(import.meta.url));

// Cron runs with a bare environment and this file loads no framework — without this,
// YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN et al. are unset on EC2 and every scheduled run
// would refuse (or worse). Self-load this channel's .env (never overriding real env).
function loadDotenv(path) {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, "utf-8").split("\n")) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!m) continue;
    const k = m[1];
    let v = m[2];
    if (v.startsWith("#")) continue;
    v = v.replace(/^["']|["']$/g, "");
    if (process.env[k] === undefined) process.env[k] = v;
  }
}
loadDotenv(resolve(HERE, ".env"));

// ─── THIS CHANNEL IS NOT FOR KIDS ─────────────────────────────────────────────
// History storytelling for a general audience is NOT child-directed. This MUST be
// false for this channel. The kids channel sets this true — do not copy that here.
const MADE_FOR_KIDS = false;
// ──────────────────────────────────────────────────────────────────────────────

const CHANNEL_LABEL = "History Channel"; // used in every log line + notification

function log(msg) {
  process.stdout.write(`[${CHANNEL_LABEL}] ${msg}\n`);
}

function parseArgs(argv) {
  const get = (flag) => {
    const a = argv.find((x) => x === flag || x.startsWith(flag + "="));
    if (!a) return undefined;
    return a.includes("=") ? a.split("=")[1] : argv[argv.indexOf(a) + 1];
  };
  const privacy = (get("--privacy") || process.env.HISTORY_PUBLISH_PRIVACY || "private").trim();
  if (!["private", "unlisted", "public"].includes(privacy)) {
    throw new Error(`--privacy must be private|unlisted|public (got "${privacy}")`);
  }
  return { dryRun: argv.includes("--dry-run"), file: get("--file"), privacy };
}

async function withRetry(fn, label, { retries = 4 } = {}) {
  let lastErr;
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const delay = Math.min(2 ** (attempt - 1) * 1000, 30000); // 1s,2s,4s,8s cap 30s
      log(`  ${label} attempt ${attempt}/${retries} failed: ${err?.message || err}`);
      if (attempt < retries) await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw new Error(`${label} failed after ${retries} attempts: ${lastErr?.message || lastErr}`);
}

function tokenFingerprint(tok) {
  if (!tok) return "none";
  return `${tok.slice(0, 6)}…(${tok.length} chars)`; // safe, non-secret identifier
}

// ─── Episode source: local JSON (dev/mock) or this channel's Google Sheet ────────
async function loadReadyEpisode(args) {
  if (args.file || !process.env.HISTORY_SHEET_ID) {
    const path = resolve(HERE, args.file || "data/ep1.json");
    if (!existsSync(path)) throw new Error(`Episode file not found: ${path}`);
    const d = JSON.parse(readFileSync(path, "utf-8"));
    if (d.status !== "ready") {
      log(`episode is '${d.status}', not 'ready' — nothing to publish.`);
      return null;
    }
    return {
      source: "file",
      path,
      data: d,
      videoFilePath: d.video_file_path,
      thumbnailPath: d.thumbnail_path,
      title: d.title_hindi || d.title,
      description: d.description_hindi || d.description,
      tags: d.tags || [],
      youtubeVideoId: d.youtube_video_id || null,
    };
  }
  // Sheet mode (this channel's tab only). Uses the same Google creds as the pipeline.
  const { google } = await import("googleapis");
  const { GoogleAuth } = await import("google-auth-library");
  const sheetId = process.env.HISTORY_SHEET_ID;
  const tab = process.env.HISTORY_WORKSHEET || "hindi_history";
  const auth = new GoogleAuth({
    keyFile: process.env.GOOGLE_SERVICE_ACCOUNT_JSON,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const sheets = google.sheets({ version: "v4", auth: await auth.getClient() });
  const resp = await sheets.spreadsheets.values.get({ spreadsheetId: sheetId, range: tab });
  const rows = resp.data.values || [];
  const header = rows[0] || [];
  const col = (name) => header.indexOf(name);
  const idx = rows.findIndex((r, i) => i > 0 && (r[col("status")] || "").trim() === "ready");
  if (idx === -1) {
    log("no row with status='ready' in this channel's Sheet — nothing to publish.");
    return null;
  }
  const r = rows[idx];
  return {
    source: "sheet",
    sheets,
    sheetId,
    tab,
    header,
    rowNumber: idx + 1,
    videoFilePath: r[col("video_file_path")],
    thumbnailPath: r[col("thumbnail_path")],
    title: r[col("title_hindi")],
    description: r[col("description_hindi")],
    tags: (r[col("tags")] || "").split(",").map((t) => t.trim()).filter(Boolean),
    youtubeVideoId: (r[col("youtube_video_id")] || "").trim() || null,
  };
}

async function markPublished(ep, videoId) {
  if (ep.source === "file") {
    ep.data.youtube_video_id = videoId;
    ep.data.status = "published";
    writeFileSync(ep.path, JSON.stringify(ep.data, null, 2));
    return;
  }
  const setCell = async (name, value) => {
    let c = ep.header.indexOf(name);
    if (c === -1) return; // column may not exist (e.g. youtube_video_id) — skip silently
    const a1 = `${ep.tab}!${String.fromCharCode(65 + c)}${ep.rowNumber}`;
    await ep.sheets.spreadsheets.values.update({
      spreadsheetId: ep.sheetId,
      range: a1,
      valueInputOption: "USER_ENTERED",
      requestBody: { values: [[value]] },
    });
  };
  await setCell("youtube_video_id", videoId);
  await setCell("status", "published");
}

async function notify(text) {
  const token = process.env.TELEGRAM_HISTORY_BOT_TOKEN;
  const chat = process.env.TELEGRAM_HISTORY_CHAT_ID;
  const msg = `🏛️ [${CHANNEL_LABEL}] ${text}`;
  if (token && chat) {
    try {
      await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: chat, text: msg }),
      });
      log("notification sent (Telegram)");
      return;
    } catch (e) {
      log(`Telegram notify failed (${e?.message}); logging instead`);
    }
  }
  log(`notify: ${msg}  (set TELEGRAM_HISTORY_BOT_TOKEN + TELEGRAM_HISTORY_CHAT_ID to send)`);
}

class YouTubeMcp {
  constructor(client) {
    this.client = client;
  }
  static async connect({ mock, historyToken }) {
    const root = resolve(process.env.YOUTUBE_MCP_ROOT || resolve(HERE, ".."));
    const tsx = resolve(root, "node_modules/.bin/tsx");
    const server = resolve(root, "src/mcp/youtube-server.ts");
    if (!existsSync(server)) throw new Error(`YouTube MCP server not found at ${server} (set YOUTUBE_MCP_ROOT).`);
    const transport = new StdioClientTransport({
      command: tsx,
      args: [server],
      cwd: root,
      // Inject THIS channel's token as the server's YOUTUBE_REFRESH_TOKEN, overriding
      // whatever the parent env holds. This is the isolation boundary.
      env: {
        ...process.env,
        YOUTUBE_REFRESH_TOKEN: historyToken || "",
        YOUTUBE_MOCK: mock ? "1" : "0",
      },
      stderr: "inherit",
    });
    const client = new Client({ name: "history-orchestrator", version: "0.1.0" });
    await client.connect(transport);
    return new YouTubeMcp(client);
  }
  async call(name, args) {
    const res = await this.client.callTool({ name, arguments: args });
    if (res.isError) {
      const t = res.content?.[0]?.text ?? "unknown MCP tool error";
      throw new Error(`${name}: ${t}`);
    }
    if (res.structuredContent) return res.structuredContent;
    return JSON.parse(res.content?.[0]?.text ?? "{}");
  }
  close() {
    return this.client.close();
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const historyToken = process.env.YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN?.trim() || "";
  // MOCK only when EXPLICITLY requested. A real run with no token REFUSES rather than
  // silently mocking (which would falsely mark the row published without uploading).
  const mock = args.dryRun;
  if (!mock && !historyToken) {
    throw new Error(
      "Refusing to publish: YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN is not set. This channel " +
        "must use its OWN token — never the kids channel's. Use --dry-run to test in mock mode.",
    );
  }

  const ep = await loadReadyEpisode(args);
  if (!ep) return; // nothing 'ready' — normal, exit cleanly
  log(`episode: "${ep.title}"  video=${ep.videoFilePath}`);

  // Double-publish guard.
  if (ep.youtubeVideoId) {
    log(`already published as ${ep.youtubeVideoId} — skipping (double-publish guard).`);
    return;
  }
  for (const [k, v] of Object.entries({
    video_file_path: ep.videoFilePath,
    thumbnail_path: ep.thumbnailPath,
    title: ep.title,
    description: ep.description,
  })) {
    if (!v) throw new Error(`Episode is missing ${k} — cannot publish.`);
  }
  if (!mock && !existsSync(ep.videoFilePath)) throw new Error(`Video file missing: ${ep.videoFilePath}`);

  log(`mode=${mock ? "MOCK (no real upload)" : "LIVE"}  token=${tokenFingerprint(historyToken)} ` +
      `(from YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN)`);
  log(`made_for_kids=${MADE_FOR_KIDS}  privacy=${args.privacy}`);

  const yt = await YouTubeMcp.connect({ mock, historyToken });
  try {
    const up = await withRetry(
      () =>
        yt.call("upload_video", {
          file_path: ep.videoFilePath,
          title: ep.title,
          description: ep.description,
          tags: ep.tags,
          made_for_kids: MADE_FOR_KIDS, // FALSE — general audience
          privacy_status: args.privacy,
          category_id: "27", // Education
          language: "hi", // Hindi title/description/audio
        }),
      "upload_video",
    );
    const videoId = up.videoId || up.video_id;
    log(`✅ uploaded video_id=${videoId}  url=https://youtu.be/${videoId}`);

    // Record the video_id IMMEDIATELY — before the thumbnail. If we set the thumbnail
    // first and that (or markPublished) fails, the row stays 'ready' with no id and the
    // next cron run re-uploads a DUPLICATE. A missing thumbnail is fixable; a duplicate
    // upload is not. So: arm the double-publish guard first, then best-effort thumbnail.
    await markPublished(ep, videoId);
    log(`status=published (video_id recorded — double-publish guard armed)`);

    try {
      await withRetry(() => yt.call("set_thumbnail", { video_id: videoId, thumbnail_path: ep.thumbnailPath }),
        "set_thumbnail");
      log(`thumbnail set from ${ep.thumbnailPath}`);
    } catch (e) {
      log(`⚠️ thumbnail failed (video is already published as ${videoId}): ${e?.message}. ` +
          `Set it manually later; NOT re-uploading.`);
    }

    // Channel confirmation: the token used identifies the channel; also echo the
    // channel's most recent upload so you can eyeball it landed on the right one.
    try {
      const recent = await yt.call("list_recent_uploads", { limit: 1 });
      const top = (recent.uploads || [])[0];
      log(`channel check — most recent upload on this token's channel: ${JSON.stringify(top)}`);
    } catch (e) {
      log(`channel check skipped (${e?.message})`);
    }

    await notify(`"${ep.title}" uploaded as ${args.privacy} (made_for_kids=${MADE_FOR_KIDS}) → https://youtu.be/${videoId}`);
  } finally {
    await yt.close();
  }
}

main().catch((err) => {
  process.stderr.write(`[${CHANNEL_LABEL}] FATAL: ${err?.stack || err}\n`);
  process.exit(1);
});
