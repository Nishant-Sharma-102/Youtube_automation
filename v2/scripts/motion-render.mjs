// Motion-graphics fallback renderer (stand-in for the Blender 3D render): builds
// renders/epN.mp4 from audio/epN.mp3 + the episode's script (as synced captions).
//   node scripts/motion-render.mjs --episode N
import { execFileSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import ffmpegPath from "ffmpeg-static";
import Database from "better-sqlite3";

const FF = ffmpegPath;
const FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf";
const ep = Number(process.argv[process.argv.indexOf("--episode") + 1]);
if (!Number.isInteger(ep)) throw new Error("--episode N required");

const audio = `audio/ep${ep}.mp3`, out = `renders/ep${ep}.mp4`, thumb = `renders/ep${ep}.jpg`, ass = `renders/ep${ep}.ass`;
mkdirSync("renders", { recursive: true });

const db = new Database("./data/queue.db");
const row = db.prepare("SELECT title, script FROM episodes WHERE video_number=?").get(ep);
db.close();
if (!row?.script) throw new Error(`Episode ${ep} has no script`);
const title = row.title || `Giggle Grove — Episode ${ep}`;

function dialogue(script) {
  const out = [];
  for (const raw of script.split(/\r?\n/)) {
    let l = raw.trim();
    if (!l || /^(int\.|ext\.|scene\b|fade\b|cut to)/i.test(l)) continue;
    if (/ - (day|night|morning|evening|continuous)\b/i.test(l) && !/[a-z]/.test(l)) continue;
    l = l.replace(/\[[^\]]*\]/g, "").replace(/\([^)]*\)/g, "").trim();
    if (!l) continue;
    const m = l.match(/^([A-Z0-9 .&'\-]{1,30}?):\s*(.+)$/);
    if (m && !/[a-z]/.test(m[1])) { out.push(m[2].trim()); continue; }
    if (/^[A-Z0-9 .&'\-]{1,30}$/.test(l) && !/[a-z]/.test(l)) continue;
    out.push(l);
  }
  return out;
}
const cues = [];
for (const line of dialogue(row.script))
  for (const s of line.match(/[^.!?]+[.!?]*/g) ?? [line]) { const t = s.trim(); if (t) cues.push(t.length > 90 ? t.slice(0, 88) + "…" : t); }

const probe = (() => { try { execFileSync(FF, ["-i", audio], { stdio: ["ignore", "ignore", "pipe"] }); } catch (e) { return String(e.stderr); } return ""; })();
const m = probe.match(/Duration: (\d+):(\d+):(\d+\.\d+)/);
const dur = m ? +m[1] * 3600 + +m[2] * 60 + parseFloat(m[3]) : 60;
const cs = (s) => { const h = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = s % 60; return `${h}:${String(mm).padStart(2, "0")}:${ss.toFixed(2).padStart(5, "0")}`; };
const esc = (t) => t.replace(/[{}\\]/g, "");

const head = `[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline, Shadow, Encoding
Style: Title,DejaVu Sans,110,&H00FFFFFF,&H00403010,&H64000000,-1,5,120,120,0,1,5,3,1
Style: Cap,DejaVu Sans,70,&H00FFFFFF,&H00403010,&H64000000,-1,2,140,140,120,1,4,3,1
Style: Brand,DejaVu Sans,44,&H0066E0FF,&H00403010,&H64000000,-1,8,80,80,50,1,3,2,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;
const ev = [], intro = Math.min(4, dur * 0.15);
ev.push(`Dialogue: 0,${cs(0)},${cs(intro)},Title,,0,0,0,,${esc(title)}`);
ev.push(`Dialogue: 0,${cs(0)},${cs(dur)},Brand,,0,0,0,,Giggle Grove`);
const per = Math.max(1, dur - intro) / Math.max(1, cues.length);
cues.forEach((c, i) => ev.push(`Dialogue: 0,${cs(intro + i * per)},${cs(intro + (i + 1) * per)},Cap,,0,0,0,,${esc(c)}`));
writeFileSync(ass, head + ev.join("\n") + "\n");

execFileSync(FF, ["-y", "-f", "lavfi", "-i", `color=c=0x2A9D8F:s=1920x1080:r=24:d=${dur.toFixed(2)}`, "-i", audio, "-vf", `ass=${ass}`, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest", out], { stdio: ["ignore", "ignore", "inherit"] });
execFileSync(FF, ["-y", "-ss", (intro / 2).toFixed(1), "-i", out, "-frames:v", "1", "-update", "1", "-q:v", "2", thumb], { stdio: ["ignore", "ignore", "inherit"] });
console.log(`built ${out} (${dur.toFixed(1)}s, ${cues.length} cues) + ${thumb}`);
