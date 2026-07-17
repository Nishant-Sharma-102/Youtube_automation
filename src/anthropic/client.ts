import Anthropic from "@anthropic-ai/sdk";

import type { Config } from "../config.js";
import { logger } from "../logger.js";
import { withRetry } from "../retry.js";
import type { ContentRow, GeneratedMetadata } from "../types.js";
import { buildScriptPrompt } from "../gemini/script-prompt.js";
import { buildMetadataPrompt } from "../gemini/metadata-prompt.js";

/** JSON schema for the 3-variant metadata (Anthropic structured outputs). */
const METADATA_FORMAT = {
  type: "json_schema" as const,
  schema: {
    type: "object",
    properties: {
      variants: {
        type: "array",
        items: {
          type: "object",
          properties: {
            title: { type: "string" },
            description: { type: "string" },
            tags: { type: "array", items: { type: "string" } },
            thumbnailText: { type: "string" },
          },
          required: ["title", "description", "tags", "thumbnailText"],
          additionalProperties: false,
        },
      },
    },
    required: ["variants"],
    additionalProperties: false,
  },
};

/** Retry transient Anthropic errors (5xx / overloaded / network); not 4xx like auth or quota. */
function isRetryableAnthropicError(err: unknown): boolean {
  if (err instanceof Anthropic.APIError && typeof err.status === "number") {
    return err.status === 429 || err.status >= 500;
  }
  return err instanceof Anthropic.APIConnectionError;
}

/**
 * Claude text-generation client. Same surface as GeminiClient (generateScript +
 * generateMetadata), used as the fallback writer.
 */
export class ClaudeClient {
  private readonly client: Anthropic;
  private readonly model: string;
  private readonly contentMode: Config["contentMode"];

  constructor(cfg: Config) {
    // The SDK also resolves ANTHROPIC_API_KEY from the environment on its own.
    this.client = new Anthropic({ apiKey: cfg.anthropicApiKey });
    this.model = cfg.claudeModel;
    this.contentMode = cfg.contentMode;
  }

  async generateScript(row: ContentRow): Promise<string> {
    const prompt = buildScriptPrompt(row, this.contentMode);
    const text = await withRetry(
      async () => {
        const resp = await this.client.messages.create({
          model: this.model,
          max_tokens: 16000,
          messages: [{ role: "user", content: prompt }],
        });
        const out = resp.content
          .filter((b): b is Anthropic.TextBlock => b.type === "text")
          .map((b) => b.text)
          .join("")
          .trim();
        if (!out) throw new Error("Claude returned an empty script");
        return out;
      },
      { label: `claude.generateScript(v${row.videoNumber})`, shouldRetry: isRetryableAnthropicError },
    );
    logger.info("Script generated (claude)", { videoNumber: row.videoNumber, chars: text.length });
    return text;
  }

  async generateMetadata(
    row: ContentRow,
    script: string,
  ): Promise<{ chosen: GeneratedMetadata; variants: GeneratedMetadata[] }> {
    const prompt = buildMetadataPrompt(row, script);
    const variants = await withRetry(
      async () => {
        const resp = await this.client.messages.create({
          model: this.model,
          max_tokens: 4000,
          messages: [{ role: "user", content: prompt }],
          output_config: { format: METADATA_FORMAT },
        });
        const raw = resp.content
          .filter((b): b is Anthropic.TextBlock => b.type === "text")
          .map((b) => b.text)
          .join("")
          .trim();
        if (!raw) throw new Error("Claude returned empty metadata");
        return parseVariants(raw);
      },
      { label: `claude.generateMetadata(v${row.videoNumber})`, shouldRetry: isRetryableAnthropicError },
    );
    variants.forEach((v, i) =>
      logger.info(`Metadata variant ${i + 1} (claude)`, { videoNumber: row.videoNumber, title: v.title }),
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
    throw new Error(`Claude metadata was not valid JSON: ${raw.slice(0, 200)}`);
  }
  const arr = (obj as { variants?: unknown }).variants;
  const variants = Array.isArray(arr)
    ? arr.map((v) => parseVariant(v as Record<string, unknown>)).filter((v): v is GeneratedMetadata => v !== null)
    : [];
  if (variants.length === 0) throw new Error(`No valid Claude metadata variants: ${raw.slice(0, 200)}`);
  return variants;
}
