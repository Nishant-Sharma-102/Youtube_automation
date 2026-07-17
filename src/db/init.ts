/**
 * `npm run db:init` — create the content queue and seed the 17 calendar episodes.
 *
 * Launch date: pass --launch=YYYY-MM-DD (a Monday). Defaults to the next Monday
 * on/after 2026-08-03 as a sensible placeholder; re-run with a real date anytime
 * (seeding is idempotent, but scheduled_date is only set on first insert).
 */
import { loadConfig } from "../config.js";
import { logger } from "../logger.js";
import { createRepo } from "./index.js";
import { CALENDAR } from "../../data/calendar.js";

const DEFAULT_LAUNCH = "2026-08-03"; // a Monday

function parseLaunchDate(argv: string[]): string {
  const arg = argv.find((a) => a.startsWith("--launch="));
  const value = arg ? arg.slice("--launch=".length) : DEFAULT_LAUNCH;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`--launch must be YYYY-MM-DD, got "${value}"`);
  }
  return value;
}

function main(): void {
  const cfg = loadConfig();
  const launch = parseLaunchDate(process.argv.slice(2));
  const repo = createRepo(cfg);
  try {
    const { inserted, skipped } = repo.seed([...CALENDAR], launch);
    logger.info("Content queue initialized", {
      driver: cfg.dbDriver,
      dbPath: cfg.dbPath,
      launch,
      inserted,
      skipped,
      total: CALENDAR.length,
    });
  } finally {
    repo.close();
  }
}

main();
