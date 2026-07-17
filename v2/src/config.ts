// Central config. Loads the parent project's .env (../.env) so keys live in ONE place
// and are never hardcoded. Run scripts from the v2/ directory.
import { config as loadEnv } from "dotenv";

loadEnv({ path: "../.env" }); // reuse the shared credentials file
loadEnv(); // also allow a local v2/.env to override, if present

export interface Config {
  geminiApiKey: string | undefined;
  geminiModel: string;
  anthropicApiKey: string | undefined;
  claudeModel: string;
  elevenLabsKey: string | undefined;
  elevenLabsVoiceId: string;
  elevenLabsModel: string;
  elevenLabsMonthlyLimit: number;
  googleTtsKey: string | undefined;
  googleTtsVoice: string;
  youtube: {
    clientId: string | undefined;
    clientSecret: string | undefined;
    refreshToken: string | undefined;
    redirectUri: string;
    mock: boolean;
  };
  dbPath: string;
}

export function loadConfig(): Config {
  return {
    geminiApiKey: process.env.GEMINI_API_KEY?.trim() || undefined,
    geminiModel: process.env.GEMINI_MODEL?.trim() || "gemini-2.5-flash",
    anthropicApiKey: process.env.ANTHROPIC_API_KEY?.trim() || undefined,
    claudeModel: process.env.ANTHROPIC_MODEL?.trim() || process.env.CLAUDE_MODEL?.trim() || "claude-sonnet-5",
    elevenLabsKey: process.env.ELEVENLABS_API_KEY?.trim() || undefined,
    elevenLabsVoiceId: process.env.ELEVENLABS_VOICE_ID?.trim() || "EXAVITQu4vr4xnSDxMaL",
    elevenLabsModel: process.env.ELEVENLABS_MODEL?.trim() || "eleven_multilingual_v2",
    elevenLabsMonthlyLimit: Number(process.env.ELEVENLABS_MONTHLY_LIMIT?.trim() || "10000"),
    googleTtsKey: process.env.GOOGLE_TTS_API_KEY?.trim() || undefined,
    googleTtsVoice: process.env.GOOGLE_TTS_VOICE?.trim() || "en-US-Neural2-F",
    youtube: (() => {
      const refreshToken = process.env.YOUTUBE_REFRESH_TOKEN?.trim() || undefined;
      return {
        clientId: process.env.YOUTUBE_CLIENT_ID?.trim() || undefined,
        clientSecret: process.env.YOUTUBE_CLIENT_SECRET?.trim() || undefined,
        refreshToken,
        redirectUri: process.env.YOUTUBE_REDIRECT_URI?.trim() || "http://localhost:5757/oauth2callback",
        // Mock unless a refresh token exists and mock isn't explicitly requested.
        mock: process.env.YOUTUBE_MOCK?.trim() === "1" || !refreshToken,
      };
    })(),
    dbPath: process.env.V2_DB_PATH?.trim() || "./data/queue.db",
  };
}

export function requireGeminiKey(cfg: Config): string {
  if (!cfg.geminiApiKey) throw new Error("GEMINI_API_KEY is not set (in ../.env).");
  return cfg.geminiApiKey;
}
