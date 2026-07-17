// Create the queue and seed it from the calendar (idempotent). Assigns Mon/Wed/Fri/Sun
// scheduled_dates from a launch Monday.
import { loadConfig } from "./config.js";
import { openDb } from "./db.js";
import { CALENDAR } from "../data/calendar.js";

const LAUNCH = process.argv.find((a) => a.startsWith("--launch="))?.split("=")[1] ?? "2026-08-03";

// Mon/Wed/Fri/Sun cadence: day offsets within each week.
function scheduledDate(index: number): string {
  const offsets = [0, 2, 4, 6]; // Mon, Wed, Fri, Sun
  const week = Math.floor(index / 4);
  const day = offsets[index % 4];
  const d = new Date(`${LAUNCH}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + week * 7 + day);
  return d.toISOString().slice(0, 10);
}

const db = openDb(loadConfig().dbPath);
const insert = db.prepare(
  `INSERT OR IGNORE INTO episodes (video_number, topic, format, scheduled_date, status)
   VALUES (@n, @topic, @format, @scheduled_date, 'draft')`,
);
let inserted = 0;
CALENDAR.forEach((t, i) => {
  const info = insert.run({ n: t.n, topic: t.topic, format: t.format, scheduled_date: scheduledDate(i) });
  inserted += info.changes;
});
console.log(`DB ready at ${loadConfig().dbPath} — seeded ${inserted} new (of ${CALENDAR.length}) episodes, launch ${LAUNCH}.`);
db.close();
