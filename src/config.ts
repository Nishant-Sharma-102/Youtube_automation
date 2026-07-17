import "dotenv/config";

export interface Config {
  geminiApiKey: string | undefined;
  geminiModel: string;
  anthropicApiKey: string | undefined;
  claudeModel: string;
  /** 'story' (screenplay) or 'rhyme' (nursery-rhyme song). */
  contentMode: "story" | "rhyme";
  dbDriver: string;
  dbPath: string;
  youtube: {
    clientId: string | undefined;
    clientSecret: string | undefined;
    refreshToken: string | undefined;
    redirectUri: string;
    mock: boolean;
  };
  voice: {
    elevenLabsKey: string | undefined;
    elevenLabsVoiceId: string;
    elevenLabsModel: string;
    elevenLabsMonthlyLimit: number;
    googleTtsKey: string | undefined;
    googleTtsVoice: string;
  };
}

export function loadConfig(): Config {
  const refreshToken = process.env.YOUTUBE_REFRESH_TOKEN?.trim() || undefined;
  // Mock when explicitly requested OR when credentials are absent — never attempt a
  // real upload without a refresh token.
  const mock = process.env.YOUTUBE_MOCK?.trim() === "1" || !refreshToken;
  return {
    geminiApiKey: process.env.GEMINI_API_KEY?.trim() || undefined,
    geminiModel: process.env.GEMINI_MODEL?.trim() || "gemini-2.5-flash",
    anthropicApiKey: process.env.ANTHROPIC_API_KEY?.trim() || undefined,
    claudeModel:
      process.env.ANTHROPIC_MODEL?.trim() || process.env.CLAUDE_MODEL?.trim() || "claude-opus-4-8",
    contentMode: process.env.CONTENT_MODE?.trim() === "rhyme" ? "rhyme" : "story",
    dbDriver: process.env.DB_DRIVER?.trim() || "sqlite",
    dbPath: process.env.DB_PATH?.trim() || "./data/content-queue.db",
    youtube: {
      clientId: process.env.YOUTUBE_CLIENT_ID?.trim() || undefined,
      clientSecret: process.env.YOUTUBE_CLIENT_SECRET?.trim() || undefined,
      refreshToken,
      redirectUri:
        process.env.YOUTUBE_REDIRECT_URI?.trim() || "http://localhost:5757/oauth2callback",
      mock,
    },
    voice: {
      elevenLabsKey: process.env.ELEVENLABS_API_KEY?.trim() || undefined,
      elevenLabsVoiceId: process.env.ELEVENLABS_VOICE_ID?.trim() || "EXAVITQu4vr4xnSDxMaL",
      elevenLabsModel: process.env.ELEVENLABS_MODEL?.trim() || "eleven_multilingual_v2",
      elevenLabsMonthlyLimit: Number(process.env.ELEVENLABS_MONTHLY_LIMIT?.trim() || "10000"),
      googleTtsKey: process.env.GOOGLE_TTS_API_KEY?.trim() || undefined,
      googleTtsVoice: process.env.GOOGLE_TTS_VOICE?.trim() || "en-US-Neural2-F",
    },
  };
}

/**
 * Require a Gemini API key. Called only on the live path — `--dry-run` skips it so
 * the pipeline is testable with no credentials.
 */
export function requireGeminiKey(cfg: Config): string {
  if (!cfg.geminiApiKey) {
    throw new Error(
      "GEMINI_API_KEY is not set. Add it to .env, or run with --dry-run to test without a key.",
    );
  }
  return cfg.geminiApiKey;
}
