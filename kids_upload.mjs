// Upload a finished kids video to the KIDS channel via the YouTube MCP server.
// Uses the kids token (root .env YOUTUBE_REFRESH_TOKEN — NOT the history token) and
// forces made_for_kids=TRUE (COPPA compliance for child-directed content).
//   node kids_upload.mjs <episodeNumber> [privacy]
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { google } from "googleapis";

// This file lives at the repo root; derive ROOT from it so it runs on the host
// and in the Docker container (/app) unchanged. Override with KIDS_ROOT.
const ROOT = process.env.KIDS_ROOT || dirname(fileURLToPath(import.meta.url));
const N = process.argv[2] || "90";
const PRIVACY = process.argv[3] || "public";
const PLAYLIST_TITLE = process.env.KIDS_PLAYLIST || "Giggle Grove Rhymes";

// --- kids-token YouTube Data API client (for the playlist step; MCP has no playlist tool) ---
function envFrom(path, key) {
  for (const line of readFileSync(path, "utf-8").split("\n")) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m && m[1] === key) return m[2].replace(/^["']|["']$/g, "");
  }
  return "";
}
function ytClient() {
  const id = envFrom(`${ROOT}/.env`, "YOUTUBE_CLIENT_ID");
  const secret = envFrom(`${ROOT}/.env`, "YOUTUBE_CLIENT_SECRET");
  const refresh = envFrom(`${ROOT}/.env`, "YOUTUBE_REFRESH_TOKEN");
  const oauth = new google.auth.OAuth2(id, secret);
  oauth.setCredentials({ refresh_token: refresh });
  return google.youtube({ version: "v3", auth: oauth });
}
// Find the playlist by title (create once if missing), then add the video to it.
async function addToPlaylist(videoId, title) {
  const yt = ytClient();
  let playlistId, pageToken;
  do {
    const r = await yt.playlists.list({ part: ["snippet"], mine: true, maxResults: 50, pageToken });
    const hit = (r.data.items || []).find((p) => p.snippet?.title === title);
    if (hit) { playlistId = hit.id; break; }
    pageToken = r.data.nextPageToken;
  } while (pageToken);
  if (!playlistId) {
    const c = await yt.playlists.insert({
      part: ["snippet", "status"],
      requestBody: { snippet: { title }, status: { privacyStatus: "public" } },
    });
    playlistId = c.data.id;
    console.log(`[Kids] created playlist "${title}" (${playlistId})`);
  }
  await yt.playlistItems.insert({
    part: ["snippet"],
    requestBody: { snippet: { playlistId, resourceId: { kind: "youtube#video", videoId } } },
  });
  console.log(`[Kids] added to playlist "${title}"`);
}

const ep = JSON.parse(readFileSync(`${ROOT}/hindi-history/data/ep${N}.json`, "utf-8"));
const video = ep.video_file_path;
const thumb = ep.thumbnail_path;
const title = ep.title_hindi || ep.title;
if (!existsSync(video)) throw new Error(`video missing: ${video}`);
if (!title) throw new Error("empty title");

const tsx = resolve(ROOT, "node_modules/.bin/tsx");
const server = resolve(ROOT, "src/mcp/youtube-server.ts");
// cwd=ROOT so the server's dotenv loads the KIDS root .env (kids token, YOUTUBE_MOCK=0).
const transport = new StdioClientTransport({
  command: tsx, args: [server], cwd: ROOT,
  env: { ...process.env, YOUTUBE_MOCK: "0" }, stderr: "inherit",
});
const client = new Client({ name: "kids-uploader", version: "0.1.0" });
await client.connect(transport);

const call = async (name, args) => {
  const r = await client.callTool({ name, arguments: args });
  if (r.isError) throw new Error(`${name}: ${r.content?.[0]?.text ?? "error"}`);
  return r.structuredContent ?? JSON.parse(r.content?.[0]?.text ?? "{}");
};

console.log(`[Kids] uploading "${title}"  made_for_kids=TRUE  privacy=${PRIVACY}`);
const up = await call("upload_video", {
  file_path: video, title,
  description: ep.description_hindi || ep.description || "",
  tags: ep.tags || [],
  made_for_kids: true,          // hard TRUE — child-directed content
  privacy_status: PRIVACY,
  category_id: "1",             // Film & Animation
  language: "en",
});
const id = up.videoId || up.video_id;
console.log(`[Kids] ✅ uploaded video_id=${id}  url=https://youtu.be/${id}`);
if (thumb && existsSync(thumb)) {
  try { await call("set_thumbnail", { video_id: id, thumbnail_path: thumb }); console.log("[Kids] thumbnail set"); }
  catch (e) { console.log(`[Kids] thumbnail failed (video is up): ${e?.message}`); }
}
try { await addToPlaylist(id, PLAYLIST_TITLE); }
catch (e) { console.log(`[Kids] playlist add failed (video is up): ${e?.errors?.[0]?.reason || e?.message}`); }
try {
  const recent = await call("list_recent_uploads", { limit: 1 });
  console.log(`[Kids] channel check — most recent: ${JSON.stringify((recent.uploads||[])[0])}`);
} catch {}
await client.close();
console.log("[Kids] DONE");
