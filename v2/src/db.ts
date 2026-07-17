// SQLite content queue — the pipeline's source of truth (mirrors the brief's Sheet
// columns: title, description, tags, thumbnail_url, video_file_path, status,
// scheduled_date), plus the fields each phase needs.
import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

export type Status = "draft" | "script_ready" | "voiced" | "ready" | "published";

export interface Episode {
  video_number: number;
  topic: string;
  format: string;
  title: string | null;
  description: string | null;
  tags: string[];
  variants: unknown[]; // the 3 title/description/tag variants (Phase 1)
  thumbnail_url: string | null;
  video_file_path: string | null;
  audio_path: string | null;
  script: string | null;
  status: Status;
  scheduled_date: string | null;
  youtube_video_id: string | null;
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS episodes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  video_number    INTEGER NOT NULL UNIQUE,
  topic           TEXT NOT NULL,
  format          TEXT NOT NULL,
  title           TEXT,
  description     TEXT,
  tags            TEXT NOT NULL DEFAULT '[]',
  variants        TEXT NOT NULL DEFAULT '[]',
  thumbnail_url   TEXT,
  video_file_path TEXT,
  audio_path      TEXT,
  script          TEXT,
  status          TEXT NOT NULL DEFAULT 'draft',
  scheduled_date  TEXT,
  youtube_video_id TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);`;

export function openDb(dbPath: string): Database.Database {
  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new Database(dbPath);
  db.pragma("journal_mode = WAL");
  db.exec(SCHEMA);
  return db;
}

interface Raw {
  video_number: number; topic: string; format: string;
  title: string | null; description: string | null; tags: string; variants: string;
  thumbnail_url: string | null; video_file_path: string | null; audio_path: string | null;
  script: string | null; status: Status; scheduled_date: string | null; youtube_video_id: string | null;
}

function toEpisode(r: Raw): Episode {
  const safe = (s: string) => { try { return JSON.parse(s); } catch { return []; } };
  return { ...r, tags: safe(r.tags), variants: safe(r.variants) };
}

/** Lowest-numbered episode with status = 'draft', or null. */
export function nextDraft(db: Database.Database): Episode | null {
  const r = db.prepare(`SELECT * FROM episodes WHERE status='draft' ORDER BY video_number LIMIT 1`).get() as Raw | undefined;
  return r ? toEpisode(r) : null;
}

export function getByNumber(db: Database.Database, n: number): Episode | null {
  const r = db.prepare(`SELECT * FROM episodes WHERE video_number=?`).get(n) as Raw | undefined;
  return r ? toEpisode(r) : null;
}

/** Next episode that has a script but no audio yet (Phase 2 target). */
export function nextForVoice(db: Database.Database): Episode | null {
  const r = db.prepare(
    `SELECT * FROM episodes WHERE status='script_ready' AND audio_path IS NULL ORDER BY video_number LIMIT 1`,
  ).get() as Raw | undefined;
  return r ? toEpisode(r) : null;
}

/** Phase 2 write-back: record the narration audio path. Status stays 'script_ready'
 * (per the brief's status set — Phase 3's render is what advances it to 'ready'). */
export function setAudio(db: Database.Database, n: number, audioPath: string): void {
  const info = db.prepare(
    `UPDATE episodes SET audio_path=?, updated_at=datetime('now') WHERE video_number=?`,
  ).run(audioPath, n);
  if (info.changes === 0) throw new Error(`setAudio: no episode #${n}`);
}

/** Phase 5: rows ready to publish (status='ready'), optionally due on/before a date. */
export function readyForPublish(db: Database.Database, dueOnOrBefore?: string): Episode[] {
  const sql = dueOnOrBefore
    ? `SELECT * FROM episodes WHERE status='ready' AND (scheduled_date IS NULL OR scheduled_date<=?) ORDER BY scheduled_date, video_number`
    : `SELECT * FROM episodes WHERE status='ready' ORDER BY scheduled_date, video_number`;
  const stmt = db.prepare(sql);
  const rows = (dueOnOrBefore ? stmt.all(dueOnOrBefore) : stmt.all()) as Raw[];
  return rows.map(toEpisode);
}

/** Phase 5 write-back: record the upload + advance to 'published'. */
export function markPublished(db: Database.Database, n: number, videoId: string): void {
  const info = db.prepare(
    `UPDATE episodes SET youtube_video_id=?, status='published', updated_at=datetime('now') WHERE video_number=?`,
  ).run(videoId, n);
  if (info.changes === 0) throw new Error(`markPublished: no episode #${n}`);
}

/** Phase 3 write-back: attach the render + thumbnail, advance to 'ready'. */
export function setReady(db: Database.Database, n: number, videoPath: string, thumbPath: string | null): void {
  const info = db.prepare(
    `UPDATE episodes SET video_file_path=@v, thumbnail_url=@t, status='ready', updated_at=datetime('now')
     WHERE video_number=@n AND status='script_ready'`,
  ).run({ n, v: videoPath, t: thumbPath });
  if (info.changes === 0) throw new Error(`setReady: no 'script_ready' episode #${n}`);
}

/** Phase 1 write-back: script + chosen metadata + all variants, then status='script_ready'. */
export function saveScript(
  db: Database.Database,
  n: number,
  data: { script: string; title: string; description: string; tags: string[]; variants: unknown[] },
): void {
  const info = db.prepare(
    `UPDATE episodes SET script=@script, title=@title, description=@description,
       tags=@tags, variants=@variants, status='script_ready', updated_at=datetime('now')
     WHERE video_number=@n AND status='draft'`,
  ).run({
    n, script: data.script, title: data.title, description: data.description,
    tags: JSON.stringify(data.tags), variants: JSON.stringify(data.variants),
  });
  if (info.changes === 0) throw new Error(`saveScript: no 'draft' episode #${n} (already generated?)`);
}
