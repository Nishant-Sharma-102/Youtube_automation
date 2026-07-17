"""Unified Google credential loading for Sheets + Cloud TTS.

Two supported credential types (service account preferred for headless/cron):
  1. Service account  -> GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_APPLICATION_CREDENTIALS
  2. OAuth user token -> token.json minted once by auth_setup.py from an OAuth client
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from config import Config

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TTS_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
# token.json is minted with the union so one consent covers both APIs.
ALL_SCOPES = SHEETS_SCOPES + TTS_SCOPES

_NO_CREDS = (
    "No Google credentials found. Either:\n"
    "  (a) set GOOGLE_SERVICE_ACCOUNT_JSON to a service-account key (headless, best for cron), or\n"
    "  (b) run `python auth_setup.py` once (browser) to create token.json from your OAuth client."
)


def project_id(cfg: Config) -> str | None:
    env = (os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if env:
        return env
    cf = cfg.oauth_client_file
    if cf and Path(cf).exists():
        data = json.loads(Path(cf).read_text(encoding="utf-8"))
        blk = data.get("installed") or data.get("web") or {}
        return blk.get("project_id")
    return None


def credentials_available(cfg: Config) -> str | None:
    if cfg.service_account_file and Path(cfg.service_account_file).exists():
        return "service_account"
    if cfg.oauth_token_file and Path(cfg.oauth_token_file).exists():
        return "oauth"
    return None


def load_google_credentials(cfg: Config, scopes: list[str], *, gcp_quota: bool = False):
    """Return google.auth credentials for the given scopes.

    gcp_quota=True attaches a quota/billing project (needed when calling a GCP
    service like Cloud TTS with OAuth *user* credentials)."""
    sa = cfg.service_account_file
    if sa and Path(sa).exists():
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(sa, scopes=scopes)

    tok = cfg.oauth_token_file
    if tok and Path(tok).exists():
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(tok, scopes)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                Path(tok).write_text(creds.to_json(), encoding="utf-8")
            else:
                raise SystemExit(
                    f"OAuth token {tok} is invalid and cannot refresh. Re-run `python auth_setup.py`."
                )
        if gcp_quota:
            pid = project_id(cfg)
            if pid:
                creds = creds.with_quota_project(pid)
        return creds

    raise SystemExit(_NO_CREDS)
