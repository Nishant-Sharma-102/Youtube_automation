/**
 * Track TTS character usage over time so free-tier limits are visible.
 * Appends one JSON line per generation to audio/usage.jsonl.
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";

const USAGE_FILE = "audio/usage.jsonl";

export interface UsageRecord {
  ts: string;
  videoNumber: number;
  provider: string;
  chars: number;
}

export function recordUsage(rec: UsageRecord): void {
  mkdirSync("audio", { recursive: true });
  appendFileSync(USAGE_FILE, JSON.stringify(rec) + "\n");
}

/** Characters used by a provider in the given YYYY-MM month (default: current month). */
export function monthToDateChars(provider: string, monthIso: string): number {
  if (!existsSync(USAGE_FILE)) return 0;
  let total = 0;
  for (const line of readFileSync(USAGE_FILE, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const r = JSON.parse(line) as UsageRecord;
      if (r.provider === provider && r.ts.startsWith(monthIso)) total += r.chars;
    } catch {
      /* skip malformed */
    }
  }
  return total;
}
