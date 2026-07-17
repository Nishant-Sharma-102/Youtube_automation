/**
 * Content-generation stage (brief Section 5).
 *
 * Flow per episode:
 *   1. Pick a draft row (next, a specific --video N, or --all).
 *   2. Gemini call #1 → episode script.
 *   3. Gemini call #2 → title / description / tags / thumbnail text.
 *   4. Persist + set status='script_ready'.
 *   5. Log a "ready for animation" notification.
 *
 * Usage:
 *   npm run generate                 # next draft episode
 *   npm run generate -- --week       # one week's uploads (next 4 drafts)
 *   npm run generate -- --video 3    # a specific episode
 *   npm run generate -- --all        # every remaining draft
 *   npm run generate -- --limit 4    # cap the batch (stay under daily free-tier quota)
 *   npm run generate -- --dry-run    # no API key; canned output
 */
import { loadConfig } from "./config.js";
import { logger } from "./logger.js";
import { createRepo } from "./db/index.js";
import type { ContentQueueRepo } from "./db/repo.js";
import { DryRunGenerator, LlmGenerator, type Generator } from "./generator.js";
import { isRetryableGeminiError } from "./gemini/client.js";
import type { ContentRow } from "./types.js";

/** A quota-exhaustion error means the whole batch should stop, not just this episode. */
function isQuotaError(err: unknown): boolean {
  return !isRetryableGeminiError(err);
}

interface Args {
  dryRun: boolean;
  all: boolean;
  week: boolean;
  video: number | null;
  limit: number | null;
}

/** How many episodes make up one week's uploads (Mon/Wed/Fri/Sun). */
const WEEKLY_BATCH = 4;

function parseArgs(argv: string[]): Args {
  const videoArg = argv.find((a) => a.startsWith("--video"));
  let video: number | null = null;
  if (videoArg) {
    const raw = videoArg.includes("=")
      ? videoArg.split("=")[1]
      : argv[argv.indexOf(videoArg) + 1];
    const n = Number(raw);
    if (!Number.isInteger(n) || n <= 0) {
      throw new Error(`--video requires a positive integer, got "${raw}"`);
    }
    video = n;
  }
  const limitArg = argv.find((a) => a.startsWith("--limit"));
  let limit: number | null = null;
  if (limitArg) {
    const raw = limitArg.includes("=") ? limitArg.split("=")[1] : argv[argv.indexOf(limitArg) + 1];
    const n = Number(raw);
    if (!Number.isInteger(n) || n <= 0) {
      throw new Error(`--limit requires a positive integer, got "${raw}"`);
    }
    limit = n;
  }

  return {
    dryRun: argv.includes("--dry-run"),
    all: argv.includes("--all"),
    week: argv.includes("--week"),
    video,
    limit,
  };
}

/** Resolve which rows to generate for, honoring flags and skipping non-draft work. */
function selectRows(repo: ContentQueueRepo, args: Args): ContentRow[] {
  if (args.video !== null) {
    const row = repo.getByVideoNumber(args.video);
    if (!row) throw new Error(`No episode with video_number=${args.video}. Run 'npm run db:init'.`);
    if (row.status !== "draft") {
      logger.warn(`Episode #${row.videoNumber} is '${row.status}', not 'draft' — skipping.`, {
        hint: "Regeneration of already-generated rows is intentionally blocked (idempotency).",
      });
      return [];
    }
    return [row];
  }
  // Batch selection: all drafts, a week's worth (--week), or the single next draft.
  const drafts = repo.listByStatus("draft");
  let selected: ContentRow[];
  if (args.all) {
    selected = drafts;
  } else if (args.week) {
    selected = drafts.slice(0, WEEKLY_BATCH);
  } else {
    selected = drafts.slice(0, 1);
  }

  // --limit caps whatever was selected (useful to stay under the daily free-tier quota).
  if (args.limit !== null && selected.length > args.limit) {
    selected = selected.slice(0, args.limit);
  }
  return selected;
}

async function generateOne(repo: ContentQueueRepo, gen: Generator, row: ContentRow): Promise<void> {
  logger.info(`Generating episode #${row.videoNumber}`, { topic: row.topic, format: row.format });
  const result = await gen.generate(row);
  repo.saveGenerated(row.videoNumber, result);
  logger.info(`✅ Episode #${row.videoNumber} script_ready — ready for animation`, {
    title: result.title,
    tags: result.tags.length,
  });
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  // --rhyme switches content generation into nursery-rhyme song mode (before config load).
  if (process.argv.includes("--rhyme")) process.env.CONTENT_MODE = "rhyme";
  const cfg = loadConfig();
  const repo = createRepo(cfg);

  try {
    const rows = selectRows(repo, args);
    if (rows.length === 0) {
      // Brief 4.6: warn rather than fail silently when there is nothing to do.
      logger.warn("No draft episodes to generate. (Seed with 'npm run db:init' if empty.)");
      return;
    }

    const gen: Generator = args.dryRun ? new DryRunGenerator() : new LlmGenerator(cfg);
    logger.info(`Starting content generation`, {
      mode: args.dryRun
        ? "dry-run"
        : [cfg.geminiApiKey && `gemini:${cfg.geminiModel}`, cfg.anthropicApiKey && `claude:${cfg.claudeModel}`]
            .filter(Boolean)
            .join(" → "),
      episodes: rows.map((r) => r.videoNumber),
    });

    let ok = 0;
    for (const row of rows) {
      try {
        await generateOne(repo, gen, row);
        ok++;
      } catch (err) {
        logger.error(`Failed to generate episode #${row.videoNumber}`, {
          error: err instanceof Error ? err.message : String(err),
        });
        if (isQuotaError(err)) {
          logger.warn(
            "Gemini quota exhausted — stopping the batch. Re-run once the quota resets; " +
              "already-generated episodes are skipped automatically.",
          );
          break;
        }
        // Otherwise continue with remaining episodes rather than aborting the whole batch.
      }
    }
    logger.info(`Done. ${ok}/${rows.length} episode(s) moved to script_ready.`);
  } finally {
    repo.close();
  }
}

main().catch((err) => {
  logger.error("Fatal error in content generation", {
    error: err instanceof Error ? err.message : String(err),
  });
  process.exit(1);
});
