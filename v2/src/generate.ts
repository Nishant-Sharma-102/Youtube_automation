// PHASE 1 — Content generation.
//   npm run generate            # next draft episode
//   npm run generate -- --video 3
//
// Reads a 'draft' episode, calls Gemini 2.5 Flash for a 5–8 min script + 3 metadata
// variants, writes everything back, sets status = 'script_ready'. Variant #1 is chosen
// as the row's title/description/tags; all 3 are stored for review.
import { loadConfig } from "./config.js";
import { openDb, nextDraft, getByNumber, saveScript, type Episode } from "./db.js";
import { Gemini, type Metadata } from "./gemini.js";
import { Claude } from "./claude.js";

interface Writer { name: string; script(ep: Episode): Promise<string>; metadata(ep: Episode, s: string): Promise<Metadata[]>; }

// Adapt a client instance to the Writer shape (bind methods, add nothing else).
function bindWriter(c: { script(ep: Episode): Promise<string>; metadata(ep: Episode, s: string): Promise<Metadata[]> }) {
  return { script: (ep: Episode) => c.script(ep), metadata: (ep: Episode, s: string) => c.metadata(ep, s) };
}

function pickEpisode(db: ReturnType<typeof openDb>): Episode | null {
  const a = process.argv.find((x) => x.startsWith("--video"));
  if (a) {
    const n = Number(a.includes("=") ? a.split("=")[1] : process.argv[process.argv.indexOf(a) + 1]);
    if (!Number.isInteger(n)) throw new Error("--video requires a number");
    const ep = getByNumber(db, n);
    if (!ep) throw new Error(`No episode #${n} (run npm run db:init)`);
    if (ep.status !== "draft") { console.warn(`Episode #${n} is '${ep.status}', not 'draft' — skipping.`); return null; }
    return ep;
  }
  return nextDraft(db);
}

async function main(): Promise<void> {
  const cfg = loadConfig();
  const db = openDb(cfg.dbPath);
  try {
    const ep = pickEpisode(db);
    if (!ep) { console.warn("No draft episode to generate."); return; }
    console.log(`\n▶ Generating episode #${ep.video_number}: ${ep.topic}\n`);

    // Provider chain: Gemini first (free tier), Claude fallback on no-key/quota/error.
    const writers: Writer[] = [];
    if (cfg.geminiApiKey) writers.push({ name: "gemini", ...bindWriter(new Gemini(cfg)) });
    if (cfg.anthropicApiKey) writers.push({ name: "claude", ...bindWriter(new Claude(cfg)) });
    if (!writers.length) throw new Error("No provider: set GEMINI_API_KEY and/or ANTHROPIC_API_KEY");

    let script = "", variants: Metadata[] = [], used = "";
    let lastErr: unknown;
    for (const w of writers) {
      try {
        console.log(`  … trying ${w.name}`);
        script = await w.script(ep);
        variants = await w.metadata(ep, script);
        used = w.name;
        break;
      } catch (e) {
        lastErr = e;
        console.warn(`  ${w.name} failed (${e instanceof Error ? e.message.slice(0, 80) : e}) — trying next`);
      }
    }
    if (!used) throw new Error(`All providers failed. Last: ${lastErr instanceof Error ? lastErr.message : lastErr}`);
    console.log(`  ✓ ${used}: script (${script.split(/\s+/).length} words)`);
    variants.forEach((v, i) => console.log(`  ✓ ${used} variant ${i + 1}: ${v.title}`));

    const chosen = variants[0];
    saveScript(db, ep.video_number, {
      script, title: chosen.title, description: chosen.description, tags: chosen.tags, variants,
    });
    console.log(`\n✅ Episode #${ep.video_number} → status 'script_ready' (chose variant 1, stored all ${variants.length}).`);
  } finally {
    db.close();
  }
}

main().catch((e) => { console.error("Phase 1 failed:", e instanceof Error ? e.message : e); process.exit(1); });
