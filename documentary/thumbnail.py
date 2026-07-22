"""Thumbnail rendering (Phase 8).

Overlays a short, high-impact phrase on the chosen keyframe with a treatment that
stays legible at tiny sizes: heavy uppercase font, thick dark stroke + drop shadow,
and a bottom gradient scrim. Exports 1280x720 JPEG.
"""
from __future__ import annotations

import glob
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
MARGIN = 70
MAX_LINES = 3

# Candidate fonts, best-first. Devanagari-capable fonts come first so Hindi thumbnail
# text renders as real glyphs (Latin-only fonts like Liberation/DejaVu would show
# tofu boxes for Hindi). All common Debian/Ubuntu install paths are covered.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/Sarai/Sarai.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _resolve_font_path(preferred: str | None) -> str:
    """Return a font file that PIL can actually open. Tries the configured font, then
    a Devanagari-first candidate list, then any Devanagari/DejaVu TTF on the system."""
    tried = [preferred] if preferred else []
    for p in tried + _FONT_CANDIDATES:
        if p and Path(p).is_file():
            try:
                ImageFont.truetype(p, 40)
                return p
            except OSError:
                continue
    # Last resort: scan for any Devanagari font, then any DejaVu.
    for pat in ("/usr/share/fonts/**/*evanagari*.ttf", "/usr/share/fonts/**/DejaVuSans*.ttf"):
        for p in glob.glob(pat, recursive=True):
            try:
                ImageFont.truetype(p, 40)
                return p
            except OSError:
                continue
    raise OSError("No usable TrueType font found. Install fonts-lohit-deva "
                  "(Devanagari) or set DOC_THUMB_FONT to a valid .ttf.")


def _cover(img: Image.Image) -> Image.Image:
    """Resize + center-crop to exactly 1280x720."""
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def _scrim(img: Image.Image) -> Image.Image:
    """Darken the bottom ~55% with a smooth gradient so text stays readable."""
    grad = Image.new("L", (1, H), 0)
    start = int(H * 0.42)
    for y in range(H):
        grad.putpixel((0, y), 0 if y < start else int(215 * (y - start) / (H - start)))
    alpha = grad.resize((W, H))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(black, img, alpha)


def _wrap_to_fit(draw, text, font_path, max_w):
    """Find the largest font size at which `text` wraps into <= MAX_LINES within max_w.
    Returns (font, lines)."""
    words = text.upper().split()
    for size in range(190, 42, -6):
        font = ImageFont.truetype(font_path, size)
        # greedy word wrap
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= MAX_LINES and all(draw.textlength(ln, font=font) <= max_w for ln in lines):
            return font, lines
    return ImageFont.truetype(font_path, 46), [text.upper()]


def render_thumbnail(source_path: str, text: str, out_path: Path, font_path: str) -> None:
    font_path = _resolve_font_path(font_path)   # never crash on a missing/bad font
    base = _scrim(_cover(Image.open(source_path).convert("RGB")))
    draw = ImageDraw.Draw(base)
    font, lines = _wrap_to_fit(draw, text, font_path, W - 2 * MARGIN)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    gap = int(line_h * 0.08)
    total_h = len(lines) * line_h + (len(lines) - 1) * gap
    y = H - MARGIN - total_h  # anchor to lower area
    stroke = max(4, font.size // 11)
    shadow = max(3, font.size // 16)

    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = (W - w) / 2
        # drop shadow
        draw.text((x + shadow, y + shadow), ln, font=font, fill=(0, 0, 0),
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        # main: white fill, thick black outline
        draw.text((x, y), ln, font=font, fill=(255, 255, 255),
                  stroke_width=stroke, stroke_fill=(12, 12, 12))
        y += line_h + gap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(out_path, "JPEG", quality=90)
