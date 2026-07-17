// Audio assembly via the bundled ffmpeg (ffmpeg-static): normalize per-chunk audio to
// a uniform WAV, concatenate, encode one MP3. Keeps output consistent regardless of
// which TTS produced each chunk.
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import ffmpegPathImport from "ffmpeg-static";

const FF = ffmpegPathImport as unknown as string;
const TMP = "audio/.tmp";

export interface Chunk { buffer: Buffer; ext: string; }

function ff(args: string[]): void {
  const r = spawnSync(FF, args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (r.status !== 0) throw new Error(`ffmpeg failed: ${(r.stderr || "").split("\n").slice(-4).join(" ")}`);
}

export function assembleMp3(chunks: Chunk[], outPath: string): void {
  if (!chunks.length) throw new Error("no audio chunks");
  mkdirSync(TMP, { recursive: true });
  const wavs: string[] = [];
  try {
    chunks.forEach((c, i) => {
      const src = `${TMP}/src${i}.${c.ext}`;
      const wav = `${TMP}/norm${i}.wav`;
      writeFileSync(src, c.buffer);
      ff(["-y", "-i", src, "-ar", "44100", "-ac", "1", "-f", "wav", wav]);
      wavs.push(wav);
    });
    const list = `${TMP}/list.txt`;
    writeFileSync(list, wavs.map((w) => `file '${w.split("/").pop()}'`).join("\n") + "\n");
    const combined = `${TMP}/combined.wav`;
    ff(["-y", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", combined]);
    ff(["-y", "-i", combined, "-c:a", "libmp3lame", "-q:a", "4", outPath]);
  } finally {
    rmSync(TMP, { recursive: true, force: true });
  }
}

export function durationSeconds(path: string): number {
  const r = spawnSync(FF, ["-hide_banner", "-i", path], { encoding: "utf8" });
  const m = (r.stderr || "").match(/Duration: (\d+):(\d+):(\d+\.\d+)/);
  return m ? +m[1] * 3600 + +m[2] * 60 + parseFloat(m[3]) : 0;
}
