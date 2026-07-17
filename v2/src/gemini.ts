// Gemini 2.5 Flash client — episode script + 3 metadata variants.
import { GoogleGenAI, Type, type Schema } from "@google/genai";
import { type Config, requireGeminiKey } from "./config.js";
import { bibleText, BIBLE } from "../data/bible.js";
import type { Episode } from "./db.js";

export interface Metadata { title: string; description: string; tags: string[]; thumbnailText: string; }

const VARIANTS_SCHEMA: Schema = {
  type: Type.OBJECT,
  properties: {
    variants: {
      type: Type.ARRAY,
      description: "Exactly 3 distinct metadata variants, best first.",
      items: {
        type: Type.OBJECT,
        properties: {
          title: { type: Type.STRING, description: 'Pattern "Learn [Topic] with [Character] | Fun Kids Story", <100 chars' },
          description: { type: Type.STRING, description: "2–4 kid-friendly sentences; subscribe CTA + a few hashtags" },
          tags: { type: Type.ARRAY, items: { type: Type.STRING }, description: "12–15 lowercase SEO tags" },
          thumbnailText: { type: Type.STRING, description: "1–3 punchy words" },
        },
        required: ["title", "description", "tags", "thumbnailText"],
        propertyOrdering: ["title", "description", "tags", "thumbnailText"],
      },
    },
  },
  required: ["variants"],
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Retry transient errors (503); fail fast on quota (429/RESOURCE_EXHAUSTED). */
async function withRetry<T>(label: string, fn: () => Promise<T>): Promise<T> {
  let last: unknown;
  for (let attempt = 1; attempt <= 4; attempt++) {
    try {
      return await fn();
    } catch (e) {
      last = e;
      const msg = (e instanceof Error ? e.message : String(e)).toLowerCase();
      if (msg.includes("429") || msg.includes("resource_exhausted") || msg.includes("quota")) {
        throw e; // quota — retrying won't help
      }
      if (attempt < 4) {
        console.warn(`${label} failed (attempt ${attempt}/4), retrying…`);
        await sleep(1000 * 2 ** (attempt - 1));
      }
    }
  }
  throw last;
}

export class Gemini {
  private ai: GoogleGenAI;
  private model: string;
  constructor(cfg: Config) {
    this.ai = new GoogleGenAI({ apiKey: requireGeminiKey(cfg) });
    this.model = cfg.geminiModel;
  }

  /** 5–8 minute episode script (~700–1100 words) as a readable screenplay. */
  async script(ep: Episode): Promise<string> {
    const prompt = [
      `You are the head writer for the "Made for Kids" channel "${BIBLE.channel}".`,
      `Write a complete 5–8 minute episode script (~700–1100 words of spoken content).`,
      ``,
      `=== CHARACTER BIBLE (follow exactly) ===`,
      bibleText(),
      ``,
      `=== EPISODE ===`,
      `#${ep.video_number} — Topic: ${ep.topic} (${ep.format})`,
      ``,
      `Structure: cold-open hook → learning/story beats → clear lesson reinforcement →`,
      `the "Giggle Grove Goodbye" sign-off. Write as a screenplay: SCENE headings,`,
      `CHARACTER cue lines with dialogue, brief [action] cues. Simple, warm language for`,
      `ages 2–5, with the participation moments. Output ONLY the script text.`,
    ].join("\n");
    return withRetry(`gemini.script(#${ep.video_number})`, async () => {
      const resp = await this.ai.models.generateContent({ model: this.model, contents: prompt });
      const text = resp.text?.trim();
      if (!text) throw new Error("empty script");
      return text;
    });
  }

  /** 3 distinct metadata variants based on the script. */
  async metadata(ep: Episode, script: string): Promise<Metadata[]> {
    const names = BIBLE.characters.map((c) => c.name).join(" and ");
    const excerpt = script.length > 2000 ? script.slice(0, 2000) + "…" : script;
    const prompt = [
      `YouTube SEO for "${BIBLE.channel}" (Made for Kids). Characters: ${names}.`,
      `Episode #${ep.video_number} — ${ep.topic} (${ep.format}).`,
      `Produce EXACTLY 3 distinct metadata variants (vary the hook/keywords), best first.`,
      `Title pattern: "Learn [Topic] with [Character] | Fun Kids Story". Descriptions end`,
      `with a subscribe CTA + 3–5 hashtags. Base them on this script:`,
      `"""`, excerpt, `"""`,
      `Return JSON: { "variants": [ ...3 items... ] }.`,
    ].join("\n");
    return withRetry(`gemini.metadata(#${ep.video_number})`, async () => {
      const resp = await this.ai.models.generateContent({
        model: this.model,
        contents: prompt,
        config: { responseMimeType: "application/json", responseSchema: VARIANTS_SCHEMA },
      });
      const raw = resp.text?.trim();
      if (!raw) throw new Error("empty metadata");
      const arr = (JSON.parse(raw) as { variants?: Metadata[] }).variants ?? [];
      const clean = arr.filter((v) => v?.title && v?.description && v?.thumbnailText && Array.isArray(v.tags) && v.tags.length);
      if (!clean.length) throw new Error("no valid variants");
      return clean;
    });
  }
}
