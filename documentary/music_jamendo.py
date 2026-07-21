"""Jamendo music source (Phase 6) — the recommended real source.

Jamendo has a documented music API (https://developer.jamendo.com/v3.0/tracks)
returning per-track Creative Commons license metadata — exactly what a monetized
channel needs for a paper trail. Free client_id from developer.jamendo.com.

⚠️ LICENSING for a monetized channel — handled here:
  • Jamendo API tracks carry CC licenses. NonCommercial (…-nc-…) licenses are NOT
    allowed on a monetized channel — this client FILTERS THEM OUT when
    music_require_commercial is set (default), and also drops NoDerivatives (…-nd-…),
    which is risky for use inside an audiovisual work.
  • The commercial-safe CC-BY / CC-BY-SA licenses REQUIRE ATTRIBUTION. This client
    captures per-track attribution text so you can credit correctly.
  • For guaranteed, attribution-free commercial clearance, Jamendo also sells
    Jamendo Licensing (Pro) — separate from the free CC API; not automated here.

Without DOC_JAMENDO_CLIENT_ID this runs in MOCK mode (labelled sample tracks,
including one NC track that gets filtered out to demonstrate the guard).
"""
from __future__ import annotations

import time
import urllib.parse

import httpx

from config import Config
from music_pixabay import Track  # reuse the shared Track dataclass


# Only these raw license codes are accepted for a monetized channel. Everything
# else — any NonCommercial (nc) or NoDerivatives (nd) variant, public-domain,
# missing, or unrecognized — is skipped, not guessed at.
ALLOWED_CODES = {"by", "by-sa"}


def classify_cc(ccurl: str) -> dict:
    """Turn a Creative Commons URL into a license record.

    `code` is the RAW license identifier verbatim from the API's ccurl (e.g. "by",
    "by-sa", "by-nc-nd"), or "" if the URL is missing/unparseable. `ambiguous` is
    True when there is no clean, recognizable code to act on.
    """
    u = (ccurl or "").lower()
    if not u:
        return {"code": "", "name": "MISSING", "url": ccurl or "", "clean": False,
                "ambiguous": True, "commercial_ok": False, "attribution_required": True,
                "no_derivatives": False, "summary": "no license field returned."}
    if "publicdomain" in u or "/zero" in u or "cc0" in u:
        return {"code": "cc0", "name": "CC0 (Public Domain)", "url": ccurl, "clean": False,
                "ambiguous": False, "commercial_ok": True, "attribution_required": False,
                "no_derivatives": False,
                "summary": "public domain — not a CC-BY/CC-BY-SA variant, skipped by policy."}
    seg = u.split("/licenses/")[1].split("/")[0] if "/licenses/" in u else ""
    tokens = set(seg.split("-")) if seg else set()
    if not seg or "by" not in tokens:
        return {"code": seg, "name": "Unknown/ambiguous", "url": ccurl, "clean": False,
                "ambiguous": True, "commercial_ok": False, "attribution_required": True,
                "no_derivatives": "nd" in tokens, "summary": f"unrecognized license '{seg}'."}
    commercial_ok = "nc" not in tokens
    no_deriv = "nd" in tokens
    clean = seg in ALLOWED_CODES  # {"by","by-sa"} — commercial-safe, attribution-only
    bits = ["commercial use " + ("ALLOWED" if commercial_ok else "NOT allowed (NonCommercial)"),
            "attribution REQUIRED"]
    if no_deriv:
        bits.append("no derivatives (risky in an AV work)")
    if "sa" in tokens:
        bits.append("share-alike")
    return {"code": seg, "name": "CC " + seg.upper(), "url": ccurl, "clean": clean,
            "ambiguous": False, "commercial_ok": commercial_ok,
            "attribution_required": True, "no_derivatives": no_deriv,
            "summary": "; ".join(bits) + "."}


def attribution_text(track: Track) -> str:
    lic = track.license
    if not lic.get("attribution_required"):
        return ""  # CC0 / none
    return f"“{track.title}” by {track.author} — {lic['name']} ({lic['url']})"


def description_credit(track: Track) -> str:
    """Standard video-description attribution line (Phase 8 template drops these in):
    “<track>” by <artist> — via Jamendo, CC-BY[-SA]."""
    lic = "CC-BY-SA" if track.license.get("code") == "by-sa" else "CC-BY"
    artist = track.author or "Unknown Artist"
    return f"“{track.title}” by {artist} — via Jamendo, {lic}"


# MOCK candidates. Durations are short so the multi-track path is exercised. One
# track is CC-BY-NC to demonstrate the NonCommercial filter dropping it.
_MOCK = {
    "epic-orchestral": [
        ("mock-j1", "Empires of Dust", 214, "https://creativecommons.org/licenses/by/4.0/", "Aeon Strings"),
        ("mock-j2", "The Long Siege", 187, "https://creativecommons.org/licenses/by-sa/4.0/", "Marc Ostermann"),
        ("mock-j3", "Golden Hour Requiem", 236, "https://creativecommons.org/licenses/by/3.0/", "Lucia Vale"),
        ("mock-j4", "Vault of Kings", 168, "https://creativecommons.org/licenses/by/4.0/", "Aeon Strings"),
        ("mock-jNC", "Cathedral (NC demo)", 300, "https://creativecommons.org/licenses/by-nc-nd/4.0/", "Noncom Artist"),
    ],
    "tense-minimal": [
        ("mock-t1", "Static Pulse", 201, "https://creativecommons.org/licenses/by/4.0/", "Kort"),
        ("mock-t2", "No Answer", 223, "https://creativecommons.org/licenses/by-sa/4.0/", "Hollow Room"),
        ("mock-t3", "Thin Ice", 176, "https://creativecommons.org/publicdomain/zero/1.0/", "Anon"),
    ],
    "curious-bright": [
        ("mock-s1", "First Signal", 199, "https://creativecommons.org/licenses/by/4.0/", "Halcyon"),
        ("mock-s2", "Small Steps", 182, "https://creativecommons.org/licenses/by/4.0/", "Halcyon"),
        ("mock-s3", "Blue Shift", 241, "https://creativecommons.org/licenses/by-sa/4.0/", "Ione"),
    ],
    "dramatic-speculative": [
        ("mock-a1", "Divergence", 208, "https://creativecommons.org/licenses/by/4.0/", "Paradox"),
        ("mock-a2", "Other Roads", 195, "https://creativecommons.org/licenses/by/4.0/", "Paradox"),
        ("mock-a3", "Counterfactual", 233, "https://creativecommons.org/licenses/by-sa/4.0/", "Vael"),
    ],
}


class JamendoSource:
    name = "jamendo"

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self.mock = not bool(cfg.jamendo_client_id)
        self.filtered_out: list[str] = []  # tracks dropped by the license guard

    def _keep(self, t: Track) -> bool:
        if not self._cfg.music_require_commercial:
            return True
        lic = t.license
        if lic.get("clean"):  # strict allowlist: raw code in {"by","by-sa"}
            return True
        if lic.get("ambiguous"):
            reason = "missing/ambiguous license — skipped, not guessed"
        elif not lic.get("commercial_ok"):
            reason = "NonCommercial"
        elif lic.get("no_derivatives"):
            reason = "NoDerivatives"
        else:
            reason = "not a clean CC-BY/CC-BY-SA variant"
        self.filtered_out.append(
            f"{t.title} [{lic.get('name','?')} ({lic.get('code') or 'n/a'}): {reason}]")
        return False

    def search(self, mood_key: str, query: str) -> list[Track]:
        raw = self._search_mock(mood_key) if self.mock else self._search_live(query)
        return [t for t in raw if self._keep(t)]

    def _search_mock(self, mood_key: str) -> list[Track]:
        out = []
        for tid, title, dur, ccurl, artist in _MOCK.get(mood_key, []):
            out.append(Track(tid, title, dur, f"https://jamendo.com/track/{tid}",
                             f"mock://{tid}", "", artist, True, classify_cc(ccurl)))
        return out

    # NOTE: Jamendo's `license=` query param is NOT a reliable commercial filter —
    # tested live, `license=by` returns a full mix of by-nc-*/by-nd tracks. So we do
    # NOT filter server-side; we fetch a broad pool and enforce CC-BY/CC-BY-SA
    # strictly client-side (_keep). CC-BY is rare (~2-5%), so we paginate.
    PAGE_SIZE = 200
    MAX_PAGES = 3

    def _search_live(self, query: str) -> list[Track]:
        tags = "+".join(query.split())
        out: list[Track] = []
        for page in range(self.MAX_PAGES):
            params = {
                "client_id": self._cfg.jamendo_client_id, "format": "json",
                "limit": str(self.PAGE_SIZE), "offset": str(page * self.PAGE_SIZE),
                "fuzzytags": tags, "vocalinstrumental": "instrumental",
                "audioformat": "mp32", "order": "popularity_total",
                "durationbetween": "120_600", "audiodownload_allowed": "true",
                "include": "musicinfo licenses",
            }
            url = f"{self._cfg.jamendo_base_url}/tracks/?" + urllib.parse.urlencode(params)
            results = None
            last = None
            for attempt in range(self._cfg.retry_attempts):
                try:
                    r = httpx.get(url, timeout=60.0)
                    r.raise_for_status()
                    results = r.json().get("results", [])
                    break
                except Exception as e:  # noqa: BLE001
                    last = e
                    if attempt < self._cfg.retry_attempts - 1:
                        time.sleep(self._cfg.retry_base_delay * (2 ** attempt))
            if results is None:
                if out:
                    break  # keep what we have if a later page fails
                raise RuntimeError(f"Jamendo live search failed after retries: {last}")
            for h in results:
                dl = h.get("audiodownload", "")
                if not (dl and h.get("audiodownload_allowed", True)):
                    continue
                out.append(Track(
                    id=str(h.get("id", "")), title=h.get("name", "")[:80],
                    duration_sec=float(h.get("duration", 0) or 0),
                    page_url=h.get("shareurl", ""), download_url=dl,
                    tags=str((h.get("musicinfo", {}) or {}).get("tags", {}))[:120],
                    author=h.get("artist_name", ""), is_mock=False,
                    license=classify_cc(h.get("license_ccurl", "")),
                ))
            if len(results) < self.PAGE_SIZE:
                break  # no more pages
        return out

    def download(self, track: Track, out_path) -> None:
        if track.is_mock or track.download_url.startswith("mock://"):
            out_path.write_bytes(
                f"MOCK-JAMENDO-TRACK\ntitle={track.title}\nartist={track.author}\n"
                f"duration={track.duration_sec}s\nlicense={track.license['name']}\n"
                f"ccurl={track.license['url']}\n".encode())
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
        raise RuntimeError(f"Jamendo track download failed after retries: {last}")
