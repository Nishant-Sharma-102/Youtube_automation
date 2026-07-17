/**
 * One-time helper: obtain a YouTube OAuth2 refresh token.
 *
 *   npm run youtube:auth
 *
 * Prereqs (in .env): YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REDIRECT_URI.
 * The redirect URI must be listed as an authorized redirect URI on your OAuth client
 * (default http://localhost:5757/oauth2callback).
 *
 * Flow: prints a Google consent URL → you approve in a browser → Google redirects to
 * the local server started here → we exchange the code and print the refresh token.
 * Copy it into .env as YOUTUBE_REFRESH_TOKEN.
 */
import { createServer } from "node:http";
import { URL } from "node:url";

import { loadConfig } from "../config.js";
import { logger } from "../logger.js";
import { buildOAuthClient, YOUTUBE_SCOPES } from "./youtube-auth.js";

function main(): void {
  const cfg = loadConfig();
  const oauth = buildOAuthClient(cfg);
  const redirect = new URL(cfg.youtube.redirectUri);
  const port = Number(redirect.port || 80);

  const authUrl = oauth.generateAuthUrl({
    access_type: "offline", // required to receive a refresh token
    prompt: "consent", // force a refresh token even on re-auth
    scope: YOUTUBE_SCOPES,
  });

  const server = createServer(async (req, res) => {
    if (!req.url || !req.url.startsWith(redirect.pathname)) {
      res.writeHead(404).end("Not found");
      return;
    }
    const code = new URL(req.url, `http://localhost:${port}`).searchParams.get("code");
    if (!code) {
      res.writeHead(400).end("Missing ?code");
      return;
    }
    try {
      const { tokens } = await oauth.getToken(code);
      res.writeHead(200, { "Content-Type": "text/plain" });
      res.end("Success! You can close this tab and return to the terminal.");
      if (tokens.refresh_token) {
        logger.info("Refresh token obtained. Add this line to your .env:");
        console.log(`\nYOUTUBE_REFRESH_TOKEN=${tokens.refresh_token}\n`);
      } else {
        logger.warn(
          "No refresh token returned. Revoke prior access and retry (we already force prompt=consent).",
        );
      }
    } catch (err) {
      logger.error("Token exchange failed", {
        error: err instanceof Error ? err.message : String(err),
      });
      res.writeHead(500).end("Token exchange failed — see terminal.");
    } finally {
      server.close();
    }
  });

  server.listen(port, () => {
    logger.info(`Waiting for OAuth redirect on ${cfg.youtube.redirectUri}`);
    console.log(`\nOpen this URL in your browser to authorize:\n\n${authUrl}\n`);
  });
}

main();
