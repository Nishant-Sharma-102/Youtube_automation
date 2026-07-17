import type { EpisodeFormat } from "../data/calendar.js";

export type { EpisodeFormat };

/** Pipeline status, per brief Section 4.1: draft → script_ready → ready → published. */
export type Status = "draft" | "script_ready" | "ready" | "published";

/** A row in the content queue. */
export interface ContentRow {
  id: number;
  videoNumber: number;
  topic: string;
  format: EpisodeFormat;
  scheduledDate: string | null;
  status: Status;
  title: string | null;
  description: string | null;
  tags: string[];
  thumbnailText: string | null;
  script: string | null;
  /** Local path to the narration audio (set by the voice stage, Phase 2). */
  audioPath: string | null;
  /** Local path to the rendered video file (set by the animator before publish). */
  videoFilePath: string | null;
  /** Local path to the thumbnail image. */
  thumbnailPath: string | null;
  /** YouTube video id, populated after a successful upload. */
  youtubeVideoId: string | null;
  /** ISO timestamp of publish. */
  publishedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Output of the script-generation Gemini call. */
export interface GeneratedScript {
  script: string;
}

/** Output of the metadata-generation Gemini call (structured JSON). */
export interface GeneratedMetadata {
  title: string;
  description: string;
  tags: string[];
  thumbnailText: string;
}

/** Everything produced for one episode, ready to persist. */
export interface GenerationResult extends GeneratedScript, GeneratedMetadata {}
