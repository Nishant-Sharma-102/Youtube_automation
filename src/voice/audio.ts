/**
 * Audio assembly helpers built on the bundled ffmpeg (ffmpeg-static).
 * Normalizes per-chunk audio (any format) to a uniform WAV, concatenates, and
 * encodes a single MP3 — so downstream steps get one consistent audio/epN.mp3.
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import ffmpegPathImport from "ffmpeg-static";

const ffmpegPath = ffmpegPathImport as unknown as string;

const TMP = "audio/.tmp";

export interface AudioChunk {
  buffer: Buffer;
  ext: string; // container/extension ffmpeg can read, e.g. "mp3" or "wav"
}

function ffmpeg(args: string[]): void {
  const r = spawnSync(ffmpegPath, args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (r.status !== 0) {
    throw new Error(`ffmpeg failed: ${(r.stderr || "").split("\n").slice(-6).join(" ")}`);
  }
}

/** Wrap raw signed-16-bit little-endian PCM in a WAV container. */
export function pcmToWav(pcm: Buffer, sampleRate: number, channels = 1): Buffer {
  const bps = 16;
  const blockAlign = (channels * bps) / 8;
  const byteRate = sampleRate * blockAlign;
  const h = Buffer.alloc(44);
  h.write("RIFF", 0);
  h.writeUInt32LE(36 + pcm.length, 4);
  h.write("WAVE", 8);
  h.write("fmt ", 12);
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20);
  h.writeUInt16LE(channels, 22);
  h.writeUInt32LE(sampleRate, 24);
  h.writeUInt32LE(byteRate, 28);
  h.writeUInt16LE(blockAlign, 32);
  h.writeUInt16LE(bps, 34);
  h.write("data", 36);
  h.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([h, pcm]);
}

/** Assemble chunks into a single MP3 at outPath. */
export function assembleMp3(chunks: AudioChunk[], outPath: string): void {
  if (chunks.length === 0) throw new Error("assembleMp3: no audio chunks");
  mkdirSync(TMP, { recursive: true });
  const wavs: string[] = [];
  try {
    chunks.forEach((c, i) => {
      const src = `${TMP}/src${i}.${c.ext}`;
      const wav = `${TMP}/norm${i}.wav`; // distinct name so src.wav != out.wav
      writeFileSync(src, c.buffer);
      ffmpeg(["-y", "-i", src, "-ar", "44100", "-ac", "1", "-f", "wav", wav]);
      wavs.push(wav);
    });
    const list = `${TMP}/list.txt`;
    writeFileSync(list, wavs.map((w) => `file '${w.split("/").pop()}'`).join("\n") + "\n");
    const combined = `${TMP}/combined.wav`;
    ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", combined]);
    ffmpeg(["-y", "-i", combined, "-c:a", "libmp3lame", "-q:a", "4", outPath]);
  } finally {
    rmSync(TMP, { recursive: true, force: true });
  }
}

/** Duration of an audio/video file in seconds (0 if undetectable). */
export function durationSeconds(path: string): number {
  const r = spawnSync(ffmpegPath, ["-hide_banner", "-i", path], { encoding: "utf8" });
  const m = (r.stderr || "").match(/Duration: (\d+):(\d+):(\d+\.\d+)/);
  return m ? +m[1] * 3600 + +m[2] * 60 + parseFloat(m[3]) : 0;
}
