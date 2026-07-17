// Media stream guard (ffmpeg): confirm a render has BOTH video and audible audio
// before it can be marked 'ready'. Guards against the silent-audio bug.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import ffmpegPathImport from "ffmpeg-static";

const FF = ffmpegPathImport as unknown as string;

export interface Probe {
  hasVideo: boolean;
  hasAudio: boolean;
  silent: boolean;
  maxDb: number | null;
  streams: string[];
}

function ffOut(args: string[]): string {
  const r = spawnSync(FF, args, { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  return `${r.stderr ?? ""}${r.stdout ?? ""}`;
}

export function probe(path: string): Probe {
  if (!existsSync(path)) throw new Error(`file not found: ${path}`);
  const info = ffOut(["-hide_banner", "-i", path]);
  const streams = info.split("\n").map((l) => l.trim()).filter((l) => /^Stream #\d+:\d+.*: (Video|Audio):/.test(l));
  const hasVideo = /Stream #\d+:\d+.*: Video:/.test(info);
  const hasAudio = /Stream #\d+:\d+.*: Audio:/.test(info);
  let maxDb: number | null = null;
  if (hasAudio) {
    const vd = ffOut(["-hide_banner", "-i", path, "-af", "volumedetect", "-vn", "-f", "null", "-"]);
    const m = vd.match(/max_volume:\s*(-?[\d.]+) dB/);
    maxDb = m ? Number(m[1]) : null;
  }
  return { hasVideo, hasAudio, silent: maxDb === null ? true : maxDb <= -70, maxDb, streams };
}

export function assertPublishable(path: string): Probe {
  const p = probe(path);
  if (!p.hasVideo) throw new Error(`${path} has no video stream`);
  if (!p.hasAudio) throw new Error(`${path} has no audio stream`);
  if (p.silent && process.env.ALLOW_SILENT !== "1") {
    throw new Error(`${path} audio is SILENT (max ${p.maxDb} dB) — voiceover missing/muted`);
  }
  return p;
}
