"""Mix a subtle, royalty-free cinematic ambient bed under a narration track.

No licensed music (can't download that) — the bed is SYNTHESIZED with ffmpeg:
a warm low drone (root + fifth + octave), slow tremolo for movement, a soft
low-pass + light reverb for air, faded in/out. It is then side-chain ducked by
the narration so speech always stays clear (the bed dips whenever the narrator
speaks and swells in the gaps). Output duration matches the narration exactly,
so Phase-4 sync is unaffected.

Toggle with HISTORY_MUSIC_BED=0 to disable; HISTORY_MUSIC_VOLUME to tune (default 0.11).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from audio_utils import duration_seconds, ffmpeg_bin


def add_music_bed(narration: Path | str, out: Path | str, *, volume: float | None = None,
                  style: str | None = None) -> None:
    ff = ffmpeg_bin()
    narration, out = Path(narration), Path(out)
    style = (style or os.environ.get("HISTORY_MUSIC_STYLE") or "cinematic").strip()
    dur = duration_seconds(narration)
    fade_out_st = max(dur - 3.0, 0.0)
    t = f"{dur + 1:.2f}"

    if style == "kids":
        # Bright, playful MAJOR chord (C4-E4-G4) + a gentle C5 twinkle, faster tremolo,
        # keep the highs for a cheerful sparkle. Warmer/louder than the history drone.
        vol = volume if volume is not None else float(os.environ.get("HISTORY_MUSIC_VOLUME", "0.13"))
        freqs = ["261.63", "329.63", "392.00", "523.25"]
        filt = (
            "[1:a][2:a][3:a][4:a]amix=inputs=4:normalize=0[chord];"
            f"[chord]tremolo=f=2.0:d=0.4,lowpass=f=3200,aecho=0.8:0.6:45:0.2,"
            f"volume={vol},afade=t=in:st=0:d=2,afade=t=out:st={fade_out_st:.2f}:d=3[bed];"
            "[bed][0:a]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=400[bedd];"
            "[0:a][bedd]amix=inputs=2:normalize=0:duration=first[mix]"
        )
    else:
        # Warm low cinematic drone (E2 + A2 + E3), slow tremolo, dark/soft.
        vol = volume if volume is not None else float(os.environ.get("HISTORY_MUSIC_VOLUME", "0.11"))
        freqs = ["82.41", "110.0", "164.81", "82.41"]  # 4th is a harmless dup for a uniform cmd
        filt = (
            "[1:a][2:a][3:a]amix=inputs=3:normalize=0[drone];"
            f"[drone]tremolo=f=0.12:d=0.5,lowpass=f=650,aecho=0.8:0.7:70:0.3,"
            f"volume={vol},afade=t=in:st=0:d=3,afade=t=out:st={fade_out_st:.2f}:d=4[bed];"
            "[bed][0:a]sidechaincompress=threshold=0.015:ratio=8:attack=15:release=500[bedd];"
            "[0:a][bedd]amix=inputs=2:normalize=0:duration=first[mix]"
        )

    cmd = [ff, "-y", "-i", str(narration)]
    n_src = 4 if style == "kids" else 3
    for f in freqs[:n_src]:
        cmd += ["-f", "lavfi", "-t", t, "-i", f"sine=frequency={f}"]
    cmd += ["-filter_complex", filt, "-map", "[mix]", "-c:a", "libmp3lame", "-q:a", "2", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"music-bed mix failed:\n{p.stderr[-800:]}")


def enabled() -> bool:
    return os.environ.get("HISTORY_MUSIC_BED", "1").strip() != "0"
