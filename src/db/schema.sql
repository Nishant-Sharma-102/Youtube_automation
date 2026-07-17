-- Content queue for the Giggle Grove pipeline (brief Section 4.1).
-- Status moves: draft -> script_ready -> ready -> published.
CREATE TABLE IF NOT EXISTS content_queue (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  video_number   INTEGER NOT NULL UNIQUE,
  topic          TEXT    NOT NULL,
  format         TEXT    NOT NULL CHECK (format IN ('Educational', 'Story')),
  scheduled_date TEXT,
  status         TEXT    NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'script_ready', 'ready', 'published')),
  title          TEXT,
  description    TEXT,
  tags           TEXT    NOT NULL DEFAULT '[]',   -- JSON array
  thumbnail_text TEXT,
  script         TEXT,
  audio_path      TEXT,
  video_file_path TEXT,
  thumbnail_path  TEXT,
  youtube_video_id TEXT,
  published_at    TEXT,
  created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_content_queue_status ON content_queue(status);
