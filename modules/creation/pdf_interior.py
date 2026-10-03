"""
KDP Interior PDF Generator — ReportLab v2  (professional edition)
Produces a polished 6×9" interior with:
  - Decorative welcome page + "How to use this book"
  - Detailed Table of Contents with section descriptions
  - Full-page decorative section-break pages
  - Illustrated journal pages (prompt box, mood tracker, corner ornaments)
  - Illustrated log pages (sketch box, GPS field, specimen table, rating stars)
  - Quiz pages with score boxes and answer sheets
  - Running page headers + centered page numbers
  - Thank You page
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Callable, Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.units import inch as IN
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, PageBreak, KeepTogether,
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)


@dataclass
class PageTemplate:
    name: str          # "qa_standard" | "qa_compact" | "qa_two_column"
    layout: str        # "full_width" | "two_column" | "hero_image"
    font_body: str
    font_header: str
    pairs_per_page: int


_QA_TEMPLATES = [
    PageTemplate("qa_standard",   "full_width",  "Times-Roman",    "Helvetica-Bold", 5),
    PageTemplate("qa_compact",    "full_width",  "Times-Roman",    "Helvetica-Bold", 8),
    PageTemplate("qa_two_column", "two_column",  "Times-Roman",    "Helvetica-Bold", 6),
]


# ── Register Bitstream Vera (broader Unicode than Helvetica/Times) ────────────
# Vera ships with ReportLab and renders most dingbats + geometric symbols
# correctly across all PDF readers (incl. KDP's previewer).
_VERA_REGISTERED = False
def _ensure_vera_registered():
    global _VERA_REGISTERED
    if _VERA_REGISTERED:
        return
    try:
        import reportlab as _rl, os as _os
        font_dir = _os.path.join(_os.path.dirname(_rl.__file__), "fonts")
        for face_name, file_name in [
            ("Vera",    "Vera.ttf"),
            ("VeraBd",  "VeraBd.ttf"),
            ("VeraIt",  "VeraIt.ttf"),
            ("VeraBI",  "VeraBI.ttf"),
        ]:
            path = _os.path.join(font_dir, file_name)
            if _os.path.exists(path):
                pdfmetrics.registerFont(TTFont(face_name, path))
        _VERA_REGISTERED = True
    except Exception as e:
        logger.warning(f"Vera font registration failed: {e}")


# Track which theme font sets we've already registered (avoid duplicates)
_REGISTERED_THEMES = set()

def register_theme_fonts(theme_name: str) -> Dict[str, str]:
    """
    Registers the 4 fonts (display, body, body_bold, italic) for a theme
    with ReportLab, using safe internal names. Returns a dict of:
      {"display": "ThemeDisplay-<theme>", "body": "ThemeBody-<theme>", ...}
    so callers can use these names directly in ParagraphStyle.
    If a font file is missing, falls back to the built-in Helvetica/Times.
    """
    from modules.creation.niche_themes import get_theme_fonts
    import os

    recipe = get_theme_fonts(theme_name)
    safe_theme = theme_name.replace("_", "-")

    # Default fallbacks (built-in PDF fonts — always work)
    names = {
        "display":   "Helvetica-Bold",
        "body":      "Times-Roman",
        "body_bold": "Times-Bold",
        "italic":    "Times-Italic",
    }

    if theme_name in _REGISTERED_THEMES:
        # Already registered — return the cached names
        return {
            "display":   f"ThemeDisplay-{safe_theme}",
            "body":      f"ThemeBody-{safe_theme}",
            "body_bold": f"ThemeBodyBold-{safe_theme}",
            "italic":    f"ThemeItalic-{safe_theme}",
        }

    for role, file_path in recipe.items():
        if role == "label":
            continue
        if not os.path.exists(file_path):
            logger.warning(f"Font not found for {theme_name}/{role}: {file_path}")
            continue
        font_name = {
            "display":   f"ThemeDisplay-{safe_theme}",
            "body":      f"ThemeBody-{safe_theme}",
            "body_bold": f"ThemeBodyBold-{safe_theme}",
            "italic":    f"ThemeItalic-{safe_theme}",
        }[role]
        try:
            pdfmetrics.registerFont(TTFont(font_name, file_path))
            names[role] = font_name
        except Exception as e:
            logger.warning(f"Could not register {file_path} as {font_name}: {e}")

    _REGISTERED_THEMES.add(theme_name)
    return names

# ── KDP default 6×9 specs (overridden per-listing via trim_size_w/h) ─────────
# Gutter (inner margin) scales with page count per KDP spec :
#   ≤150 p : 0.375" min, we use 0.875"  (generous, pro look)
#   150-300 p : 0.75"  min, we use 1.000"
#   300-500 p : 0.875" min, we use 1.125"
#   501-828 p : 1.000" min, we use 1.250"
PAGE_W    = 6    * IN
PAGE_H    = 9    * IN
M_TOP     = 0.75 * IN
M_BOT     = 0.75 * IN
M_INNER   = 0.875 * IN
M_OUTER   = 0.625 * IN
CONTENT_W = PAGE_W - M_INNER - M_OUTER   # usable width ≈ 4.5"


def _gutter_for_page_count(page_count: int) -> float:
    """Return inner-margin (gutter) in inches respecting KDP rules WITH margin.

    KDP B&W minimums: 24-150p=0.375" · 151-300p=0.5" · 301-500p=0.625" ·
    501-700p=0.75" · 701-828p=0.875". We return well ABOVE each tier so a book
    never sits at the exact limit (which still trips KDP's checker).
    """
    if page_count <= 150:   return 0.875
    if page_count <= 300:   return 1.000
    if page_count <= 500:   return 1.125
    if page_count <= 700:   return 1.250
    return 1.375  # 701-828p — KDP min 0.875", we give 1.375"


def _estimate_final_pages(listing: Dict) -> int:
    """
    Best estimate of the FINAL interior page count BEFORE the PDF is built.
    Critical for puzzle books: the listing's page_count is the *target* (e.g.
    120) but the real book can be 200+ pages → gutter must be sized for the
    real count, not the target, or KDP rejects "insufficient gutter".
    """
    pc = int(listing.get("page_count") or 0)
    ptype = listing.get("product_type", "")
    if ptype in ("puzzle", "activity_book"):
        # Count puzzles actually populated for this build
        n = 0
        if listing.get("_puzzles"):
            n = len(listing["_puzzles"])
        elif listing.get("_puzzle_sets"):
            n = sum(len(p) for _, p in listing["_puzzle_sets"])
        elif listing.get("puzzle_count"):
            n = int(listing["puzzle_count"] or 0)
        if n > 0:
            # ~1 page/puzzle + solutions (~n/6 pages) + front/back matter (~12)
            est = n + (n // 6) + 12
            return max(pc, est)
    return pc


def _apply_listing_trim(listing: Dict) -> None:
    """Override module-level PAGE_W/H/CONTENT_W when listing has custom trim.
    Sets M_INNER (gutter) from the ESTIMATED FINAL page count (not just the
    target) so puzzle books that grow past their target stay KDP-compliant.
    Hard floor of 0.5" guarantees we never go below KDP's spec."""
    global PAGE_W, PAGE_H, CONTENT_W, M_INNER
    try:
        if listing.get("trim_size_w"):
            PAGE_W = float(listing["trim_size_w"]) * IN
        if listing.get("trim_size_h"):
            PAGE_H = float(listing["trim_size_h"]) * IN
        pc = _estimate_final_pages(listing)
        if pc > 0:
            M_INNER = _gutter_for_page_count(pc) * IN
        # Hard safety floor — never below KDP's largest minimum tier shorthand
        M_INNER = max(M_INNER, 0.5 * IN)
        CONTENT_W = PAGE_W - M_INNER - M_OUTER
    except Exception:
        pass


# ── Color palettes ─────────────────────────────────────────────────────────────

_PALETTES = {
    "journal":  {
        "accent":  colors.HexColor("#4A4063"),
        "accent2": colors.HexColor("#7C6FA0"),
        "light":   colors.HexColor("#F3F0F8"),
        "text":    colors.black,
        "symbol":  "✦",
    },
    "log": {
        "accent":  colors.HexColor("#2D5A27"),
        "accent2": colors.HexColor("#5A9E53"),
        "light":   colors.HexColor("#EDF5EC"),
        "text":    colors.black,
        "symbol":  "◈",
    },
    "quiz": {
        "accent":  colors.HexColor("#1A3A5C"),
        "accent2": colors.HexColor("#3A6A9C"),
        "light":   colors.HexColor("#EEF3F8"),
        "text":    colors.black,
        "symbol":  "★",
    },
    "planner": {
        "accent":  colors.HexColor("#8B3A3A"),
        "accent2": colors.HexColor("#C06060"),
        "light":   colors.HexColor("#FBF0F0"),
        "text":    colors.black,
        "symbol":  "◆",
    },
    "coloring": {
        "accent":  colors.HexColor("#5B4A8A"),
        "accent2": colors.HexColor("#8B7AC0"),
        "light":   colors.HexColor("#F4F0FA"),
        "text":    colors.black,
        "symbol":  "❈",
    },
}

def _pal(product_type: str) -> Dict:
    return _PALETTES.get(product_type, _PALETTES["journal"])


# ── Niche-specific page header/tracker fields ─────────────────────────────────
# Each theme maps to 3 (label, placeholder) pairs shown at the top of content pages.
# The label tells the reader what to fill in — tailored to the niche.
_NICHE_TRACKER_FIELDS = {
    "music":       [("Date", "_____________"), ("Key / Scale", "________"), ("BPM", "______")],
    "nature":      [("Date", "_____________"), ("Location", "__________"), ("Temp", "____°")],
    "aquarium":    [("Date", "_____________"), ("Tank", "__________"), ("pH / Temp°F", "______")],
    "education":   [("Date", "_____________"), ("Subject", "__________"), ("Goal", "____________")],
    "fitness":     [("Date", "_____________"), ("Activity", "__________"), ("Duration", "___min")],
    "travel":      [("Date", "_____________"), ("Destination", "__________"), ("Mood", "○○○○○")],
    "cooking":     [("Date", "_____________"), ("Recipe", "__________"), ("Rating", "☆ ☆ ☆ ☆ ☆")],
    "spiritual":   [("Date", "_____________"), ("Intention", "__________"), ("Energy", "○○○○○")],
    "gaming":      [("Date", "_____________"), ("Game", "__________"), ("Score / Level", "______")],
    "finance":     [("Date", "_____________"), ("Category", "__________"), ("Amount $", "______")],
    "wellness":    [("Date", "_____________"), ("Sleep hrs", "______"), ("Water oz", "______")],
    "art":         [("Date", "_____________"), ("Medium", "__________"), ("Theme", "____________")],
    "writing":     [("Date", "_____________"), ("Word count", "______"), ("Chapter", "_____")],
    "gardening":   [("Date", "_____________"), ("Plant", "__________"), ("Temp", "____°")],
    "parenting":   [("Date", "_____________"), ("Child", "__________"), ("Mood", "○○○○○")],
    "business":    [("Date", "_____________"), ("Focus", "__________"), ("Revenue $", "______")],
    "pet":         [("Date", "_____________"), ("Pet", "__________"), ("Weight", "______")],
    "photography": [("Date", "_____________"), ("Location", "__________"), ("Lens", "____mm")],
    "quiz":        [("Round", "______"), ("Score", "___/10"), ("Time", "____min")],
    "default":     [("Date", "_____________"), ("Mood", "○○○○○"), ("Energy", "○○○○○")],
}


def _niche_tracker_row(theme_name: str, pal: Dict) -> Table:
    """Niche-branded tracker header row at the top of each content page."""
    fields = _NICHE_TRACKER_FIELDS.get(theme_name, _NICHE_TRACKER_FIELDS["default"])
    n = len(fields)
    col_w = CONTENT_W / n
    label_style = ParagraphStyle(
        "TrkLbl", fontName="Helvetica-Bold", fontSize=7,
        textColor=pal["accent"], alignment=TA_LEFT, leading=10,
    )
    ph_style = ParagraphStyle(
        "TrkPh", fontName="Helvetica", fontSize=7,
        textColor=colors.HexColor("#AAAAAA"), alignment=TA_LEFT, leading=10,
    )
    cells = [
        [Paragraph(label, label_style), Paragraph(ph, ph_style)]
        for label, ph in fields
    ]
    # Flatten: each column is a sub-table (label over placeholder)
    col_tables = []
    for label, ph in fields:
        inner = Table(
            [[Paragraph(label, label_style)], [Paragraph(ph, ph_style)]],
            colWidths=[col_w - 4],
        )
        inner.setStyle(TableStyle([
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ]))
        col_tables.append(inner)
    row_t = Table([col_tables], colWidths=[col_w] * n)
    row_t.setStyle(TableStyle([
        ("LINEBELOW",     (0, 0), (-1, -1), 0.6, pal["accent"]),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return row_t


# ── Style factory ─────────────────────────────────────────────────────────────

def _styles(pal: Dict, fonts: Optional[Dict] = None,
            theme_fonts: Optional[Dict[str, str]] = None) -> Dict:
    """
    Builds the paragraph style dict.
    Priority order for fonts:
      1. theme_fonts (from register_theme_fonts) — niche-specific typography
      2. fonts (from style variant) — batch-level styling
      3. defaults (Times/Helvetica)
    """
    acc = pal["accent"]
    f   = fonts or {}
    tf  = theme_fonts or {}

    # Theme typography wins, then variant fonts, then defaults
    body_font    = tf.get("body")      or f.get("body",    "Times-Roman")
    head_font    = tf.get("display")   or f.get("heading", "Helvetica-Bold")
    bold_font    = tf.get("body_bold") or tf.get("display") or f.get("heading", "Helvetica-Bold")
    italic_font  = tf.get("italic")    or f.get("italic",  "Times-Italic")

    return {
        "title": ParagraphStyle("Title2",
            fontName=head_font, fontSize=22, textColor=acc,
            alignment=TA_CENTER, spaceAfter=6, leading=28),
        "h1": ParagraphStyle("H1b",
            fontName=head_font, fontSize=18, textColor=acc,
            alignment=TA_CENTER, spaceAfter=6, leading=24),
        "h2": ParagraphStyle("H2b",
            fontName=head_font, fontSize=14, textColor=acc,
            alignment=TA_CENTER, spaceAfter=4, leading=18),
        "h3": ParagraphStyle("H3b",
            fontName=head_font, fontSize=11, textColor=acc,
            alignment=TA_LEFT, spaceAfter=4, leading=15),
        "body": ParagraphStyle("Bodyb",
            fontName=body_font, fontSize=10.5,
            textColor=colors.HexColor("#222222"), alignment=TA_JUSTIFY,
            spaceAfter=6, leading=15),
        "center": ParagraphStyle("Centerb",
            fontName=body_font, fontSize=10.5,
            textColor=colors.HexColor("#222222"), alignment=TA_CENTER,
            spaceAfter=4, leading=15),
        "italic": ParagraphStyle("Italicb",
            fontName=italic_font, fontSize=10,
            textColor=colors.HexColor("#555555"), alignment=TA_CENTER,
            spaceAfter=4, leading=14),
        "prompt": ParagraphStyle("Promptb",
            fontName=italic_font, fontSize=10, textColor=acc,
            alignment=TA_LEFT, spaceAfter=2, leading=14),
        "small": ParagraphStyle("Smallb",
            fontName="Helvetica", fontSize=7.5,
            textColor=colors.HexColor("#999999"), alignment=TA_CENTER, leading=10),
        "toc_title": ParagraphStyle("TocTitleb",
            fontName=head_font, fontSize=11, textColor=acc,
            alignment=TA_LEFT, leading=14),
        "toc_desc": ParagraphStyle("TocDescb",
            fontName=italic_font, fontSize=9,
            textColor=colors.HexColor("#666666"), alignment=TA_LEFT,
            spaceBefore=1, leading=12),
        "qa_q": ParagraphStyle("QAQb",
            fontName=head_font, fontSize=10.5, textColor=acc,
            alignment=TA_LEFT, spaceAfter=2, leading=14),
        "qa_a": ParagraphStyle("QAAb",
            fontName=body_font, fontSize=10.5,
            textColor=colors.HexColor("#333333"), alignment=TA_LEFT,
            spaceAfter=8, leading=14, leftIndent=14),
        "section_banner": ParagraphStyle("SectionBanner",
            fontName=head_font, fontSize=28, textColor=colors.white,
            alignment=TA_CENTER, spaceAfter=0, leading=34),
        "section_sub": ParagraphStyle("SectionSub",
            fontName=italic_font, fontSize=13, textColor=colors.HexColor("#DDDDDD"),
            alignment=TA_CENTER, spaceAfter=0, leading=18),
    }


# ── Decorative flowables ───────────────────────────────────────────────────────

class _DecorativeSymbolRow(Flowable):
    """A row with 3 small vector diamonds connected by dotted lines.
    Used in place of unicode-based '✦ · · · ✦' rows that fail when the
    active body font doesn't include dingbat code points."""
    def __init__(self, width: float, color, theme_name: str = "default"):
        super().__init__()
        self.width = width
        self.color = color
        self.theme_name = theme_name
        self.height = 18

    def draw(self):
        c = self.canv
        c.saveState()
        cy = self.height / 2
        w = self.width
        from modules.creation.niche_themes import draw_theme_shape
        # Draw 3 small theme shapes evenly spaced
        for i, frac in enumerate([0.32, 0.50, 0.68]):
            draw_theme_shape(
                canvas=c, cx=w * frac, cy=cy, size=4.5,
                theme_name=self.theme_name, fill_color=self.color,
            )
        # Dotted connector lines between them
        c.setStrokeColor(self.color)
        c.setLineWidth(0.6)
        c.setDash(1.4, 2.6)
        c.line(w * 0.36, cy, w * 0.46, cy)
        c.line(w * 0.54, cy, w * 0.64, cy)
        c.setDash()   # reset
        c.restoreState()

    def wrap(self, *args):
        return self.width, self.height


class _OrnamentalDivider(Flowable):
    """Line — symbol — line decorative divider."""
    def __init__(self, width: float, color, symbol: str = "✦", thickness: float = 0.8):
        super().__init__()
        self.width    = width
        self.color    = color
        self.symbol   = symbol
        self.thickness = thickness
        self.height   = 20

    def draw(self):
        c = self.canv
        c.saveState()
        y = self.height * 0.5
        sym_gap = 14

        c.setStrokeColor(self.color)
        c.setFillColor(self.color)
        c.setLineWidth(self.thickness)
        c.line(0, y, self.width / 2 - sym_gap, y)
        c.line(self.width / 2 + sym_gap, y, self.width, y)

        c.setFont("Helvetica", 11)
        c.drawCentredString(self.width / 2, y - 4.5, self.symbol)
        c.restoreState()

    def wrap(self, *args):
        return self.width, self.height


class _CornerFrame(Flowable):
    """Decorative corner-bracket frame drawn around a content block."""
    def __init__(self, width: float, height: float, color, thickness: float = 1.5):
        super().__init__()
        self.width    = width
        self.height   = height
        self.color    = color
        self.thickness = thickness

    def draw(self):
        c = self.canv
        c.saveState()
        c.setStrokeColor(self.color)
        c.setLineWidth(self.thickness)
        cs = 0.22 * IN   # corner size
        w, h = self.width, self.height

        for (x1, y1, x2, y2) in [
            (0, h, cs, h), (0, h, 0, h - cs),          # top-left
            (w - cs, h, w, h), (w, h, w, h - cs),       # top-right
            (0, 0, cs, 0), (0, 0, 0, cs),               # bottom-left
            (w - cs, 0, w, 0), (w, 0, w, cs),           # bottom-right
        ]:
            c.line(x1, y1, x2, y2)
        c.restoreState()

    def wrap(self, *args):
        return self.width, self.height


class _SectionBannerPage(Flowable):
    """Full-page colored banner for section breaks with a drawn vector shape
    OR an AI-generated niche icon (if image_path is supplied)."""
    def __init__(self, title: str, description: str, color, light_color,
                 symbol: str = "✦", theme_name: str = "default",
                 image_path: Optional[str] = None):
        super().__init__()
        self.title       = title
        self.description = description
        self.color       = color
        self.light_color = light_color
        self.symbol      = symbol           # kept as fallback
        self.theme_name  = theme_name
        self.image_path  = image_path       # optional AI-generated icon
        # ReportLab frames have 6 pt padding each side — stay within bounds
        self.width  = CONTENT_W - 14
        self.height = PAGE_H - M_TOP - M_BOT - 14

    def draw(self):
        c = self.canv
        c.saveState()
        w, h = self.width, self.height

        # Colored background block
        c.setFillColor(self.color)
        c.roundRect(0, 0, w, h, 8, fill=1, stroke=0)

        # Subtle inner border
        c.setStrokeColor(colors.HexColor("#FFFFFF"))
        c.setLineWidth(0.5)
        m = 0.18 * IN
        c.roundRect(m, m, w - 2 * m, h - 2 * m, 5, fill=0, stroke=1)

        # ── Big visual: AI illustration (RGBA) OR vector shape ──────────
        # Position in UPPER THIRD so it can NEVER overlap the title.
        cx = w / 2
        cy = h * 0.70                # 70% up from bottom
        # Illustration is drawn in WHITE (recolored from black-RGBA) for
        # crisp visibility on the dark/colored banner background.
        if self.image_path and __import__("os").path.exists(self.image_path):
            try:
                from reportlab.lib.utils import ImageReader
                # Use PIL to recolor the black RGBA → white RGBA on the fly
                # so the illustration is visible on any banner color.
                from PIL import Image as _PILImage, ImageMath as _ImageMath
                pil = _PILImage.open(self.image_path).convert("RGBA")
                if pil.mode == "RGBA":
                    r, g, b, alpha = pil.split()
                    # Pure white channels, keep original alpha
                    white = _PILImage.new("L", pil.size, 255)
                    pil = _PILImage.merge("RGBA", (white, white, white, alpha))
                import io as _io
                buf = _io.BytesIO()
                pil.save(buf, format="PNG")
                buf.seek(0)
                img = ImageReader(buf)

                # Compute draw box (square, max 1.4 inch)
                box = 100   # half-size in points → 1.4-inch square total
                c.drawImage(
                    img,
                    cx - box, cy - box,
                    width=box * 2, height=box * 2,
                    mask="auto",
                    preserveAspectRatio=True,
                )
            except Exception as e:
                logger.debug(f"Banner illustration draw failed: {e}")
                from modules.creation.niche_themes import draw_theme_shape
                draw_theme_shape(canvas=c, cx=cx, cy=cy, size=38,
                                 theme_name=self.theme_name,
                                 fill_color=colors.HexColor("#FFFFFF"))
        else:
            from modules.creation.niche_themes import draw_theme_shape
            draw_theme_shape(canvas=c, cx=cx, cy=cy, size=38,
                             theme_name=self.theme_name,
                             fill_color=colors.HexColor("#FFFFFF"))

        # ── Title — auto-fit (shrink + wrap to 2 lines if needed) ───────
        max_title_w = w * 0.82        # 82% of banner width (safe margin)
        max_font    = 24
        min_font    = 12
        title      = self.title or ""

        # Step 1: try to fit on ONE line by shrinking the font
        font_size = max_font
        while font_size >= min_font:
            if c.stringWidth(title, "Helvetica-Bold", font_size) <= max_title_w:
                break
            font_size -= 1

        c.setFillColor(colors.HexColor("#FFFFFF"))

        if c.stringWidth(title, "Helvetica-Bold", font_size) <= max_title_w:
            # Fits on one line
            c.setFont("Helvetica-Bold", font_size)
            c.drawCentredString(w / 2, h * 0.40, title)
            divider_y = h * 0.34
        else:
            # Step 2: still too wide → wrap to 2 lines at best word boundary
            words = title.split()
            best_split = 1
            best_diff  = float("inf")
            for i in range(1, len(words)):
                l1 = " ".join(words[:i])
                l2 = " ".join(words[i:])
                diff = abs(c.stringWidth(l1, "Helvetica-Bold", font_size)
                           - c.stringWidth(l2, "Helvetica-Bold", font_size))
                if diff < best_diff:
                    best_diff = diff
                    best_split = i
            line1 = " ".join(words[:best_split])
            line2 = " ".join(words[best_split:])

            # Shrink further if either line is still too wide
            for _ in range(8):
                w1 = c.stringWidth(line1, "Helvetica-Bold", font_size)
                w2 = c.stringWidth(line2, "Helvetica-Bold", font_size)
                if max(w1, w2) <= max_title_w or font_size <= min_font:
                    break
                font_size -= 1

            c.setFont("Helvetica-Bold", font_size)
            line_h = font_size * 1.2
            c.drawCentredString(w / 2, h * 0.40 + line_h / 2, line1)
            c.drawCentredString(w / 2, h * 0.40 - line_h / 2, line2)
            divider_y = h * 0.40 - line_h - 6

        # Divider line (position adapts to title height)
        c.setStrokeColor(colors.HexColor("#FFFFFF"))
        c.setLineWidth(0.8)
        c.line(w * 0.2, divider_y, w * 0.8, divider_y)

        # Description
        c.setFont("Times-Italic", 12)
        c.setFillColor(colors.HexColor("#DDDDDD"))
        # Word-wrap description (within 76% of banner width)
        words = (self.description or "").split()
        lines, line = [], []
        for word in words:
            test = " ".join(line + [word])
            if c.stringWidth(test, "Times-Italic", 12) < w * 0.76:
                line.append(word)
            else:
                if line: lines.append(" ".join(line))
                line = [word]
        if line: lines.append(" ".join(line))
        # Position description just below the divider (which can move)
        y = divider_y - 18
        for ln in lines[:3]:
            c.drawCentredString(w / 2, y, ln)
            y -= 16

        c.restoreState()

    def wrap(self, *args):
        return self.width, self.height


class _SketchBox(Flowable):
    """An empty bordered box with 'Sketch / Photo' label — for log books."""
    def __init__(self, width: float, height: float, color, label: str = "Sketch / Photo"):
        super().__init__()
        self.width  = width
        self.height = height
        self.color  = color
        self.label  = label

    def draw(self):
        c = self.canv
        c.saveState()
        c.setStrokeColor(self.color)
        c.setFillColor(colors.HexColor("#FAFAFA"))
        c.setLineWidth(0.7)
        c.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)

        # Diagonal cross-lines (placeholder graphic)
        c.setStrokeColor(colors.HexColor("#DDDDDD"))
        c.setLineWidth(0.4)
        c.line(0, 0, self.width, self.height)
        c.line(0, self.height, self.width, 0)

        # Label
        c.setFillColor(self.color)
        c.setFont("Helvetica", 8)
        label_w = c.stringWidth(self.label, "Helvetica", 8)
        lx = (self.width - label_w) / 2
        ly = (self.height - 8) / 2
        # White pill behind label
        pad = 4
        c.setFillColor(colors.white)
        c.roundRect(lx - pad, ly - 2, label_w + pad * 2, 14, 3, fill=1, stroke=0)
        c.setFillColor(self.color)
        c.drawString(lx, ly, self.label)
        c.restoreState()

    def wrap(self, *args):
        return self.width, self.height


class _HeroPageFlowable(Flowable):
    """Full-page hero: illustration in upper 55%, solid theme-color band lower 45% + caption."""
    def __init__(self, pal: Dict, caption: str = "", image_path: Optional[str] = None,
                 theme_name: str = "default"):
        super().__init__()
        self.pal        = pal
        self.caption    = caption
        self.image_path = image_path
        self.theme_name = theme_name
        self.width  = CONTENT_W - 14
        self.height = PAGE_H - M_TOP - M_BOT - 14

    def draw(self):
        c = self.canv
        c.saveState()
        w, h = self.width, self.height
        split_y = h * 0.45     # lower 45% = solid band

        # Upper zone background
        c.setFillColor(colors.HexColor("#F0F0F0"))
        c.rect(0, split_y, w, h - split_y, fill=1, stroke=0)

        # Try to draw illustration
        drawn = False
        if self.image_path and __import__("os").path.exists(self.image_path):
            try:
                from reportlab.lib.utils import ImageReader
                img_area_h = h - split_y - 24
                img_area_w = min(w - 24, img_area_h)
                img = ImageReader(self.image_path)
                c.drawImage(
                    img,
                    (w - img_area_w) / 2, split_y + 12,
                    width=img_area_w, height=img_area_h,
                    mask="auto", preserveAspectRatio=True,
                )
                drawn = True
            except Exception:
                pass

        if not drawn:
            # Decorative vector shapes as fallback
            from modules.creation.niche_themes import draw_theme_shape
            mid_y = split_y + (h - split_y) / 2
            for frac, sz in [(0.25, 24), (0.5, 36), (0.75, 24)]:
                draw_theme_shape(c, cx=w * frac, cy=mid_y, size=sz,
                                 theme_name=self.theme_name,
                                 fill_color=self.pal["accent2"])

        # Solid color band at bottom
        c.setFillColor(self.pal["accent"])
        c.rect(0, 0, w, split_y, fill=1, stroke=0)

        # Thin white top border on band
        c.setStrokeColor(colors.white)
        c.setLineWidth(1)
        c.line(w * 0.1, split_y, w * 0.9, split_y)

        # Caption text (up to 2 lines)
        caption = (self.caption or "")[:140]
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        words = caption.split()
        line, lines = [], []
        for word in words:
            test = " ".join(line + [word])
            if c.stringWidth(test, "Helvetica-Bold", 11) < w * 0.82:
                line.append(word)
            else:
                if line:
                    lines.append(" ".join(line))
                line = [word]
        if line:
            lines.append(" ".join(line))

        y = split_y * 0.62
        for ln in lines[:2]:
            c.drawCentredString(w / 2, y, ln)
            y -= 17

        # Small "Hero Fact" label above caption
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#FFFFFF88"))
        c.drawCentredString(w / 2, split_y * 0.78, "★  HERO FACT  ★")

        c.restoreState()

    def wrap(self, *args):
        return self.width, self.height


class _NichePageAccent(Flowable):
    """Thin themed accent line + small vector shape — stamps niche identity on every content page."""
    def __init__(self, pal: Dict, theme_name: str = "default", page_idx: int = 0):
        super().__init__()
        self.pal        = pal
        self.theme_name = theme_name
        self.page_idx   = page_idx
        self.width      = CONTENT_W
        self.height     = 10

    def draw(self):
        c = self.canv
        c.saveState()
        acc = self.pal["accent"]
        # Solid line across 87% of width, fading effect via lighter end cap
        c.setStrokeColor(acc)
        c.setLineWidth(1.2)
        c.line(0, self.height * 0.5, self.width * 0.87, self.height * 0.5)
        # Small theme shape as end ornament
        from modules.creation.niche_themes import draw_theme_shape
        draw_theme_shape(
            c, cx=self.width * 0.93, cy=self.height * 0.5,
            size=4.5, theme_name=self.theme_name, fill_color=acc,
        )
        c.restoreState()

    def wrap(self, *args):
        return self.width, self.height


# ── Helper builders ────────────────────────────────────────────────────────────

def _divider(pal: Dict, symbol: str = None) -> _OrnamentalDivider:
    return _OrnamentalDivider(CONTENT_W, pal["accent"],
                              symbol or pal.get("symbol", "✦"))

def _writing_lines(n: int = 14, shade_alt: bool = False,
                   line_style: str = "solid") -> List:
    """
    Blank writing lines. shade_alt=True gives every other row a very light tint.
    line_style ∈ {"solid", "dotted", "lined"} — driven by the niche preset.
      - solid : classic line under each row
      - dotted: very subtle dotted underline (wellness / mindful niches)
      - lined : double tone (lined-notebook feel for productivity niches)
    """
    rows = [[""] for _ in range(n)]
    t = Table(rows, colWidths=[CONTENT_W])
    line_color = colors.HexColor("#C0C0C0")
    thickness  = 0.4
    if line_style == "dotted":
        thickness = 0.5
        line_color = colors.HexColor("#D8D2E0")
        line_cmd = ("LINEBELOW", (0, 0), (-1, -1), thickness, line_color, None, (1, 2))
    elif line_style == "lined":
        thickness = 0.6
        line_color = colors.HexColor("#A8C8E0")
        line_cmd = ("LINEBELOW", (0, 0), (-1, -1), thickness, line_color)
    else:
        line_cmd = ("LINEBELOW", (0, 0), (-1, -1), thickness, line_color)

    style_cmds = [
        line_cmd,
        ("TOPPADDING",  (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]
    if shade_alt:
        style_cmds += [
            ("ROWBACKGROUNDS", (0, 0), (-1, -1),
             [colors.white, colors.HexColor("#F8F8F8")]),
        ]
    t.setStyle(TableStyle(style_cmds))
    return [t]


def _resolve_preset(listing: Dict) -> Dict:
    """Returns the preset dict from listing, or DEFAULT_PRESET if absent/broken."""
    try:
        from modules.creation.template_presets import DEFAULT_PRESET
        p = listing.get("_preset") if isinstance(listing, dict) else None
        if isinstance(p, dict) and p.get("name"):
            return {**DEFAULT_PRESET, **p}
        return dict(DEFAULT_PRESET)
    except Exception:
        return {
            "name": "default", "ornament_density": "medium",
            "corner_motif": True, "section_banner": "framed",
            "line_style": "solid", "mood_tracker": True,
            "quote_pages_pct": 0.05,
        }

def _prompt_box(text: str, pal: Dict, styles: Dict) -> Table:
    """Shaded box with left accent bar for writing prompts."""
    inner = Paragraph(f"<b>{pal.get('symbol','✦')}</b>  <i>{text}</i>", styles["prompt"])
    t = Table([[inner]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), pal["light"]),
        ("LINEBEFORE",    (0, 0), (0, -1),  3, pal["accent"]),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t

def _mood_tracker(styles: Dict, pal: Dict, extras: Optional[List[str]] = None) -> Table:
    """
    Date + mood row with PDF-safe Unicode symbols (no color emojis).
    If `extras` is provided (e.g. ["energy","intention"] from directives),
    those features get added to enrich the page vs. competitors.
    """
    mood_str    = "○  ○  ○  ○  ○"
    extras = extras or []

    # Build the cells dynamically based on extras
    cells = [
        Paragraph("Date: ___________________", styles["small"]),
        Paragraph(f"Mood:  {mood_str}", styles["small"]),
    ]
    extra_cells = []
    if "weather" in extras:
        extra_cells.append(Paragraph("Weather:  ☐ Sun ☐ Cloud ☐ Rain", styles["small"]))
    if "energy" in extras:
        extra_cells.append(Paragraph("Energy:  ○ ○ ○ ○ ○", styles["small"]))
    if "intention" in extras:
        extra_cells.append(Paragraph("Intention: _____________________", styles["small"]))
    if not extra_cells:
        # Always include weather as a useful default
        extra_cells.append(Paragraph("Weather:  ☐ Sun  ☐ Cloud  ☐ Rain  ☐ Snow", styles["small"]))

    cells.extend(extra_cells[:1])  # Keep header line compact: 1 extra
    data = [cells]
    t = Table(data, colWidths=[CONTENT_W * 0.38, CONTENT_W * 0.38, CONTENT_W * 0.24])
    t.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR",     (0, 0), (-1, -1), colors.HexColor("#888888")),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.5, pal["accent"]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return t

def _stars_rating(label: str = "Overall Rating") -> Paragraph:
    return Paragraph(
        f"<font size='7' color='#888888'>{label}:</font>  "
        "<font size='11' color='#CCAA00'>☆  ☆  ☆  ☆  ☆</font>",
        ParagraphStyle("Stars", fontName="Helvetica", fontSize=9,
                       textColor=colors.HexColor("#888888"),
                       alignment=TA_LEFT, leading=12)
    )


# ── Page header / footer via canvas callback ───────────────────────────────────

def _make_page_callbacks(listing: Dict, pal: Dict):
    """Returns (onFirstPage, onLaterPages) for headers + footers."""
    short_title = listing["title"][:45]
    acc = pal["accent"]

    def _draw(canvas, doc):
        canvas.saveState()
        page = doc.page

        # ── Header (skip page 1 — welcome page) ──────────────────────────
        if page > 1:
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor("#AAAAAA"))
            if page % 2 == 0:
                # Even page: title on left
                canvas.drawString(M_INNER, PAGE_H - M_TOP * 0.55, short_title)
            else:
                # Odd page: publisher on right
                pub = listing.get("publisher_name", "")[:35]
                canvas.drawRightString(PAGE_W - M_OUTER, PAGE_H - M_TOP * 0.55, pub)
            # Header rule
            canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
            canvas.setLineWidth(0.4)
            canvas.line(M_INNER, PAGE_H - M_TOP * 0.65,
                        PAGE_W - M_OUTER, PAGE_H - M_TOP * 0.65)

        # ── Footer: page number ───────────────────────────────────────────
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawCentredString(PAGE_W / 2, M_BOT * 0.42, str(page))
        # Footer rule
        canvas.setStrokeColor(acc)
        canvas.setLineWidth(0.3)
        canvas.line(M_INNER, M_BOT * 0.62, PAGE_W - M_OUTER, M_BOT * 0.62)

        canvas.restoreState()

    return _draw, _draw


# ── Page builders ──────────────────────────────────────────────────────────────

from reportlab.platypus import SimpleDocTemplate as _RLSimpleDoc
from reportlab.platypus.tableofcontents import TableOfContents as _RLTableOfContents


class _TocDocTemplate(_RLSimpleDoc):
    """SimpleDocTemplate that feeds a real, page-numbered Table of Contents.
    afterFlowable notifies a TOCEntry for each chapter opener (level 0) and each
    section heading (level 1) — reportlab's multiBuild then fills real page #s."""

    def afterFlowable(self, flowable):
        try:
            from modules.creation.highcontent.render import _ChapterOpener
        except Exception:
            _ChapterOpener = ()
        op = None
        heading_para = None
        if isinstance(flowable, _ChapterOpener):
            op = flowable
        else:
            inner = getattr(flowable, "_content", None)
            if inner:
                if _ChapterOpener and isinstance(inner[0], _ChapterOpener):
                    op = inner[0]
                elif isinstance(inner[0], Paragraph) and \
                        getattr(inner[0].style, "name", "").startswith("HCH2"):
                    heading_para = inner[0]
        if op is None and isinstance(flowable, Paragraph) and \
                getattr(flowable.style, "name", "").startswith("HCH2"):
            heading_para = flowable

        if op is not None:
            label = str(getattr(op, "title", "")).strip()
            if label:
                self.notify("TOCEntry", (0, label, self.page))
        elif heading_para is not None:
            txt = heading_para.getPlainText().strip()
            if txt:
                self.notify("TOCEntry", (1, txt, self.page))


def _build_toc(listing: Dict, styles: Dict, pal: Dict, theme_name: str) -> List:
    """A detailed, niche-styled Table of Contents (real page numbers via multiBuild)."""
    accent = pal["accent"]
    disp = styles["h1"].fontName
    toc = _RLTableOfContents()
    toc.levelStyles = [
        ParagraphStyle("TOCL0", fontName=disp, fontSize=11.5, textColor=accent,
                       leading=18, spaceBefore=8, spaceAfter=2),
        ParagraphStyle("TOCL1", fontName="Helvetica", fontSize=9.5,
                       textColor=colors.HexColor("#444444"), leftIndent=0.32 * IN,
                       leading=14, spaceBefore=0, spaceAfter=0),
    ]
    elems: List = [Spacer(1, 0.35 * IN),
                   Paragraph("Table of Contents", styles["h1"]),
                   _divider(pal), Spacer(1, 0.15 * IN), toc, PageBreak()]
    return elems


def _title_copyright_page(listing: Dict, styles: Dict, pal: Dict,
                          theme_name: str = "default") -> List:
    """Professional TITLE PAGE: big title + subtitle + author, then a copyright
    disclaimer and limitation-of-liability block near the bottom (niche-styled)."""
    import datetime as _dt
    elems: List = []
    accent = pal["accent"]
    author = (listing.get("author") or listing.get("publisher_name")
              or "Independent Publisher").strip()
    year = str(_dt.date.today().year)

    elems.append(Spacer(1, 1.15 * IN))
    elems.append(_DecorativeSymbolRow(CONTENT_W * 0.5, accent, theme_name))
    elems.append(Spacer(1, 0.18 * IN))
    elems.append(Paragraph(listing.get("title", ""), styles["title"]))
    elems.append(Spacer(1, 0.10 * IN))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.10 * IN))
    if listing.get("subtitle"):
        sub_st = ParagraphStyle("TPSub", parent=styles["h2"], alignment=TA_CENTER)
        elems.append(Paragraph(listing["subtitle"], sub_st))

    # push the legal block toward the lower third
    elems.append(Spacer(1, 2.4 * IN))
    auth_st = ParagraphStyle("TPAuth", fontName="Helvetica", fontSize=12,
                             textColor=colors.HexColor("#333333"), alignment=TA_CENTER, leading=16)
    elems.append(Paragraph(author, auth_st))
    elems.append(Spacer(1, 0.5 * IN))

    head_st = ParagraphStyle("TPLegalH", fontName="Helvetica-Bold", fontSize=8.5,
                             textColor=colors.HexColor("#444444"), leading=12, spaceAfter=2)
    body_st = ParagraphStyle("TPLegal", fontName="Helvetica", fontSize=8,
                             textColor=colors.HexColor("#555555"), leading=11, alignment=TA_JUSTIFY,
                             spaceAfter=6)
    elems.append(Paragraph("Copyright Disclaimer", head_st))
    elems.append(Paragraph(
        f"© {year} {author}. All rights reserved. No part of this publication may be "
        f"reproduced, distributed, or transmitted in any form or by any means — including "
        f"photocopying, recording, or other electronic or mechanical methods — without the "
        f"prior written permission of the publisher, except in the case of brief quotations "
        f"embodied in reviews and certain other noncommercial uses permitted by copyright law.",
        body_st))
    elems.append(HRFlowable(width="100%", thickness=0.5,
                            color=colors.HexColor("#DDDDDD"), spaceBefore=2, spaceAfter=5))
    elems.append(Paragraph("Limitation of Liability", head_st))
    elems.append(Paragraph(
        "The information in this publication is provided for educational and informational "
        "purposes only. The author and publisher make no representations or warranties with "
        "respect to the accuracy or completeness of the contents and specifically disclaim any "
        "implied warranties of merchantability or fitness for a particular purpose. The reader "
        "is responsible for their own safety and use of any tools, materials, and techniques "
        "described herein. The author and publisher shall not be liable for any damages or "
        "injuries arising from the use of this book or the information contained within.",
        body_st))
    elems.append(PageBreak())
    return elems


def _welcome_page(listing: Dict, styles: Dict, pal: Dict,
                  directives: Optional[Dict] = None,
                  hero_image_path: Optional[str] = None,
                  theme_name: str = "default") -> List:
    elems = []
    elems.append(Spacer(1, 0.4 * IN))

    # ── Hero image (AI-generated, niche-themed, B&W) ────────────────────
    if hero_image_path and __import__("os").path.exists(hero_image_path):
        try:
            from reportlab.platypus import Image as RLImage
            hero_w = CONTENT_W * 0.55       # ~55% of page width
            hero_h = hero_w                  # square
            elems.append(RLImage(hero_image_path, width=hero_w, height=hero_h,
                                 hAlign="CENTER"))
            elems.append(Spacer(1, 0.18 * IN))
        except Exception as e:
            logger.debug(f"Hero image draw failed: {e}")

    # Decorative symbol row — drawn vector shapes (font-independent)
    elems.append(_DecorativeSymbolRow(CONTENT_W * 0.6, pal["accent"], theme_name))
    elems.append(Spacer(1, 0.12 * IN))

    # Title
    elems.append(Paragraph(listing["title"], styles["title"]))
    elems.append(Spacer(1, 0.08 * IN))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.08 * IN))

    # Subtitle
    if listing.get("subtitle"):
        elems.append(Paragraph(listing["subtitle"], styles["h2"]))
        elems.append(Spacer(1, 0.25 * IN))

    # Welcome text
    welcome_text = ""
    for sec in listing.get("content_sections", []):
        if sec.get("type") == "welcome":
            welcome_text = sec.get("description", "")
            break
    if not welcome_text:
        niche = listing.get("niche", "your journey")
        welcome_text = (
            f"Welcome to your <i>{listing['title']}</i>. "
            "This book was crafted with care to give you a dedicated space "
            "to observe, record, and reflect. Every page is an open invitation — "
            "show up, dive in, and make it entirely your own."
        )
    elems.append(Paragraph(welcome_text, styles["body"]))
    elems.append(Spacer(1, 0.2 * IN))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.2 * IN))
    elems.append(Paragraph(f"Published by <b>{listing.get('publisher_name','')}</b>", styles["small"]))
    elems.append(PageBreak())

    # ── How to use this book (page 2) ─────────────────────────────────────
    elems.append(Spacer(1, 0.4 * IN))
    elems.append(Paragraph("How to Use This Book", styles["h1"]))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.15 * IN))

    pt = listing.get("product_type", "journal")
    how_to_rows = {
        "journal": [
            ("1. Start Anywhere", "There are no rules. Open to any page and begin writing."),
            ("2. Use the Prompt", "Each page opens with a curated writing prompt — use it as a spark or ignore it."),
            ("3. Track Your Mood", "The mood tracker at the top takes less than 5 seconds but tells a big story over time."),
            ("4. Be Honest", "This journal is for your eyes only. Write without censorship."),
            ("5. Review & Reflect", "Every 30 days, flip back through your entries. Notice patterns."),
        ],
        "log": [
            ("1. One Entry Per Page", "Record each observation, specimen, or event on its own page."),
            ("2. Fill Every Field", "The more detail you capture now, the more valuable your records become."),
            ("3. Use the Sketch Box", "Quick drawings, diagrams, or attached photos make records come alive."),
            ("4. Rate Each Entry", "The star rating helps you identify your best finds at a glance."),
            ("5. Date Everything", "Always record the date, time, and location — context is everything."),
        ],
        "quiz": [
            ("1. Choose Your Mode", "Play solo or challenge friends — the rounds work for both."),
            ("2. Don't Peek", "Answer all questions in a Round before checking the Answers page."),
            ("3. Score Yourself", "Write your score in the box at the top of each Round page."),
            ("4. Learn from Mistakes", "The Answer pages include the correct answers — use them to learn."),
            ("5. Track Your Progress", "Each round page has a score box — track improvement over time."),
        ],
    }
    rows = how_to_rows.get(pt, how_to_rows["journal"])

    for title, desc in rows:
        elems.append(KeepTogether([
            Paragraph(f"<b>{title}</b>", styles["h3"]),
            Paragraph(desc, styles["body"]),
        ]))
    elems.append(PageBreak())

    # ── "Why This Book Is Different" page — leveraging competitor gaps ──
    if directives and directives.get("interior", {}).get("add_differentiation"):
        intr  = directives["interior"]
        extras = intr.get("extra_header_elements", [])
        gaps   = intr.get("gap_fixing_features", [])
        lines_target = intr.get("lines_per_page_target", 14)

        elems.append(Spacer(1, 0.5 * IN))
        elems.append(Paragraph("Why This Book Is Different", styles["h1"]))
        elems.append(_divider(pal))
        elems.append(Spacer(1, 0.18 * IN))
        elems.append(Paragraph(
            "This book was designed after studying the best-selling competitors "
            "in its niche. Every page goes further than the standard:",
            styles["body"]
        ))
        elems.append(Spacer(1, 0.18 * IN))

        diff_rows = []
        if lines_target >= 14:
            diff_rows.append((
                f"More writing space — {lines_target} lines per page",
                "Generous room to actually capture your thoughts, not just headlines."
            ))
        if "weather" in extras:
            diff_rows.append((
                "Weather tracking on every page",
                "Build the connection between your environment and your mood."
            ))
        if "energy" in extras:
            diff_rows.append((
                "Energy rating built in",
                "Notice patterns in when you feel most alive vs. drained."
            ))
        if "intention" in extras:
            diff_rows.append((
                "Daily intention line",
                "Set a clear direction before the day pulls you elsewhere."
            ))
        if gaps:
            diff_rows.append((
                "Designed to fix common gaps in this niche",
                "Built with attention to what other books overlook."
            ))
        diff_rows.append((
            "Premium typography & color palette",
            "Designed to feel like a kept book — not a disposable notebook."
        ))

        for sub, body in diff_rows:
            elems.append(KeepTogether([
                Paragraph(f"<b>{pal.get('symbol','✦')}  {sub}</b>", styles["h3"]),
                Paragraph(body, styles["body"]),
            ]))
        elems.append(PageBreak())

    return elems


def _toc_page(listing: Dict, styles: Dict, pal: Dict) -> List:
    elems = []
    elems.append(Spacer(1, 0.4 * IN))
    elems.append(Paragraph("Contents", styles["h1"]))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.2 * IN))

    # Build TOC table: [section name + description | page number]
    toc_data = []
    page_num = 5   # welcome=2p, toc=1p
    sym = pal.get("symbol", "✦")

    for sec in listing.get("content_sections", []):
        if sec.get("type") in ("toc",):
            continue
        name   = sec.get("title", "Section")
        desc   = sec.get("description", "")[:90]
        pages  = sec.get("pages", 2)

        title_para = Paragraph(f"<b>{sym}  {name}</b>", styles["toc_title"])
        desc_para  = Paragraph(desc, styles["toc_desc"]) if desc else Spacer(1, 2)
        page_para  = Paragraph(str(page_num), ParagraphStyle(
            "TocPg", fontName="Helvetica-Bold", fontSize=11,
            textColor=pal["accent"], alignment=TA_CENTER, leading=14))

        toc_data.append([
            [title_para, desc_para],
            page_para,
        ])
        page_num += pages

        # Separator
        toc_data.append([
            HRFlowable(width="100%", thickness=0.3,
                       color=colors.HexColor("#DDDDDD"), spaceAfter=3, spaceBefore=3),
            "",
        ])

    if toc_data:
        t = Table(toc_data, colWidths=[CONTENT_W * 0.87, CONTENT_W * 0.13])
        t.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elems.append(t)

    elems.append(PageBreak())
    return elems


def _section_title_page(
    sec: Dict, pal: Dict, section_index: int = 0,
    niche_icon: str = None, theme_name: str = "default",
    image_path: Optional[str] = None,
    banner_style: str = "framed",
) -> List:
    """Full-page decorative section break — 8-shade rotation, drawn niche shape."""
    base_a  = pal["accent"]
    base_b  = pal["accent2"]

    def _shade(hex_color, factor=1.0, sat=1.0):
        """Apply lightness and saturation transforms."""
        if hasattr(hex_color, "rgb"):
            r, g, b = hex_color.rgb()
        else:
            r, g, b = 0.5, 0.5, 0.5
        # Brightness
        r = min(1.0, max(0.0, r * factor))
        g = min(1.0, max(0.0, g * factor))
        b = min(1.0, max(0.0, b * factor))
        # Saturation (push toward / away from mid-gray)
        if sat != 1.0:
            mid = (r + g + b) / 3
            r = mid + (r - mid) * sat
            g = mid + (g - mid) * sat
            b = mid + (b - mid) * sat
            r = min(1.0, max(0.0, r))
            g = min(1.0, max(0.0, g))
            b = min(1.0, max(0.0, b))
        return colors.Color(r, g, b)

    # 8-color palette derived from the variant accent + accent2
    # Each section gets a distinct shade — no two consecutive look alike
    color_palette = [
        base_a,                          # 0: pure accent
        base_b,                          # 1: pure accent2
        _shade(base_a, 0.72),            # 2: darker accent
        _shade(base_b, 1.20, sat=0.85),  # 3: lighter, slightly desaturated accent2
        _shade(base_a, 1.18, sat=0.75),  # 4: lighter accent, muted
        _shade(base_b, 0.78),            # 5: darker accent2
        _shade(base_a, 0.92, sat=1.15),  # 6: vivid accent
        _shade(base_b, 1.05, sat=0.65),  # 7: pastel accent2
    ]
    color  = color_palette[section_index % len(color_palette)]
    symbol = niche_icon or pal.get("symbol", "✦")

    # Banner-style preset bias: minimal banners use the light color as base,
    # stripe banners desaturate the dominant color, framed = unchanged.
    if banner_style == "minimal":
        color = _shade(color, 1.30, sat=0.45)
    elif banner_style == "stripe":
        color = _shade(color, 0.85, sat=1.10)

    banner = _SectionBannerPage(
        title       = sec.get("title", ""),
        description = sec.get("description", "")[:120],
        color       = color,
        light_color = pal["light"],
        symbol      = symbol,
        theme_name  = theme_name,
        image_path  = image_path,
    )
    return [Spacer(1, 0.4 * IN), banner, PageBreak()]


def _reference_pages(sec: Dict, listing: Dict, styles: Dict, pal: Dict, product_type: str) -> List:
    """Full content for 'reference' sections (How to Use, Answer Key, Glossary, etc.)"""
    elems = []
    title = sec.get("title", "Reference")
    desc  = sec.get("description", "")
    pages = sec.get("pages", 2)
    sym   = pal.get("symbol", "✦")

    # Headline + description
    elems.append(Spacer(1, 0.2 * IN))
    elems.append(Paragraph(title, styles["h1"]))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.15 * IN))

    if desc:
        elems.append(Paragraph(f"<i>{desc}</i>", styles["italic"]))
        elems.append(Spacer(1, 0.2 * IN))

    title_lower = title.lower()

    # ── "Answer Key" recap (quiz books) ───────────────────────────────────
    if "answer" in title_lower or "key" in title_lower:
        elems.append(Paragraph(
            "<b>Note:</b> Individual answers are provided at the end of each Round "
            "throughout this book. This section serves as a quick-reference index.",
            styles["body"]
        ))
        elems.append(Spacer(1, 0.15 * IN))
        # List all rounds we generated
        rounds = []
        for s in listing.get("content_sections", []):
            if s.get("type") == "qa":
                # Estimate number of rounds in this section
                items = s.get("items", [])
                n_q = sum(1 for it in items if it.startswith("Q:"))
                n_rounds = max(1, n_q // 10)
                rounds.append((s.get("title", "Section"), n_rounds))
        for round_idx, (sec_title, n_r) in enumerate(rounds, 1):
            elems.append(Paragraph(
                f"<b>{sym}  {sec_title}</b>  —  <i>{n_r} round(s)</i>",
                styles["h3"]
            ))
            elems.append(Spacer(1, 4))

    # ── "How to Use" detailed instructions ─────────────────────────────────
    elif "how to use" in title_lower or "instructions" in title_lower or "guide" in title_lower:
        type_specific = {
            "quiz": [
                ("Pick a Round", "Each Round contains 10 questions of mixed difficulty."),
                ("Try Before You Peek", "Answer all 10 questions on the Questions page before turning to the Answers page."),
                ("Score Yourself", "Write your score in the box at the top of each Round page (out of 10)."),
                ("Mix It Up", "Play solo, challenge friends, or use as a party game — Rounds work for all formats."),
                ("Track Progress", "The score box lets you replay later and see your improvement."),
            ],
            "log": [
                ("One Entry Per Page", "Each page is a complete record — date, location, observation, sketch, rating."),
                ("Fill Every Field", "Detailed entries become more valuable as your collection grows."),
                ("Sketch Box", "Use it for quick drawings, diagrams, or to mark where photos go."),
                ("Rate Your Finds", "The star rating helps you spot your best entries at a glance."),
                ("Cross-reference", "Use the date and location fields to spot patterns over time."),
            ],
            "journal": [
                ("Start Anywhere", "Open to any page and begin — there's no required order."),
                ("Use the Prompt", "Each page opens with a prompt — let it spark you, or ignore it."),
                ("Track Your Mood", "The mood scale at top takes 5 seconds but reveals patterns over time."),
                ("Write Without Filter", "This journal is for your eyes only. Be honest."),
                ("Review Monthly", "Every 30 days, flip back and notice what shifted."),
            ],
            "planner": [
                ("Set Top 3 Priorities", "Each day, write the 3 things that MUST get done."),
                ("Time Block", "Assign tasks to specific hours — your schedule guides your energy."),
                ("Track Habits", "Mark the 7 habit dots and 8 water glasses every day."),
                ("End-of-Day Gratitude", "Use the prompt box to capture one gratitude before bed."),
                ("Review Weekly", "Each Sunday, scan the week — what worked, what didn't."),
            ],
            "coloring": [
                ("Pick Your Mood", "Browse the book and pick the illustration matching your day."),
                ("Suggested Palette", "Each page suggests a color palette — use it or improvise."),
                ("Use Any Medium", "Markers, colored pencils, watercolors — there's no wrong choice."),
                ("Color Swatches", "The bottom swatch boxes let you save colors you used."),
                ("Display Your Art", "Pages are perforated-friendly — frame your favorites."),
            ],
        }
        rows = type_specific.get(product_type, type_specific["journal"])
        for sub, body in rows:
            elems.append(KeepTogether([
                Paragraph(f"<b>{sym}  {sub}</b>", styles["h3"]),
                Paragraph(body, styles["body"]),
            ]))

    # ── Generic reference fallback — render items as a clean guide ───────
    else:
        items = sec.get("items", [])
        if items:
            # Alternate between two visual treatments for variety
            for idx, it in enumerate(items[:30]):
                if idx % 4 == 0:
                    # Accent-bar callout every 4th item
                    callout = Table(
                        [[Paragraph(f"<b>{sym}</b>  {it}", styles["body"])]],
                        colWidths=[CONTENT_W],
                    )
                    callout.setStyle(TableStyle([
                        ("BACKGROUND",    (0, 0), (-1, -1), pal["light"]),
                        ("LINEBEFORE",    (0, 0), (0, -1),  3, pal["accent"]),
                        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                        ("TOPPADDING",    (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]))
                    elems.append(callout)
                    elems.append(Spacer(1, 4))
                else:
                    elems.append(Paragraph(f"{sym}  {it}", styles["body"]))
                    elems.append(Spacer(1, 3))
        else:
            # Last resort: section description expanded into a how-to block
            elems.append(Paragraph(
                desc or "Use this section as a handy quick reference while working through your book.",
                styles["body"]
            ))

    # Fill remaining pages with notes lines if section claimed more than 1 page
    elems.append(Spacer(1, 0.2 * IN))
    if pages > 1:
        elems.append(Paragraph("<b>Notes:</b>", styles["h3"]))
        elems.extend(_writing_lines(10))
    elems.append(PageBreak())

    # Additional blank notes pages if section is large (e.g., Answer Key claiming 10p)
    extra_pages = max(0, pages - 2)
    for _ in range(min(extra_pages, 8)):
        elems.append(Spacer(1, 0.3 * IN))
        elems.append(Paragraph("<b>Notes</b>", styles["h3"]))
        elems.append(_divider(pal))
        elems.extend(_writing_lines(20))
        elems.append(PageBreak())

    return elems


def _journal_content_pages(
    section: Dict, listing: Dict, styles: Dict, pal: Dict,
    directives: Optional[Dict] = None,
    theme_name: str = "default",
    image_assets: Optional[Dict] = None,
) -> List:
    """
    Lined journal pages with 2 alternating layouts and niche-specific tracker fields.
    Layout A (even pages): niche tracker + accent strip + prompt box + writing lines.
    Layout B (odd pages): accent strip + larger prompt heading + more writing lines.
    """
    elems   = []
    items   = section.get("items", [])
    n_pages = section.get("pages", 80)

    intr         = (directives or {}).get("interior", {})
    lines_target = max(10, min(intr.get("lines_per_page_target", 14), 18))

    preset       = _resolve_preset(listing)
    line_style   = preset.get("line_style", "solid")
    use_tracker  = bool(preset.get("mood_tracker", True))
    use_accent   = bool(preset.get("corner_motif", True))
    ornament_lo  = preset.get("ornament_density") == "low"

    def _prompt_for(i: int) -> str:
        """
        Niche-aware prompt selection :
          1. design_brief.reflection_prompts (Claude-tailored to niche)
          2. Claude expand_content items
          3. Curated 28-prompt bank fallback
        """
        return _reflection_for_page_with_brief(listing, items, i)

    # 4 rotating journal layouts so 90 pages don't look photocopied
    def _layout_a(idx, prompt):
        out = []
        if use_tracker:
            out.append(_niche_tracker_row(theme_name, pal))
            out.append(Spacer(1, 6))
        if use_accent and not ornament_lo:
            out.append(_NichePageAccent(pal, theme_name, idx))
            out.append(Spacer(1, 6))
        out.append(_prompt_box(prompt, pal, styles))
        out.append(Spacer(1, 6))
        out.extend(_writing_lines(lines_target, shade_alt=False, line_style=line_style))
        return out

    def _layout_b(idx, prompt):
        out = []
        if use_accent and not ornament_lo:
            out.append(_NichePageAccent(pal, theme_name, idx))
            out.append(Spacer(1, 8))
        out.append(Paragraph(
            f"<i>{prompt}</i>",
            ParagraphStyle(f"JrnPromptB{idx}", fontName="Times-Italic", fontSize=12,
                            textColor=pal["accent"], alignment=TA_LEFT,
                            spaceAfter=4, leading=15, leftIndent=6),
        ))
        out.append(HRFlowable(width="100%", thickness=0.5,
                               color=pal["accent2"] if "accent2" in pal else pal["accent"],
                               spaceAfter=6, spaceBefore=2))
        out.extend(_writing_lines(lines_target + 2,
                                   shade_alt=(line_style != "dotted"),
                                   line_style=line_style))
        return out

    def _layout_c(idx, prompt):
        """Two-half page: top = prompt + 6 lines, bottom = 'what happened today?' + 6 lines."""
        out = []
        out.append(Paragraph(f"<b>Prompt:</b> <i>{prompt}</i>",
                              ParagraphStyle(f"JC1{idx}", fontName="Helvetica",
                                              fontSize=11, leading=14, textColor=pal["accent"])))
        out.extend(_writing_lines(6, line_style=line_style))
        out.append(Spacer(1, 10))
        out.append(HRFlowable(width="100%", thickness=0.4,
                               color=colors.HexColor("#CCCCCC")))
        out.append(Spacer(1, 6))
        out.append(Paragraph(f"<b>What happened today?</b>",
                              ParagraphStyle(f"JC2{idx}", fontName="Helvetica-Bold",
                                              fontSize=11, leading=14, textColor=pal["accent"])))
        out.extend(_writing_lines(lines_target - 2, line_style=line_style))
        return out

    def _layout_d(idx, prompt):
        """Quote-of-the-day on top, 1 question, big writing area."""
        quote = _REFLECTION_PROMPTS[(idx * 3) % len(_REFLECTION_PROMPTS)]
        out = []
        if use_accent and not ornament_lo:
            out.append(_NichePageAccent(pal, theme_name, idx))
        out.append(Paragraph(
            f"<font color='#888' size='9'><i>Reflection:</i></font>  "
            f"<i>{quote}</i>",
            ParagraphStyle(f"JDquote{idx}", fontName="Times-Italic", fontSize=10,
                            leading=13, spaceAfter=12),
        ))
        out.append(Paragraph(
            f"<b>Today's prompt</b>",
            ParagraphStyle(f"JDhead{idx}", fontName="Helvetica-Bold", fontSize=11,
                            textColor=pal["accent"], spaceAfter=4),
        ))
        out.append(Paragraph(f"<i>{prompt}</i>",
                              ParagraphStyle(f"JDp{idx}", fontName="Times-Italic",
                                              fontSize=11, leading=14, leftIndent=8,
                                              spaceAfter=8)))
        out.extend(_writing_lines(lines_target + 4, shade_alt=False, line_style=line_style))
        return out

    layouts = [_layout_a, _layout_b, _layout_c, _layout_d]
    icons = []
    if image_assets and image_assets.get("icons"):
        icons = [str(p) for p in image_assets["icons"]]
    # Niche-specific tracker (from design_brief) — shown on every journal page top
    niche_tracker = _niche_tracker_table(listing, pal, styles)

    for i in range(n_pages):
        if niche_tracker is not None:
            elems += [niche_tracker, Spacer(1, 6)]
        prompt = _prompt_for(i)
        elems.extend(layouts[i % len(layouts)](i, prompt))
        # Small niche illustration in the footer on layouts C/D (the cleaner ones)
        if icons and i % len(layouts) in (2, 3):
            icon = _niche_icon_flowable(icons[i % len(icons)], size_in=0.4)
            if icon:
                elems += [Spacer(1, 6), icon]
        elems.append(PageBreak())

    return elems


def _log_content_pages(
    section: Dict, listing: Dict, styles: Dict, pal: Dict,
    directives: Optional[Dict] = None,
    theme_name: str = "default",
    image_assets: Optional[Dict] = None,
) -> List:
    """Structured log entry pages: niche accent strip + table + sketch box + notes."""
    elems  = []
    items  = section.get("items", [])
    n_pages = section.get("pages", 80)
    niche   = listing.get("niche", "")

    # Parse column headers — design_brief overrides if available
    headers = ["Date", "Location", "Species / Item", "Qty", "Notes"]
    brief = _design_brief(listing)
    if brief.get("tracker_fields"):
        headers = [f["label"][:18] for f in brief["tracker_fields"][:6]]
    elif items:
        first = items[0]
        if "," in first:
            headers = [h.strip() for h in first.split(",")][:6]

    col_count = len(headers)
    col_w = CONTENT_W / col_count

    preset      = _resolve_preset(listing)
    use_accent  = bool(preset.get("corner_motif", True))
    ornament_lo = preset.get("ornament_density") == "low"

    # Helper: render brief tracker_fields as a VERTICAL form (label left, input right)
    # Never overflows because each field gets its own row at full width.
    from modules.creation.design_brief import render_field_html as _rfh
    brief_fields = brief.get("tracker_fields") if brief else []

    def _vertical_form_rows():
        """Returns a Table flowable rendering all tracker fields stacked vertically."""
        if not brief_fields:
            return None
        rows = []
        for f in brief_fields:
            rows.append([Paragraph(_rfh(f), styles["small"])])
        t = Table(rows, colWidths=[CONTENT_W])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), pal["light"]),
            ("LINEBEFORE",    (0, 0), (0, -1),  3, pal["accent"]),
            ("LINEBELOW",     (0, 0), (-1, -2), 0.3, colors.HexColor("#DDDDDD")),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    # 3 rotating log layouts — A: vertical-form + illustration + obs,
    # B: form + notes lines, C: narrative + big sketch on top
    def _log_a(i, icon_path=None):
        out = []
        hdr = Table([[Paragraph(f"<b>Entry  #{i+1:03d}</b>", styles["h3"]),
                       Paragraph("Date: ____________  &nbsp; Location: ____________________",
                                  styles["small"])]],
                     colWidths=[CONTENT_W * 0.30, CONTENT_W * 0.70])
        hdr.setStyle(TableStyle([("LINEBELOW", (0,0),(-1,-1), 0.7, pal["accent"]),
                                  ("BOTTOMPADDING", (0,0),(-1,-1), 4),
                                  ("VALIGN", (0,0),(-1,-1), "BOTTOM")]))
        out += [hdr, Spacer(1, 8)]

        # Niche-specific FORM (vertical, no overflow, checkbox-heavy)
        form = _vertical_form_rows()
        if form is not None:
            out += [form, Spacer(1, 8)]
        else:
            # Fallback to the old horizontal mini-table when no brief
            td = [headers[:4]] + [[""] * min(4, col_count) for _ in range(3)]
            mini = Table(td, colWidths=[CONTENT_W / 4] * 4, rowHeights=[18] + [32] * 3)
            mini.setStyle(TableStyle([
                ("BACKGROUND", (0,0),(-1,0), pal["accent"]),
                ("TEXTCOLOR",  (0,0),(-1,0), colors.white),
                ("FONTNAME",   (0,0),(-1,0), "Helvetica-Bold"),
                ("FONTSIZE",   (0,0),(-1,0), 7),
                ("FONTSIZE",   (0,1),(-1,-1), 8),
                ("GRID",       (0,0),(-1,-1), 0.4, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, pal["light"]]),
            ]))
            out += [mini, Spacer(1, 8)]

        # Niche illustration (BIG, used as visual reference for the user)
        # OR sketch box if no icon available
        from reportlab.platypus import Image as RLImage
        import os as _os
        big = None
        if icon_path and _os.path.exists(str(icon_path)):
            try:
                from PIL import Image as _PILImage
                iw, ih = _PILImage.open(str(icon_path)).size
                target_w = CONTENT_W * 0.42
                ratio = target_w / iw
                big = RLImage(str(icon_path), width=target_w, height=ih * ratio)
            except Exception:
                big = None
        if big is None:
            big = _SketchBox(CONTENT_W * 0.42, 1.5 * IN, pal["accent"],
                             label="Sketch / Photo")
        obs_inner = [Paragraph("<b>Observations &amp; Notes</b>", styles["h3"])] + _writing_lines(5)
        obs = Table([[big, obs_inner]], colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.54])
        obs.setStyle(TableStyle([("VALIGN", (0,0),(-1,-1), "TOP"),
                                  ("RIGHTPADDING", (0,0),(0,0), 10)]))
        out += [obs, Spacer(1, 6)]
        return out

    def _log_b(i, icon_path=None):
        """Wide notes layout — vertical form + 12 writing lines + side metrics."""
        out = []
        meta = Table([[Paragraph(f"<b>Entry  #{i+1:03d}</b>", styles["h3"]),
                        Paragraph("Date: __________  &nbsp; Time: __________ &nbsp; "
                                  "Location: ____________________",
                                  styles["small"])]],
                      colWidths=[CONTENT_W * 0.25, CONTENT_W * 0.75])
        meta.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1), pal["light"]),
                                   ("LINEBEFORE", (0,0),(0,-1), 3, pal["accent"]),
                                   ("LEFTPADDING", (0,0),(-1,-1), 8),
                                   ("TOPPADDING", (0,0),(-1,-1), 6),
                                   ("BOTTOMPADDING", (0,0),(-1,-1), 6),
                                   ("VALIGN", (0,0),(-1,-1), "MIDDLE")]))
        out += [meta, Spacer(1, 10)]
        form = _vertical_form_rows()
        if form is not None:
            out += [form, Spacer(1, 8)]
        out.append(Paragraph("<b>What I observed</b>", styles["h3"]))
        out.extend(_writing_lines(10))
        return out

    def _log_c(i, icon_path=None):
        """Narrative — BIG niche illustration on top, vertical form, brief notes."""
        out = []
        title = Table([[Paragraph(f"<b>Entry  #{i+1:03d}</b>  "
                                   f"<font color='#888' size='9'>· quick log</font>",
                                   styles["h3"]),
                         Paragraph("Date: ____________", styles["small"])]],
                       colWidths=[CONTENT_W * 0.65, CONTENT_W * 0.35])
        title.setStyle(TableStyle([("LINEBELOW", (0,0),(-1,-1), 0.7, pal["accent2"]),
                                    ("VALIGN", (0,0),(-1,-1), "BOTTOM")]))
        out += [title, Spacer(1, 8)]
        # BIG niche illustration centered (uses the AI niche icon)
        from reportlab.platypus import Image as RLImage
        import os as _os
        if icon_path and _os.path.exists(str(icon_path)):
            try:
                from PIL import Image as _PILImage
                iw, ih = _PILImage.open(str(icon_path)).size
                target_w = CONTENT_W * 0.55
                ratio = target_w / iw
                out.append(RLImage(str(icon_path), width=target_w, height=ih * ratio,
                                    hAlign="CENTER"))
            except Exception:
                out.append(_SketchBox(CONTENT_W, 1.6 * IN, pal["accent"],
                                       label="Sketch / Photo placeholder"))
        else:
            out.append(_SketchBox(CONTENT_W, 1.6 * IN, pal["accent"],
                                   label="Sketch / Photo placeholder"))
        out.append(Spacer(1, 8))
        form = _vertical_form_rows()
        if form is not None:
            out += [form, Spacer(1, 8)]
        out.append(Paragraph("<b>Notes</b>", styles["h3"]))
        out.extend(_writing_lines(4))
        return out

    layouts = [_log_a, _log_b, _log_c]
    icons = []
    if image_assets and image_assets.get("icons"):
        icons = [str(p) for p in image_assets["icons"]]

    for i in range(n_pages):
        if use_accent and not ornament_lo:
            elems.append(_NichePageAccent(pal, theme_name, i))
            elems.append(Spacer(1, 4))
        icon_path = icons[i % len(icons)] if icons else None
        elems.extend(layouts[i % len(layouts)](i, icon_path=icon_path))
        elems.append(PageBreak())

    return elems


def _quiz_pages(
    section: Dict, listing: Dict, styles: Dict, pal: Dict,
    image_assets: Optional[Dict] = None,
    theme_name: str = "default",
) -> List:
    """
    Quiz pages with 3 rotating layout templates + hero pages every 5th content page.
    Templates: standard (5 Q&A/page), compact (8 Q&A/page), two_column (6 Q&A/page).
    """
    elems = []
    items = section.get("items", [])

    # Parse Q&A pairs — STRICT: only pairs with non-empty Q and A
    pairs, i = [], 0
    while i < len(items):
        line = items[i]
        if line.startswith("Q:"):
            q = line[2:].strip()
            a = ""
            if i + 1 < len(items) and items[i + 1].startswith("A:"):
                a = items[i + 1][2:].strip()
                i += 1
            if q and a:
                pairs.append((q, a))
        i += 1

    if not pairs:
        return elems

    templates = _QA_TEMPLATES   # standard → compact → two_column, cycling
    content_page_idx = 0
    pair_idx = 0

    while pair_idx < len(pairs):
        # Every 5th content page (after page 0) → hero page
        if content_page_idx > 0 and content_page_idx % 5 == 0:
            caption_q = pairs[pair_idx][0] if pair_idx < len(pairs) else ""
            elems.extend(_hero_page_elements(pal, caption_q, image_assets, theme_name))
            content_page_idx += 1
            continue

        tpl = templates[content_page_idx % len(templates)]
        chunk = pairs[pair_idx: pair_idx + tpl.pairs_per_page]
        if not chunk:
            break

        round_no = content_page_idx + 1

        if tpl.name == "qa_standard":
            elems.extend(_qa_page_standard(chunk, styles, pal, content_page_idx, round_no))
        elif tpl.name == "qa_compact":
            elems.extend(_qa_page_compact(chunk, styles, pal, content_page_idx, round_no))
        else:
            elems.extend(_qa_page_two_column(chunk, styles, pal, content_page_idx, round_no))

        pair_idx += len(chunk)
        content_page_idx += 1

    return elems


# ── Banque de prompts de réflexion (rotation page par page) ────────────────
# Garantit qu'aucune page ne pose la même question quand le pool d'items
# Claude est petit. Augmente artificiellement la diversité visible.
_REFLECTION_PROMPTS = [
    "What systems or rituals are working well?",
    "What drained your energy today and why?",
    "Which decision will you be proud of in 5 years?",
    "What did you learn that surprised you?",
    "What would you do differently if you replayed today?",
    "Where did you feel most alive today?",
    "Which person deserves a thank-you message tonight?",
    "What is one thing only you can do tomorrow?",
    "What did procrastination cost you today?",
    "What conversation are you avoiding?",
    "What small win deserves to be celebrated?",
    "Where did you say yes when you meant no?",
    "What boundary did you protect today?",
    "What story are you telling yourself that is not true?",
    "Which habit moved the needle this week?",
    "What is the one task you keep postponing?",
    "What feedback have you ignored too long?",
    "Where did fear shape today's choices?",
    "What would the calmer version of you do next?",
    "Which 20% of effort produced 80% of progress?",
    "What metric matters more than busyness?",
    "What did your body try to tell you today?",
    "Where can you simplify your week?",
    "What is one risk worth taking this month?",
    "Which relationship needs investment now?",
    "What does success look like by Friday?",
    "What expectation can you let go of?",
    "Which yes today is a no to something else?",
]


def _reflection_for_page(items: List[str], page_idx: int) -> str:
    """Prefer Claude items if rich, otherwise rotate through the curated bank."""
    if items and len(items) >= 5:
        return items[page_idx % len(items)]
    # Mix Claude items + bank — deterministic rotation per page
    pool = (items or []) + _REFLECTION_PROMPTS
    return pool[page_idx % len(pool)]


# ── Headers variations (rotation hebdo) ─────────────────────────────────────

def _header_variant(pal: Dict, styles: Dict, variant: int) -> Table:
    """Returns one of 4 header styles to vary the daily look."""
    if variant % 4 == 0:
        cells = [[
            Paragraph("<b>Date:</b> ___________________", styles["small"]),
            Paragraph("<b>Day:</b> M  T  W  T  F  S  S", styles["small"]),
            Paragraph("<b>Energy:</b>  &#9675; &#9675; &#9675; &#9675; &#9675;", styles["small"]),
        ]]
        widths = [CONTENT_W * 0.38, CONTENT_W * 0.33, CONTENT_W * 0.29]
    elif variant % 4 == 1:
        cells = [[
            Paragraph("<b>Date:</b> _____________", styles["small"]),
            Paragraph("<b>Mood:</b>  &#9786; &#9787; &#9785;  &nbsp;<b>Sleep:</b> ___h", styles["small"]),
            Paragraph("<b>Weather:</b>  &#9728; &#9729; &#9730;", styles["small"]),
        ]]
        widths = [CONTENT_W * 0.30, CONTENT_W * 0.40, CONTENT_W * 0.30]
    elif variant % 4 == 2:
        cells = [[
            Paragraph("<b>Today is:</b> ________________", styles["small"]),
            Paragraph("<b>Focus theme:</b> __________________", styles["small"]),
        ]]
        widths = [CONTENT_W * 0.42, CONTENT_W * 0.58]
    else:
        cells = [[
            Paragraph("<b>Week of:</b> ___________", styles["small"]),
            Paragraph("<b>Day #:</b> ___ / 90", styles["small"]),
            Paragraph("<b>Vibe:</b>  &#9733; &#9733; &#9733; &#9733; &#9733;", styles["small"]),
        ]]
        widths = [CONTENT_W * 0.33, CONTENT_W * 0.27, CONTENT_W * 0.40]

    t = Table(cells, colWidths=widths)
    t.setStyle(TableStyle([
        ("LINEBELOW",     (0, 0), (-1, -1), 0.7, pal["accent"]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return t


# ── Dynamic niche-tracker (consumes design_brief.tracker_fields) ──────────

def _design_brief(listing: Dict) -> Dict:
    """Returns the listing's design_brief or empty dict."""
    db = listing.get("_design_brief")
    return db if isinstance(db, dict) else {}


def _reflection_for_page_with_brief(listing: Dict, items: List[str], page_idx: int) -> str:
    """Prefer design_brief prompts (niche-tailored), then Claude items, then bank."""
    brief = _design_brief(listing)
    pool = []
    if brief.get("reflection_prompts"):
        pool = list(brief["reflection_prompts"])
    if items:
        pool += list(items)
    if not pool:
        pool = list(_REFLECTION_PROMPTS)
    return pool[page_idx % len(pool)]


def _niche_tracker_table(listing: Dict, pal: Dict, styles: Dict):
    """
    Render the design_brief.tracker_fields as a clean 2-column table at the
    top of a daily page. Falls back to a generic 3-cell row if no brief.
    """
    from modules.creation.design_brief import render_field_html
    brief = _design_brief(listing)
    fields = brief.get("tracker_fields") or []
    if not fields:
        return None
    # 2-col layout: alternate fields left/right
    cells = []
    row = []
    for i, f in enumerate(fields):
        row.append(Paragraph(render_field_html(f), styles["small"]))
        if len(row) == 2:
            cells.append(row); row = []
    if row:
        row.append("")
        cells.append(row)
    t = Table(cells, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), pal["light"]),
        ("LINEBEFORE",    (0, 0), (0, -1),  3, pal["accent"]),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


# ── Niche illustration helper ─────────────────────────────────────────────
# Embeds one of the AI-generated niche icons as a small inline element so each
# daily page carries the visual signature of its niche.

def _niche_icon_flowable(icon_path, size_in: float = 0.55):
    """Returns a ReportLab Image flowable for a small niche icon, or None."""
    if not icon_path:
        return None
    import os
    try:
        from reportlab.platypus import Image as RLImage
        if not os.path.exists(str(icon_path)):
            return None
        s = size_in * IN
        return RLImage(str(icon_path), width=s, height=s, hAlign="CENTER")
    except Exception:
        return None


def _planner_layout_wellness(items, idx, pal, styles, sym, icon_path=None, listing=None):
    """Wellness-focused day : mood scale + body scan + grounding + gentle prompt."""
    out = [Spacer(1, 5)]
    # Mood scale
    mood = Table([[
        Paragraph("<b>Mood now</b>", styles["small"]),
        Paragraph("1 &nbsp; 2 &nbsp; 3 &nbsp; 4 &nbsp; 5 &nbsp; 6 &nbsp; 7 &nbsp; 8 &nbsp; 9 &nbsp; 10",
                   styles["small"]),
        Paragraph("<b>Energy</b>  &#9675; &#9675; &#9675; &#9675; &#9675;", styles["small"]),
    ]], colWidths=[CONTENT_W * 0.18, CONTENT_W * 0.50, CONTENT_W * 0.32])
    mood.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), pal["light"]),
        ("LINEBEFORE", (0,0),(0,-1), 3, pal["accent"]),
        ("LEFTPADDING", (0,0),(-1,-1), 8),
        ("TOPPADDING", (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
    ]))
    out += [mood, Spacer(1, 8)]
    # Body scan
    out.append(Paragraph(f"<b>{sym}  Body scan</b>  "
                          "<font color='#888' size='8'>· where do you feel tension right now?</font>",
                          styles["h3"]))
    out.extend(_writing_lines(3, line_style="dotted"))
    out.append(Spacer(1, 6))
    # 3 grounding
    out.append(Paragraph("<b>3 things I can see / 2 I can hear / 1 I can touch</b>", styles["h3"]))
    out.extend(_writing_lines(3, line_style="dotted"))
    out.append(Spacer(1, 6))
    # Tonight's gentle act
    out.append(Paragraph("<b>One gentle act for tonight</b>", styles["h3"]))
    out.extend(_writing_lines(2, line_style="dotted"))
    out.append(Spacer(1, 8))
    # Niche icon as a soft watermark vignette
    icon = _niche_icon_flowable(icon_path, size_in=0.55)
    if icon:
        out += [icon, Spacer(1, 4)]
    out.append(_prompt_box(_reflection_for_page_with_brief(listing, items, idx), pal, styles))
    return out


def _planner_layout_focus(items, idx, pal, styles, sym, icon_path=None, listing=None):
    """Deep-focus / ADHD day : energy bars + 1 priority + 4 pomodoros + micro-reward."""
    out = [Spacer(1, 5)]
    # Energy snapshot
    snap = Table([[
        Paragraph("<b>Energy now</b>  &#9608; &#9608; &#9608; &#9633; &#9633;",
                   styles["small"]),
        Paragraph("<b>Focus state</b>  &#9744; sharp &#9744; foggy &#9744; tired",
                   styles["small"]),
    ]], colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.55])
    snap.setStyle(TableStyle([("LINEBELOW", (0,0),(-1,-1), 0.6, pal["accent"]),
                                ("BOTTOMPADDING", (0,0),(-1,-1), 4)]))
    out += [snap, Spacer(1, 8)]
    # ONE priority
    out.append(Paragraph(f"<b>{sym}  ONE thing today, no negotiations</b>",
                          styles["h3"]))
    one = Table([[Paragraph("<font size='10'>"
                              "_______________________________________________</font>",
                              styles["body"])]],
                 colWidths=[CONTENT_W])
    one.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1), pal["light"]),
                              ("LINEBEFORE", (0,0),(0,-1), 4, pal["accent"]),
                              ("LEFTPADDING", (0,0),(-1,-1), 10),
                              ("TOPPADDING", (0,0),(-1,-1), 12),
                              ("BOTTOMPADDING", (0,0),(-1,-1), 12)]))
    out += [one, Spacer(1, 10)]
    # 4 pomodoro slots
    out.append(Paragraph("<b>4 × 25-min focus blocks</b>", styles["h3"]))
    rows = []
    for k in range(1, 5):
        rows.append([Paragraph(f"<b>#{k}</b>", styles["small"]),
                      Paragraph("Task: _____________________________________",
                                 styles["small"]),
                      Paragraph("Done &#9744;", styles["small"])])
    pomo = Table(rows, colWidths=[CONTENT_W * 0.08, CONTENT_W * 0.72, CONTENT_W * 0.20],
                  rowHeights=[24] * 4)
    pomo.setStyle(TableStyle([("LINEBELOW", (0,0),(-1,-1), 0.3, colors.HexColor("#DDDDDD")),
                                ("VALIGN", (0,0),(-1,-1), "MIDDLE")]))
    out += [pomo, Spacer(1, 8)]
    # Brain dump
    out.append(Paragraph("<b>Brain dump</b> "
                          "<font color='#888' size='8'>· thoughts NOT on the task</font>",
                          styles["h3"]))
    out.extend(_writing_lines(5, line_style="dotted"))
    out.append(Spacer(1, 6))
    out.append(Paragraph("<b>Micro-reward after the priority is DONE:</b>  "
                          "_______________________", styles["small"]))
    icon = _niche_icon_flowable(icon_path, size_in=0.45)
    if icon:
        out += [Spacer(1, 4), icon]
    return out


def _planner_layout_a(items, idx, pal, styles, sym, icon_path=None, listing=None):
    """Layout A — Classic: priorities + 2-col time blocks + reflection + habits."""
    elems = [Spacer(1, 5)]
    # Top 3 priorities box
    pri_label = Paragraph(f"<b>{sym}  TOP 3 PRIORITIES</b>", styles["h3"])
    pri_lines = Table(
        [["&#9744;  _______________________________________________"],
         ["&#9744;  _______________________________________________"],
         ["&#9744;  _______________________________________________"]],
        colWidths=[CONTENT_W - 16],
    )
    pri_lines.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
    ]))
    pri_box = Table([[pri_label], [pri_lines]], colWidths=[CONTENT_W])
    pri_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pal["light"]),
        ("LINEBEFORE", (0, 0), (0, -1), 3, pal["accent"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (0, 0), 6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
    ]))
    elems += [pri_box, Spacer(1, 6)]
    # Time blocks
    hours = ["6:00", "7:00", "8:00", "9:00", "10:00", "11:00", "12:00", "13:00",
             "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00"]
    col_w = (CONTENT_W - 6) / 2
    def _time_col(hour_list):
        rows = [[Paragraph(f"<font color='#888888' size='7'>{h}</font>  ",
                            styles["small"]), ""] for h in hour_list]
        t = Table(rows, colWidths=[col_w * 0.22, col_w * 0.78],
                  rowHeights=[22] * len(hour_list))
        t.setStyle(TableStyle([
            ("LINEBELOW",     (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        return t
    tt = Table([[_time_col(hours[:8]), Spacer(6, 1), _time_col(hours[8:])]],
               colWidths=[col_w, 6, col_w])
    tt.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 0),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elems += [tt, Spacer(1, 5)]
    elems.append(_prompt_box(_reflection_for_page_with_brief(listing, items, idx), pal, styles))
    elems.append(Spacer(1, 4))
    return elems


def _planner_layout_b(items, idx, pal, styles, sym, icon_path=None, listing=None):
    """Layout B — Focus day: single big priority + brain dump + evening check-in."""
    elems = [Spacer(1, 5)]
    # ONE big focus priority
    elems.append(Paragraph(f"<b>{sym}  TODAY'S ONE THING</b>", styles["h3"]))
    one_box = Table([[Paragraph(
        "<font size='10'>___________________________________________________</font><br/>"
        "<font size='10'>___________________________________________________</font>",
        styles["body"])]],
        colWidths=[CONTENT_W])
    one_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pal["light"]),
        ("LINEBEFORE", (0, 0), (0, -1), 4, pal["accent"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    elems += [one_box, Spacer(1, 10)]
    # Brain dump
    elems.append(Paragraph("<b>Brain dump</b>  <font color='#888' size='8'>"
                            "(everything in your head, no order):</font>", styles["h3"]))
    elems.extend(_writing_lines(8, line_style="dotted"))
    elems.append(Spacer(1, 6))
    elems.append(Paragraph(f"<b>Evening check-in</b>", styles["h3"]))
    elems.append(_prompt_box(_reflection_for_page_with_brief(listing, items, idx), pal, styles))
    elems.extend(_writing_lines(3))
    return elems


def _planner_layout_c(items, idx, pal, styles, sym, icon_path=None, listing=None):
    """Layout C — 3-block day: Morning / Afternoon / Evening goals + reflection."""
    elems = [Spacer(1, 5)]
    blocks = [
        ("MORNING", "Energy peak — protect for deep work"),
        ("AFTERNOON", "Meetings, errands, second wind tasks"),
        ("EVENING", "Wind-down, family, rest, no screens"),
    ]
    for label, hint in blocks:
        head = Paragraph(f"<b>{sym} {label}</b>  "
                          f"<font color='#888' size='8'>· {hint}</font>", styles["h3"])
        lines = Table([[" "], [" "], [" "]], colWidths=[CONTENT_W - 12],
                       rowHeights=[22, 22, 22])
        lines.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ]))
        wrap = Table([[head], [lines]], colWidths=[CONTENT_W])
        wrap.setStyle(TableStyle([
            ("LINEBEFORE", (0, 0), (0, -1), 2, pal["accent2"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (0, 0), 4),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ]))
        elems += [wrap, Spacer(1, 6)]
    elems.append(_prompt_box(_reflection_for_page_with_brief(listing, items, idx), pal, styles))
    return elems


def _planner_layout_d(items, idx, pal, styles, sym, icon_path=None, listing=None):
    """Layout D — Visual / habit-heavy: priorities + habit grid + gratitude trio."""
    elems = [Spacer(1, 5)]
    elems.append(Paragraph(f"<b>{sym}  Today's 3 must-do</b>", styles["h3"]))
    pri_lines = Table(
        [["1.  ____________________________________________"],
         ["2.  ____________________________________________"],
         ["3.  ____________________________________________"]],
        colWidths=[CONTENT_W - 12])
    pri_lines.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elems += [pri_lines, Spacer(1, 10)]
    # Habit tracking row
    habit_names = ["Move", "Read", "Water", "Sleep", "No phone AM", "Meditate", "Connect"]
    head_row = [Paragraph(f"<b>{h}</b>", styles["small"]) for h in habit_names]
    check_row = ["&#9744;"] * len(habit_names)
    grid = Table([head_row, check_row], colWidths=[CONTENT_W / len(habit_names)] * len(habit_names))
    grid.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), pal["light"]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 1), (-1, 1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.4, pal["accent"]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, pal["accent"]),
    ]))
    elems += [grid, Spacer(1, 10)]
    # Gratitude trio
    elems.append(Paragraph("<b>3 small things I'm grateful for today</b>", styles["h3"]))
    grat = Table(
        [["&#10047;  _________________________________________"],
         ["&#10047;  _________________________________________"],
         ["&#10047;  _________________________________________"]],
        colWidths=[CONTENT_W - 12])
    grat.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elems += [grat, Spacer(1, 8)]
    elems.append(_prompt_box(_reflection_for_page_with_brief(listing, items, idx), pal, styles))
    return elems


def _weekly_review_page(week_num: int, pal: Dict, styles: Dict, sym: str, blocks=None) -> List:
    """A full-page weekly review inserted every 7 days."""
    elems = [Spacer(1, 0.2 * IN)]
    elems.append(Paragraph(
        f"<b>WEEKLY REVIEW &nbsp;·&nbsp; Week {week_num}</b>",
        ParagraphStyle("WkRev", fontName="Helvetica-Bold", fontSize=18,
                        textColor=pal["accent"], alignment=TA_LEFT,
                        leading=22, spaceAfter=10),
    ))
    elems.append(HRFlowable(width="100%", thickness=1.2, color=pal["accent"],
                             spaceAfter=12))
    default_blocks = [
        ("WINS",         "What worked? What am I most proud of?"),
        ("LESSONS",      "What did I learn the hard way?"),
        ("ENERGY MAP",   "What drained me? What recharged me?"),
        ("NEXT WEEK",    "Top 3 priorities + one habit to double down on"),
    ]
    if blocks and isinstance(blocks, list) and len(blocks) >= 2:
        # Brief returns plain headers; pair them with a generic hint
        hint_pool = ["What stood out this week?",
                      "What pattern is emerging?",
                      "What deserves more time?",
                      "What needs to change?"]
        block_pairs = [(str(b).upper()[:24], hint_pool[i % len(hint_pool)])
                       for i, b in enumerate(blocks[:4])]
    else:
        block_pairs = default_blocks
    for title, hint in block_pairs:
        elems.append(Paragraph(f"<b>{sym}  {title}</b>  "
                                f"<font color='#888' size='9'>{hint}</font>",
                                styles["h3"]))
        elems.extend(_writing_lines(4))
        elems.append(Spacer(1, 6))
    return elems + [PageBreak()]


# ── Planner layout REGISTRY (preset picks the pool per niche family) ──────
PLANNER_LAYOUT_REGISTRY = {
    "a":         _planner_layout_a,
    "b":         _planner_layout_b,
    "c":         _planner_layout_c,
    "d":         _planner_layout_d,
    "wellness":  _planner_layout_wellness,
    "focus":     _planner_layout_focus,
}


def _resolve_planner_pool(preset: Dict) -> List:
    """Return the list of layout fns to rotate, falling back to all 4 generics."""
    names = preset.get("daily_layouts") or ["a", "b", "c", "d"]
    pool = [PLANNER_LAYOUT_REGISTRY[n] for n in names if n in PLANNER_LAYOUT_REGISTRY]
    return pool or [_planner_layout_a, _planner_layout_b,
                    _planner_layout_c, _planner_layout_d]


def _planner_content_pages(
    section: Dict, listing: Dict, styles: Dict, pal: Dict,
    directives: Optional[Dict] = None,
    theme_name: str = "default",
    image_assets: Optional[Dict] = None,
) -> List:
    """
    Daily planner pages — niche-AWARE rendering driven by listing._design_brief:
      - daily_layouts pool comes from Claude's brief if present
      - tracker_fields render the daily tracker (niche-specific)
      - reflection_prompts populate every reflection slot (niche-specific)
      - weekly_review_blocks customize the weekly review headers
      - per-page niche illustration from image_assets icons
    Falls back to preset rules if no brief.
    """
    elems  = []
    items  = section.get("items", [])
    n_pages = section.get("pages", 80)
    sym    = pal.get("symbol", "◆")

    preset      = _resolve_preset(listing)
    brief       = _design_brief(listing)
    use_accent  = bool(preset.get("corner_motif", True))
    ornament_lo = preset.get("ornament_density") == "low"

    # Layout pool : design_brief wins, preset second, generic last
    if brief.get("daily_layouts"):
        layouts = [PLANNER_LAYOUT_REGISTRY[n] for n in brief["daily_layouts"]
                   if n in PLANNER_LAYOUT_REGISTRY] or _resolve_planner_pool(preset)
    else:
        layouts = _resolve_planner_pool(preset)

    icons   = []
    if image_assets and image_assets.get("icons"):
        icons = [str(p) for p in image_assets["icons"]]

    # Cache the niche-specific tracker table (same on every daily page)
    niche_tracker = _niche_tracker_table(listing, pal, styles)

    daily_idx = 0
    week_num  = 1
    pages_emitted = 0
    while pages_emitted < n_pages:
        if daily_idx > 0 and daily_idx % 7 == 0:
            elems.extend(_weekly_review_page(
                week_num, pal, styles, sym,
                blocks=brief.get("weekly_review_blocks")))
            week_num += 1
            pages_emitted += 1
            if pages_emitted >= n_pages:
                break

        if use_accent and not ornament_lo:
            elems.append(_NichePageAccent(pal, theme_name, daily_idx))
            elems.append(Spacer(1, 4))
        elems.append(_header_variant(pal, styles, daily_idx))
        # Niche tracker (Claude's brief fields) — top of EVERY daily page
        if niche_tracker is not None:
            elems += [Spacer(1, 4), niche_tracker, Spacer(1, 6)]

        layout_fn = layouts[daily_idx % len(layouts)]
        icon_path = icons[daily_idx % len(icons)] if icons else None
        # Layout receives the brief-aware reflection through listing
        elems.extend(layout_fn(items, daily_idx, pal, styles, sym,
                                icon_path=icon_path, listing=listing))
        # Habit tracker footer — alternates 2 styles to add micro-variation
        if daily_idx % 2 == 0:
            footer = [[
                Paragraph("<font color='#888888' size='7'>Habits:</font>", styles["small"]),
                Paragraph("&#9675; &#9675; &#9675; &#9675; &#9675; &#9675; &#9675;", styles["small"]),
                Paragraph("Water: &#9744; &#9744; &#9744; &#9744; &#9744; &#9744; &#9744; &#9744;", styles["small"]),
            ]]
            widths = [CONTENT_W * 0.15, CONTENT_W * 0.32, CONTENT_W * 0.53]
        else:
            footer = [[
                Paragraph("<font color='#888888' size='7'>Sleep:</font>", styles["small"]),
                Paragraph("___h  &nbsp;<font color='#888' size='7'>Steps:</font> _____", styles["small"]),
                Paragraph("Screens: &#9744; under 2h  &nbsp;&nbsp; Workout: &#9744;", styles["small"]),
            ]]
            widths = [CONTENT_W * 0.13, CONTENT_W * 0.32, CONTENT_W * 0.55]
        ht2 = Table(footer, colWidths=widths)
        ht2.setStyle(TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        elems += [ht2, PageBreak()]
        daily_idx += 1
        pages_emitted += 1

    return elems


def _blank_back_page(styles: Dict) -> List:
    """A near-blank verso page (so markers don't bleed through to the next drawing)."""
    return [
        Spacer(1, PAGE_H * 0.45),
        Paragraph(
            "This page is intentionally left blank",
            ParagraphStyle(
                "BlankBack", fontName="Helvetica", fontSize=7,
                textColor=colors.HexColor("#DDDDDD"), alignment=TA_CENTER, leading=9,
            ),
        ),
        PageBreak(),
    ]


def _coloring_illustration_page(
    img_path: str, title_text: str, styles: Dict, pal: Dict,
) -> List:
    """One full-page coloring line-art illustration with a subtle title caption."""
    import os
    from reportlab.platypus import Image as RLImage

    elems = [Spacer(1, 4)]
    drawn = False
    if img_path and os.path.exists(str(img_path)):
        try:
            from PIL import Image as _PILImage
            iw, ih = _PILImage.open(str(img_path)).size
            max_w = CONTENT_W
            max_h = PAGE_H - M_TOP - M_BOT - 30   # leave room for the caption
            ratio = min(max_w / iw, max_h / ih)
            dw, dh = iw * ratio, ih * ratio
            elems.append(RLImage(str(img_path), width=dw, height=dh, hAlign="CENTER"))
            drawn = True
        except Exception as e:
            logger.debug(f"Coloring image draw failed: {e}")

    if not drawn:
        # Fallback: empty bordered art space (only if the AI image is missing)
        elems.append(_SketchBox(CONTENT_W, 6.5 * IN, pal["accent"],
                                label=f"Color this page  ·  {title_text}"))

    elems.append(Spacer(1, 4))
    elems.append(Paragraph(
        title_text,
        ParagraphStyle(
            "ColCaption", fontName="Helvetica", fontSize=8,
            textColor=colors.HexColor("#999999"), alignment=TA_CENTER, leading=10,
        ),
    ))
    elems.append(PageBreak())
    return elems


def _coloring_content_pages(
    section: Dict, listing: Dict, styles: Dict, pal: Dict,
    directives: Optional[Dict] = None,
    theme_name: str = "default",
    coloring_images: Optional[List] = None,
) -> List:
    """
    Professional coloring-book pages: each AI line-art drawing on its own page,
    followed by a blank verso (drawing + blank-back format).
    Falls back to a bordered art space only if no AI images were generated.
    """
    elems   = []
    items   = section.get("items", [])
    coloring_images = coloring_images or []

    if coloring_images:
        for idx, img_path in enumerate(coloring_images):
            title_text = items[idx % len(items)] if items else f"Design {idx + 1}"
            elems.extend(_coloring_illustration_page(img_path, title_text, styles, pal))
            elems.extend(_blank_back_page(styles))
        return elems

    # ── Fallback (no AI images) — bordered art space + blank back ──────────
    n_pages = section.get("pages", 10)
    for i in range(n_pages):
        title_text = items[i % len(items)] if items else f"Design {i + 1}"
        elems.extend(_coloring_illustration_page(None, title_text, styles, pal))
        elems.extend(_blank_back_page(styles))

    return elems


def _hero_page_elements(
    pal: Dict, caption: str = "", image_assets: Optional[Dict] = None,
    theme_name: str = "default",
) -> List:
    """Returns flowable list for a full-page hero illustration + caption."""
    image_path = None
    if image_assets and image_assets.get("icons"):
        icons = image_assets["icons"]
        if icons:
            image_path = str(icons[0])
    hero = _HeroPageFlowable(pal, caption, image_path, theme_name)
    return [Spacer(1, 0.4 * IN), hero, PageBreak()]


def _qa_page_standard(pairs: List, styles: Dict, pal: Dict,
                      page_idx: int = 0, round_no: int = 1) -> List:
    """Q bold left-aligned, A indented 12pt below, thin separator. Fits 5-6 pairs."""
    elems = []
    acc = pal["accent"]
    sym = pal.get("symbol", "★")

    # Subtle page header
    hdr_data = [[
        Paragraph(f"<font color='#888888' size='7'>Section {round_no}</font>", styles["small"]),
        Paragraph(
            f"<font color='#888888' size='7'>Q&amp;A  ·  Page {page_idx + 1}</font>",
            ParagraphStyle("HdrR", fontName="Helvetica", fontSize=7,
                           textColor=colors.HexColor("#888888"), alignment=TA_RIGHT, leading=10)
        ),
    ]]
    ht = Table(hdr_data, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
    ht.setStyle(TableStyle([
        ("LINEBELOW",     (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    elems.append(ht)
    elems.append(Spacer(1, 6))

    q_style = ParagraphStyle("QStd", fontName="Helvetica-Bold", fontSize=10.5,
                             textColor=acc, alignment=TA_LEFT, spaceAfter=2, leading=14)
    a_style = ParagraphStyle("AStd", fontName="Times-Roman", fontSize=10.5,
                             textColor=colors.HexColor("#333333"),
                             alignment=TA_LEFT, spaceAfter=2, leading=14, leftIndent=14)

    for q, a in pairs:
        elems.append(KeepTogether([
            Paragraph(f"<b>{sym}</b>  {q}", q_style),
            Paragraph(a, a_style),
            HRFlowable(width="100%", thickness=0.3,
                       color=colors.HexColor("#DDDDDD"), spaceAfter=5, spaceBefore=2),
        ]))

    elems.append(PageBreak())
    return elems


def _qa_page_compact(pairs: List, styles: Dict, pal: Dict,
                     page_idx: int = 0, round_no: int = 1) -> List:
    """Compact: 9pt font, tight leading. Fits 8-9 pairs. Has a light background band."""
    elems = []
    acc = pal["accent"]
    light = pal["light"]

    # Accent-colored top strip
    strip_data = [[Paragraph(
        f"<font color='white' size='8'><b>Quick Fire Round · {round_no}</b></font>",
        ParagraphStyle("Strip", fontName="Helvetica-Bold", fontSize=8,
                       textColor=colors.white, alignment=TA_LEFT, leading=10)
    )]]
    strip = Table(strip_data, colWidths=[CONTENT_W])
    strip.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), acc),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    elems.append(strip)
    elems.append(Spacer(1, 6))

    compact_q = ParagraphStyle("QCmpct", fontName="Helvetica-Bold", fontSize=9,
                               textColor=acc, alignment=TA_LEFT, spaceAfter=1, leading=12)
    compact_a = ParagraphStyle("ACmpct", fontName="Times-Roman", fontSize=9,
                               textColor=colors.HexColor("#333333"),
                               alignment=TA_LEFT, spaceAfter=6, leading=12, leftIndent=10)

    for i, (q, a) in enumerate(pairs):
        row_bg = light if i % 2 == 0 else colors.white
        row_data = [[
            Paragraph(q, compact_q),
            Paragraph(a, compact_a),
        ]]
        rt = Table(row_data, colWidths=[CONTENT_W * 0.48, CONTENT_W * 0.52])
        rt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), row_bg),
            ("LINEBELOW",     (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
            ("COLSEP",        (0, 0), (0, -1),  0.5, acc),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        elems.append(rt)

    elems.append(PageBreak())
    return elems


def _qa_page_two_column(pairs: List, styles: Dict, pal: Dict,
                        page_idx: int = 0, round_no: int = 1) -> List:
    """Two-column layout: Questions | Answers, separated by vertical rule."""
    elems = []
    acc = pal["accent"]
    light = pal["light"]
    col_w = (CONTENT_W - 8) / 2

    # Column headers
    hdr_data = [[
        Paragraph("<b>Questions</b>", ParagraphStyle(
            "ColHdrQ", fontName="Helvetica-Bold", fontSize=9,
            textColor=colors.white, alignment=TA_CENTER, leading=12)),
        Paragraph("<b>Answers</b>", ParagraphStyle(
            "ColHdrA", fontName="Helvetica-Bold", fontSize=9,
            textColor=colors.white, alignment=TA_CENTER, leading=12)),
    ]]
    hdr = Table(hdr_data, colWidths=[col_w, col_w])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), acc),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEAFTER",     (0, 0), (0, -1),  1, colors.white),
    ]))
    elems.append(hdr)

    q_style = ParagraphStyle("QCol", fontName="Helvetica-Bold", fontSize=9.5,
                             textColor=acc, alignment=TA_LEFT, spaceAfter=2, leading=13)
    a_style = ParagraphStyle("ACol", fontName="Times-Roman", fontSize=9.5,
                             textColor=colors.HexColor("#333333"),
                             alignment=TA_LEFT, spaceAfter=2, leading=13)

    rows = []
    for q, a in pairs:
        rows.append([Paragraph(q, q_style), Paragraph(a, a_style)])

    if rows:
        t = Table(rows, colWidths=[col_w, col_w])
        t.setStyle(TableStyle([
            ("LINEBELOW",     (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
            ("LINEAFTER",     (0, 0), (0, -1),  0.8, acc),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, light]),
        ]))
        elems.append(t)

    elems.append(Spacer(1, 4))
    elems.append(Paragraph(
        f"<font color='#AAAAAA' size='7'>Round {round_no}  ·  Page {page_idx + 1}</font>",
        ParagraphStyle("FtrNote", fontName="Helvetica", fontSize=7,
                       textColor=colors.HexColor("#AAAAAA"), alignment=TA_RIGHT, leading=9)
    ))
    elems.append(PageBreak())
    return elems


def _closing_page(listing: Dict, styles: Dict, pal: Dict,
                  theme_name: str = "default") -> List:
    elems = []
    elems.append(Spacer(1, 1.0 * IN))
    # Decorative row — vector shapes (no font dependency)
    elems.append(_DecorativeSymbolRow(CONTENT_W * 0.6, pal["accent"], theme_name))
    elems.append(Spacer(1, 0.2 * IN))
    elems.append(Paragraph("Thank You", styles["h1"]))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.25 * IN))

    thanks = (
        f"Thank you for choosing <i>{listing['title']}</i>. "
        "We hope every page brings you joy, clarity, and purpose. "
        "<br/><br/>"
        "If this book added value to your life, a review on Amazon means "
        "the world to independent publishers like us — it takes just 60 seconds "
        "and makes a huge difference."
        "<br/><br/>"
        f"With gratitude,<br/><b>{listing.get('publisher_name','The Publisher')}</b>"
    )
    elems.append(Paragraph(thanks, styles["body"]))
    elems.append(Spacer(1, 0.4 * IN))

    # Star CTA
    elems.append(Paragraph(
        "★ ★ ★ ★ ★  Leave a 5-star review on Amazon  ★ ★ ★ ★ ★",
        ParagraphStyle("StarCTA", fontName="Helvetica-Bold", fontSize=9,
                       textColor=colors.HexColor("#CCAA00"),
                       alignment=TA_CENTER, leading=13)
    ))
    elems.append(Spacer(1, 0.3 * IN))
    elems.append(_divider(pal))
    elems.append(Spacer(1, 0.15 * IN))
    elems.append(Paragraph(
        f"© {listing.get('publisher_name','All rights reserved.')}  ·  All rights reserved.",
        styles["small"]
    ))
    return elems


# ── Master builder ─────────────────────────────────────────────────────────────

def create_interior(
    listing: Dict,
    output_path: str,
    status_cb: Optional[Callable] = None,
    style_variant: Optional[Dict] = None,
    image_assets: Optional[Dict] = None,
) -> str:
    """
    Builds the complete professional 6×9" interior PDF.
    If `style_variant` is provided, its palette / symbol / fonts override
    the product_type defaults — guarantees visual uniqueness across a batch.
    Returns output_path on success.
    """
    _ensure_vera_registered()   # ensures Unicode symbols render
    _apply_listing_trim(listing) # NEW: honour custom trim size

    product_type = listing.get("product_type", "journal")
    pal  = dict(_pal(product_type))   # copy so we can mutate

    # ── Apply variant overrides ──────────────────────────────────────────
    fonts_override = None
    if style_variant:
        if style_variant.get("palette"):
            v_pal = style_variant["palette"]
            pal["accent"]  = colors.HexColor(v_pal.get("accent",  "#4A4063"))
            pal["accent2"] = colors.HexColor(v_pal.get("accent2", "#7C6FA0"))
            pal["light"]   = colors.HexColor(v_pal.get("light",   "#F3F0F8"))
        if style_variant.get("symbol"):
            pal["symbol"] = style_variant["symbol"]
        if style_variant.get("fonts"):
            fonts_override = style_variant["fonts"]

    # Niche-aware decoration: detect theme + register its fonts + pick icons
    from modules.creation.niche_themes import detect_theme
    theme = detect_theme(listing.get("niche", ""))
    theme_icons = theme["icons"]
    theme_name  = theme.get("name", "default")
    theme_fonts = register_theme_fonts(theme_name)

    if status_cb:
        status_cb(f"🔤 Typo: {theme.get('name','default')}  ({theme_fonts.get('display','?')})")

    st = _styles(pal, fonts=fonts_override, theme_fonts=theme_fonts)

    # ── Design directives from competitor sample analysis ────────────────
    directives = None
    if status_cb is not None:
        try:
            from modules.learning.sample_reader import (
                get_sample_insights, compute_design_directives, directives_summary_for_status,
            )
            from config import Config as _Cfg
            sample_insights = get_sample_insights(_Cfg.LEARNING_DIR, listing.get("niche", ""))
            if sample_insights:
                directives = compute_design_directives(sample_insights)
                status_cb(f"🎯 Design directives: {directives_summary_for_status(directives)}")
        except Exception as e:
            logger.debug(f"Design directives skipped: {e}")

    if status_cb:
        status_cb(f"📄 Génération PDF intérieur ({listing.get('page_count',120)} pages)...")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    first_page_cb, later_pages_cb = _make_page_callbacks(listing, pal)

    # A detailed, page-numbered Table of Contents (via multiBuild) is used for
    # high-content books that have chapter/recipe/part openers — NOT kids facts
    # (no formal TOC) and NOT low-content (their own simple front matter).
    _use_toc = (product_type in ("recipe_book", "how_to")
                and not listing.get("_facts"))
    _DocClass = _TocDocTemplate if _use_toc else SimpleDocTemplate
    doc = _DocClass(
        output_path,
        pagesize   = (PAGE_W, PAGE_H),
        leftMargin  = M_INNER,
        rightMargin = M_OUTER,
        topMargin   = M_TOP,
        bottomMargin = M_BOT,
        title   = listing["title"],
        author  = listing.get("publisher_name", ""),
        subject = listing.get("subtitle", ""),
    )

    story = []

    # Welcome (2 pages) + TOC (1 page)
    hero_path = None
    if image_assets and image_assets.get("hero"):
        _hp = str(image_assets["hero"])
        # Guard: only use the hero if it actually opens as a valid image —
        # a missing/corrupt/unreadable file would otherwise CRASH the whole PDF
        # build at flowable-wrap time (and lose the entire generation).
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(_hp) as _im:
                _im.verify()
            hero_path = _hp
        except Exception as _he:
            logger.warning(f"hero image unusable, skipping: {_he}")
            if status_cb:
                status_cb("⚠️ Image hero illisible — ignorée (le livre est généré sans)")
    if product_type in ("recipe_book", "how_to"):
        # High-content → pro TITLE PAGE, then a detailed page-numbered TOC
        # (the B&W cover page is prepended after cover gen).
        story.extend(_title_copyright_page(listing, st, pal, theme_name))
        if _use_toc:
            story.extend(_build_toc(listing, st, pal, theme_name))
    else:
        story.extend(_welcome_page(listing, st, pal, directives,
                                   hero_image_path=hero_path, theme_name=theme_name))
        story.extend(_toc_page(listing, st, pal))

    # ── Puzzle book / activity book short-circuit ─────────────────────────
    # Content is purely algorithmic — no Claude items, no welcome prompts.
    # We render straight into puzzle pages + solutions section.
    if product_type in ("puzzle", "activity_book"):
        from modules.creation.puzzles import PUZZLE_REGISTRY
        from modules.creation.puzzles import activity_book as ab_mod
        content_w_avail = PAGE_W - M_INNER - M_OUTER
        content_h_avail = PAGE_H - M_TOP - M_BOT

        if product_type == "puzzle":
            puzzle_type = listing.get("puzzle_type", "mazes")
            sets = [(puzzle_type, listing.get("_puzzles", []))]
        else:
            sets = listing.get("_puzzle_sets", [])

        for ptype, pzs in sets:
            if not pzs:
                continue
            mod_info = PUZZLE_REGISTRY.get(ptype)
            if not mod_info:
                continue
            mod  = mod_info["module"]
            label = mod_info["label"]
            # Section banner per puzzle type
            banner_sec = {"title": label, "description": "", "pages": 1, "type": "content"}
            niche_icon = theme_icons[0] if theme_icons else "✦"
            _bs = _resolve_preset(listing).get("section_banner", "stripe")
            story.extend(_section_title_page(banner_sec, pal, 0, niche_icon,
                                             theme_name, banner_style=_bs))
            story.extend(mod.render_pages(pzs, listing, pal, st,
                                          content_w_avail, content_h_avail))
        # Solutions for all sets that need them
        needs_sol = any(PUZZLE_REGISTRY.get(t, {}).get("needs_solutions") for t, _ in sets)
        if needs_sol:
            for ptype, pzs in sets:
                if not pzs:
                    continue
                mod_info = PUZZLE_REGISTRY.get(ptype, {})
                if not mod_info.get("needs_solutions"):
                    continue
                mod = mod_info["module"]
                story.extend(mod.render_solutions(pzs, listing, pal, st,
                                                  content_w_avail, content_h_avail))
        story.extend(_closing_page(listing, st, pal, theme_name))
        doc.build(story, onFirstPage=first_page_cb, onLaterPages=later_pages_cb)
        if status_cb:
            status_cb(f"✅ PDF intérieur puzzle créé → {Path(output_path).name}")
        return

    # ── HIGH-CONTENT branch (recipe_book / how_to) — Phase 2 ──────────────
    # Real written content generated by the highcontent engine (web-grounded).
    if product_type in ("recipe_book", "how_to"):
        from modules.creation.highcontent import (
            render_recipe_pages, render_guide_pages,
            render_bonus_pages, render_facts_pages,
            render_anecdotes_pages,
            render_technique_section,
        )
        content_w_avail = PAGE_W - M_INNER - M_OUTER
        content_h_avail = PAGE_H - M_TOP - M_BOT

        if product_type == "recipe_book":
            # Bonus front-matter FIRST (intro + meal plan + shopping list),
            # then a Techniques reference section, then the recipes.
            bonus = listing.get("_bonus")
            if bonus:
                story.extend(render_bonus_pages(bonus, listing, pal, st,
                                                content_w_avail, content_h_avail))
            techniques = listing.get("_diagrams")
            if techniques:
                story.extend(render_technique_section(techniques, listing, pal, st,
                                                      content_w_avail, content_h_avail))
            recipes = listing.get("_recipes", [])
            story.extend(render_recipe_pages(recipes, listing, pal, st,
                                             content_w_avail, content_h_avail))
        elif listing.get("_facts"):
            story.extend(render_facts_pages(listing["_facts"], listing, pal, st,
                                            content_w_avail, content_h_avail))
        elif listing.get("_anecdotes"):
            story.extend(render_anecdotes_pages(listing["_anecdotes"], listing, pal, st,
                                                content_w_avail, content_h_avail))
        else:
            guide = listing.get("_guide", {})
            story.extend(render_guide_pages(guide, listing, pal, st,
                                            content_w_avail, content_h_avail))
        story.extend(_closing_page(listing, st, pal, theme_name))
        if _use_toc:
            # multiBuild renders twice so the TOC picks up real page numbers.
            doc.multiBuild(story, onFirstPage=first_page_cb, onLaterPages=later_pages_cb)
        else:
            doc.build(story, onFirstPage=first_page_cb, onLaterPages=later_pages_cb)
        if status_cb:
            status_cb(f"✅ PDF intérieur high-content créé → {Path(output_path).name}")
        return

    # Content sections — pass section_index for alternating colors + niche icon
    sections = listing.get("content_sections", [])

    # ── Pre-distribute coloring line-art images across coloring sections ──
    coloring_alloc = {}
    if product_type == "coloring" and image_assets and image_assets.get("coloring_pages"):
        col_imgs = list(image_assets["coloring_pages"])
        col_secs = [s for s in sections if s.get("type") in ("content", "tracker", "qa")]
        if col_secs and col_imgs:
            per = max(1, len(col_imgs) // len(col_secs))
            cur = 0
            for s_idx, s in enumerate(col_secs):
                if s_idx == len(col_secs) - 1:
                    coloring_alloc[id(s)] = col_imgs[cur:]          # last gets remainder
                else:
                    coloring_alloc[id(s)] = col_imgs[cur:cur + per]
                    cur += per

    content_section_index = 0   # only counts non-welcome/toc sections
    for sec in sections:
        sec_type = sec.get("type", "content")

        if sec_type in ("welcome", "toc"):
            continue

        elif sec_type == "closing":
            story.extend(_closing_page(listing, st, pal, theme_name))

        elif sec_type in ("content", "tracker", "qa"):
            niche_icon = theme_icons[content_section_index % len(theme_icons)]
            # Pick a niche-specific AI icon for this section (rotate through the 6)
            ai_icon_path = None
            if image_assets and image_assets.get("icons"):
                icons = image_assets["icons"]
                ai_icon_path = str(icons[content_section_index % len(icons)])
            _bs = _resolve_preset(listing).get("section_banner", "framed")
            story.extend(_section_title_page(
                sec, pal, content_section_index, niche_icon, theme_name,
                image_path=ai_icon_path,
                banner_style=_bs,
            ))

            # Dispatch to the right content builder based on product type
            if product_type == "quiz":
                story.extend(_quiz_pages(sec, listing, st, pal,
                                         image_assets=image_assets, theme_name=theme_name))
            elif product_type == "log":
                story.extend(_log_content_pages(sec, listing, st, pal, directives,
                                                theme_name=theme_name,
                                                image_assets=image_assets))
            elif product_type == "planner":
                story.extend(_planner_content_pages(sec, listing, st, pal, directives,
                                                    theme_name=theme_name,
                                                    image_assets=image_assets))
            elif product_type == "coloring":
                story.extend(_coloring_content_pages(
                    sec, listing, st, pal, directives,
                    theme_name=theme_name,
                    coloring_images=coloring_alloc.get(id(sec), []),
                ))
            else:
                story.extend(_journal_content_pages(sec, listing, st, pal, directives,
                                                    theme_name=theme_name,
                                                    image_assets=image_assets))
            content_section_index += 1

        elif sec_type == "reference":
            niche_icon = theme_icons[content_section_index % len(theme_icons)]
            _bs = _resolve_preset(listing).get("section_banner", "framed")
            story.extend(_section_title_page(sec, pal, content_section_index, niche_icon, theme_name,
                                             banner_style=_bs))
            story.extend(_reference_pages(sec, listing, st, pal, product_type))
            content_section_index += 1

    # Auto-add closing if missing
    if not any(s.get("type") == "closing" for s in sections):
        story.extend(_closing_page(listing, st, pal, theme_name))

    doc.build(story,
              onFirstPage=first_page_cb,
              onLaterPages=later_pages_cb)

    if status_cb:
        status_cb(f"✅ PDF intérieur créé → {Path(output_path).name}")

    return output_path
