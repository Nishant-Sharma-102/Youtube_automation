/**
 * Publishing schedule — the source of truth for WHEN episodes go live.
 *
 * Consumed by the upcoming publishing stage (YouTube MCP orchestrator). Nothing
 * publishes yet, but the schedule lives here so the orchestrator and its cron entry
 * derive from one place.
 *
 * === Why 11:00 UTC on Mon/Wed/Fri/Sun ===
 * Target audience: GLOBAL / MIXED. For "Made for Kids" content the largest and
 * highest-RPM market is the US, so we optimize for the US morning and let it spill
 * into Europe's afternoon. Publishing ~2 hours before the viewing peak gives YouTube
 * time to process and index the video first.
 *
 * 11:00 UTC equals:
 *   - 07:00 US Eastern (EDT) — kids' prime breakfast slot, ~2h before the 9am peak
 *   - 04:00 US Pacific (PDT)
 *   - 12:00 UK / 13:00 Central Europe — afternoon viewing
 *   - 16:30 IST — for local reference
 *
 * NOTE: this deliberately replaces the brief's default of 8:00 PM, which lands at a
 * toddler audience's bedtime and is poor for this niche.
 */

/** Upload days (0 = Sunday … 6 = Saturday). Brief cadence: Mon, Wed, Fri, Sun. */
export const PUBLISH_DAYS_OF_WEEK = [1, 3, 5, 0] as const;

/** Publish time, expressed in UTC to stay timezone-safe. */
export const PUBLISH_HOUR_UTC = 11;
export const PUBLISH_MINUTE_UTC = 0;

/**
 * Cron expression for the future publish orchestrator, in UTC.
 * IMPORTANT: cron uses the machine's local timezone. If this host runs on IST, the
 * equivalent local cron is `30 16 * * 1,3,5,0`. Prefer running the publish job with
 * `TZ=UTC` (or `CRON_TZ=UTC`) so this expression is correct as written.
 */
export const PUBLISH_CRON_UTC = `${PUBLISH_MINUTE_UTC} ${PUBLISH_HOUR_UTC} * * 1,3,5,0`;
