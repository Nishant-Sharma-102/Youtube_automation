"""Pixabay music source (Phase 6).

⚠️ REALITY CHECK: Pixabay's public API (https://pixabay.com/api/docs/) officially
documents IMAGE and VIDEO search only. There is no documented public music/audio
search endpoint. Pixabay music tracks exist on-site under the Pixabay Content
License (free commercial use, no attribution required, no standalone
redistribution), but they are not reliably reachable through the documented API.

So this module has two modes:
  • LIVE  — used only if DOC_PIXABAY_API_KEY is set. Best-effort against the
            configured base URL, in the documented Pixabay param style. VERIFY the
            endpoint/params against your account before trusting a live run; if
            Pixabay returns no audio, switch to a source with a real music API
            (Jamendo, Freesound) — the rest of Phase 6 is source-agnostic.
  • MOCK  — default (no key). Returns clearly-labelled sample candidates so the
            mood mapping, multi-track selection, license logging, and write-back
            can be validated end-to-end without a key. MOCK tracks are NOT real
            and must never be used as an actual licensing paper trail.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from config import Config

# The Pixabay Content License — the same terms apply to every track on Pixabay.
PIXABAY_LICENSE = {
    "name": "Pixabay Content License",
    "summary": ("Free for commercial and non-commercial use with no attribution "
                "required. May not be sold/redistributed as a standalone file, and "
                "may not be used in a service that competes with Pixabay."),
    "url": "https://pixabay.com/service/license-summary/",
}


@dataclass
class Track:
    id: str
    title: str
    duration_sec: float
    page_url: str
    download_url: str
    tags: str = ""
    author: str = ""
    is_mock: bool = False
    license: dict = field(default_factory=lambda: dict(PIXABAY_LICENSE))


# Representative sample candidates per mood for MOCK mode. Durations are realistic
# for Pixabay instrumental tracks (~2-4 min) — deliberately shorter than a 10-15
# min episode so the multi-track/loop selection logic is exercised.
_MOCK: dict[str, list[Track]] = {
    "epic-orchestral": [
        Track("mock-e1", "Rise of Empires (Epic Orchestral)", 168, "https://pixabay.com/music/mock-e1", "mock://e1", "epic,orchestral,cinematic", "MockComposer", True),
        Track("mock-e2", "The Last Stand (Cinematic Drums)", 142, "https://pixabay.com/music/mock-e2", "mock://e2", "epic,drums,trailer", "MockComposer", True),
        Track("mock-e3", "Ashes of Glory (Orchestral Adagio)", 205, "https://pixabay.com/music/mock-e3", "mock://e3", "orchestral,emotional,strings", "MockComposer", True),
        Track("mock-e4", "March of Ages (Measured Epic)", 231, "https://pixabay.com/music/mock-e4", "mock://e4", "epic,measured,brass", "MockComposer", True),
    ],
    "tense-minimal": [
        Track("mock-t1", "Cold Signal (Minimal Tension)", 176, "https://pixabay.com/music/mock-t1", "mock://t1", "tense,minimal,dark", "MockComposer", True),
        Track("mock-t2", "Unanswered (Unsettling Drone)", 198, "https://pixabay.com/music/mock-t2", "mock://t2", "suspense,drone,ambient", "MockComposer", True),
        Track("mock-t3", "Trace Evidence (Ticking Suspense)", 154, "https://pixabay.com/music/mock-t3", "mock://t3", "mystery,pulse,tension", "MockComposer", True),
    ],
    "curious-bright": [
        Track("mock-s1", "First Light (Curious Ambient)", 188, "https://pixabay.com/music/mock-s1", "mock://s1", "science,curious,bright", "MockComposer", True),
        Track("mock-s2", "Small Steps (Building Synth)", 172, "https://pixabay.com/music/mock-s2", "mock://s2", "hopeful,building,electronic", "MockComposer", True),
        Track("mock-s3", "Discovery (Restrained Wonder)", 214, "https://pixabay.com/music/mock-s3", "mock://s3", "wonder,ambient,restrained", "MockComposer", True),
    ],
    "dramatic-speculative": [
        Track("mock-a1", "What If (Dramatic Hybrid)", 190, "https://pixabay.com/music/mock-a1", "mock://a1", "dramatic,hybrid,epic,tense", "MockComposer", True),
        Track("mock-a2", "Divergence (Speculative Build)", 166, "https://pixabay.com/music/mock-a2", "mock://a2", "speculative,build,cinematic", "MockComposer", True),
        Track("mock-a3", "Other Timelines (Epic Tension)", 222, "https://pixabay.com/music/mock-a3", "mock://a3", "epic,tension,dramatic", "MockComposer", True),
    ],
}


class PixabaySource:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self.mock = not bool(cfg.pixabay_api_key)

    def search(self, mood_key: str, query: str) -> list[Track]:
        if self.mock:
            return list(_MOCK.get(mood_key, []))
        return self._search_live(query)

    def _search_live(self, query: str) -> list[Track]:
        # Best-effort, documented Pixabay param style. Unverified for audio.
        params = {"key": self._cfg.pixabay_api_key, "q": query, "per_page": "50", "order": "popular"}
        last = None
        for attempt in range(self._cfg.retry_attempts):
            try:
                r = httpx.get(self._cfg.pixabay_base_url, params=params, timeout=60.0)
                r.raise_for_status()
                hits = r.json().get("hits", [])
                out = []
                for h in hits:
                    dur = float(h.get("duration", 0) or 0)
                    dl = h.get("download_url") or h.get("audio") or h.get("previewURL") or ""
                    if not dur or not dl:
                        continue
                    out.append(Track(
                        id=str(h.get("id", "")), title=h.get("title") or h.get("tags", "")[:40],
                        duration_sec=dur, page_url=h.get("pageURL", ""), download_url=dl,
                        tags=h.get("tags", ""), author=h.get("user", ""), is_mock=False,
                    ))
                return out
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < self._cfg.retry_attempts - 1:
                    time.sleep(self._cfg.retry_base_delay * (2 ** attempt))
        raise RuntimeError(
            f"Pixabay live search failed ({last}). Pixabay's API may not expose audio — "
            "consider a documented music API (Jamendo/Freesound)."
        )

    def download(self, track: Track, out_path) -> None:
        if track.is_mock or track.download_url.startswith("mock://"):
            out_path.write_bytes(
                f"MOCK-MUSIC-TRACK\ntitle={track.title}\nduration={track.duration_sec}s\n"
                f"page={track.page_url}\nlicense={track.license['name']}\n".encode()
            )
            return
        last = None
        for attempt in range(self._cfg.retry_attempts):
            try:
                r = httpx.get(track.download_url, timeout=300.0, follow_redirects=True)
                r.raise_for_status()
                out_path.write_bytes(r.content)
                return
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < self._cfg.retry_attempts - 1:
                    time.sleep(self._cfg.retry_base_delay * (2 ** attempt))
        raise RuntimeError(f"Track download failed after retries: {last}")
