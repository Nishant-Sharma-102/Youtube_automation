import { GoogleGenAI } from "@google/genai";

import type { Config } from "../config.js";
import { logger } from "../logger.js";
import { assembleMp3, pcmToWav, type AudioChunk } from "./audio.js";
import { chunkText } from "./chunk.js";
import type { VoiceProvider } from "./types.js";

const PER_REQUEST_MAX = 1500;
const TTS_MODEL = "gemini-2.5-flash-preview-tts";
const VOICE = "Aoede"; // warm, friendly
const SAMPLE_RATE = 24000;

/**
 * Final fallback: Gemini TTS. Not in the original spec, but it uses the Gemini key we
 * already have, so the pipeline can produce audio even before ElevenLabs/Google keys
 * exist. Output is PCM → wrapped to WAV → assembled to MP3.
 */
export const geminiTtsProvider: VoiceProvider = {
  name: "gemini-tts",

  isConfigured(cfg: Config): boolean {
    return Boolean(cfg.geminiApiKey);
  },

  async synthesize(cfg: Config, text: string, outPath: string): Promise<{ chars: number }> {
    const ai = new GoogleGenAI({ apiKey: cfg.geminiApiKey! });
    const chunks = chunkText(text, PER_REQUEST_MAX);
    const audio: AudioChunk[] = [];
    for (const [i, chunk] of chunks.entries()) {
      const resp = await ai.models.generateContent({
        model: TTS_MODEL,
        contents: [{ parts: [{ text: `Say in a warm, cheerful storyteller voice for little kids: ${chunk}` }] }],
        config: {
          responseModalities: ["AUDIO"],
          speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: VOICE } } },
        },
      });
      const b64 = resp.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
      if (!b64) throw new Error("Gemini TTS returned no audio");
      audio.push({ buffer: pcmToWav(Buffer.from(b64, "base64"), SAMPLE_RATE), ext: "wav" });
      logger.info(`Gemini TTS chunk ${i + 1}/${chunks.length} ok`, { chars: chunk.length });
    }
    assembleMp3(audio, outPath);
    return { chars: text.length };
  },
};
