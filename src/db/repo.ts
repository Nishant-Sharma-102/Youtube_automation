import type { ContentRow, GenerationResult, Status } from "../types.js";
import type { CalendarEpisode } from "../../data/calendar.js";

/**
 * Storage seam for the content queue. Today only SqliteContentQueueRepo implements it,
 * but the generation logic depends ONLY on this interface — swap in Postgres/MySQL
 * later without touching generate.ts.
 */
export interface ContentQueueRepo {
  /** Create schema and insert calendar episodes as `draft` rows. Idempotent. */
  seed(episodes: CalendarEpisode[], launchDateIso: string): { inserted: number; skipped: number };

  /** Lowest video_number with status='draft', or null if none remain. */
  findNextDraft(): ContentRow | null;

  /** Fetch a single row by video number. */
  getByVideoNumber(videoNumber: number): ContentRow | null;

  /** All rows with the given status, ordered by video_number. */
  listByStatus(status: Status): ContentRow[];

  /** Persist generated script + metadata and set status='script_ready'. */
  saveGenerated(videoNumber: number, result: GenerationResult): void;

  /** Update just the status of a row. */
  updateStatus(videoNumber: number, status: Status): void;

  /** Record the narration audio path (Phase 2). Does NOT change status. */
  setAudioPath(videoNumber: number, audioPath: string): void;

  /**
   * Attach a rendered video (+ optional thumbnail) and move the row to 'ready'.
   * This is the animator handoff: 'script_ready' → 'ready'.
   */
  attachRender(videoNumber: number, videoFilePath: string, thumbnailPath?: string | null): void;

  /**
   * Rows ready to publish: status='ready' and (if `dueOnOrBefore` given) scheduled
   * on/before that ISO date. Ordered by scheduled_date then video_number.
   */
  findReadyForPublish(dueOnOrBefore?: string): ContentRow[];

  /** Record a successful upload and move the row to 'published'. */
  markPublished(videoNumber: number, youtubeVideoId: string, publishedAtIso: string): void;

  close(): void;
}
