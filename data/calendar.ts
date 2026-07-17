/**
 * The 30-day content calendar from the project brief (Section 3).
 * 4 uploads/week: Mon, Wed, Fri, Sun — 17 episodes.
 *
 * `dayOffset` is the day number within the launch month (day 1 = launch Monday).
 * `scheduledDate` is computed at seed time relative to a launch date so we don't
 * hardcode calendar dates here.
 */

export type EpisodeFormat = "Educational" | "Story";

export interface CalendarEpisode {
  videoNumber: number;
  dayOffset: number;
  topic: string;
  format: EpisodeFormat;
}

export const CALENDAR: readonly CalendarEpisode[] = [
  { videoNumber: 1, dayOffset: 1, topic: "Meet the Giggle Grove friends — intro episode", format: "Story" },
  { videoNumber: 2, dayOffset: 3, topic: "Learn Colors — Rainbow Adventure", format: "Educational" },
  { videoNumber: 3, dayOffset: 5, topic: "Counting 1–10 with Milo", format: "Educational" },
  { videoNumber: 4, dayOffset: 7, topic: "Shapes in the Garden", format: "Educational" },
  { videoNumber: 5, dayOffset: 8, topic: "Sharing is Caring (moral story)", format: "Story" },
  { videoNumber: 6, dayOffset: 10, topic: "Animal Sounds Adventure", format: "Educational" },
  { videoNumber: 7, dayOffset: 12, topic: "Learn Colors Part 2 — Fruits", format: "Educational" },
  { videoNumber: 8, dayOffset: 14, topic: "Bedtime Manners Story", format: "Story" },
  { videoNumber: 9, dayOffset: 15, topic: "Counting 11–20", format: "Educational" },
  { videoNumber: 10, dayOffset: 17, topic: "Opposites (big/small, up/down)", format: "Educational" },
  { videoNumber: 11, dayOffset: 19, topic: "Helping Friends (moral story)", format: "Story" },
  { videoNumber: 12, dayOffset: 21, topic: "Days of the Week Song-Story", format: "Educational" },
  { videoNumber: 13, dayOffset: 22, topic: "Learn Shapes Part 2", format: "Educational" },
  { videoNumber: 14, dayOffset: 24, topic: "Brushing Teeth / Hygiene Habits", format: "Story" },
  { videoNumber: 15, dayOffset: 26, topic: "Counting with Animals", format: "Educational" },
  { videoNumber: 16, dayOffset: 28, topic: "Weather & Seasons", format: "Educational" },
  { videoNumber: 17, dayOffset: 29, topic: '"Best Friends" finale / recap episode', format: "Story" },
] as const;

/**
 * Compute an ISO date (YYYY-MM-DD) for an episode given a launch date.
 * @param launchDateIso launch Monday, e.g. "2026-08-03"
 */
export function scheduledDateFor(dayOffset: number, launchDateIso: string): string {
  const launch = new Date(`${launchDateIso}T00:00:00Z`);
  const d = new Date(launch);
  d.setUTCDate(launch.getUTCDate() + (dayOffset - 1));
  return d.toISOString().slice(0, 10);
}
