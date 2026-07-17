import { google } from "googleapis";
import type { OAuth2Client } from "google-auth-library";

import type { Config } from "../config.js";

/**
 * Scopes: `youtube.upload` covers upload + thumbnail; `youtube.force-ssl` is
 * additionally required to insert captions (captions.insert) and to read
 * (get_upload_status / list_recent_uploads). Re-run `npm run youtube:auth` after
 * changing scopes so the refresh token is re-granted.
 */
export const YOUTUBE_SCOPES = [
  "https://www.googleapis.com/auth/youtube.upload",
  "https://www.googleapis.com/auth/youtube.force-ssl",
];

/** Build an OAuth2 client from config (no refresh token attached). */
export function buildOAuthClient(cfg: Config): OAuth2Client {
  const { clientId, clientSecret, redirectUri } = cfg.youtube;
  if (!clientId || !clientSecret) {
    throw new Error(
      "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET are not set. Add them to .env from your Google Cloud OAuth client.",
    );
  }
  return new google.auth.OAuth2(clientId, clientSecret, redirectUri);
}

/** Build an authenticated OAuth2 client using the stored refresh token. */
export function buildAuthenticatedClient(cfg: Config): OAuth2Client {
  const client = buildOAuthClient(cfg);
  if (!cfg.youtube.refreshToken) {
    throw new Error(
      "YOUTUBE_REFRESH_TOKEN is not set. Run `npm run youtube:auth` once to obtain it.",
    );
  }
  client.setCredentials({ refresh_token: cfg.youtube.refreshToken });
  return client;
}
