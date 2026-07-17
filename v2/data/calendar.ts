// Seed topics for the content queue (brief's 30-day calendar). One row per episode.
export interface Topic {
  n: number;
  topic: string;
  format: "Educational" | "Story";
}

export const CALENDAR: readonly Topic[] = [
  { n: 1, topic: "Meet the Giggle Grove friends — intro episode", format: "Story" },
  { n: 2, topic: "Learn Colors — Rainbow Adventure", format: "Educational" },
  { n: 3, topic: "Counting 1–10 with Milo", format: "Educational" },
  { n: 4, topic: "Shapes in the Garden", format: "Educational" },
  { n: 5, topic: "Sharing is Caring (moral story)", format: "Story" },
  { n: 6, topic: "Animal Sounds Adventure", format: "Educational" },
  { n: 7, topic: "Learn Colors Part 2 — Fruits", format: "Educational" },
  { n: 8, topic: "Bedtime Manners Story", format: "Story" },
  { n: 9, topic: "Counting 11–20", format: "Educational" },
  { n: 10, topic: "Opposites (big/small, up/down)", format: "Educational" },
  { n: 11, topic: "Helping Friends (moral story)", format: "Story" },
  { n: 12, topic: "Days of the Week Song", format: "Educational" },
  { n: 13, topic: "Learn Shapes Part 2", format: "Educational" },
  { n: 14, topic: "Brushing Teeth / Hygiene Habits", format: "Story" },
  { n: 15, topic: "Counting with Animals", format: "Educational" },
  { n: 16, topic: "Weather & Seasons", format: "Educational" },
  { n: 17, topic: '"Best Friends" finale / recap episode', format: "Story" },
] as const;
