"""Google Sheets content queue for the Hindi history channel.

A NEW worksheet (tab), separate from the kids channel queue. Columns:
  topic | script_hindi | title_hindi | description_hindi | tags |
  scene_breakdown | status | scheduled_date

Auth is via a Google service account (headless-friendly, correct for cron on EC2):
share the target spreadsheet with the service account's client_email, then point
GOOGLE_SERVICE_ACCOUNT_JSON at its key file.
"""
from __future__ import annotations

import json

import gspread
from gspread.utils import rowcol_to_a1

from config import COLUMNS, Config
from gemini_client import Episode
from google_auth import SHEETS_SCOPES, load_google_credentials


class HistorySheet:
    def __init__(self, cfg: Config):
        # Works with a service account or an OAuth user token (see google_auth).
        self._gc = gspread.authorize(load_google_credentials(cfg, SHEETS_SCOPES))
        self._sh = self._gc.open_by_key(cfg.sheet_id)
        self._title = cfg.worksheet

    # -- worksheet / header management ------------------------------------------
    def ensure_worksheet(self, seed_topics: list[str] | None = None) -> None:
        """Create the tab if missing, write the header row, and optionally seed
        one or more draft topics. Safe to run repeatedly."""
        try:
            ws = self._sh.worksheet(self._title)
        except gspread.WorksheetNotFound:
            ws = self._sh.add_worksheet(title=self._title, rows=100, cols=len(COLUMNS))

        header = ws.row_values(1)
        if header != COLUMNS:
            ws.update(range_name=rowcol_to_a1(1, 1) + ":" + rowcol_to_a1(1, len(COLUMNS)),
                      values=[COLUMNS])

        for topic in seed_topics or []:
            existing = ws.col_values(1)  # topic column
            if topic in existing:
                continue
            row = [""] * len(COLUMNS)
            row[COLUMNS.index("topic")] = topic
            row[COLUMNS.index("status")] = "draft"
            ws.append_row(row, value_input_option="USER_ENTERED")

    def _ws(self):
        return self._sh.worksheet(self._title)

    def _header_map(self, ws) -> dict[str, int]:
        header = ws.row_values(1)
        return {name: i + 1 for i, name in enumerate(header)}  # 1-based column index

    # -- queue operations -------------------------------------------------------
    def get_next_draft(self) -> tuple[int, str] | None:
        """Return (row_number, topic) for the first row with status == 'draft'."""
        ws = self._ws()
        cols = self._header_map(ws)
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:], start=2):  # skip header; 1-based row numbers

            def cell(name: str) -> str:
                idx = cols.get(name)
                return row[idx - 1].strip() if idx and idx - 1 < len(row) else ""

            if cell("status").lower() == "draft" and cell("topic"):
                return i, cell("topic")
        return None

    def get_row_topic(self, row_number: int) -> str:
        ws = self._ws()
        cols = self._header_map(ws)
        return ws.cell(row_number, cols["topic"]).value or ""

    def write_result(self, row_number: int, ep: Episode) -> None:
        """Write the generated fields back to the row and set status=script_ready.
        topic and scheduled_date are left untouched."""
        ws = self._ws()
        cols = self._header_map(ws)
        values = {
            "script_hindi": ep.full_script,
            "title_hindi": ep.title,
            "description_hindi": ep.description,
            "tags": ", ".join(ep.tags),
            "scene_breakdown": json.dumps(
                [s.model_dump() for s in ep.scenes], ensure_ascii=False, indent=2
            ),
            "status": "script_ready",
        }
        updates = []
        for name, val in values.items():
            if name not in cols:
                raise SystemExit(
                    f"Sheet is missing the '{name}' column. Run with --init to fix the header."
                )
            updates.append({"range": rowcol_to_a1(row_number, cols[name]), "values": [[val]]})
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    # -- Phase 2 (voice) ---------------------------------------------------------
    def _scenes_at(self, ws, cols: dict[str, int], row_number: int) -> list[dict]:
        raw = ws.cell(row_number, cols["scene_breakdown"]).value or ""
        if not raw.strip():
            raise SystemExit(f"Row {row_number} has an empty scene_breakdown — run Phase 1 first.")
        try:
            scenes = json.loads(raw)
        except json.JSONDecodeError as e:
            raise SystemExit(f"scene_breakdown in row {row_number} is not valid JSON: {e}")
        if not isinstance(scenes, list):
            raise SystemExit(f"scene_breakdown in row {row_number} is not a JSON array.")
        return scenes

    def get_next_ready_for_audio(self) -> tuple[int, list[dict]] | None:
        """Return (row_number, scenes) for the first status=='script_ready' row."""
        ws = self._ws()
        cols = self._header_map(ws)
        rows = ws.get_all_values()
        status_idx = cols["status"] - 1
        for i, row in enumerate(rows[1:], start=2):
            status = row[status_idx].strip().lower() if status_idx < len(row) else ""
            if status == "script_ready":
                return i, self._scenes_at(ws, cols, i)
        return None

    def get_row_scenes(self, row_number: int) -> tuple[int, list[dict]]:
        ws = self._ws()
        cols = self._header_map(ws)
        return row_number, self._scenes_at(ws, cols, row_number)

    def write_audio_result(self, row_number: int, scenes: list[dict], audio_path: str) -> None:
        """Write scenes-with-durations back, store the full audio path, set audio_ready."""
        ws = self._ws()
        cols = self._header_map(ws)
        values = {
            "scene_breakdown": json.dumps(scenes, ensure_ascii=False, indent=2),
            "audio_path": audio_path,
            "status": "audio_ready",
        }
        updates = []
        for name, val in values.items():
            if name not in cols:
                raise SystemExit(f"Sheet is missing the '{name}' column. Run Phase 1 --init to fix the header.")
            updates.append({"range": rowcol_to_a1(row_number, cols[name]), "values": [[val]]})
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    # -- Phase 3 (illustrations) -------------------------------------------------
    def get_next_ready_for_images(self) -> tuple[int, list[dict]] | None:
        """Return (row_number, scenes) for the first status=='audio_ready' row."""
        ws = self._ws()
        cols = self._header_map(ws)
        rows = ws.get_all_values()
        status_idx = cols["status"] - 1
        for i, row in enumerate(rows[1:], start=2):
            status = row[status_idx].strip().lower() if status_idx < len(row) else ""
            if status == "audio_ready":
                return i, self._scenes_at(ws, cols, i)
        return None

    # -- Phase 4 (video) ---------------------------------------------------------
    def get_next_ready_for_video(self) -> tuple[int, list[dict]] | None:
        """Return (row_number, scenes) for the first status=='images_ready' row."""
        ws = self._ws()
        cols = self._header_map(ws)
        rows = ws.get_all_values()
        status_idx = cols["status"] - 1
        for i, row in enumerate(rows[1:], start=2):
            status = row[status_idx].strip().lower() if status_idx < len(row) else ""
            if status == "images_ready":
                return i, self._scenes_at(ws, cols, i)
        return None

    def write_video_result(self, row_number: int, video_path: str, thumbnail_path: str) -> None:
        """Store the render + thumbnail paths and set status=ready (Phase 5 picks this up)."""
        ws = self._ws()
        cols = self._header_map(ws)
        values = {
            "video_file_path": video_path,
            "thumbnail_path": thumbnail_path,
            "status": "ready",
        }
        updates = []
        for name, val in values.items():
            if name not in cols:
                raise SystemExit(f"Sheet is missing the '{name}' column. Run Phase 1 --init to fix the header.")
            updates.append({"range": rowcol_to_a1(row_number, cols[name]), "values": [[val]]})
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    def write_images_result(self, row_number: int, scenes: list[dict], images_map: dict) -> None:
        """Persist scenes (with image_path), the images_json map, set status=images_ready."""
        ws = self._ws()
        cols = self._header_map(ws)
        values = {
            "scene_breakdown": json.dumps(scenes, ensure_ascii=False, indent=2),
            "images_json": json.dumps(images_map, ensure_ascii=False, indent=2),
            "status": "images_ready",
        }
        updates = []
        for name, val in values.items():
            if name not in cols:
                raise SystemExit(f"Sheet is missing the '{name}' column. Run Phase 1 --init to fix the header.")
            updates.append({"range": rowcol_to_a1(row_number, cols[name]), "values": [[val]]})
        ws.batch_update(updates, value_input_option="USER_ENTERED")
