// READ-ONLY: enumerate every video on the KIDS channel (uploads playlist).
// Does NOT delete anything. Uses the kids refresh token from root .env.
import { readFileSync } from "node:fs";
import { google } from "googleapis";

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
const refreshToken = envFrom(`${ROOT}/.env`, "YOUTUBE_REFRESH_TOKEN");
if (!clientId || !clientSecret || !refreshToken) throw new Error("missing kids client creds / refresh token");

const oauth = new google.auth.OAuth2(clientId, clientSecret);
oauth.setCredentials({ refresh_token: refreshToken });
const yt = google.youtube({ version: "v3", auth: oauth });

const ch = await yt.channels.list({ part: ["contentDetails", "snippet"], mine: true });
const chan = ch.data.items?.[0];
const uploads = chan?.contentDetails?.relatedPlaylists?.uploads;
console.log(`Channel: ${chan?.snippet?.title}  (uploads playlist: ${uploads})`);

let pageToken, all = [];
do {
  const r = await yt.playlistItems.list({ part: ["snippet", "contentDetails"], playlistId: uploads, maxResults: 50, pageToken });
  for (const it of r.data.items ?? []) {
    all.push({ id: it.contentDetails.videoId, title: it.snippet.title, publishedAt: it.contentDetails.videoPublishedAt });
  }
  pageToken = r.data.nextPageToken;
} while (pageToken);

console.log(`\nTotal videos on channel: ${all.length}\n`);
for (const v of all) console.log(`  ${v.id}  ${v.publishedAt ?? "?"}  ${v.title}`);
