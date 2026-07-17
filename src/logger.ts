import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const LOG_FILE = "./logs/generate.log";

let logDirReady = false;
function ensureLogDir(): void {
  if (logDirReady) return;
  mkdirSync(dirname(LOG_FILE), { recursive: true });
  logDirReady = true;
}

type Level = "INFO" | "WARN" | "ERROR";

function write(level: Level, message: string, meta?: Record<string, unknown>): void {
  const ts = new Date().toISOString();
  const metaStr = meta && Object.keys(meta).length ? " " + JSON.stringify(meta) : "";
  const line = `${ts} [${level}] ${message}${metaStr}`;

  const consoleFn = level === "ERROR" ? console.error : level === "WARN" ? console.warn : console.log;
  consoleFn(line);

  try {
    ensureLogDir();
    appendFileSync(LOG_FILE, line + "\n");
  } catch {
    // Never let logging failures break the pipeline.
  }
}

export const logger = {
  info: (message: string, meta?: Record<string, unknown>) => write("INFO", message, meta),
  warn: (message: string, meta?: Record<string, unknown>) => write("WARN", message, meta),
  error: (message: string, meta?: Record<string, unknown>) => write("ERROR", message, meta),
};
