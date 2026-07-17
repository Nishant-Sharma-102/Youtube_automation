import { createReadStream, existsSync, statSync } from "node:fs";
import { basename } from "node:path";

import { google, type youtube_v3 } from "googleapis";

import type { Config } from "../config.js";
import { buildAuthenticatedClient } from "./youtube-auth.js";

export type PrivacyStatus = "private" | "unlisted" | "public";

export interface UploadParams {
  filePath: string;
  title: string;
  description: string;
  tags: string[];
  madeForKids: boolean;
  privacyStatus: PrivacyStatus;
  /** YouTube video category id. Default "27" = Education. */
  categoryId: string;
  /** BCP-47 language of the title/description and audio, e.g. "en". */
  language: string;
}

export interface RecentUpload {
  videoId: string;
  title: string;
  publishedAt: string;
}

/** The tool surface exposed by the YouTube MCP server (brief §4.3). */
export interface YouTubeService {
  uploadVideo(p: UploadParams): Promise<{ videoId: string }>;
  setThumbnail(videoId: string, thumbnailPath: string): Promise<void>;
  /** Change privacy (public/unlisted/private). Requires the youtube.force-ssl scope. */
  setPrivacy(videoId: string, privacy: PrivacyStatus): Promise<void>;
  /** Upload an SRT caption track. Requires the youtube.force-ssl scope. */
  setCaptions(videoId: string, srtPath: string, language: string): Promise<void>;
  getUploadStatus(videoId: string): Promise<{ uploadStatus: string; processingStatus: string }>;
  listRecentUploads(limit: number): Promise<RecentUpload[]>;
}

function assertFile(path: string, kind: string): void {
  if (!existsSync(path) || !statSync(path).isFile()) {
    throw new Error(`${kind} not found at path: ${path}`);
  }
}

/** Real implementation, backed by YouTube Data API v3. */
export class RealYouTubeService implements YouTubeService {
  private readonly yt: youtube_v3.Youtube;

  constructor(cfg: Config) {
    this.yt = google.youtube({ version: "v3", auth: buildAuthenticatedClient(cfg) });
  }

  async uploadVideo(p: UploadParams): Promise<{ videoId: string }> {
    assertFile(p.filePath, "Video file");
    // googleapis performs a resumable upload for a streamed media body, which is
    // important for reliability on larger renders (brief §4.3).
    const res = await this.yt.videos.insert({
      part: ["snippet", "status"],
      requestBody: {
        snippet: {
          title: p.title,
          description: p.description,
          tags: p.tags,
          categoryId: p.categoryId,
          defaultLanguage: p.language,
          defaultAudioLanguage: p.language,
        },
        status: {
          privacyStatus: p.privacyStatus,
          selfDeclaredMadeForKids: p.madeForKids,
        },
      },
      // notifySubscribers defaults to true — subscribers get the upload notification.
      media: { body: createReadStream(p.filePath) },
    });
    const videoId = res.data.id;
    if (!videoId) throw new Error("Upload succeeded but no video id was returned");
    return { videoId };
  }

  async setThumbnail(videoId: string, thumbnailPath: string): Promise<void> {
    assertFile(thumbnailPath, "Thumbnail");
    await this.yt.thumbnails.set({ videoId, media: { body: createReadStream(thumbnailPath) } });
  }

  /** Change a video's privacy (public/unlisted/private), preserving made-for-kids. */
  async setPrivacy(videoId: string, privacy: PrivacyStatus): Promise<void> {
    const cur = await this.yt.videos.list({ part: ["status"], id: [videoId] });
    const status = cur.data.items?.[0]?.status;
    if (!status) throw new Error(`Video ${videoId} not found`);
    await this.yt.videos.update({
      part: ["status"],
      requestBody: {
        id: videoId,
        status: {
          privacyStatus: privacy,
          selfDeclaredMadeForKids: status.selfDeclaredMadeForKids, // don't clobber
          madeForKids: status.madeForKids,
        },
      },
    });
  }

  async setCaptions(videoId: string, srtPath: string, language: string): Promise<void> {
    assertFile(srtPath, "Caption file");
    await this.yt.captions.insert({
      part: ["snippet"],
      requestBody: { snippet: { videoId, language, name: "", isDraft: false } },
      media: { mimeType: "application/octet-stream", body: createReadStream(srtPath) },
    });
  }

  async getUploadStatus(videoId: string): Promise<{ uploadStatus: string; processingStatus: string }> {
    const res = await this.yt.videos.list({ part: ["status", "processingDetails"], id: [videoId] });
    const item = res.data.items?.[0];
    return {
      uploadStatus: item?.status?.uploadStatus ?? "unknown",
      processingStatus: item?.processingDetails?.processingStatus ?? "unknown",
    };
  }

  async listRecentUploads(limit: number): Promise<RecentUpload[]> {
    const res = await this.yt.search.list({
      part: ["snippet"],
      forMine: true,
      type: ["video"],
      order: "date",
      maxResults: Math.min(Math.max(limit, 1), 50),
    });
    return (res.data.items ?? []).map((i) => ({
      videoId: i.id?.videoId ?? "",
      title: i.snippet?.title ?? "",
      publishedAt: i.snippet?.publishedAt ?? "",
    }));
  }
}

/**
 * Mock implementation — no network, no credentials. Validates the file exists and
 * returns deterministic fake data so the whole pipeline is testable end-to-end.
 */
export class MockYouTubeService implements YouTubeService {
  private counter = 0;
  private readonly uploads: RecentUpload[] = [];

  async uploadVideo(p: UploadParams): Promise<{ videoId: string }> {
    assertFile(p.filePath, "Video file");
    this.counter += 1;
    const videoId = `MOCK_${this.counter.toString().padStart(4, "0")}_${basename(p.filePath)}`;
    this.uploads.unshift({ videoId, title: p.title, publishedAt: "mock" });
    return { videoId };
  }

  async setThumbnail(_videoId: string, thumbnailPath: string): Promise<void> {
    assertFile(thumbnailPath, "Thumbnail");
  }

  async setPrivacy(_videoId: string, _privacy: PrivacyStatus): Promise<void> {
    /* mock: no-op */
  }

  async setCaptions(_videoId: string, srtPath: string, _language: string): Promise<void> {
    assertFile(srtPath, "Caption file");
  }

  async getUploadStatus(): Promise<{ uploadStatus: string; processingStatus: string }> {
    return { uploadStatus: "processed", processingStatus: "succeeded" };
  }

  async listRecentUploads(limit: number): Promise<RecentUpload[]> {
    return this.uploads.slice(0, limit);
  }
}

export function createYouTubeService(cfg: Config): YouTubeService {
  return cfg.youtube.mock ? new MockYouTubeService() : new RealYouTubeService(cfg);
}
