import type { Config } from "../config.js";
import { logger } from "../logger.js";
import { assembleMp3, type AudioChunk } from "./audio.js";
import { chunkText } from "./chunk.js";
import { monthToDateChars } from "./usage.js";
import type { VoiceProvider } from "./types.js";

const PER_REQUEST_MAX = 2500; // conservative per-call character size

export const elevenLabsProvider: VoiceProvider = {
  name: "elevenlabs",

  isConfigured(cfg: Config): boolean {
    return Boolean(cfg.voice.elevenLabsKey);
  },

  async synthesize(cfg: Config, text: string, outPath: string): Promise<{ chars: number }> {
    const key = cfg.voice.elevenLabsKey!;
    const chars = text.length;

    // Free-tier budget warning (upfront estimate).
    const used = monthToDateChars("elevenlabs", new Date().toISOString().slice(0, 7));
    const limit = cfg.voice.elevenLabsMonthlyLimit;
    if (used + chars > limit) {
      logger.warn(
        `ElevenLabs monthly budget likely exceeded: ${used} used + ${chars} this episode > ${limit} limit. ` +
          `This may fail and fall back to Google TTS.`,
      );
    }

    const chunks = chunkText(text, PER_REQUEST_MAX);
    const audio: AudioChunk[] = [];
    for (const [i, chunk] of chunks.entries()) {
      const res = await fetch(
        `https://api.elevenlabs.io/v1/text-to-speech/${cfg.voice.elevenLabsVoiceId}`,
        {
          method: "POST",
          headers: {
            "xi-api-key": key,
            "Content-Type": "application/json",
            Accept: "audio/mpeg",
          },
          body: JSON.stringify({
            text: chunk,
            model_id: cfg.voice.elevenLabsModel,
            voice_settings: { stability: 0.5, similarity_boost: 0.75 },
          }),
        },
      );
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new Error(`ElevenLabs HTTP ${res.status}: ${body.slice(0, 200)}`);
      }
      audio.push({ buffer: Buffer.from(await res.arrayBuffer()), ext: "mp3" });
      logger.info(`ElevenLabs chunk ${i + 1}/${chunks.length} ok`, { chars: chunk.length });
    }
    assembleMp3(audio, outPath);
    return { chars };
  },
};
