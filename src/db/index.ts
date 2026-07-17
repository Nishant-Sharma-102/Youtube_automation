import type { Config } from "../config.js";
import type { ContentQueueRepo } from "./repo.js";
import { SqliteContentQueueRepo } from "./sqlite-repo.js";

/**
 * Build the content-queue repo for the configured driver.
 * Only 'sqlite' is implemented; the switch is where Postgres/MySQL slot in later.
 */
export function createRepo(cfg: Config): ContentQueueRepo {
  switch (cfg.dbDriver) {
    case "sqlite":
      return new SqliteContentQueueRepo(cfg.dbPath);
    default:
      throw new Error(
        `Unsupported DB_DRIVER "${cfg.dbDriver}". Only 'sqlite' is implemented so far.`,
      );
  }
}
