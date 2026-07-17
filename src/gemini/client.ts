import { GoogleGenAI } from "@google/genai";

import type { Config } from "../config.js";
import { requireGeminiKey } from "../config.js";
import { logger } from "../logger.js";
import { withRetry } from "../retry.js";
import type { ContentRow, GeneratedMetadata } from "../types.js";
import { buildScriptPrompt } from "./script-prompt.js";
import { buildMetadataPrompt, METADATA_SCHEMA } from "./metadata-prompt.js";

/**
 * Retry only on transient failures. Do NOT retry quota exhaustion (HTTP 429 /
 * RESOURCE_EXHAUSTED): the daily free-tier cap won't clear in seconds, so retrying
 * just burns more of the day's allowance. Server overload (503 / UNAVAILABLE) and
 * network blips are worth retrying.
 */
export function isRetryableGeminiError(err: unknown): boolean {
  const msg = (err instanceof Error ? err.message : String(err)).toLowerCase();
  if (msg.includes("429") || msg.includes("resource_exhausted") || msg.includes("quota")) {
    return false;
  }
  return true;
}

export class GeminiClient {
  private readonly ai: GoogleGenAI;
  private readonly model: string;

  private readonly contentMode: Config["contentMode"];

  constructor(cfg: Config) {
    this.ai = new GoogleGenAI({ apiKey: requireGeminiKey(cfg) });
    this.model = cfg.geminiModel;
    this.contentMode = cfg.contentMode;
  }

  /** Gemini call #1 — free-text episode script (or rhyme song). */
  async generateScript(row: ContentRow): Promise<string> {
    const prompt = buildScriptPrompt(row, this.contentMode);
    const text = await withRetry(
      async () => {
        const resp = await this.ai.models.generateContent({
          model: this.model,
          contents: prompt,
        });
        const out = resp.text?.trim();
        if (!out) throw new Error("Gemini returned an empty script");
        return out;
      },
      { label: `gemini.generateScript(v${row.videoNumber})`, shouldRetry: isRetryableGeminiError },
    );
    logger.info("Script generated", { videoNumber: row.videoNumber, chars: text.length });
    return text;
  }

  /**
   * Gemini call #2 — generate 3 metadata variants (Phase 1 spec).
   * Returns { chosen, variants }: `chosen` is variant #1; all are logged for review.
   */
  async generateMetadata(
    row: ContentRow,
    script: string,
  ): Promise<{ chosen: GeneratedMetadata; variants: GeneratedMetadata[] }> {
    const prompt = buildMetadataPrompt(row, script);
    const variants = await withRetry(
      async () => {
        const resp = await this.ai.models.generateContent({
          model: this.model,
          contents: prompt,
          config: {
            responseMimeType: "application/json",
            responseSchema: METADATA_SCHEMA,
          },
        });
        const raw = resp.text?.trim();
        if (!raw) throw new Error("Gemini returned empty metadata");
        return parseVariants(raw);
      },
      { label: `gemini.generateMetadata(v${row.videoNumber})`, shouldRetry: isRetryableGeminiError },
    );
    variants.forEach((v, i) =>
      logger.info(`Metadata variant ${i + 1}`, { videoNumber: row.videoNumber, title: v.title }),
    );
    return { chosen: variants[0], variants };
  }
}

function parseVariant(m: Record<string, unknown>): GeneratedMetadata | null {
  const title = typeof m.title === "string" ? m.title.trim() : "";
  const description = typeof m.description === "string" ? m.description.trim() : "";
  const thumbnailText = typeof m.thumbnailText === "string" ? m.thumbnailText.trim() : "";
  const tags = Array.isArray(m.tags)
    ? m.tags.filter((t): t is string => typeof t === "string").map((t) => t.trim())
    : [];
  if (!title || !description || !thumbnailText || tags.length === 0) return null;
  return { title, description, tags, thumbnailText };
}

function parseVariants(raw: string): GeneratedMetadata[] {
  let obj: unknown;
  try {
    obj = JSON.parse(raw);
  } catch {
    throw new Error(`Metadata was not valid JSON: ${raw.slice(0, 200)}`);
  }
  const arr = (obj as { variants?: unknown }).variants;
  const variants = Array.isArray(arr)
    ? arr.map((v) => parseVariant(v as Record<string, unknown>)).filter((v): v is GeneratedMetadata => v !== null)
    : [];
  if (variants.length === 0) {
    throw new Error(`No valid metadata variants returned: ${raw.slice(0, 200)}`);
  }
  return variants;
}
