// OAuth2 client for the YouTube Data API. Credentials come from env (../.env) —
// never hardcoded. Refresh token is obtained once, out of band.
import { google } from "googleapis";
import type { Config } from "./config.js";

// upload + thumbnail need youtube.upload; captions/read/privacy need youtube.force-ssl.
export const SCOPES = [
  "https://www.googleapis.com/auth/youtube.upload",
  "https://www.googleapis.com/auth/youtube.force-ssl",
];

export function authedClient(cfg: Config) {
  const { clientId, clientSecret, refreshToken, redirectUri } = cfg.youtube;
  if (!clientId || !clientSecret) throw new Error("YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET not set");
  if (!refreshToken) throw new Error("YOUTUBE_REFRESH_TOKEN not set (obtain it once, store in ../.env)");
  const client = new google.auth.OAuth2(clientId, clientSecret, redirectUri);
  client.setCredentials({ refresh_token: refreshToken });
  return client;
}
