#!/usr/bin/env python3
"""One-time OAuth consent — mint a reusable token from your Google OAuth client.

Google Cloud TTS and Sheets can be driven by an OAuth *user* credential, but it
must be authorized once through a browser. Run this ONCE on a machine with a
browser:

    python auth_setup.py

It opens a consent page, then writes token.json (git-ignored) holding a refresh
token. After that the pipeline runs headlessly. For a server/EC2 with no browser,
run this on your laptop and copy token.json to the server — or, simpler, use a
service account (GOOGLE_SERVICE_ACCOUNT_JSON) and skip this entirely.

Prerequisites on the OAuth client's Google Cloud project:
  - Enable the **Google Sheets API** and the **Cloud Text-to-Speech API**.
  - Cloud TTS requires **billing enabled** on the project (the 1M/4M free tier
    still requires an active billing account).
  - Add your Google account as a **test user** on the OAuth consent screen if the
    app is in "testing" mode.
"""
from __future__ import annotations

from pathlib import Path

from config import load_config
from google_auth import ALL_SCOPES


def main() -> int:
    cfg = load_config()
    client = cfg.oauth_client_file
    if not client or not Path(client).exists():
        raise SystemExit(
            f"OAuth client file not found: {client}. Set GOOGLE_OAUTH_CLIENT_JSON to its path."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client, ALL_SCOPES)
    creds = flow.run_local_server(port=0)  # opens a browser for consent
    Path(cfg.oauth_token_file).write_text(creds.to_json(), encoding="utf-8")
    print(f"\n✅ Wrote {cfg.oauth_token_file}")
    print(f"   Scopes: {', '.join(ALL_SCOPES)}")
    print("   It is git-ignored. Copy it to your server for headless/cron use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
