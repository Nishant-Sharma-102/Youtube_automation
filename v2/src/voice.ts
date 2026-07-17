// PHASE 2 — Voice generation.
//   npm run voice            # next script_ready episode without audio
//   npm run voice -- --video 1
//
// Extracts spoken dialogue from the script, narrates via ElevenLabs (primary), falls
// back to Google Cloud TTS if ElevenLabs fails or the monthly budget is exhausted,
// chunks long text, saves audio/epN.mp3, records char usage, sets the row's audio_path.
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { loadConfig, type Config } from "./config.js";
import { openDb, nextForVoice, getByNumber, setAudio, type Episode } from "./db.js";
import { assembleMp3, durationSeconds, type Chunk } from "./audio.js";

const USAGE_FILE = "audio/usage.jsonl";

// --- spoken dialogue only (drop scene headings, cues, [actions]) ---
function extractNarration(script: string): string {
  const out: string[] = [];
  for (const raw of script.split(/\r?\n/)) {
    let line = raw.trim();
    if (!line) continue;
    if (/^(int\.|ext\.|scene\b|fade\b|cut to)/i.test(line)) continue;
    if (/ - (day|night|morning|evening|continuous)\b/i.test(line) && !/[a-z]/.test(line)) continue;
    line = line.replace(/\[[^\]]*\]/g, "").replace(/\([^)]*\)/g, "").trim();
    if (!line) continue;
    const inline = line.match(/^([A-Z0-9 .&'\-]{1,30}?):\s*(.+)$/);
    if (inline && !/[a-z]/.test(inline[1])) { out.push(inline[2].trim()); continue; }
    if (/^[A-Z0-9 .&'\-]{1,30}$/.test(line) && !/[a-z]/.test(line)) continue; // bare cue
    out.push(line);
  }
  return out.join(" ").replace(/\s+/g, " ").trim();
}

function chunkText(text: string, max: number): string[] {
  if (text.length <= max) return [text];
  const parts: string[] = [];
  let cur = "";
  for (const s of text.match(/[^.!?]+[.!?]*\s*/g) ?? [text]) {
    if ((cur + s).length > max) { if (cur) parts.push(cur.trim()); cur = s; }
    else cur += s;
  }
  if (cur.trim()) parts.push(cur.trim());
  return parts;
}

function monthToDate(provider: string): number {
  if (!existsSync(USAGE_FILE)) return 0;
  const month = new Date().toISOString().slice(0, 7);
  let total = 0;
  for (const line of readFileSync(USAGE_FILE, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try { const r = JSON.parse(line); if (r.provider === provider && String(r.ts).startsWith(month)) total += r.chars; } catch { /* skip */ }
  }
  return total;
}

// --- providers ---
async function elevenLabs(cfg: Config, text: string): Promise<Chunk[]> {
  const key = cfg.elevenLabsKey!;
  const used = monthToDate("elevenlabs");
  if (used + text.length > cfg.elevenLabsMonthlyLimit) {
    console.warn(`  ⚠ ElevenLabs budget: ${used} used + ${text.length} this episode > ${cfg.elevenLabsMonthlyLimit}/mo — may fail, will fall back.`);
  }
  const chunks: Chunk[] = [];
  for (const [i, part] of chunkText(text, 2500).entries()) {
    const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${cfg.elevenLabsVoiceId}`, {
      method: "POST",
      headers: { "xi-api-key": key, "Content-Type": "application/json", Accept: "audio/mpeg" },
      body: JSON.stringify({ text: part, model_id: cfg.elevenLabsModel, voice_settings: { stability: 0.5, similarity_boost: 0.75 } }),
    });
    if (!res.ok) throw new Error(`ElevenLabs HTTP ${res.status}: ${(await res.text().catch(() => "")).slice(0, 160)}`);
    chunks.push({ buffer: Buffer.from(await res.arrayBuffer()), ext: "mp3" });
    console.log(`    elevenlabs chunk ${i + 1} ok (${part.length} chars)`);
  }
  return chunks;
}

async function googleTts(cfg: Config, text: string): Promise<Chunk[]> {
  const key = cfg.googleTtsKey!;
  const lang = cfg.googleTtsVoice.split("-").slice(0, 2).join("-") || "en-US";
  const chunks: Chunk[] = [];
  for (const [i, part] of chunkText(text, 4800).entries()) {
    const res = await fetch(`https://texttospeech.googleapis.com/v1/text:synthesize?key=${key}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: { text: part }, voice: { languageCode: lang, name: cfg.googleTtsVoice }, audioConfig: { audioEncoding: "MP3" } }),
    });
    if (!res.ok) throw new Error(`Google TTS HTTP ${res.status}: ${(await res.text().catch(() => "")).slice(0, 160)}`);
    const json = (await res.json()) as { audioContent?: string };
    if (!json.audioContent) throw new Error("Google TTS: no audioContent");
    chunks.push({ buffer: Buffer.from(json.audioContent, "base64"), ext: "mp3" });
    console.log(`    google-tts chunk ${i + 1} ok (${part.length} chars)`);
  }
  return chunks;
}

async function generateVoice(cfg: Config, n: number, text: string): Promise<{ provider: string; chars: number; path: string }> {
  mkdirSync("audio", { recursive: true });
  const outPath = `audio/ep${n}.mp3`;
  const chain: Array<[string, (c: Config, t: string) => Promise<Chunk[]>]> = [];
  if (cfg.elevenLabsKey) chain.push(["elevenlabs", elevenLabs]);
  if (cfg.googleTtsKey) chain.push(["google-tts", googleTts]);
  if (!chain.length) throw new Error("No TTS provider configured (ELEVENLABS_API_KEY or GOOGLE_TTS_API_KEY).");

  let lastErr: unknown;
  for (const [name, fn] of chain) {
    try {
      console.log(`  … trying ${name}`);
      const chunks = await fn(cfg, text);
      assembleMp3(chunks, outPath);
      appendFileSync(USAGE_FILE, JSON.stringify({ ts: new Date().toISOString(), video: n, provider: name, chars: text.length }) + "\n");
      return { provider: name, chars: text.length, path: outPath };
    } catch (e) { lastErr = e; console.warn(`  ${name} failed (${e instanceof Error ? e.message.slice(0, 100) : e}) — trying next`); }
  }
  throw new Error(`All TTS providers failed. Last: ${lastErr instanceof Error ? lastErr.message : lastErr}`);
}

function pick(db: ReturnType<typeof openDb>): Episode | null {
  const a = process.argv.find((x) => x.startsWith("--video"));
  if (a) {
    const n = Number(a.includes("=") ? a.split("=")[1] : process.argv[process.argv.indexOf(a) + 1]);
    const ep = getByNumber(db, n);
    if (!ep) throw new Error(`No episode #${n}`);
    return ep;
  }
  return nextForVoice(db);
}

async function main(): Promise<void> {
  const cfg = loadConfig();
  const db = openDb(cfg.dbPath);
  try {
    const ep = pick(db);
    if (!ep) { console.warn("No script_ready episode without audio."); return; }
    if (!ep.script) throw new Error(`Episode #${ep.video_number} has no script.`);
    const narration = extractNarration(ep.script);
    console.log(`\n▶ Voicing episode #${ep.video_number} (${narration.length} chars of narration)\n`);

    const r = await generateVoice(cfg, ep.video_number, narration);
    setAudio(db, ep.video_number, r.path);
    console.log(`\n✅ Voice by ${r.provider} — ${r.chars} chars, month-to-date ${monthToDate(r.provider)}/${cfg.elevenLabsMonthlyLimit}`);
    console.log(`   ${r.path} (${Math.round(durationSeconds(r.path))}s), audio_path saved (status stays 'script_ready').`);
  } finally {
    db.close();
  }
}

main().catch((e) => { console.error("Phase 2 failed:", e instanceof Error ? e.message : e); process.exit(1); });
