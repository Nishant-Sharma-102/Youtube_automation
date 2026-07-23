/**
 * Shorts publishing orchestrator.
 *
 * Publishes a vertical Short to the SAME channel as the documentary pipeline. There is
 * NO separate "upload Short" API on YouTube — a video is treated as a Short when it is
 * vertical (9:16) and short (≤ ~3 min). So this reuses the kids channel's YouTube MCP
 * server UNCHANGED and the documentary channel's OWN refresh token (channel isolation),
 * exactly like orchestrator_documentary.js — the only differences are the source file
 * (shorts/data/short_<id>.json) and a "#Shorts" hint appended to the title/description.
 *
 * Usage:
 *   node orchestrator_shorts.js --dry-run                 # mock, no real upload
 *   node orchestrator_shorts.js                            # newest status='ready' short (PRIVATE)
 *   node orchestrator_shorts.js --file data/short_7.json   # a specific short
 *   node orchestrator_shorts.js --privacy public           # explicit privacy
 */
import { existsSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = resolve(HERE, "data");

// Cron runs with a bare environment. Self-load the documentary channel's .env (it owns
// the token + language config this pipeline shares) then the repo-root .env, never
// overriding anything already set in the real environment.
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
loadDotenv(resolve(HERE, "..", "documentary", ".env"));
loadDotenv(resolve(HERE, "..", ".env"));

// General-audience, same as the documentary/history channels — NEVER made-for-kids.
const MADE_FOR_KIDS = false;
const CHANNEL_LABEL = "Documentary Channel (Shorts)";
// Same token as the documentary pipeline — Shorts land on the same channel.
const TOKEN_ENV = "YOUTUBE_DOCUMENTARY_CHANNEL_REFRESH_TOKEN";
const LANGUAGE_CODE = (process.env.DOC_LANGUAGE_CODE || "hi").trim();

const log = (m) => process.stdout.write(`[${CHANNEL_LABEL}] ${m}\n`);

function parseArgs(argv) {
  const get = (flag) => {
    const a = argv.find((x) => x === flag || x.startsWith(flag + "="));
    if (!a) return undefined;
    return a.includes("=") ? a.split("=")[1] : argv[argv.indexOf(a) + 1];
  };
  const privacy = (get("--privacy") || process.env.SHORTS_PUBLISH_PRIVACY || "private").trim();
  if (!["private", "unlisted", "public"].includes(privacy)) {
    throw new Error(`--privacy must be private|unlisted|public (got "${privacy}")`);
  }
  return { dryRun: argv.includes("--dry-run"), privacy, file: get("--file") };
}

async function withRetry(fn, label, { retries = 4 } = {}) {
  let lastErr;
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const delay = Math.min(2 ** (attempt - 1) * 1000, 30000);
      log(`  ${label} attempt ${attempt}/${retries} failed: ${err?.message || err}`);
      if (attempt < retries) await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw new Error(`${label} failed after ${retries} attempts: ${lastErr?.message || lastErr}`);
}

const tokenFingerprint = (t) => (t ? `${t.slice(0, 6)}…(${t.length} chars)` : "none");

// Append a "#Shorts" hint if it isn't already there — helps YouTube classify the video
// as a Short (the vertical + short-duration signals are the real drivers).
function withShortsHint(text) {
  return /#shorts\b/i.test(text || "") ? text : `${(text || "").trimEnd()}\n#Shorts`;
}

function loadReadyShort(explicitFile) {
  let path;
  if (explicitFile) {
    path = resolve(HERE, explicitFile);
    if (!existsSync(path)) throw new Error(`short file not found: ${path}`);
  } else {
    // Newest status='ready', not-yet-published short.
    const files = existsSync(DATA_DIR)
      ? readdirSync(DATA_DIR).filter((f) => /^short_\d+\.json$/.test(f)).sort()
      : [];
    for (const f of files.reverse()) {
      const d = JSON.parse(readFileSync(resolve(DATA_DIR, f), "utf-8"));
      if ((d.status || "").trim() === "ready" && !d.youtube_video_id) {
        path = resolve(DATA_DIR, f);
        break;
      }
    }
    if (!path) {
      log("no status='ready' short in shorts/data — nothing to publish.");
      return null;
    }
  }
  const rec = JSON.parse(readFileSync(path, "utf-8"));
  return { path, rec };
}

function markPublished(path, rec, videoId, channel = {}) {
  rec.youtube_video_id = videoId;
  rec.status = "published";
  rec.published_channel = {
    channel_id: channel.channelId ?? null,
    channel_title: channel.channelTitle ?? null,
    channel_label: CHANNEL_LABEL,
    token_env: TOKEN_ENV,
  };
  writeFileSync(path, JSON.stringify(rec, null, 2));
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
      env: {
        ...process.env,
        YOUTUBE_REFRESH_TOKEN: token || "",
        YOUTUBE_MOCK: mock ? "1" : "0",
        YOUTUBE_MOCK_CHANNEL_LABEL: CHANNEL_LABEL,
      },
      stderr: "inherit",
    });
    const client = new Client({ name: "shorts-orchestrator", version: "0.1.0" });
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
  const mock = args.dryRun;
  if (!mock && !token) {
    throw new Error(
      `Refusing to publish: ${TOKEN_ENV} is not set. Shorts use the documentary ` +
        "channel's OWN token. Use --dry-run to test in mock mode.",
    );
  }

  const loaded = loadReadyShort(args.file);
  if (!loaded) return;
  const { path, rec } = loaded;

  if (rec.youtube_video_id) {
    log(`already published as ${rec.youtube_video_id} — skipping (double-publish guard).`);
    return;
  }
  const title = withShortsHint(rec.title);
  const description = withShortsHint(rec.description);
  for (const [k, v] of Object.entries({ video_file_path: rec.video_file_path, title, description })) {
    if (!v) throw new Error(`Short is missing ${k} — cannot publish. (Did gen_short.py finish?)`);
  }
  if (!mock && !existsSync(rec.video_file_path)) throw new Error(`Video file missing: ${rec.video_file_path}`);

  log(`mode=${mock ? "MOCK (no real upload)" : "LIVE"}  token=${tokenFingerprint(token)} (from ${TOKEN_ENV})`);
  log(`made_for_kids=${MADE_FOR_KIDS}  privacy=${args.privacy}  language=${LANGUAGE_CODE}  category=27(Education)`);
  log(`title="${title.replace(/\n/g, " ")}"  video=${rec.video_file_path}  tags=${(rec.tags || []).length}`);

  const yt = await YouTubeMcp.connect({ mock, token });
  try {
    const up = await withRetry(
      () =>
        yt.call("upload_video", {
          file_path: rec.video_file_path,
          title,
          description,
          tags: [...new Set([...(rec.tags || []), "shorts", "short"])],
          made_for_kids: MADE_FOR_KIDS,
          privacy_status: args.privacy,
          category_id: "27",
          language: LANGUAGE_CODE,
          public_stats_viewable: false, // hide likes/view stats on the watch page
        }),
      "upload_video",
    );
    const videoId = up.videoId || up.video_id;
    log(`✅ uploaded video_id=${videoId}  url=https://youtu.be/${videoId}`);
    log(`   published to channel: "${up.channelTitle ?? "?"}" (${up.channelId ?? "?"})`);

    markPublished(path, rec, videoId, up);
    log("status=published (video_id + channel recorded — double-publish guard armed)");

    try {
      const recent = await yt.call("list_recent_uploads", { limit: 1 });
      const top = (recent.uploads || [])[0];
      const match = top && top.videoId === videoId ? "✅ matches this upload" : "⚠️ does NOT match — check channel!";
      log(`channel check — token=${tokenFingerprint(token)} (${TOKEN_ENV}); newest upload: ${JSON.stringify(top)} ${match}`);
    } catch (e) {
      log(`channel check skipped (${e?.message})`);
    }

    await notify(
      `Short "${rec.title}" uploaded as ${args.privacy} → https://youtu.be/${videoId}. ` +
        "Verify it shows as a Short on the Documentary channel, then flip to public.",
    );
  } finally {
    await yt.close();
  }
}

main().catch((err) => {
  process.stderr.write(`[${CHANNEL_LABEL}] FATAL: ${err?.stack || err}\n`);
  process.exit(1);
});
