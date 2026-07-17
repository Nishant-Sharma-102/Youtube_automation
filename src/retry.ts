import { logger } from "./logger.js";

export interface RetryOptions {
  attempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  label?: string;
  /**
   * Decide whether an error is worth retrying. Return false to fail fast
   * (e.g. daily-quota exhaustion, where retrying seconds later cannot succeed
   * and only burns more quota). Default: retry everything.
   */
  shouldRetry?: (err: unknown) => boolean;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Retry an async operation with exponential backoff.
 * Anticipates the brief's Section 4.6 error-handling needs; shared by the Gemini
 * client now and reusable by the future publish orchestrator.
 */
export async function withRetry<T>(fn: () => Promise<T>, opts: RetryOptions = {}): Promise<T> {
  const attempts = opts.attempts ?? 4;
  const baseDelayMs = opts.baseDelayMs ?? 1000;
  const maxDelayMs = opts.maxDelayMs ?? 15000;
  const label = opts.label ?? "operation";
  const shouldRetry = opts.shouldRetry ?? (() => true);

  let lastErr: unknown;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (!shouldRetry(err)) {
        logger.warn(`${label} failed with a non-retryable error — not retrying`, {
          error: err instanceof Error ? err.message : String(err),
        });
        break;
      }
      if (attempt === attempts) break;
      const delay = Math.min(baseDelayMs * 2 ** (attempt - 1), maxDelayMs);
      logger.warn(`${label} failed (attempt ${attempt}/${attempts}), retrying in ${delay}ms`, {
        error: err instanceof Error ? err.message : String(err),
      });
      await sleep(delay);
    }
  }
  throw lastErr;
}
