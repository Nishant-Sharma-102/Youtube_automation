// One-off: delete specific videos from the HISTORY channel via YouTube Data API.
// Uses the history channel's refresh token (force-ssl scope permits videos.delete).
import { readFileSync } from "node:fs";
import { google } from "googleapis";

// --- hard allow/deny lists (safety) ---
const DELETE = ["gQ3HphCrgLM", "-sNUubXhqmo"];      // older Rome tests — remove
const KEEP = ["p4xgX90NRNs", "dcCbKD1pNDA"];        // real episodes — must NEVER be deleted

function envFrom(path, key) {
  for (const line of readFileSync(path, "utf-8").split("\n")) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m && m[1] === key) return m[2].replace(/^["']|["']$/g, "");
  }
  return "";
}

const ROOT = "/home/user/Documents/agentic_ai";
const clientId = envFrom(`${ROOT}/.env`, "YOUTUBE_CLIENT_ID");
const clientSecret = envFrom(`${ROOT}/.env`, "YOUTUBE_CLIENT_SECRET");
const refreshToken = envFrom(`${ROOT}/hindi-history/.env`, "YOUTUBE_HISTORY_CHANNEL_REFRESH_TOKEN");
if (!clientId || !clientSecret || !refreshToken) throw new Error("missing client creds or history refresh token");

const oauth = new google.auth.OAuth2(clientId, clientSecret);
oauth.setCredentials({ refresh_token: refreshToken });
const yt = google.youtube({ version: "v3", auth: oauth });

for (const id of DELETE) {
  if (KEEP.includes(id)) { console.log(`REFUSING to delete keep-listed ${id}`); continue; }
  try {
    await yt.videos.delete({ id });
    console.log(`✅ deleted ${id}`);
  } catch (e) {
    console.log(`❌ failed to delete ${id}: ${e?.errors?.[0]?.reason || e?.message}`);
  }
}
