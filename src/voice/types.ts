import type { Config } from "../config.js";

export interface VoiceResult {
  provider: string;
  chars: number;
  outPath: string;
}

/** A text-to-speech backend. Providers do their own chunking + assembly. */
export interface VoiceProvider {
  readonly name: string;
  /** True if the necessary credentials/config are present. */
  isConfigured(cfg: Config): boolean;
  /** Synthesize the full text to an MP3 at outPath. Returns characters synthesized. */
  synthesize(cfg: Config, text: string, outPath: string): Promise<{ chars: number }>;
}
