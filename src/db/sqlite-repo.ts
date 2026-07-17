import Database from "better-sqlite3";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ContentQueueRepo } from "./repo.js";
import type { ContentRow, GenerationResult, Status, EpisodeFormat } from "../types.js";
import { scheduledDateFor, type CalendarEpisode } from "../../data/calendar.js";
import { assertPublishableRender } from "../media/probe.js";

const SCHEMA_PATH = resolve(fileURLToPath(import.meta.url), "..", "schema.sql");

interface RawRow {
  id: number;
  video_number: number;
  topic: string;
  format: EpisodeFormat;
  scheduled_date: string | null;
  status: Status;
  title: string | null;
  description: string | null;
  tags: string;
  thumbnail_text: string | null;
  script: string | null;
  audio_path: string | null;
  video_file_path: string | null;
  thumbnail_path: string | null;
  youtube_video_id: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

function toRow(raw: RawRow): ContentRow {
  let tags: string[] = [];
  try {
    tags = JSON.parse(raw.tags);
  } catch {
    tags = [];
  }
  return {
    id: raw.id,
    videoNumber: raw.video_number,
    topic: raw.topic,
    format: raw.format,
    scheduledDate: raw.scheduled_date,
    status: raw.status,
    title: raw.title,
    description: raw.description,
    tags,
    thumbnailText: raw.thumbnail_text,
    script: raw.script,
    audioPath: raw.audio_path,
    videoFilePath: raw.video_file_path,
    thumbnailPath: raw.thumbnail_path,
    youtubeVideoId: raw.youtube_video_id,
    publishedAt: raw.published_at,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

export class SqliteContentQueueRepo implements ContentQueueRepo {
  private readonly db: Database.Database;

  constructor(dbPath: string) {
    mkdirSync(dirname(dbPath), { recursive: true });
    this.db = new Database(dbPath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("foreign_keys = ON");
    this.db.exec(readFileSync(SCHEMA_PATH, "utf8"));
    this.migrate();
  }

  /** Add columns introduced after a DB was first created (SQLite has no IF NOT EXISTS for ADD COLUMN). */
  private migrate(): void {
    const existing = new Set(
      (this.db.prepare(`PRAGMA table_info(content_queue)`).all() as { name: string }[]).map(
        (c) => c.name,
      ),
    );
    const columns: Record<string, string> = {
      audio_path: "TEXT",
      video_file_path: "TEXT",
      thumbnail_path: "TEXT",
      youtube_video_id: "TEXT",
      published_at: "TEXT",
    };
    for (const [name, type] of Object.entries(columns)) {
      if (!existing.has(name)) {
        this.db.exec(`ALTER TABLE content_queue ADD COLUMN ${name} ${type}`);
      }
    }
  }

  seed(episodes: CalendarEpisode[], launchDateIso: string): { inserted: number; skipped: number } {
    const insert = this.db.prepare(
      `INSERT OR IGNORE INTO content_queue (video_number, topic, format, scheduled_date, status)
       VALUES (@video_number, @topic, @format, @scheduled_date, 'draft')`,
    );
    let inserted = 0;
    let skipped = 0;
    const tx = this.db.transaction((eps: CalendarEpisode[]) => {
      for (const ep of eps) {
        const info = insert.run({
          video_number: ep.videoNumber,
          topic: ep.topic,
          format: ep.format,
          scheduled_date: scheduledDateFor(ep.dayOffset, launchDateIso),
        });
        if (info.changes > 0) inserted++;
        else skipped++;
      }
    });
    tx(episodes);
    return { inserted, skipped };
  }

  findNextDraft(): ContentRow | null {
    const raw = this.db
      .prepare(`SELECT * FROM content_queue WHERE status = 'draft' ORDER BY video_number LIMIT 1`)
      .get() as RawRow | undefined;
    return raw ? toRow(raw) : null;
  }

  getByVideoNumber(videoNumber: number): ContentRow | null {
    const raw = this.db
      .prepare(`SELECT * FROM content_queue WHERE video_number = ?`)
      .get(videoNumber) as RawRow | undefined;
    return raw ? toRow(raw) : null;
  }

  listByStatus(status: Status): ContentRow[] {
    const rows = this.db
      .prepare(`SELECT * FROM content_queue WHERE status = ? ORDER BY video_number`)
      .all(status) as RawRow[];
    return rows.map(toRow);
  }

  saveGenerated(videoNumber: number, result: GenerationResult): void {
    const info = this.db
      .prepare(
        `UPDATE content_queue
           SET title = @title,
               description = @description,
               tags = @tags,
               thumbnail_text = @thumbnail_text,
               script = @script,
               status = 'script_ready',
               updated_at = datetime('now')
         WHERE video_number = @video_number`,
      )
      .run({
        video_number: videoNumber,
        title: result.title,
        description: result.description,
        tags: JSON.stringify(result.tags),
        thumbnail_text: result.thumbnailText,
        script: result.script,
      });
    if (info.changes === 0) {
      throw new Error(`saveGenerated: no row with video_number=${videoNumber}`);
    }
  }

  updateStatus(videoNumber: number, status: Status): void {
    this.db
      .prepare(
        `UPDATE content_queue SET status = ?, updated_at = datetime('now') WHERE video_number = ?`,
      )
      .run(status, videoNumber);
  }

  setAudioPath(videoNumber: number, audioPath: string): void {
    const info = this.db
      .prepare(
        `UPDATE content_queue SET audio_path = ?, updated_at = datetime('now') WHERE video_number = ?`,
      )
      .run(audioPath, videoNumber);
    if (info.changes === 0) throw new Error(`setAudioPath: no row with video_number=${videoNumber}`);
  }

  attachRender(videoNumber: number, videoFilePath: string, thumbnailPath?: string | null): void {
    // Pre-flight: refuse to mark 'ready' if the render lacks audible audio.
    // Catches the "silent upload" bug before it can ever reach YouTube.
    assertPublishableRender(videoFilePath);

    const info = this.db
      .prepare(
        `UPDATE content_queue
           SET video_file_path = @video_file_path,
               thumbnail_path = @thumbnail_path,
               status = 'ready',
               updated_at = datetime('now')
         WHERE video_number = @video_number AND status = 'script_ready'`,
      )
      .run({
        video_number: videoNumber,
        video_file_path: videoFilePath,
        thumbnail_path: thumbnailPath ?? null,
      });
    if (info.changes === 0) {
      throw new Error(
        `attachRender: no 'script_ready' row with video_number=${videoNumber} (already ready/published, or not generated yet)`,
      );
    }
  }

  findReadyForPublish(dueOnOrBefore?: string): ContentRow[] {
    const sql = dueOnOrBefore
      ? `SELECT * FROM content_queue
           WHERE status = 'ready' AND (scheduled_date IS NULL OR scheduled_date <= ?)
           ORDER BY scheduled_date, video_number`
      : `SELECT * FROM content_queue WHERE status = 'ready' ORDER BY scheduled_date, video_number`;
    const stmt = this.db.prepare(sql);
    const rows = (dueOnOrBefore ? stmt.all(dueOnOrBefore) : stmt.all()) as RawRow[];
    return rows.map(toRow);
  }

  markPublished(videoNumber: number, youtubeVideoId: string, publishedAtIso: string): void {
    const info = this.db
      .prepare(
        `UPDATE content_queue
           SET youtube_video_id = @yid,
               published_at = @published_at,
               status = 'published',
               updated_at = datetime('now')
         WHERE video_number = @video_number`,
      )
      .run({ video_number: videoNumber, yid: youtubeVideoId, published_at: publishedAtIso });
    if (info.changes === 0) {
      throw new Error(`markPublished: no row with video_number=${videoNumber}`);
    }
  }

  close(): void {
    this.db.close();
  }
}
