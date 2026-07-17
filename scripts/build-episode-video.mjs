// Build a narrated episode video: colored background + timed text cards over the
// generated narration audio. Not 3D animation — clean motion-graphics with real audio.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import ffmpegPath from "ffmpeg-static";

const AUDIO = "renders/ep1-audio.wav";
const ASS = "renders/ep1.ass";
const OUT = "renders/ep1.mp4";
const THUMB = "renders/ep1.jpg";
const TITLE = "Meet New Friends with Milo & Lulu";

// dialogue lines to show (kept in sync-ish with the narration by even distribution)
const lines = process.argv.slice(2);

// audio duration
const probe = `${(() => {
  try { execFileSync(ffmpegPath, ["-i", AUDIO], { stdio: ["ignore", "ignore", "pipe"] }); } catch (e) { return String(e.stderr); }
  return "";
})()}`;
const m = probe.match(/Duration: (\d+):(\d+):(\d+\.\d+)/);
const dur = m ? (+m[1]) * 3600 + (+m[2]) * 60 + parseFloat(m[3]) : 78;

const cs = (s) => {
  const h = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = (s % 60);
  return `${h}:${String(mm).padStart(2, "0")}:${ss.toFixed(2).padStart(5, "0")}`;
};

const head = `[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline, Shadow, Encoding
Style: Title,DejaVu Sans,86,&H00FFFFFF,&H00403010,&H64000000,-1,5,80,80,0,1,4,2,1
Style: Line,DejaVu Sans,58,&H00FFFFFF,&H00403010,&H64000000,-1,2,90,90,90,1,4,3,1
Style: Brand,DejaVu Sans,40,&H0066E0FF,&H00403010,&H64000000,-1,8,60,60,40,1,3,2,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;

const ev = [];
// intro title card 0 -> 5s
ev.push(`Dialogue: 0,${cs(0)},${cs(5)},Title,,0,0,0,,Giggle Grove`);
ev.push(`Dialogue: 0,${cs(0)},${cs(Math.min(5, dur))},Line,,0,0,0,,${TITLE}`);
// brand footer whole video
ev.push(`Dialogue: 0,${cs(0)},${cs(dur)},Brand,,0,0,0,,Giggle Grove  •  Learn & Play`);
// dialogue lines spread from 5s to end
const start = 5, span = Math.max(1, dur - start), per = span / Math.max(1, lines.length);
lines.forEach((ln, i) => {
  const a = start + i * per, b = start + (i + 1) * per;
  const safe = ln.replace(/[{}]/g, "").trim();
  ev.push(`Dialogue: 0,${cs(a)},${cs(b)},Line,,0,0,0,,${safe}`);
});

writeFileSync(ASS, head + ev.join("\n") + "\n");

// render video: warm teal background + burned text + narration, encoded for YouTube
execFileSync(ffmpegPath, [
  "-y",
  "-f", "lavfi", "-i", `color=c=0x2A9D8F:s=1280x720:r=25:d=${dur.toFixed(2)}`,
  "-i", AUDIO,
  "-vf", `ass=${ASS}`,
  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
  "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
  "-shortest", OUT,
], { stdio: ["ignore", "ignore", "inherit"] });

// thumbnail from a frame during the title card
execFileSync(ffmpegPath, ["-y", "-ss", "2", "-i", OUT, "-vframes", "1", "-q:v", "2", THUMB], { stdio: ["ignore", "ignore", "inherit"] });

console.log("built", OUT, "and", THUMB);
