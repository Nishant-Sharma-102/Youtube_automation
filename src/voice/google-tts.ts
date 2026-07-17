import type { Config } from "../config.js";
import { logger } from "../logger.js";
import { assembleMp3, type AudioChunk } from "./audio.js";
import { chunkText } from "./chunk.js";
import type { VoiceProvider } from "./types.js";

const PER_REQUEST_MAX = 4800; // Google TTS hard limit is 5000 chars/request

export const googleTtsProvider: VoiceProvider = {
  name: "google-tts",

  isConfigured(cfg: Config): boolean {
    return Boolean(cfg.voice.googleTtsKey);
  },

  async synthesize(cfg: Config, text: string, outPath: string): Promise<{ chars: number }> {
    const key = cfg.voice.googleTtsKey!;
    const langCode = cfg.voice.googleTtsVoice.split("-").slice(0, 2).join("-") || "en-US";
    const chunks = chunkText(text, PER_REQUEST_MAX);
    const audio: AudioChunk[] = [];
    for (const [i, chunk] of chunks.entries()) {
      const res = await fetch(
        `https://texttospeech.googleapis.com/v1/text:synthesize?key=${key}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            input: { text: chunk },
            voice: { languageCode: langCode, name: cfg.voice.googleTtsVoice },
            audioConfig: { audioEncoding: "MP3" },
          }),
        },
      );
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new Error(`Google TTS HTTP ${res.status}: ${body.slice(0, 200)}`);
      }
      const json = (await res.json()) as { audioContent?: string };
      if (!json.audioContent) throw new Error("Google TTS returned no audioContent");
      audio.push({ buffer: Buffer.from(json.audioContent, "base64"), ext: "mp3" });
      logger.info(`Google TTS chunk ${i + 1}/${chunks.length} ok`, { chars: chunk.length });
    }
    assembleMp3(audio, outPath);
    return { chars: text.length };
  },
};
