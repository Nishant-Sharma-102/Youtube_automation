// Real backend actions shared by the dashboard's API routes (framework-agnostic ESM,
// so it's testable with `node` now and importable by Next.js API routes later).
//
// Channels:
//   documentary  -> local JSON mirror  documentary/data/topics_mirror.json
//   history      -> per-episode files  hindi-history/data/ep<N>.json
//
// Every function here has a REAL effect (Sheet/file update + spawning the next phase as
// a background child process). Pass {dryRun:true} to compute the effect without spawning.
import { spawn, execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, readdirSync, openSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const DOC_MIRROR = resolve(ROOT, "documentary/data/topics_mirror.json");
const HH_DATA = resolve(ROOT, "hindi-history/data");
const SHORTS_DATA = resolve(ROOT, "shorts/data");
const LOG_DIR = resolve(ROOT, "logs/dashboard");

const readJSON = (p, d = null) => { try { return JSON.parse(readFileSync(p, "utf-8")); } catch { return d; } };
const writeJSON = (p, o) => writeFileSync(p, JSON.stringify(o, null, 2));

// A pipeline row/file is "in-flight" once past draft and before published.
const DOC_ACTIVE = new Set(["approved", "script_ready", "storyboard_ready", "audio_ready",
  "visuals_ready", "music_ready", "assembly_ready", "metadata_ready", "ready"]);
// Leftover kids-rhyme episodes still sit in hindi-history/data — the channel is
// history-only now, so exclude them from the review queue.
const KIDS_RE = /milo|giggle grove|nursery|rhyme for kids/i;

export const DOC_PILLARS = ["History", "Mysteries", "Science & Space", "Alternate History"];
export const HISTORY_CATEGORIES = [
  "Indus Valley Civilization", "Vedic Period", "Maurya Empire", "Gupta Empire",
  "Chola Dynasty", "Delhi Sultanate", "Vijayanagara Empire", "Mughal Empire",
  "Maratha Empire", "British Raj", "Indian Freedom Struggle", "Partition of India (1947)",
];

function nextHistoryEpisode() {
  let max = 100;
  if (existsSync(HH_DATA)) {
    for (const f of readdirSync(HH_DATA)) {
      const m = /^ep(\d+)\.json$/.exec(f);
      if (m) max = Math.max(max, Number(m[1]));
    }
  }
  return max + 1;
}

// ---- Review Queue: list pending items across BOTH channels ------------------
export function listPending() {
  const items = [];

  // Documentary review points: title/thumbnail choice (metadata_ready) + keyframe
  // review (visuals_ready). These are the human gates in that pipeline's design.
  const rows = readJSON(DOC_MIRROR, []);
  rows.forEach((r, i) => {
    const st = (r.status || "").toLowerCase();
    if (st !== "metadata_ready" && st !== "visuals_ready") return;
    let meta = {};
    try { meta = JSON.parse(r.scene_breakdown || "{}").metadata || {}; } catch { /* ignore */ }
    items.push({
      channel: "documentary", id: String(i), topic: r.topic || "(untitled)",
      status: st,
      kind: st === "metadata_ready" ? "title & thumbnail choice" : "keyframe review",
      titles: meta.titles || [], thumbnails: meta.thumbnails || [],
    });
  });

  // Hindi History review point: episode assembled (status=ready) but not yet uploaded.
  if (existsSync(HH_DATA)) {
    for (const f of readdirSync(HH_DATA)) {
      const m = /^ep(\d+)\.json$/.exec(f);
      if (!m) continue;
      const d = readJSON(resolve(HH_DATA, f), {});
      const title = d.title || d.title_hindi || f;
      if (KIDS_RE.test(title)) continue;  // skip stale kids-rhyme episodes
      if ((d.status || "").toLowerCase() === "ready" && !d.youtube_video_id) {
        items.push({
          channel: "history", id: `ep${m[1]}`, episode: Number(m[1]),
          topic: d.title || d.title_hindi || f, status: "ready",
          kind: "awaiting upload", video_file: d.video_file_path || null,
        });
      }
    }
  }

  // Shorts review point: short generated (status=ready) but not yet uploaded.
  if (existsSync(SHORTS_DATA)) {
    for (const f of readdirSync(SHORTS_DATA)) {
      const m = /^short_(\d+)\.json$/.exec(f);
      if (!m) continue;
      const d = readJSON(resolve(SHORTS_DATA, f), {});
      if ((d.status || "").toLowerCase() === "ready" && !d.youtube_video_id) {
        items.push({
          channel: "shorts", id: `short_${m[1]}`, shortId: Number(m[1]),
          topic: d.title || d.topic || f, status: "ready",
          kind: "awaiting upload", video_file: d.video_file_path || null,
        });
      }
    }
  }
  return items;
}

function spawnJob(argv, { env = {}, label } = {}) {
  const stamp = label || `job-${argv.join("_").replace(/[^a-z0-9]+/gi, "-").slice(0, 40)}`;
  const logPath = resolve(LOG_DIR, `${stamp}.log`);
  const fd = openSync(logPath, "a");
  const child = spawn(argv[0], argv.slice(1), {
    cwd: ROOT, env: { ...process.env, ...env }, stdio: ["ignore", fd, fd], detached: true,
  });
  child.unref();
  return { pid: child.pid, logPath };
}

// ---- Approve: update status AND trigger the next phase for real -------------
export function approve(channel, id, { choice = "v1", privacy = "private", dryRun = false } = {}) {
  if (channel === "documentary") {
    const rows = readJSON(DOC_MIRROR, []);
    const idx = Number(id);
    const row = rows[idx];
    if (!row) throw new Error(`documentary row ${id} not found`);
    const st = (row.status || "").toLowerCase();
    if (st === "metadata_ready") {
      row.title_choice = choice; row.thumbnail_choice = choice;
      if (!dryRun) writeJSON(DOC_MIRROR, rows);
      // finalize -> publish (private by default for review).
      const argv = ["bash", "-lc",
        `cd ${ROOT}/documentary && .venv/bin/python finalize.py && ` +
        `cd ${ROOT} && node documentary/orchestrator_documentary.js --privacy ${privacy}`];
      const job = dryRun ? { dryRun: true } : spawnJob(argv, { label: `doc-approve-${idx}` });
      return { ok: true, action: `set choices=${choice}, finalize + publish(${privacy})`, ...job };
    }
    if (st === "visuals_ready") {
      // Keyframes approved -> continue the pipeline (music -> assemble -> metadata).
      const argv = ["bash", "-lc",
        `cd ${ROOT}/documentary && .venv/bin/python gen_music.py && .venv/bin/python assemble.py && .venv/bin/python gen_metadata.py`];
      const job = dryRun ? { dryRun: true } : spawnJob(argv, { label: `doc-visuals-${idx}` });
      return { ok: true, action: "keyframes approved; run music→assemble→metadata", ...job };
    }
    throw new Error(`documentary row ${id} is '${st}', not a review state`);
  }

  if (channel === "history") {
    const ep = String(id).replace(/^ep/, "");
    const file = resolve(HH_DATA, `ep${ep}.json`);
    if (!existsSync(file)) throw new Error(`history ${id} not found`);
    // Upload the assembled episode (matches make_episode.sh's final step).
    const argv = ["bash", "-lc",
      `cd ${ROOT} && node hindi-history/orchestrator_history.js --privacy ${privacy} --file data/ep${ep}.json`];
    const job = dryRun ? { dryRun: true } : spawnJob(argv, { label: `hist-approve-ep${ep}` });
    return { ok: true, action: `upload ep${ep} (${privacy})`, ...job };
  }

  if (channel === "shorts") {
    const sid = String(id).replace(/^short_/, "");
    const file = resolve(SHORTS_DATA, `short_${sid}.json`);
    if (!existsSync(file)) throw new Error(`shorts ${id} not found`);
    const argv = ["bash", "-lc",
      `cd ${ROOT} && node shorts/orchestrator_shorts.js --privacy ${privacy} --file data/short_${sid}.json`];
    const job = dryRun ? { dryRun: true } : spawnJob(argv, { label: `shorts-approve-${sid}` });
    return { ok: true, action: `upload short_${sid} (${privacy})`, ...job };
  }
  throw new Error(`unknown channel ${channel}`);
}

// ---- Reject: mark rejected (no publish) -------------------------------------
export function reject(channel, id, { dryRun = false } = {}) {
  if (channel === "documentary") {
    const rows = readJSON(DOC_MIRROR, []);
    const row = rows[Number(id)];
    if (!row) throw new Error(`documentary row ${id} not found`);
    row.status = "rejected";
    if (!dryRun) writeJSON(DOC_MIRROR, rows);
    return { ok: true, action: "status=rejected" };
  }
  if (channel === "history") {
    const ep = String(id).replace(/^ep/, "");
    const file = resolve(HH_DATA, `ep${ep}.json`);
    const d = readJSON(file);
    if (!d) throw new Error(`history ${id} not found`);
    d.status = "rejected";
    if (!dryRun) writeJSON(file, d);
    return { ok: true, action: "status=rejected" };
  }
  if (channel === "shorts") {
    const sid = String(id).replace(/^short_/, "");
    const file = resolve(SHORTS_DATA, `short_${sid}.json`);
    const d = readJSON(file);
    if (!d) throw new Error(`shorts ${id} not found`);
    d.status = "rejected";
    if (!dryRun) writeJSON(file, d);
    return { ok: true, action: "status=rejected" };
  }
  throw new Error(`unknown channel ${channel}`);
}

function insertApprovedDoc(topic, pillar) {
  const rows = readJSON(DOC_MIRROR, []);
  if (rows.some((r) => DOC_ACTIVE.has((r.status || "").toLowerCase())))
    throw new Error("documentary already has an in-flight episode");
  rows.push({
    topic, pillar, script: "", scene_breakdown: "", status: "approved",
    approved: "yes", scheduled_date: "", notes: "manual dashboard trigger",
    title_choice: "", thumbnail_choice: "",
  });
  writeJSON(DOC_MIRROR, rows);
}

// ---- Manual Trigger: write a new row + start the channel pipeline (real) ----
export function manualTrigger(channel, { topic = "", category = "", mode = "review",
                                         privacy = "private", dryRun = false } = {}) {
  // SAFETY: fast mode never publishes public.
  if (mode === "fast") privacy = "private";
  if (!["private", "unlisted", "public"].includes(privacy)) throw new Error("bad privacy");
  topic = topic.trim(); category = category.trim();

  if (channel === "documentary") {
    const pillar = DOC_PILLARS.includes(category) ? category : DOC_PILLARS[0];
    if (!topic) {
      if (dryRun) { topic = `(AI-suggested for ${pillar})`; }
      else topic = execFileSync(resolve(ROOT, "documentary/.venv/bin/python"),
        [resolve(ROOT, "documentary/suggest_topic.py"), "--pillar", pillar],
        { cwd: resolve(ROOT, "documentary"), encoding: "utf-8", timeout: 600000 }).trim();
    }
    if (!topic) throw new Error("no topic (AI returned empty)");
    if (!dryRun) insertApprovedDoc(topic, pillar);
    const argv = ["bash", resolve(ROOT, "scripts/run-pipeline.sh"), privacy];
    const job = dryRun ? { dryRun: true } : spawnJob(argv, { env: { DOC_PUBLISH_PRIVACY: privacy }, label: "doc-manual" });
    return { ok: true, channel, topic, pillar, privacy, ...job };
  }

  if (channel === "history") {
    const seed = topic || category;
    if (!seed) throw new Error("pick a category or type a topic");
    const ep = nextHistoryEpisode();
    const argv = ["bash", resolve(ROOT, "hindi-history/make_episode.sh"), String(ep), seed, privacy];
    const job = dryRun ? { dryRun: true } : spawnJob(argv, { label: `hist-manual-ep${ep}` });
    return { ok: true, channel, topic: seed, episode: ep, privacy, ...job };
  }

  if (channel === "shorts") {
    // Dedicated short-form script from a topic. If none given, borrow the documentary
    // topic-suggester (same channel, same pillars) so the button always works.
    const pillar = DOC_PILLARS.includes(category) ? category : DOC_PILLARS[0];
    if (!topic) {
      if (dryRun) { topic = `(AI-suggested for ${pillar})`; }
      else topic = execFileSync(resolve(ROOT, "documentary/.venv/bin/python"),
        [resolve(ROOT, "documentary/suggest_topic.py"), "--pillar", pillar],
        { cwd: resolve(ROOT, "documentary"), encoding: "utf-8", timeout: 600000 }).trim();
    }
    if (!topic) throw new Error("no topic (AI returned empty)");
    const argv = ["bash", resolve(ROOT, "shorts/make_short.sh"), topic, privacy];
    const job = dryRun ? { dryRun: true } : spawnJob(argv, { label: "shorts-manual" });
    return { ok: true, channel, topic, pillar, privacy, ...job };
  }
  throw new Error(`unknown channel ${channel}`);
}

// CLI test harness:  node web/lib/pipelines.mjs list | approve <ch> <id> | reject <ch> <id>
if (import.meta.url === `file://${process.argv[1]}`) {
  const [cmd, ch, id] = process.argv.slice(2);
  if (cmd === "list") console.log(JSON.stringify(listPending(), null, 2));
  else if (cmd === "approve") console.log(JSON.stringify(approve(ch, id, { dryRun: true }), null, 2));
  else if (cmd === "reject") console.log(JSON.stringify(reject(ch, id, { dryRun: true }), null, 2));
  else if (cmd === "trigger") // node ... trigger <channel> <category> [topic]
    console.log(JSON.stringify(manualTrigger(ch, { category: id, topic: process.argv[5] || "", dryRun: true }), null, 2));
  else console.log("usage: list | approve <ch> <id> | reject <ch> <id> | trigger <ch> <category> [topic]");
}
