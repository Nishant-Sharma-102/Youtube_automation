// YouTube Data API v3 wrapper (real + mock). The MCP server exposes these as tools.
import { createReadStream, existsSync, statSync } from "node:fs";
import { basename } from "node:path";
import { google, type youtube_v3 } from "googleapis";
import type { Config } from "./config.js";
import { authedClient } from "./youtube-auth.js";

export type Privacy = "private" | "unlisted" | "public";

export interface UploadParams {
  filePath: string; title: string; description: string; tags: string[];
  madeForKids: boolean; privacyStatus: Privacy;
}
export interface RecentUpload { videoId: string; title: string; publishedAt: string; }

export interface YouTubeService {
  uploadVideo(p: UploadParams): Promise<{ videoId: string }>;
  setThumbnail(videoId: string, thumbnailPath: string): Promise<void>;
  getUploadStatus(videoId: string): Promise<{ uploadStatus: string; processingStatus: string }>;
  listRecentUploads(limit: number): Promise<RecentUpload[]>;
}

function assertFile(p: string, kind: string): void {
  if (!existsSync(p) || !statSync(p).isFile()) throw new Error(`${kind} not found: ${p}`);
}

export class RealYouTubeService implements YouTubeService {
  private yt: youtube_v3.Youtube;
  constructor(cfg: Config) { this.yt = google.youtube({ version: "v3", auth: authedClient(cfg) }); }

  async uploadVideo(p: UploadParams): Promise<{ videoId: string }> {
    assertFile(p.filePath, "Video");
    // googleapis performs a resumable upload for a streamed media body (reliability).
    const res = await this.yt.videos.insert({
      part: ["snippet", "status"],
      requestBody: {
        snippet: { title: p.title, description: p.description, tags: p.tags, categoryId: "27" },
        status: { privacyStatus: p.privacyStatus, selfDeclaredMadeForKids: p.madeForKids },
      },
      media: { body: createReadStream(p.filePath) },
    });
    const videoId = res.data.id;
    if (!videoId) throw new Error("upload returned no video id");
    return { videoId };
  }

  async setThumbnail(videoId: string, thumbnailPath: string): Promise<void> {
    assertFile(thumbnailPath, "Thumbnail");
    await this.yt.thumbnails.set({ videoId, media: { body: createReadStream(thumbnailPath) } });
  }

  async getUploadStatus(videoId: string): Promise<{ uploadStatus: string; processingStatus: string }> {
    const res = await this.yt.videos.list({ part: ["status", "processingDetails"], id: [videoId] });
    const it = res.data.items?.[0];
    return {
      uploadStatus: it?.status?.uploadStatus ?? "unknown",
      processingStatus: it?.processingDetails?.processingStatus ?? "unknown",
    };
  }

  async listRecentUploads(limit: number): Promise<RecentUpload[]> {
    const res = await this.yt.search.list({
      part: ["snippet"], forMine: true, type: ["video"], order: "date",
      maxResults: Math.min(Math.max(limit, 1), 50),
    });
    return (res.data.items ?? []).map((i) => ({
      videoId: i.id?.videoId ?? "", title: i.snippet?.title ?? "", publishedAt: i.snippet?.publishedAt ?? "",
    }));
  }
}

export class MockYouTubeService implements YouTubeService {
  private n = 0; private uploads: RecentUpload[] = [];
  async uploadVideo(p: UploadParams) { assertFile(p.filePath, "Video"); const videoId = `MOCK_${++this.n}_${basename(p.filePath)}`; this.uploads.unshift({ videoId, title: p.title, publishedAt: "mock" }); return { videoId }; }
  async setThumbnail(_v: string, t: string) { assertFile(t, "Thumbnail"); }
  async getUploadStatus() { return { uploadStatus: "processed", processingStatus: "succeeded" }; }
  async listRecentUploads(limit: number) { return this.uploads.slice(0, limit); }
}

export function createYouTubeService(cfg: Config): YouTubeService {
  return cfg.youtube.mock ? new MockYouTubeService() : new RealYouTubeService(cfg);
}
