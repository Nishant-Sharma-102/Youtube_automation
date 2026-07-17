/**
 * Media pre-flight checks for renders, using the bundled ffmpeg (ffmpeg-static).
 *
 * Purpose: never let a video reach YouTube without real audio. This catches both a
 * MISSING audio stream and a present-but-SILENT track (the classic "no sound on the
 * uploaded video" bug).
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import ffmpegPathImport from "ffmpeg-static";

// ffmpeg-static's default export is the binary path string (its .d.ts mistypes it).
const ffmpegPath = ffmpegPathImport as unknown as string | null;

/** dB threshold below which audio is treated as effectively silent. */
const SILENCE_MAX_DB = -70;

export interface AudioProbe {
  hasVideoStream: boolean;
  hasAudioStream: boolean;
  meanVolumeDb: number | null;
  maxVolumeDb: number | null;
  isSilent: boolean;
  /** The raw "Stream #..." lines (ffprobe-style summary of each stream). */
  streams: string[];
}

function ffmpegOutput(args: string[]): string {
  if (!ffmpegPath) throw new Error("ffmpeg-static binary not found — run `npm install`.");
  const r = spawnSync(ffmpegPath, args, { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  // ffmpeg writes stream/analysis info to stderr; capture both regardless of exit code.
  return `${r.stderr ?? ""}${r.stdout ?? ""}`;
}

export function probeAudio(filePath: string): AudioProbe {
  if (!existsSync(filePath)) throw new Error(`Render not found: ${filePath}`);

  const info = ffmpegOutput(["-hide_banner", "-i", filePath]);
  const streams = info
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => /^Stream #\d+:\d+.*: (Video|Audio):/.test(l));
  const hasVideoStream = /Stream #\d+:\d+.*: Video:/.test(info);
  const hasAudioStream = /Stream #\d+:\d+.*: Audio:/.test(info);

  let meanVolumeDb: number | null = null;
  let maxVolumeDb: number | null = null;
  if (hasAudioStream) {
    const vd = ffmpegOutput(["-hide_banner", "-i", filePath, "-af", "volumedetect", "-vn", "-f", "null", "-"]);
    meanVolumeDb = parseDb(vd, "mean_volume");
    maxVolumeDb = parseDb(vd, "max_volume");
  }
  const isSilent = maxVolumeDb === null ? true : maxVolumeDb <= SILENCE_MAX_DB;

  return { hasVideoStream, hasAudioStream, meanVolumeDb, maxVolumeDb, isSilent, streams };
}

function parseDb(text: string, key: string): number | null {
  const m = text.match(new RegExp(`${key}:\\s*(-?[\\d.]+) dB`));
  return m ? Number(m[1]) : null;
}

/**
 * Fail loudly unless the render has a video stream AND audible audio.
 * Set ALLOW_SILENT=1 to bypass the silence check (rare — e.g. intentional silent clip).
 */
export function assertPublishableRender(filePath: string): AudioProbe {
  const probe = probeAudio(filePath);
  if (!probe.hasVideoStream) {
    throw new Error(`Render "${filePath}" has no video stream — not a valid video file.`);
  }
  if (!probe.hasAudioStream) {
    throw new Error(
      `Render "${filePath}" has NO audio stream. Fix the export (include the voiceover track) before publishing.`,
    );
  }
  if (probe.isSilent && process.env.ALLOW_SILENT !== "1") {
    throw new Error(
      `Render "${filePath}" audio is SILENT (max volume ${probe.maxVolumeDb} dB). ` +
        `The voiceover is missing or muted. Re-export with audio, or set ALLOW_SILENT=1 to override.`,
    );
  }
  return probe;
}
