// Claude fallback for Phase 1 (used when Gemini has no key or hits its daily quota).
// Same surface as the Gemini client: script() + metadata().
import Anthropic from "@anthropic-ai/sdk";
import type { Config } from "./config.js";
import { bibleText, BIBLE } from "../data/bible.js";
import type { Episode } from "./db.js";
import type { Metadata } from "./gemini.js";

const METADATA_FORMAT = {
  type: "json_schema" as const,
  schema: {
    type: "object",
    properties: {
      variants: {
        type: "array",
        items: {
          type: "object",
          properties: {
            title: { type: "string" },
            description: { type: "string" },
            tags: { type: "array", items: { type: "string" } },
            thumbnailText: { type: "string" },
          },
          required: ["title", "description", "tags", "thumbnailText"],
          additionalProperties: false,
        },
      },
    },
    required: ["variants"],
    additionalProperties: false,
  },
};

export class Claude {
  private client: Anthropic;
  private model: string;
  constructor(cfg: Config) {
    this.client = new Anthropic({ apiKey: cfg.anthropicApiKey });
    this.model = cfg.claudeModel;
  }

  async script(ep: Episode): Promise<string> {
    const prompt = [
      `You are the head writer for the "Made for Kids" channel "${BIBLE.channel}".`,
      `Write a complete 5–8 minute episode script (~700–1100 words of spoken content).`,
      ``, `=== CHARACTER BIBLE (follow exactly) ===`, bibleText(), ``,
      `=== EPISODE ===`, `#${ep.video_number} — Topic: ${ep.topic} (${ep.format})`, ``,
      `Structure: cold-open hook → learning/story beats → clear lesson reinforcement →`,
      `the "Giggle Grove Goodbye" sign-off. Screenplay format: SCENE headings, CHARACTER`,
      `cue lines with dialogue, brief [action] cues. Simple warm language for ages 2–5.`,
      `Output ONLY the script text.`,
    ].join("\n");
    const resp = await this.client.messages.create({
      model: this.model, max_tokens: 16000, messages: [{ role: "user", content: prompt }],
    });
    const text = resp.content.filter((b): b is Anthropic.TextBlock => b.type === "text").map((b) => b.text).join("").trim();
    if (!text) throw new Error("Claude returned empty script");
    return text;
  }

  async metadata(ep: Episode, script: string): Promise<Metadata[]> {
    const names = BIBLE.characters.map((c) => c.name).join(" and ");
    const excerpt = script.length > 2000 ? script.slice(0, 2000) + "…" : script;
    const prompt = [
      `YouTube SEO for "${BIBLE.channel}" (Made for Kids). Characters: ${names}.`,
      `Episode #${ep.video_number} — ${ep.topic}. Produce EXACTLY 3 distinct metadata`,
      `variants (vary hook/keywords), best first. Title pattern "Learn [Topic] with`,
      `[Character] | Fun Kids Story"; descriptions end with a subscribe CTA + hashtags.`,
      `Base on this script:`, `"""`, excerpt, `"""`,
    ].join("\n");
    const resp = await this.client.messages.create({
      model: this.model, max_tokens: 4000, messages: [{ role: "user", content: prompt }],
      output_config: { format: METADATA_FORMAT },
    });
    const raw = resp.content.filter((b): b is Anthropic.TextBlock => b.type === "text").map((b) => b.text).join("").trim();
    const arr = (JSON.parse(raw) as { variants?: Metadata[] }).variants ?? [];
    const clean = arr.filter((v) => v?.title && v?.description && v?.thumbnailText && Array.isArray(v.tags) && v.tags.length);
    if (!clean.length) throw new Error("no valid Claude variants");
    return clean;
  }
}
