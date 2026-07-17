import { BIBLE } from "../data/character-bible.js";
import type { Config } from "./config.js";
import { logger } from "./logger.js";
import { GeminiClient } from "./gemini/client.js";
import { ClaudeClient } from "./anthropic/client.js";
import type { ContentRow, GeneratedMetadata, GenerationResult } from "./types.js";

/** Produces a full script + metadata for one episode row. */
export interface Generator {
  generate(row: ContentRow): Promise<GenerationResult>;
}

/** A text-generation backend (script + 3 metadata variants). */
interface Writer {
  readonly name: string;
  generateScript(row: ContentRow): Promise<string>;
  generateMetadata(
    row: ContentRow,
    script: string,
  ): Promise<{ chosen: GeneratedMetadata; variants: GeneratedMetadata[] }>;
}

/**
 * Live generator with provider fallback: tries Gemini first (free tier), then Claude.
 * If Gemini has no key or fails (e.g. daily quota), it falls through to Claude.
 * Order reflects the user's rule: "if no Gemini key available, use the Claude key."
 */
export class LlmGenerator implements Generator {
  private readonly writers: Writer[];

  constructor(cfg: Config) {
    this.writers = [];
    if (cfg.geminiApiKey) this.writers.push(wrap("gemini", new GeminiClient(cfg)));
    if (cfg.anthropicApiKey) this.writers.push(wrap("claude", new ClaudeClient(cfg)));
    if (this.writers.length === 0) {
      throw new Error(
        "No text-generation provider configured. Set GEMINI_API_KEY and/or ANTHROPIC_API_KEY, or use --dry-run.",
      );
    }
  }

  async generate(row: ContentRow): Promise<GenerationResult> {
    let lastErr: unknown;
    for (const writer of this.writers) {
      try {
        logger.info(`Generating with ${writer.name}`, { videoNumber: row.videoNumber });
        const script = await writer.generateScript(row);
        const { chosen } = await writer.generateMetadata(row, script);
        return { script, ...chosen };
      } catch (err) {
        lastErr = err;
        logger.warn(`Provider ${writer.name} failed — trying next`, {
          videoNumber: row.videoNumber,
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }
    throw new Error(
      `All text providers failed for episode #${row.videoNumber}. Last error: ${
        lastErr instanceof Error ? lastErr.message : String(lastErr)
      }`,
    );
  }
}

/** Adapt a client (GeminiClient | ClaudeClient) to the Writer interface with a name. */
function wrap(name: string, client: GeminiClient | ClaudeClient): Writer {
  return {
    name,
    generateScript: (row) => client.generateScript(row),
    generateMetadata: (row, script) => client.generateMetadata(row, script),
  };
}

/**
 * Offline generator for `--dry-run`: deterministic canned output, no API key needed.
 * Exercises the full pick → generate → persist → status flow.
 */
export class DryRunGenerator implements Generator {
  async generate(row: ContentRow): Promise<GenerationResult> {
    const [milo, lulu] = BIBLE.characters;
    const script = [
      `[DRY RUN — canned script for episode #${row.videoNumber}]`,
      ``,
      `SCENE — The Giggle Grove clearing, morning light.`,
      `${milo.name}: ${milo.catchphrase} Today we're exploring "${row.topic}"!`,
      `${lulu.name}: ${lulu.catchphrase} Let's learn it together, step by step.`,
      `[The friends explore the topic with simple, repeatable examples.]`,
      `${lulu.name}: Can you say it with me? Wonderful!`,
      ``,
      `[Reinforce the lesson clearly.]`,
      `${milo.name} & ${lulu.name}: ${BIBLE.signOff}`,
    ].join("\n");
    return {
      script,
      title: `Learn ${row.topic} with ${milo.name} | Fun Kids Story`,
      description: `Join ${milo.name} and ${lulu.name} in ${BIBLE.channelName} as they explore ${row.topic}! A fun, gentle ${row.format.toLowerCase()} for little learners.`,
      tags: [
        "kids learning",
        "toddler education",
        "preschool",
        row.topic.toLowerCase(),
        BIBLE.channelName.toLowerCase(),
        milo.name.toLowerCase(),
        lulu.name.toLowerCase(),
        "educational cartoon",
        "learn for kids",
        "fun kids story",
      ],
      thumbnailText: row.format === "Educational" ? "LET'S LEARN!" : "STORY TIME!",
    };
  }
}
