#!/usr/bin/env python3
"""Manual-trigger dashboard for the history-based channels (Documentary + Hindi History).

A zero-dependency web dashboard (Python stdlib) to kick off a full pipeline run for a
SPECIFIC topic/category instead of waiting for the automatic topic scan. Features:
  - Channel selector (Documentary / Hindi History).
  - Two input modes: free-text topic, or a per-channel category dropdown.
  - Mode toggle: "review" (default; publishes at the chosen privacy so you review) vs
    "fast" (auto-run, force PRIVATE upload — never public).
  - A SERIAL job queue (one run at a time — the box OOMs if pipelines overlap).
  - Live status: channel, topic, phase, elapsed, errors, published URL, log tail.
  - Optional password (DASHBOARD_TOKEN / DOC_WEBUI_TOKEN).

Run:  documentary/.venv/bin/python dashboard.py     (binds 0.0.0.0:${DOC_WEBUI_PORT:-8080})
"""
from __future__ import annotations

import html
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOC = ROOT / "documentary"
HH = ROOT / "hindi-history"
LOG_DIR = ROOT / "logs" / "dashboard"
TOKEN = (os.environ.get("DASHBOARD_TOKEN") or os.environ.get("DOC_WEBUI_TOKEN") or "").strip()
PRIVACIES = ["public", "unlisted", "private"]  # public is the default for Review mode

# --- categories per channel -------------------------------------------------
try:  # keep documentary pillars in sync with its config
    import sys
    sys.path.insert(0, str(DOC))
    from config import PILLARS as DOC_PILLARS  # type: ignore
except Exception:
    DOC_PILLARS = ["History", "Mysteries", "Science & Space", "Alternate History"]

HISTORY_CATEGORIES = [
    "Indus Valley Civilization", "Vedic Period", "Maurya Empire", "Gupta Empire",
    "Chola Dynasty", "Pallava Dynasty", "Delhi Sultanate", "Vijayanagara Empire",
    "Mughal Empire", "Maratha Empire", "Sikh Empire", "British Raj",
    "Indian Freedom Struggle", "Partition of India (1947)", "Ancient India",
    "Medieval India", "Post-Independence India",
]

CHANNELS = {
    "documentary": {"label": "Documentary (English pillars)", "categories": DOC_PILLARS},
    "history":     {"label": "Hindi History (eras/regions)",  "categories": HISTORY_CATEGORIES},
    "shorts":      {"label": "Shorts (vertical, same channel as Documentary)", "categories": DOC_PILLARS},
}

# --- job model + serial queue ----------------------------------------------
JOBS: dict[str, dict] = {}
JOBS_ORDER: list[str] = []
JOB_LOCK = threading.Lock()
Q: "queue.Queue[str]" = queue.Queue()
_seq = 0


def _new_job(channel: str, topic: str, category: str, mode: str, privacy: str) -> dict:
    global _seq
    with JOB_LOCK:
        _seq += 1
        jid = f"{_seq:04d}"
        job = {"id": jid, "channel": channel, "topic": topic, "category": category,
               "mode": mode, "privacy": privacy, "status": "queued", "phase": "queued",
               "created": time.time(), "started": None, "ended": None,
               "url": None, "error": None, "log_path": str(LOG_DIR / f"job-{jid}.log")}
        JOBS[jid] = job
        JOBS_ORDER.insert(0, jid)
    return job


def _next_history_episode() -> int:
    nums = [int(m.group(1)) for p in (HH / "data").glob("ep*.json")
            if (m := re.search(r"ep(\d+)\.json$", p.name))]
    return max(nums + [100]) + 1  # existing go up to ~100; start fresh above


def _doc_published_url() -> str | None:
    try:
        rows = json.loads((DOC / "data" / "topics_mirror.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    for r in reversed(rows):
        if (r.get("status") or "").lower() == "published":
            vid = json.loads(r.get("scene_breakdown") or "{}").get("metadata", {}).get("youtube_video_id")
            return f"https://youtu.be/{vid}" if vid else None
    return None


def _history_url(ep: int) -> str | None:
    try:
        vid = json.loads((HH / "data" / f"ep{ep}.json").read_text(encoding="utf-8")).get("youtube_video_id")
        return f"https://youtu.be/{vid}" if vid else None
    except Exception:
        return None


def _shorts_url() -> str | None:
    """Newest published short's watch URL (make_short.sh auto-assigns the id, so we
    read the highest-numbered short_N.json that has a video id)."""
    files = sorted((ROOT / "shorts" / "data").glob("short_*.json"),
                   key=lambda p: int(re.search(r"short_(\d+)\.json$", p.name).group(1)),
                   reverse=True)
    for p in files:
        try:
            vid = json.loads(p.read_text(encoding="utf-8")).get("youtube_video_id")
        except Exception:
            continue
        if vid:
            return f"https://youtu.be/{vid}"
    return None


PHASE_RE = re.compile(r"^\s*(#{3,4}\s*.+|P\d\b.*|PUBLISH.*)", re.MULTILINE)


def _phase_from_log(path: str) -> str:
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    hits = PHASE_RE.findall(txt)
    return hits[-1].strip().strip("# ").strip() if hits else ""


def _build_command(job: dict) -> tuple[list[str], dict]:
    """Return (argv, extra_env) for the channel. Also does any in-process seeding
    (documentary approved-topic insert). Raises on setup failure."""
    channel, topic, category, privacy = job["channel"], job["topic"], job["category"], job["privacy"]
    if channel == "documentary":
        import config as _cfg  # documentary on sys.path
        from sheet import TopicQueue
        cfg = _cfg.load_config()
        q = TopicQueue(cfg)
        if q.has_active_topic():
            raise RuntimeError("documentary pipeline already has an in-flight topic")
        pillar = category if category in DOC_PILLARS else DOC_PILLARS[0]
        if not topic:
            import research
            topic = research.suggest_one(cfg, pillar, q.existing_topics()).get("topic", "").strip()
        if not topic:
            raise RuntimeError("no topic (AI returned empty); type one")
        q.insert_approved_topic(topic, pillar, "manual dashboard trigger")
        job["topic"] = topic
        return (["bash", str(ROOT / "scripts" / "run-pipeline.sh"), privacy],
                {"DOC_PUBLISH_PRIVACY": privacy})
    if channel == "history":
        seed = topic or category  # blank topic → use the era/region as the seed
        if not seed:
            raise RuntimeError("pick a category or type a topic")
        ep = _next_history_episode()
        job["episode"] = ep
        job["topic"] = seed
        return (["bash", str(HH / "make_episode.sh"), str(ep), seed, privacy], {})
    if channel == "shorts":
        # Dedicated short-form script. Blank topic → borrow the documentary suggester.
        pillar = category if category in DOC_PILLARS else DOC_PILLARS[0]
        if not topic:
            import config as _cfg
            import research
            from sheet import TopicQueue
            cfg = _cfg.load_config()
            topic = research.suggest_one(cfg, pillar, TopicQueue(cfg).existing_topics()).get("topic", "").strip()
        if not topic:
            raise RuntimeError("no topic (AI returned empty); type one")
        job["topic"] = topic
        return (["bash", str(ROOT / "shorts" / "make_short.sh"), topic, privacy], {})
    raise RuntimeError(f"unknown channel {channel!r}")


def run_job(jid: str) -> None:
    job = JOBS[jid]
    job["status"] = "running"; job["started"] = time.time(); job["phase"] = "starting"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        argv, extra_env = _build_command(job)
    except Exception as e:  # setup failure (topic seed, busy, etc.)
        job["status"] = "error"; job["error"] = str(e); job["ended"] = time.time()
        Path(job["log_path"]).write_text(f"setup failed: {e}\n", encoding="utf-8")
        return
    env = {**os.environ, **extra_env}
    with open(job["log_path"], "w", encoding="utf-8") as logf:
        logf.write(f"# {job['channel']} | topic={job['topic']!r} | mode={job['mode']} "
                   f"| privacy={job['privacy']}\n"); logf.flush()
        try:
            proc = subprocess.run(argv, cwd=str(ROOT), env=env, stdout=logf,
                                  stderr=subprocess.STDOUT)
            rc = proc.returncode
        except Exception as e:  # noqa: BLE001
            logf.write(f"\nspawn failed: {e}\n"); rc = 1
    job["ended"] = time.time()
    job["phase"] = _phase_from_log(job["log_path"]) or "done"
    if rc == 0:
        job["status"] = "done"
        if job["channel"] == "documentary":
            job["url"] = _doc_published_url()
        elif job["channel"] == "shorts":
            job["url"] = _shorts_url()
        else:
            job["url"] = _history_url(job.get("episode", -1))
    elif rc == 42:
        job["status"] = "error"; job["error"] = "another run is in progress (lock busy)"
    else:
        job["status"] = "error"; job["error"] = f"pipeline exited with code {rc}"


def worker() -> None:
    while True:
        jid = Q.get()
        try:
            run_job(jid)
        finally:
            Q.task_done()


# --- HTTP -------------------------------------------------------------------
def _fmt_elapsed(job: dict) -> str:
    if not job["started"]:
        return "-"
    end = job["ended"] or time.time()
    s = int(end - job["started"])
    return f"{s // 60}m {s % 60:02d}s"


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Dashboard</title>
<style>
 :root{{--bg:#0e0f13;--panel:#181a20;--ink:#ece9e1;--dim:#9fa0a0;--gold:#c9a24b;--line:#2b2f38;--ok:#5fbf7f;--err:#e06a6a}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif;line-height:1.5}}
 header{{padding:1.6rem clamp(1rem,4vw,3rem) 1rem;border-bottom:1px solid var(--line)}}
 .eyebrow{{color:var(--gold);letter-spacing:.2em;text-transform:uppercase;font-size:.72rem;margin:0}}
 h1{{font-family:Georgia,serif;font-weight:600;margin:.2rem 0;font-size:clamp(1.3rem,3vw,1.9rem)}}
 main{{padding:1.2rem clamp(1rem,4vw,3rem) 4rem;max-width:960px}}
 label{{display:block;margin:.9rem 0 .3rem;color:var(--dim);font-size:.82rem}}
 select,input{{width:100%;padding:.65rem .8rem;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;font-size:1rem}}
 .row{{display:flex;gap:1rem;flex-wrap:wrap}} .row>div{{flex:1;min-width:190px}}
 .modes{{display:flex;gap:1rem;margin-top:.4rem}} .modes label{{margin:0;color:var(--ink);font-size:.95rem;display:flex;gap:.4rem;align-items:center}}
 button{{margin-top:1.4rem;padding:.8rem 1.6rem;background:var(--gold);color:#1a1a1a;border:0;border-radius:8px;font-weight:700;font-size:1rem;cursor:pointer}}
 button:disabled{{opacity:.5;cursor:not-allowed}}
 .note{{color:var(--dim);font-size:.8rem;margin-top:.3rem}}
 table{{width:100%;border-collapse:collapse;margin-top:1rem;font-size:.86rem}}
 th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}}
 th{{color:var(--dim);font-weight:600}}
 .s-running{{color:var(--gold);font-weight:700}} .s-done{{color:var(--ok);font-weight:700}}
 .s-error{{color:var(--err);font-weight:700}} .s-queued{{color:var(--dim)}}
 a{{color:var(--gold)}} pre{{white-space:pre-wrap;word-break:break-word;max-height:240px;overflow:auto;
   background:#0b0c10;border:1px solid var(--line);border-radius:8px;padding:.7rem;font-size:.78rem;color:#cfcfcf;margin-top:1rem}}
</style></head><body>
<header><p class="eyebrow">History channels</p><h1>Pipeline Dashboard — manual trigger</h1></header>
<main>
 <div class="row">
   <div><label>Channel</label><select id="channel" onchange="fillCats()">{channel_options}</select></div>
   <div><label>Privacy</label><select id="privacy">{privacy_options}</select></div>
 </div>
 <div class="row">
   <div><label>Category</label><select id="category"></select></div>
   <div><label>Topic <span class="note">(optional — blank uses the category)</span></label>
     <input id="topic" placeholder="e.g. The Fall of Vijayanagara"></div>
 </div>
 <label>Run mode</label>
 <div class="modes">
   <label><input type="radio" name="mode" value="review" checked onchange="syncMode()"> Review — publish at chosen privacy</label>
   <label><input type="radio" name="mode" value="fast" onchange="syncMode()"> Fast — force PRIVATE, no review</label>
 </div>
 {token_field}
 <button id="go" onclick="go()">Queue &amp; Run</button>
 <p class="note">Runs one at a time (serial). Fast mode always uploads PRIVATE — never public.</p>
 <h2 style="font-family:Georgia,serif">Jobs</h2>
 <table><thead><tr><th>#</th><th>Channel</th><th>Topic</th><th>Mode</th><th>Status</th><th>Phase</th><th>Elapsed</th><th>Result</th></tr></thead>
 <tbody id="jobs"></tbody></table>
 <pre id="log"></pre>
</main>
<script>
const CH={channels_json};
function fillCats(){{
  const ch=document.getElementById('channel').value, sel=document.getElementById('category');
  sel.innerHTML='<option value="">— pick a category —</option>'+(CH[ch]||[]).map(c=>`<option>${{c}}</option>`).join('');
}}
function syncMode(){{
  const fast=document.querySelector('input[name=mode]:checked').value==='fast';
  const p=document.getElementById('privacy');
  if(fast){{ p.value='private'; p.disabled=true; }} else {{ p.disabled=false; }}
}}
async function go(){{
  const btn=document.getElementById('go'); btn.disabled=true;
  const body=new URLSearchParams({{
    channel:document.getElementById('channel').value,
    category:document.getElementById('category').value,
    topic:document.getElementById('topic').value,
    privacy:document.getElementById('privacy').value,
    mode:document.querySelector('input[name=mode]:checked').value,
    token:(document.getElementById('token')||{{}}).value||''
  }});
  const r=await fetch('/generate',{{method:'POST',body}}); const j=await r.json();
  btn.disabled=false;
  if(!r.ok){{ alert(j.error||'failed'); return; }}
  poll();
}}
async function poll(){{
  const r=await fetch('/status'); const j=await r.json();
  document.getElementById('jobs').innerHTML=j.jobs.map(x=>
    `<tr><td>${{x.id}}</td><td>${{x.channel}}</td><td>${{x.topic||'-'}}</td><td>${{x.mode}}</td>`+
    `<td class="s-${{x.status}}">${{x.status}}</td><td>${{x.phase||'-'}}</td><td>${{x.elapsed}}</td>`+
    `<td>${{x.url?`<a href="${{x.url}}" target="_blank">video</a>`:(x.error||'')}}</td></tr>`).join('');
  document.getElementById('log').textContent=j.log||'';
}}
fillCats(); syncMode(); poll(); setInterval(poll,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"ok": True})
        if path == "/status":
            return self._status()
        if path in ("/", "/index.html"):
            ch_opts = "".join(f'<option value="{k}">{html.escape(v["label"])}</option>'
                              for k, v in CHANNELS.items())
            p_opts = "".join(f'<option>{p}</option>' for p in PRIVACIES)
            tok = ('<label>Access token</label><input id="token" type="password" placeholder="required">'
                   if TOKEN else "")
            return self._send(200, PAGE.format(
                channel_options=ch_opts, privacy_options=p_opts, token_field=tok,
                channels_json=json.dumps({k: v["categories"] for k, v in CHANNELS.items()})),
                "text/html; charset=utf-8")
        return self._json(404, {"error": "not found"})

    def _status(self):
        with JOB_LOCK:
            ids = list(JOBS_ORDER)
        jobs = []
        running_log = ""
        for jid in ids[:20]:
            j = JOBS[jid]
            jobs.append({"id": j["id"], "channel": j["channel"], "topic": j["topic"],
                         "mode": j["mode"], "status": j["status"],
                         "phase": _phase_from_log(j["log_path"]) if j["status"] == "running" else j["phase"],
                         "elapsed": _fmt_elapsed(j), "url": j["url"], "error": j["error"]})
            if j["status"] == "running" and not running_log:
                try:
                    running_log = "\n".join(Path(j["log_path"]).read_text(
                        encoding="utf-8", errors="replace").splitlines()[-40:])
                except Exception:
                    running_log = ""
        return self._json(200, {"jobs": jobs, "log": running_log})

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/generate":
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        f = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))
        g = lambda k, d="": (f.get(k, [d])[0]).strip()
        channel, category, topic = g("channel"), g("category"), g("topic")
        mode, privacy, token = g("mode", "review"), g("privacy", "private"), g("token")

        if TOKEN and token != TOKEN:
            return self._json(403, {"error": "invalid access token"})
        if channel not in CHANNELS:
            return self._json(400, {"error": "unknown channel"})
        if mode not in ("review", "fast"):
            return self._json(400, {"error": "mode must be review|fast"})
        # SAFETY: fast mode never publishes public — force private.
        if mode == "fast":
            privacy = "private"
        if privacy not in PRIVACIES:
            return self._json(400, {"error": "privacy must be private|unlisted|public"})
        if not topic and not category:
            return self._json(400, {"error": "pick a category or type a topic"})

        job = _new_job(channel, topic, category, mode, privacy)
        Q.put(job["id"])
        return self._json(200, {"ok": True, "id": job["id"], "queued": Q.qsize()})


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    port = int(os.environ.get("DOC_WEBUI_PORT") or "8080")
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Pipeline dashboard on http://0.0.0.0:{port}  "
          f"(access: {'token-gated' if TOKEN else 'OPEN'}; channels: {', '.join(CHANNELS)})",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
