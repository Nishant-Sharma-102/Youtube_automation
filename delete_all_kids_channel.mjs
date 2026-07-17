// One-off: permanently delete the 10 pre-existing videos on channel "Minimagictvvv".
// EXPLICITLY authorized by the channel owner, INCLUDING the 4 Hindi history episodes
// and the 2 formerly KEEP-listed IDs. Keeps ONLY the newly uploaded rhyme.
// Irreversible (YouTube videos.delete). Uses the kids token (force-ssl scope).
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
const NEVER_TOUCH = "uUYWydHO_AI"; // the video just uploaded — must survive

const DELETE = [
  "mbtrxGr5Kio", // Count 1 to 5 with Milo
  "4Dh38VH4Suk", // Kohinoor (history)
  "uXiGA8AUNq0", // Ashoka (history)
  "dcCbKD1pNDA", // Chandragupta & Chanakya (history, was KEEP-listed)
  "p4xgX90NRNs", // Rome (history, was KEEP-listed)
  "Q3o1UGWv5CU", // Friendship
  "bLiOZnp4MHI", // Days of the Week
  "yYHAdwyXCsg", // Colors
  "xNZHV67k5Tw", // Meet New Friends
  "9y0FEPXBNEg", // Learn Colors
];

const clientId = envFrom(`${ROOT}/.env`, "YOUTUBE_CLIENT_ID");
const clientSecret = envFrom(`${ROOT}/.env`, "YOUTUBE_CLIENT_SECRET");
const refreshToken = envFrom(`${ROOT}/.env`, "YOUTUBE_REFRESH_TOKEN");
if (!clientId || !clientSecret || !refreshToken) throw new Error("missing kids client creds / refresh token");

const oauth = new google.auth.OAuth2(clientId, clientSecret);
oauth.setCredentials({ refresh_token: refreshToken });
const yt = google.youtube({ version: "v3", auth: oauth });

let ok = 0, fail = 0;
for (const id of DELETE) {
  if (id === NEVER_TOUCH) { console.log(`SKIP protected new upload ${id}`); continue; }
  try {
    await yt.videos.delete({ id });
    console.log(`✅ deleted ${id}`);
    ok++;
  } catch (e) {
    console.log(`❌ failed ${id}: ${e?.errors?.[0]?.reason || e?.message}`);
    fail++;
  }
}
console.log(`\nDone. deleted=${ok} failed=${fail}. Kept: ${NEVER_TOUCH}`);
