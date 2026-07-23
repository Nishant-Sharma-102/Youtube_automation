"""Google Sheets topic queue for the documentary channel.

A dedicated worksheet/tab, separate from the other two channels. Columns are
defined in config.COLUMNS. Auth accepts either a Google service account
(headless / cron friendly — SHARE the sheet with its client_email) or an OAuth
user token.

If no Google credentials or no DOC_SHEET_ID are configured, the pipeline still
runs end-to-end against a LOCAL MIRROR (documentary/data/topics_mirror.json) so
you can test topic generation before wiring up the Sheet. The public API is the
same either way, so `generate_topics.py` doesn't care which backend is live.
"""
from __future__ import annotations

import json
from pathlib import Path

from config import APPROVED_TRUE, COLUMNS, PROJECT_DIR, Config, google_creds_available

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MIRROR_PATH = PROJECT_DIR / "data" / "topics_mirror.json"


def _load_google_credentials(cfg: Config):
    """service_account first, then OAuth user token (auto-refresh)."""
    sa = cfg.service_account_file
    if sa and Path(sa).exists():
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(
            sa, scopes=SHEETS_SCOPES
        )
    tok = cfg.oauth_token_file
    if tok and Path(tok).exists():
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(tok, SHEETS_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                Path(tok).write_text(creds.to_json(), encoding="utf-8")
            else:
                raise SystemExit(
                    f"OAuth token {tok} is invalid and cannot refresh. Re-mint it."
                )
        return creds
    raise SystemExit("No Google credentials available.")


class TopicQueue:
    """Backend-agnostic topic queue. `.backend` is 'sheet' or 'mirror'."""

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self.backend = "mirror"
        self._ws = None
        if cfg.sheet_id and google_creds_available(cfg):
            self._connect_sheet(cfg)

    # -- connection -------------------------------------------------------------
    def _connect_sheet(self, cfg: Config) -> None:
        import gspread
        from gspread.utils import rowcol_to_a1

        self._gspread = gspread
        self._rowcol_to_a1 = rowcol_to_a1
        gc = gspread.authorize(_load_google_credentials(cfg))
        sh = gc.open_by_key(cfg.sheet_id)
        try:
            ws = sh.worksheet(cfg.worksheet)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=cfg.worksheet, rows=200, cols=len(COLUMNS))
        header = ws.row_values(1)
        if header != COLUMNS:
            ws.update(
                range_name=rowcol_to_a1(1, 1) + ":" + rowcol_to_a1(1, len(COLUMNS)),
                values=[COLUMNS],
            )
        self._ws = ws
        self.backend = "sheet"

    # -- mirror helpers ---------------------------------------------------------
    def _mirror_rows(self) -> list[dict]:
        if MIRROR_PATH.exists():
            return json.loads(MIRROR_PATH.read_text(encoding="utf-8"))
        return []

    def _write_mirror(self, rows: list[dict]) -> None:
        MIRROR_PATH.parent.mkdir(parents=True, exist_ok=True)
        MIRROR_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- public API -------------------------------------------------------------
    def existing_topics(self) -> list[str]:
        """Every topic already in the queue, ALL statuses (for dedup)."""
        if self.backend == "sheet":
            col = self._ws.col_values(COLUMNS.index("topic") + 1)
            return [t.strip() for t in col[1:] if t.strip()]  # skip header
        return [r.get("topic", "").strip() for r in self._mirror_rows()
                if r.get("topic", "").strip()]

    def next_approved(self) -> dict | None:
        """Return the first row with status == 'approved', or None.

        Result: {"ref": <opaque>, "topic", "pillar", "notes"}. `ref` is passed
        back to write_script() to update the same row.
        """
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            s_idx = COLUMNS.index("status")
            for i, row in enumerate(rows[1:], start=2):  # 1-based, skip header
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if cell("status").lower() == "approved" and cell("topic"):
                    return {"ref": ("sheet", i), "topic": cell("topic"),
                            "pillar": cell("pillar"), "notes": cell("notes")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if r.get("status", "").strip().lower() == "approved" and r.get("topic", "").strip():
                return {"ref": ("mirror", i), "topic": r["topic"].strip(),
                        "pillar": r.get("pillar", "").strip(),
                        "notes": r.get("notes", "").strip()}
        return None

    def next_script_ready(self) -> dict | None:
        """Return the first row with status == 'script_ready', including its full
        script text: {"ref", "topic", "pillar", "notes", "script"} or None."""
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if cell("status").lower() == "script_ready" and cell("topic"):
                    return {"ref": ("sheet", i), "topic": cell("topic"),
                            "pillar": cell("pillar"), "notes": cell("notes"),
                            "script": (row[COLUMNS.index("script")]
                                       if COLUMNS.index("script") < len(row) else "")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if r.get("status", "").strip().lower() == "script_ready" and r.get("topic", "").strip():
                return {"ref": ("mirror", i), "topic": r["topic"].strip(),
                        "pillar": r.get("pillar", "").strip(),
                        "notes": r.get("notes", "").strip(),
                        "script": r.get("script", "")}
        return None

    def next_storyboard_ready(self) -> dict | None:
        """First row with status == 'storyboard_ready', with its scene_breakdown JSON."""
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if cell("status").lower() == "storyboard_ready" and cell("topic"):
                    return {"ref": ("sheet", i), "topic": cell("topic"),
                            "pillar": cell("pillar"),
                            "scene_breakdown": (row[COLUMNS.index("scene_breakdown")]
                                                if COLUMNS.index("scene_breakdown") < len(row) else "")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if r.get("status", "").strip().lower() == "storyboard_ready" and r.get("topic", "").strip():
                return {"ref": ("mirror", i), "topic": r["topic"].strip(),
                        "pillar": r.get("pillar", "").strip(),
                        "scene_breakdown": r.get("scene_breakdown", "")}
        return None

    def next_audio_ready(self) -> dict | None:
        """First row with status == 'audio_ready', with its scene_breakdown JSON."""
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if cell("status").lower() == "audio_ready" and cell("topic"):
                    return {"ref": ("sheet", i), "topic": cell("topic"),
                            "pillar": cell("pillar"),
                            "scene_breakdown": (row[COLUMNS.index("scene_breakdown")]
                                                if COLUMNS.index("scene_breakdown") < len(row) else "")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if r.get("status", "").strip().lower() == "audio_ready" and r.get("topic", "").strip():
                return {"ref": ("mirror", i), "topic": r["topic"].strip(),
                        "pillar": r.get("pillar", "").strip(),
                        "scene_breakdown": r.get("scene_breakdown", "")}
        return None

    def next_music_ready(self) -> dict | None:
        """First row with status=='music_ready': {ref, topic, pillar, scene_breakdown}."""
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if cell("status").lower() == "music_ready" and cell("topic"):
                    return {"ref": ("sheet", i), "topic": cell("topic"), "pillar": cell("pillar"),
                            "scene_breakdown": (row[COLUMNS.index("scene_breakdown")]
                                                if COLUMNS.index("scene_breakdown") < len(row) else "")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if r.get("status", "").strip().lower() == "music_ready" and r.get("topic", "").strip():
                return {"ref": ("mirror", i), "topic": r["topic"].strip(),
                        "pillar": r.get("pillar", "").strip(),
                        "scene_breakdown": r.get("scene_breakdown", "")}
        return None

    def write_assembly(self, ref: tuple, scene_breakdown_json: str) -> None:
        """Store the assembly-augmented scenes JSON (with video_file_path +
        thumbnail_source_path inside it) and set status='assembly_ready'."""
        kind, loc = ref
        if kind == "sheet":
            self._ws.batch_update([
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("scene_breakdown") + 1),
                 "values": [[scene_breakdown_json]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["assembly_ready"]]},
            ], value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["scene_breakdown"] = scene_breakdown_json
            mirror[loc]["status"] = "assembly_ready"
            self._write_mirror(mirror)

    def next_assembly_ready(self) -> dict | None:
        """First row with status=='assembly_ready': {ref, topic, pillar, script,
        scene_breakdown} (thumbnail_source_path lives inside scene_breakdown)."""
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if cell("status").lower() == "assembly_ready" and cell("topic"):
                    return {"ref": ("sheet", i), "topic": cell("topic"), "pillar": cell("pillar"),
                            "script": (row[COLUMNS.index("script")] if COLUMNS.index("script") < len(row) else ""),
                            "scene_breakdown": (row[COLUMNS.index("scene_breakdown")]
                                                if COLUMNS.index("scene_breakdown") < len(row) else "")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if r.get("status", "").strip().lower() == "assembly_ready" and r.get("topic", "").strip():
                return {"ref": ("mirror", i), "topic": r["topic"].strip(), "pillar": r.get("pillar", "").strip(),
                        "script": r.get("script", ""), "scene_breakdown": r.get("scene_breakdown", "")}
        return None

    def write_metadata(self, ref: tuple, scene_breakdown_json: str) -> None:
        """Store metadata JSON blob and set status='metadata_ready'. Leaves
        title_choice / thumbnail_choice blank for the human to fill."""
        kind, loc = ref
        if kind == "sheet":
            self._ws.batch_update([
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("scene_breakdown") + 1),
                 "values": [[scene_breakdown_json]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["metadata_ready"]]},
            ], value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["scene_breakdown"] = scene_breakdown_json
            mirror[loc]["status"] = "metadata_ready"
            self._write_mirror(mirror)

    def next_metadata_ready(self) -> dict | None:
        """First status=='metadata_ready' row, including the human-entered
        title_choice / thumbnail_choice (may be blank) and the metadata JSON."""
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if cell("status").lower() == "metadata_ready" and cell("topic"):
                    return {"ref": ("sheet", i), "topic": cell("topic"),
                            "title_choice": cell("title_choice"),
                            "thumbnail_choice": cell("thumbnail_choice"),
                            "scene_breakdown": (row[COLUMNS.index("scene_breakdown")]
                                                if COLUMNS.index("scene_breakdown") < len(row) else "")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if r.get("status", "").strip().lower() == "metadata_ready" and r.get("topic", "").strip():
                return {"ref": ("mirror", i), "topic": r["topic"].strip(),
                        "title_choice": r.get("title_choice", "").strip(),
                        "thumbnail_choice": r.get("thumbnail_choice", "").strip(),
                        "scene_breakdown": r.get("scene_breakdown", "")}
        return None

    def write_ready(self, ref: tuple, scene_breakdown_json: str) -> None:
        """Finalize: store the resolved metadata JSON and set status='ready'."""
        kind, loc = ref
        if kind == "sheet":
            self._ws.batch_update([
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("scene_breakdown") + 1),
                 "values": [[scene_breakdown_json]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["ready"]]},
            ], value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["scene_breakdown"] = scene_breakdown_json
            mirror[loc]["status"] = "ready"
            self._write_mirror(mirror)

    def next_visuals_approved(self) -> dict | None:
        """First row that is status=='visuals_ready' AND has the `approved` column
        set to an affirmative value — the Phase 5 human review gate. Returns
        {ref, topic, pillar, scene_breakdown} or None."""
        def is_approved(v: str) -> bool:
            return v.strip().lower() in APPROVED_TRUE

        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            for i, row in enumerate(rows[1:], start=2):
                def cell(name: str) -> str:
                    idx = COLUMNS.index(name)
                    return row[idx].strip() if idx < len(row) else ""
                if (cell("status").lower() == "visuals_ready" and cell("topic")
                        and is_approved(cell("approved"))):
                    return {"ref": ("sheet", i), "topic": cell("topic"),
                            "pillar": cell("pillar"),
                            "scene_breakdown": (row[COLUMNS.index("scene_breakdown")]
                                                if COLUMNS.index("scene_breakdown") < len(row) else "")}
            return None
        for i, r in enumerate(self._mirror_rows()):
            if (r.get("status", "").strip().lower() == "visuals_ready"
                    and r.get("topic", "").strip() and is_approved(r.get("approved", ""))):
                return {"ref": ("mirror", i), "topic": r["topic"].strip(),
                        "pillar": r.get("pillar", "").strip(),
                        "scene_breakdown": r.get("scene_breakdown", "")}
        return None

    def write_music(self, ref: tuple, scene_breakdown_json: str) -> None:
        """Write the music-augmented scenes JSON back and set status='music_ready'."""
        kind, loc = ref
        if kind == "sheet":
            updates = [
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("scene_breakdown") + 1),
                 "values": [[scene_breakdown_json]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["music_ready"]]},
            ]
            self._ws.batch_update(updates, value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["scene_breakdown"] = scene_breakdown_json
            mirror[loc]["status"] = "music_ready"
            self._write_mirror(mirror)

    def write_visuals(self, ref: tuple, scene_breakdown_json: str) -> None:
        """Write the assets-augmented scenes JSON back and set status='visuals_ready'."""
        kind, loc = ref
        if kind == "sheet":
            updates = [
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("scene_breakdown") + 1),
                 "values": [[scene_breakdown_json]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["visuals_ready"]]},
            ]
            self._ws.batch_update(updates, value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["scene_breakdown"] = scene_breakdown_json
            mirror[loc]["status"] = "visuals_ready"
            self._write_mirror(mirror)

    def write_audio(self, ref: tuple, scene_breakdown_json: str) -> None:
        """Write the durations-augmented scenes JSON back and set status='audio_ready'."""
        kind, loc = ref
        if kind == "sheet":
            updates = [
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("scene_breakdown") + 1),
                 "values": [[scene_breakdown_json]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["audio_ready"]]},
            ]
            self._ws.batch_update(updates, value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["scene_breakdown"] = scene_breakdown_json
            mirror[loc]["status"] = "audio_ready"
            self._write_mirror(mirror)

    def write_storyboard(self, ref: tuple, scene_breakdown_json: str) -> None:
        """Write the scenes JSON into 'scene_breakdown' and set status='storyboard_ready'."""
        kind, loc = ref
        if kind == "sheet":
            updates = [
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("scene_breakdown") + 1),
                 "values": [[scene_breakdown_json]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["storyboard_ready"]]},
            ]
            self._ws.batch_update(updates, value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["scene_breakdown"] = scene_breakdown_json
            mirror[loc]["status"] = "storyboard_ready"
            self._write_mirror(mirror)

    def write_script(self, ref: tuple, script: str) -> None:
        """Write the script into the 'script' column and set status='script_ready'."""
        kind, loc = ref
        if kind == "sheet":
            updates = [
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("script") + 1),
                 "values": [[script]]},
                {"range": self._rowcol_to_a1(loc, COLUMNS.index("status") + 1),
                 "values": [["script_ready"]]},
            ]
            self._ws.batch_update(updates, value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror[loc]["script"] = script
            mirror[loc]["status"] = "script_ready"
            self._write_mirror(mirror)

    def append_drafts(self, topics: list[dict]) -> int:
        """Append accepted topics as new rows with status='draft'.

        Each dict: {topic, pillar, notes}. Exact-duplicate topics already in the
        queue are skipped (belt-and-suspenders on top of Claude's own dedup).
        Returns the number of rows actually written.
        """
        have = {t.lower() for t in self.existing_topics()}
        fresh = [t for t in topics if t["topic"].strip().lower() not in have]
        if not fresh:
            return 0

        if self.backend == "sheet":
            rows = []
            for t in fresh:
                row = [""] * len(COLUMNS)
                row[COLUMNS.index("topic")] = t["topic"].strip()
                row[COLUMNS.index("pillar")] = t.get("pillar", "").strip()
                row[COLUMNS.index("status")] = "draft"
                row[COLUMNS.index("notes")] = t.get("notes", "").strip()
                rows.append(row)
            self._ws.append_rows(rows, value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            for t in fresh:
                mirror.append({
                    "topic": t["topic"].strip(),
                    "pillar": t.get("pillar", "").strip(),
                    "script": "",
                    "scene_breakdown": "",
                    "status": "draft",
                    "approved": "",
                    "scheduled_date": "",
                    "notes": t.get("notes", "").strip(),
                })
            self._write_mirror(mirror)
        return len(fresh)

    def insert_approved_topic(self, topic: str, pillar: str, notes: str = "") -> None:
        """Append ONE topic already promoted to status='approved' (approved='yes') so
        the pipeline picks it up immediately — used by the on-demand web UI. Mirrors
        what cron-documentary.sh does when it promotes a draft."""
        topic, pillar, notes = topic.strip(), pillar.strip(), notes.strip()
        if not topic:
            raise ValueError("topic must not be empty")
        if self.backend == "sheet":
            row = [""] * len(COLUMNS)
            row[COLUMNS.index("topic")] = topic
            row[COLUMNS.index("pillar")] = pillar
            row[COLUMNS.index("status")] = "approved"
            row[COLUMNS.index("approved")] = "yes"
            row[COLUMNS.index("notes")] = notes
            self._ws.append_rows([row], value_input_option="USER_ENTERED")
        else:
            mirror = self._mirror_rows()
            mirror.append({
                "topic": topic, "pillar": pillar, "script": "", "scene_breakdown": "",
                "status": "approved", "approved": "yes", "scheduled_date": "",
                "notes": notes, "title_choice": "", "thumbnail_choice": "",
            })
            self._write_mirror(mirror)

    def has_active_topic(self) -> dict | None:
        """Return the first row in an ACTIVE (mid-flight) status, or None. Active =
        anything between approved and ready inclusive — used to refuse a second
        concurrent run and to report what the pipeline is currently working on."""
        active = {"approved", "script_ready", "storyboard_ready", "audio_ready",
                  "visuals_ready", "music_ready", "assembly_ready", "metadata_ready", "ready"}
        if self.backend == "sheet":
            rows = self._ws.get_all_values()
            s_idx, t_idx = COLUMNS.index("status"), COLUMNS.index("topic")
            for row in rows[1:]:
                st = (row[s_idx] if s_idx < len(row) else "").strip().lower()
                if st in active and (row[t_idx] if t_idx < len(row) else "").strip():
                    return {"topic": row[t_idx].strip(), "status": st}
            return None
        for r in self._mirror_rows():
            st = (r.get("status") or "").strip().lower()
            if st in active and (r.get("topic") or "").strip():
                return {"topic": r["topic"].strip(), "status": st}
        return None
