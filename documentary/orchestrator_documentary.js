/**
 * Phase 9 — Documentary-channel publishing orchestrator.
 *
 * A THIRD, separate channel. This file is distinct from the kids and history
 * orchestrators so none of the three can ever cross-publish. It REUSES the kids
 * channel's YouTube MCP server unchanged (do not rebuild it): channel isolation is
 * achieved by SPAWNING that server with THIS channel's own refresh token injected as
 * the server's YOUTUBE_REFRESH_TOKEN — the kids/history tokens never enter the child.
 *
 *   ready row (this channel's Sheet, or the local data/topics_mirror.json) ->
 *   upload_video(made_for_kids:FALSE, privacy:private) -> set_thumbnail ->
 *   status=published (+ youtube_video_id) -> Documentary-labelled notification.
 *
 * Note on the Sheet: there is no Google Sheets MCP server in this repo — the proven
 * pattern (kids/history) reads the Sheet via googleapis directly, so this does too.
 * The metadata the orchestrator publishes (final title, thumbnail, description, tags)
 * lives inside the row's scene_breakdown JSON blob, written by Phase 8's finalize step.
 *
 * Usage:
 *   node orchestrator_documentary.js --dry-run          # mock, no real upload
 *   node orchestrator_documentary.js                     # from the Sheet/mirror (PRIVATE)
 *   node orchestrator_documentary.js --privacy unlisted  # explicit privacy
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const HERE = dirname(fileURLToPath(import.meta.url));

// Cron runs with a bare environment. Self-load this channel's .env (then the repo
// root .env), never overriding anything already set in the real environment.
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
loadDotenv(resolve(HERE, "..", ".env"));

// ─── THIS CHANNEL IS NOT FOR KIDS ─────────────────────────────────────────────
// General-audience documentary content — same as the history channel. The kids
// channel sets this TRUE; never copy that here.
const MADE_FOR_KIDS = false;
// ──────────────────────────────────────────────────────────────────────────────

const CHANNEL_LABEL = "Documentary Channel";
const TOKEN_ENV = "YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN";
// BCP-47 language of the title/description/audio. This channel narrates in Hindi;
// keep in sync with documentary/.env DOC_LANGUAGE_CODE (and config.py).
const LANGUAGE_CODE = (process.env.DOC_LANGUAGE_CODE || "hi").trim();

function log(msg) {
  process.stdout.write(`[${CHANNEL_LABEL}] ${msg}\n`);
}

function parseArgs(argv) {
  const get = (flag) => {
    const a = argv.find((x) => x === flag || x.startsWith(flag + "="));
    if (!a) return undefined;
    return a.includes("=") ? a.split("=")[1] : argv[argv.indexOf(a) + 1];
  };
  const privacy = (get("--privacy") || process.env.DOC_PUBLISH_PRIVACY || "private").trim();
  if (!["private", "unlisted", "public"].includes(privacy)) {
    throw new Error(`--privacy must be private|unlisted|public (got "${privacy}")`);
  }
  return { dryRun: argv.includes("--dry-run"), privacy };
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

function chooseIndex(v, n) {
  const m = /[123]/.exec(v || "");
  if (!m) return null;
  const i = Number(m[0]);
  return i >= 1 && i <= n ? i : null;
}

// Resolve the publishable fields from a row's scene_breakdown JSON blob. Prefers the
// values Phase 8 finalize already locked in (final_title/final_thumbnail); falls back
// to resolving title_choice/thumbnail_choice against the variant lists.
function resolveEpisodeFields(sb, titleChoice, thumbChoice) {
  const meta = sb.metadata || {};
  const titles = meta.titles || [];
  const thumbs = meta.thumbnails || [];
  const ti = chooseIndex(titleChoice, titles.length);
  const thi = chooseIndex(thumbChoice, thumbs.length);
  return {
    videoFilePath: sb.video_file_path,
    title: meta.final_title || (ti ? titles[ti - 1] : titles[0]),
    thumbnailPath: meta.final_thumbnail || (thi ? thumbs[thi - 1] : null),
    description: meta.description,
    tags: meta.tags || [],
    captions: meta.captions || {}, // { "hi": "…/captions.hi.srt", "en": "…" }
    youtubeVideoId: meta.youtube_video_id || null,
  };
}

// ─── Episode source: this channel's Google Sheet, or the local mirror ────────────
async function loadReadyEpisode() {
  if (!process.env.DOC_SHEET_ID) {
    // Local mirror (same file the Python phases use). Array of row objects.
    const path = resolve(HERE, "data", "topics_mirror.json");
    if (!existsSync(path)) {
      log("no DOC_SHEET_ID and no local mirror — nothing to publish.");
      return null;
    }
    const rows = JSON.parse(readFileSync(path, "utf-8"));
    const idx = rows.findIndex((r) => (r.status || "").trim() === "ready");
    if (idx === -1) {
      log("no row with status='ready' in the local mirror — nothing to publish.");
      return null;
    }
    const r = rows[idx];
    const sb = JSON.parse(r.scene_breakdown || "{}");
    const f = resolveEpisodeFields(sb, r.title_choice, r.thumbnail_choice);
    return { source: "mirror", path, rows, idx, row: r, sb, ...f };
  }
  // Sheet mode.
  const { google } = await import("googleapis");
  const { GoogleAuth } = await import("google-auth-library");
  const sheetId = process.env.DOC_SHEET_ID;
  const tab = process.env.DOC_WORKSHEET || "documentary";
  const auth = new GoogleAuth({
    keyFile: process.env.DOC_SERVICE_ACCOUNT_JSON || process.env.GOOGLE_SERVICE_ACCOUNT_JSON,
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
  const sb = JSON.parse(r[col("scene_breakdown")] || "{}");
  const f = resolveEpisodeFields(sb, r[col("title_choice")], r[col("thumbnail_choice")]);
  return { source: "sheet", sheets, sheetId, tab, header, rowNumber: idx + 1, sb, ...f };
}

async function markPublished(ep, videoId, channel = {}) {
  // Record the id + owning channel inside the scene_breakdown metadata blob (there is
  // no dedicated youtube_video_id column) and flip status to published.
  ep.sb.metadata = ep.sb.metadata || {};
  ep.sb.metadata.youtube_video_id = videoId;
  ep.sb.metadata.published_channel = {
    channel_id: channel.channelId ?? null,
    channel_title: channel.channelTitle ?? null,
    channel_label: CHANNEL_LABEL,
    token_env: TOKEN_ENV,
  };
  const sbJson = JSON.stringify(ep.sb, null, 2);

  if (ep.source === "mirror") {
    ep.row.scene_breakdown = sbJson;
    ep.row.status = "published";
    writeFileSync(ep.path, JSON.stringify(ep.rows, null, 2));
    return;
  }
  const A1 = (colName) => {
    const c = ep.header.indexOf(colName);
    return c === -1 ? null : `${ep.tab}!${String.fromCharCode(65 + c)}${ep.rowNumber}`;
  };
  const updates = [
    [A1("scene_breakdown"), sbJson],
    [A1("status"), "published"],
  ].filter(([a1]) => a1);
  for (const [range, value] of updates) {
    await ep.sheets.spreadsheets.values.update({
      spreadsheetId: ep.sheetId,
      range,
      valueInputOption: "USER_ENTERED",
      requestBody: { values: [[value]] },
    });
  }
}

async function notify(text) {
  const token = process.env.TELEGRAM_DOC_BOT_TOKEN;
  const chat = process.env.TELEGRAM_DOC_CHAT_ID;
  const msg = `🎬 [${CHANNEL_LABEL}] ${text}`;
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
  log(`notify: ${msg}  (set TELEGRAM_DOC_BOT_TOKEN + TELEGRAM_DOC_CHAT_ID to send)`);
}

class YouTubeMcp {
  constructor(client) {
    this.client = client;
  }
  static async connect({ mock, token }) {
    const root = resolve(process.env.YOUTUBE_MCP_ROOT || resolve(HERE, ".."));
    const tsx = resolve(root, "node_modules/.bin/tsx");
    const server = resolve(root, "src/mcp/youtube-server.ts");
    if (!existsSync(server)) throw new Error(`YouTube MCP server not found at ${server} (set YOUTUBE_MCP_ROOT).`);
    const transport = new StdioClientTransport({
      command: tsx,
      args: [server],
      cwd: root,
      // Inject THIS channel's token as the server's YOUTUBE_REFRESH_TOKEN — the
      // isolation boundary. The kids/history tokens are never placed here.
      env: {
        ...process.env,
        YOUTUBE_REFRESH_TOKEN: token || "",
        YOUTUBE_MOCK: mock ? "1" : "0",
        YOUTUBE_MOCK_CHANNEL_LABEL: CHANNEL_LABEL, // so mock channel-check echoes this channel
      },
      stderr: "inherit",
    });
    const client = new Client({ name: "documentary-orchestrator", version: "0.1.0" });
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
  const token = process.env[TOKEN_ENV]?.trim() || "";
  // MOCK only when EXPLICITLY requested (--dry-run). A real run with no token REFUSES
  // rather than silently mocking (which would falsely mark the row published).
  const mock = args.dryRun;
  if (!mock && !token) {
    throw new Error(
      `Refusing to publish: ${TOKEN_ENV} is not set. This channel must use its OWN token — ` +
        "never the kids or history channels'. Use --dry-run to test in mock mode.",
    );
  }

  const ep = await loadReadyEpisode();
  if (!ep) return; // nothing 'ready' — normal, exit cleanly
  log(`episode: "${ep.title}"  video=${ep.videoFilePath}`);

  // Double-publish guard.
  if (ep.youtubeVideoId) {
    log(`already published as ${ep.youtubeVideoId} — skipping (double-publish guard).`);
    return;
  }
  for (const [k, v] of Object.entries({
    video_file_path: ep.videoFilePath,
    "thumbnail (chosen)": ep.thumbnailPath,
    "title (chosen)": ep.title,
    description: ep.description,
  })) {
    if (!v) throw new Error(`Episode is missing ${k} — cannot publish. (Did Phase 8 finalize run?)`);
  }
  if (!mock && !existsSync(ep.videoFilePath)) throw new Error(`Video file missing: ${ep.videoFilePath}`);

  const hasAttribution = /via Jamendo/i.test(ep.description || "");
  log(`mode=${mock ? "MOCK (no real upload)" : "LIVE"}  token=${tokenFingerprint(token)} (from ${TOKEN_ENV})`);
  log(`made_for_kids=${MADE_FOR_KIDS}  privacy=${args.privacy}  language=${LANGUAGE_CODE}  category=27(Education)`);
  log(`title="${ep.title}"  thumbnail=${ep.thumbnailPath}`);
  log(`description Jamendo attribution present: ${hasAttribution ? "yes ✅" : "NO ⚠️"}  tags=${ep.tags.length}`);

  const yt = await YouTubeMcp.connect({ mock, token });
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
          language: LANGUAGE_CODE,
        }),
      "upload_video",
    );
    const videoId = up.videoId || up.video_id;
    log(`✅ uploaded video_id=${videoId}  url=https://youtu.be/${videoId}`);
    // Channel identity straight from the upload response — confirms WHICH channel.
    log(`   published to channel: "${up.channelTitle ?? "?"}" (${up.channelId ?? "?"})`);

    // Arm the double-publish guard (record id + status) BEFORE the thumbnail, so a
    // thumbnail failure can't cause a duplicate re-upload on the next run.
    await markPublished(ep, videoId, up);
    log(`status=published (video_id + channel recorded — double-publish guard armed)`);

    try {
      await withRetry(() => yt.call("set_thumbnail", { video_id: videoId, thumbnail_path: ep.thumbnailPath }),
        "set_thumbnail");
      log(`thumbnail set from ${ep.thumbnailPath}`);
    } catch (e) {
      log(`⚠️ thumbnail failed (video already published as ${videoId}): ${e?.message}. Set manually; NOT re-uploading.`);
    }

    // Caption tracks (Phase 8 wrote SRTs per language). Non-fatal: a caption failure
    // must never undo an otherwise-successful publish.
    const captionEntries = Object.entries(ep.captions || {}).filter(([, p]) => p && existsSync(p));
    if (captionEntries.length === 0) {
      log("captions: none found in metadata — skipping (video will rely on auto-captions).");
    }
    for (const [lang, srtPath] of captionEntries) {
      try {
        await withRetry(() => yt.call("set_captions", { video_id: videoId, srt_path: srtPath, language: lang }),
          `set_captions:${lang}`);
        log(`caption track uploaded: ${lang} (${srtPath})`);
      } catch (e) {
        log(`⚠️ caption ${lang} failed (video still published): ${e?.message}`);
      }
    }

    // Channel confirmation. The MCP upload response has no channel id, so we confirm
    // which of the three channels this landed on two ways: (1) the distinct token
    // used (below), and (2) the channel's most-recent upload should now be this video.
    try {
      const recent = await yt.call("list_recent_uploads", { limit: 1 });
      const top = (recent.uploads || [])[0];
      const match = top && (top.videoId === videoId) ? "✅ matches this upload" : "⚠️ does NOT match — check channel!";
      log(`channel check — token=${tokenFingerprint(token)} (${TOKEN_ENV}); newest upload on that channel: ` +
          `${JSON.stringify(top)} ${match}`);
    } catch (e) {
      log(`channel check skipped (${e?.message})`);
    }

    await notify(
      `"${ep.title}" uploaded as ${args.privacy} (made_for_kids=${MADE_FOR_KIDS}) → https://youtu.be/${videoId}. ` +
        `Verify it's on the Documentary channel, then flip to public.`,
    );
  } finally {
    await yt.close();
  }
}

main().catch((err) => {
  process.stderr.write(`[${CHANNEL_LABEL}] FATAL: ${err?.stack || err}\n`);
  process.exit(1);
});
