"""
Visual quality analyzer for cover PDFs.

Renders the cover via PyMuPDF, then checks:
  - brightness (not too dark, not washed out)
  - contrast (text area vs image area)
  - color variance (not a flat blank page)
  - dominant color saturation (avoid grey covers)
  - dimension sanity (renders successfully)

Also generates thumbnails (cached on disk) for the UI.
"""
import io
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class CoverVisualReport:
    rendered:        bool
    width_px:        int
    height_px:       int
    brightness:      float          # 0-255 mean luminance
    contrast:        float          # 0-100 stddev of luminance
    color_variance:  float          # how much hue varies (0-1)
    dominant_sat:    float          # dominant color saturation (0-1)
    thumb_readability: float = 0.0  # 0-100 — title legibility at Amazon thumbnail size
    issues:          list = None    # list[(severity, code, message)]

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


def _render_cover_first_page(cover_pdf: Path, dpi: int = 100) -> Optional[Image.Image]:
    """Renders the first (and only) page of a cover PDF as a PIL image."""
    try:
        import fitz
        doc = fitz.open(str(cover_pdf))
        if doc.page_count == 0:
            doc.close()
            return None
        page = doc.load_page(0)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")
        doc.close()
        return Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        logger.warning(f"Failed to render {cover_pdf}: {e}")
        return None


def _luminance_stats(img: Image.Image) -> Tuple[float, float]:
    """Returns (mean, stddev) of luminance (0-255)."""
    gray = img.convert("L")
    px = list(gray.getdata())
    n = len(px)
    if n == 0:
        return 0.0, 0.0
    mean = sum(px) / n
    var = sum((p - mean) ** 2 for p in px) / n
    return mean, math.sqrt(var)


def _hue_variance(img: Image.Image, sample: int = 2000) -> float:
    """Crude hue diversity score 0-1 — high means many distinct colors."""
    small = img.resize((50, 50))
    hsv = small.convert("HSV")
    pixels = list(hsv.getdata())
    # Bucket hues into 12 bins; count how many bins have >=2% of pixels
    bins = [0] * 12
    for h, s, v in pixels:
        if s < 30 or v < 30:   # skip near-gray / near-black
            continue
        bins[(h // 22) % 12] += 1
    total = sum(bins)
    if total == 0:
        return 0.0
    active = sum(1 for b in bins if b / total > 0.02)
    return active / 12.0


def _dominant_saturation(img: Image.Image) -> float:
    """Returns saturation (0-1) of the most frequent non-gray color."""
    small = img.convert("RGB").resize((100, 100))
    try:
        pal = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = pal.getpalette() or []
        counts = pal.getcolors() or []
        if not counts:
            return 0.0
        # Sort by frequency, find first saturated color
        counts.sort(reverse=True)
        for count, idx in counts:
            base = idx * 3
            r, g, b = palette[base], palette[base + 1], palette[base + 2]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx == 0:
                continue
            sat = (mx - mn) / mx
            if sat > 0.10:   # ignore near-grays
                return sat
        return 0.0
    except Exception:
        return 0.0


def _thumbnail_title_legibility(img: Image.Image) -> float:
    """
    Score 0-100 — estimates whether the title text is readable at
    Amazon thumbnail size (front face downscaled to ~80 px wide).

    Method (no OCR dep): downscale front-face to thumbnail, measure
    local contrast on the top 55% (where titles live). Pro covers maintain
    high local contrast in the title region even at thumbnail scale.
    """
    w, h = img.size
    # Front face = right ~45% of the wrap
    front_w = max(int(w * 0.45), 1)
    front = img.crop((w - front_w, 0, w, h))
    # Downscale to Amazon thumb-ish (80×120)
    thumb = front.resize((80, max(int(80 * front.size[1] / front.size[0]), 1)),
                         Image.LANCZOS).convert("L")
    tw, th = thumb.size
    # Title region: top 55%
    title_band = thumb.crop((4, 4, tw - 4, max(int(th * 0.55), 6)))
    px = list(title_band.getdata())
    if not px:
        return 0.0
    mean = sum(px) / len(px)
    var  = sum((p - mean) ** 2 for p in px) / len(px)
    std  = math.sqrt(var)
    # Map stddev (typical 10-90) to a 0-100 score with diminishing returns
    score = min(100.0, std * 1.5)
    return round(score, 1)


def analyze_cover(cover_pdf: Path) -> CoverVisualReport:
    """Open cover PDF, render, run visual checks, return report."""
    issues = []
    img = _render_cover_first_page(cover_pdf)
    if img is None:
        return CoverVisualReport(
            rendered=False, width_px=0, height_px=0,
            brightness=0, contrast=0, color_variance=0, dominant_sat=0,
            issues=[("critical", "cover_unreadable",
                     "cover.pdf cannot be rendered (corrupted?)")],
        )

    w, h = img.size
    brightness, contrast = _luminance_stats(img)
    hue_var = _hue_variance(img)
    dom_sat = _dominant_saturation(img)
    thumb_score = _thumbnail_title_legibility(img)

    # ── Quality checks ──────────────────────────────────────────────────
    if brightness < 30:
        issues.append(("warning", "cover_too_dark",
            f"Cover is very dark (luminance {brightness:.0f}/255) — text may be invisible"))
    elif brightness > 230:
        issues.append(("warning", "cover_washed_out",
            f"Cover is very bright/washed out (luminance {brightness:.0f}/255)"))

    if contrast < 25:
        issues.append(("warning", "cover_low_contrast",
            f"Cover has very low contrast ({contrast:.0f}) — looks flat / boring"))

    if hue_var < 0.10 and dom_sat < 0.20:
        issues.append(("warning", "cover_monochrome_grey",
            "Cover is nearly monochromatic grey — visually uninteresting"))

    if dom_sat < 0.15:
        issues.append(("info", "cover_low_saturation",
            f"Cover has low color saturation ({dom_sat:.2f}) — might look muted"))

    # ── Thumbnail readability (Amazon 50-80px) ──────────────────────────
    if thumb_score < 25:
        issues.append(("warning", "cover_unreadable_thumbnail",
            f"Title illisible à la taille thumbnail Amazon (~{thumb_score:.0f}/100). "
            "Augmenter contraste/épaisseur du titre."))
    elif thumb_score < 45:
        issues.append(("info", "cover_weak_thumbnail",
            f"Lisibilité thumbnail moyenne ({thumb_score:.0f}/100) — perfectible"))

    return CoverVisualReport(
        rendered=True, width_px=w, height_px=h,
        brightness=brightness, contrast=contrast,
        color_variance=hue_var, dominant_sat=dom_sat,
        thumb_readability=thumb_score,
        issues=issues,
    )


# ── Thumbnail cache ───────────────────────────────────────────────────────────

def thumbnail_for_cover(
    cover_pdf: Path,
    cache_dir: Path,
    width_px: int = 220,
    force: bool = False,
) -> Optional[Path]:
    """
    Generates (or loads cached) a thumbnail PNG of the cover's front face only.
    Returns the path to the .png on success, None on failure.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Use file modification time in filename for auto-invalidation
    mtime = int(cover_pdf.stat().st_mtime) if cover_pdf.exists() else 0
    thumb_path = cache_dir / f"{cover_pdf.parent.name}_thumb_{width_px}_{mtime}.png"
    if thumb_path.exists() and not force:
        return thumb_path

    img = _render_cover_first_page(cover_pdf, dpi=72)
    if img is None:
        return None
    # Crop the FRONT face only (right ~45% of the wrap)
    w, h = img.size
    front_w = int(w * 0.45)
    front_x = w - front_w
    front = img.crop((front_x, 0, w, h))
    # Resize keeping aspect
    ratio = width_px / front.size[0]
    target = (width_px, int(front.size[1] * ratio))
    front.resize(target, Image.LANCZOS).save(thumb_path, "PNG", optimize=True)
    return thumb_path
