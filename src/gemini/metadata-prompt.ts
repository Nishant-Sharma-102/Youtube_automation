import { Type, type Schema } from "@google/genai";
import { BIBLE } from "../../data/character-bible.js";
import type { ContentRow } from "../types.js";

/** Schema for a single metadata variant. */
const VARIANT_SCHEMA: Schema = {
  type: Type.OBJECT,
  properties: {
    title: {
      type: Type.STRING,
      description:
        'YouTube title following the pattern "Learn [Topic] with [Character] | Fun Kids Story". Max ~90 chars.',
    },
    description: {
      type: Type.STRING,
      description:
        "2–4 sentence kid-friendly, search-friendly video description. No links, no hashtags spam.",
    },
    tags: {
      type: Type.ARRAY,
      items: { type: Type.STRING },
      description:
        "12–15 lowercase SEO tags: mix broad ('kids songs', 'learning for toddlers'), " +
        "specific ('learn colors for toddlers'), and long-tail ('rainbow adventure for kids').",
    },
    thumbnailText: {
      type: Type.STRING,
      description: "One short, bold phrase (1–3 words) for the thumbnail overlay.",
    },
  },
  required: ["title", "description", "tags", "thumbnailText"],
  propertyOrdering: ["title", "description", "tags", "thumbnailText"],
};

/**
 * Phase-1 spec: generate 3 distinct title/description/tag + thumbnail-text VARIANTS.
 * The generator picks one as the chosen metadata; all 3 are logged for review.
 */
export const METADATA_SCHEMA: Schema = {
  type: Type.OBJECT,
  properties: {
    variants: {
      type: Type.ARRAY,
      items: VARIANT_SCHEMA,
      description: "Exactly 3 distinct metadata variants, best/most click-worthy first.",
    },
  },
  required: ["variants"],
};

/** Build the prompt for Gemini call #2 — YouTube metadata. */
export function buildMetadataPrompt(row: ContentRow, script: string): string {
  const characterNames = BIBLE.characters.map((c) => c.name).join(" and ");
  const excerpt = script.length > 2000 ? script.slice(0, 2000) + "\n…[truncated]" : script;
  return [
    `You are a YouTube SEO specialist writing metadata for the "Made for Kids" channel`,
    `"${BIBLE.channelName}". Recurring characters: ${characterNames}.`,
    `Goal: maximize search discovery and click-through for a preschool/toddler audience.`,
    ``,
    `Episode #${row.videoNumber} — Topic: ${row.topic} (${row.format}).`,
    ``,
    `Produce EXACTLY 3 DISTINCT variants (vary the hook/angle/keywords across them), best first.`,
    `Each variant must follow these rules:`,
    ``,
    `TITLE rules:`,
    `- Follow the pattern "Learn [Topic] with [Character] | Fun Kids Story" (adapt "Learn"`,
    `  to the topic where natural; always keep "| Fun Kids Story"). Under 100 characters.`,
    `- Front-load the main keyword so it reads well when truncated in search results.`,
    ``,
    `DESCRIPTION rules (kid-safe, no links):`,
    `- First sentence: keyword-rich hook (this is what shows in search snippets).`,
    `- 2–3 sentences summarizing what kids will learn, naming the characters.`,
    `- End with a friendly subscribe call-to-action (e.g. "Subscribe for a new ${BIBLE.channelName}`,
    `  episode every week!") followed by 3–5 relevant lowercase hashtags.`,
    ``,
    `THUMBNAIL_TEXT: 1–3 punchy, high-contrast words for the thumbnail overlay.`,
    ``,
    `Base everything on this script:`,
    `"""`,
    excerpt,
    `"""`,
    ``,
    `Return JSON matching the provided schema: an object with a "variants" array of 3 items.`,
  ].join("\n");
}
