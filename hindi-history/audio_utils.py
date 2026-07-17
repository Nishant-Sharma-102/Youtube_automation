"""ffmpeg helpers for Phase 2 — duration measurement, concatenation, and silent
placeholders (for testing without a TTS credential).

We reuse a static ffmpeg binary if no system ffmpeg is present. No ffprobe needed:
`ffmpeg -i <file>` prints the duration to stderr, which we parse.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from config import PROJECT_DIR

_FFMPEG: str | None = None
_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def ffmpeg_bin() -> str:
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    env = (os.environ.get("HISTORY_FFMPEG") or "").strip()
    candidates = [env] if env else []
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)
    # Fall back to the static binary bundled with the kids project's node_modules.
    candidates.append(str(PROJECT_DIR.parent / "node_modules" / "ffmpeg-static" / "ffmpeg"))
    for c in candidates:
        if c and Path(c).exists():
            _FFMPEG = c
            return c
    raise SystemExit(
        "ffmpeg not found. Install ffmpeg (apt-get install ffmpeg) or set HISTORY_FFMPEG "
        "to a binary path."
    )


def duration_seconds(path: str | Path) -> float:
    """Exact audio duration in seconds, parsed from ffmpeg's header read."""
    proc = subprocess.run(
        [ffmpeg_bin(), "-i", str(path)], capture_output=True, text=True
    )
    m = _DUR_RE.search(proc.stderr)
    if not m:
        raise RuntimeError(f"Could not parse duration for {path}:\n{proc.stderr[-400:]}")
    h, mm, ss = m.groups()
    return round(int(h) * 3600 + int(mm) * 60 + float(ss), 3)


def probe_streams(path: str | Path) -> dict:
    """Report container duration + presence of video/audio streams.

    No ffprobe dependency: `ffmpeg -i <file>` prints stream lines and Duration to
    stderr (same trick as duration_seconds), which we parse.
    """
    proc = subprocess.run(
        [ffmpeg_bin(), "-i", str(path)], capture_output=True, text=True
    )
    err = proc.stderr
    m = _DUR_RE.search(err)
    duration = None
    if m:
        h, mm, ss = m.groups()
        duration = round(int(h) * 3600 + int(mm) * 60 + float(ss), 3)
    return {
        "duration": duration,
        "has_video": "Video:" in err,
        "has_audio": "Audio:" in err,
    }


def concat_mp3(parts: list[str | Path], out_path: str | Path) -> None:
    """Join MP3 parts in order into one master track (re-encoded for a clean file)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in parts:
            # concat demuxer: escape single quotes in paths
            safe = str(Path(p).resolve()).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")
        listfile = f.name
    try:
        subprocess.run(
            [ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", listfile,
             "-c:a", "libmp3lame", "-q:a", "2", str(out_path)],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg concat failed:\n{e.stderr[-400:]}") from e
    finally:
        os.unlink(listfile)


def make_silence(seconds: float, out_path: str | Path) -> None:
    """Generate a silent MP3 of the given length — placeholder for --silent testing."""
    subprocess.run(
        [ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{max(seconds, 0.5):.3f}", "-c:a", "libmp3lame", "-q:a", "9", str(out_path)],
        capture_output=True, text=True, check=True,
    )
