"""
ReportLab renderers for high-content books (recipe_book / how_to).

Conventions match the puzzle renderers: functions take (items, listing, pal,
styles, content_w, content_h) and return a list of flowables. All text uses
solid dark colors + standard fonts (lesson learned: light-grey oblique canvas
text disappears in KDP's previewer).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import logging
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch as IN
from reportlab.platypus import (
    Flowable, HRFlowable, Image, KeepTogether, PageBreak, Paragraph, Spacer, Table,
    TableStyle,
)

logger = logging.getLogger(__name__)


def _optimized_copy(path: str, gray: bool = False, max_px: int = 1100,
                    quality: int = 82) -> Optional[str]:
    """Return a cached, print-ready JPEG copy: downscaled + compressed so the
    interior PDF / EPUB stay small (raw 1024² PNGs are ~1.8 MB each → a 75-recipe
    book would be 130-240 MB, which wrecks KDP ebook delivery fees). JPEG q82 at
    ~1100 px cuts that ~10× with no visible loss. `gray` for economical B&W print."""
    try:
        from PIL import Image as PILImage
        p = Path(path)
        suffix = ("_gray" if gray else "_rgb") + "_opt.jpg"
        out = p.with_name(p.stem + suffix)
        if not out.exists():
            im = PILImage.open(p)
            im = im.convert("L") if gray else im.convert("RGB")
            im.thumbnail((max_px, max_px))
            im.save(out, "JPEG", quality=quality, optimize=True)
        return str(out)
    except Exception as e:
        logger.debug(f"optimized copy failed: {e}")
        return path if os.path.exists(path) else None


def _item_image(path: str, content_w: float, max_h: float = 2.5 * IN,
                grayscale: bool = True) -> Optional[Image]:
    """A width-constrained, COMPRESSED interior image flowable. Grayscale for an
    economical B&W print, color otherwise. Returns None if missing/unreadable."""
    if not path or not os.path.exists(path):
        return None
    src = _optimized_copy(path, gray=grayscale)
    if not src:
        return None
    try:
        from PIL import Image as PILImage
        iw, ih = PILImage.open(src).size
        ratio = ih / iw if iw else 0.66
        w = content_w
        h = w * ratio
        if h > max_h:
            h = max_h
            w = h / ratio
        img = Image(src, width=w, height=h)
        img.hAlign = "CENTER"
        return img
    except Exception as e:
        logger.debug(f"item image flowable failed: {e}")
        return None

_DARK = colors.HexColor("#1A252F")
_BODY = colors.HexColor("#222222")
_MUTE = colors.HexColor("#555555")
_TIP_BG = colors.HexColor("#F4F1E8")
_BADGE_BG = colors.HexColor("#EFEFEA")

# ── Kids / facts book styling ────────────────────────────────────────────────
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_KID_FONT = "Helvetica-Bold"
for _p in ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
           "/System/Library/Fonts/Supplemental/Chalkboard.ttc"):
    try:
        pdfmetrics.registerFont(TTFont("KidRound", _p))
        _KID_FONT = "KidRound"
        break
    except Exception:
        continue

# Bright-but-soft card colors + matching bold number-badge colors (rotated).
_KID_CARDS = [
    ("#FFF6C9", "#F2B705"),  # sunny yellow
    ("#D8EEFF", "#2E86DE"),  # sky blue
    ("#FFE1EA", "#EB5286"),  # bubblegum pink
    ("#DCF5D6", "#3FA34D"),  # leaf green
    ("#ECE0FF", "#8E5AE0"),  # grape purple
    ("#FFE6CC", "#F2792E"),  # tangerine
]
_KID_INK = colors.HexColor("#243447")


def _kids_fact_card(num: int, text: str, card_w: float, idx: int):
    """A colorful rounded fun-fact card: number badge + big friendly text."""
    bg, badge = _KID_CARDS[idx % len(_KID_CARDS)]
    num_st = ParagraphStyle("KidNum", fontName=_KID_FONT, fontSize=17,
                            textColor=colors.white, alignment=TA_CENTER, leading=19)
    fact_st = ParagraphStyle("KidFact", fontName="Helvetica", fontSize=13.5,
                             textColor=_KID_INK, leading=19)
    badge_cell = Table([[Paragraph(str(num), num_st)]], colWidths=[34], rowHeights=[34])
    badge_cell.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(badge)),
        ("ROUNDEDCORNERS", [17, 17, 17, 17]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    card = Table([[badge_cell, Paragraph(text, fact_st)]],
                 colWidths=[46, card_w - 46])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("ROUNDEDCORNERS", [14, 14, 14, 14]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return card


# ── Niche-adaptive design (subject-driven colors + display font + motif) ──────
# Each detected theme gets a curated, PRO interior identity: an accent colour
# that fits the subject, a readable-but-characterful title font, and a motif.
# This is what makes a resin-art guide look like a resin-art book (ocean teal),
# a fitness book bold red, a gardening book green — automatically, per niche.
_DISPLAY_FONT_FILES = {
    "GeorgiaBold":  "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "Baskerville":  "/System/Library/Fonts/Supplemental/Baskerville.ttc",
    "ArialBold":    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "RockwellBold": "/System/Library/Fonts/Supplemental/Rockwell.ttc",
    "TrebuchetBold":"/System/Library/Fonts/Supplemental/Trebuchet MS Bold.ttf",
    "DINCond":      "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
}
_REG_DISPLAY: Dict[str, str] = {}


def _reg_display(name: str, fallback: str = "Helvetica-Bold") -> str:
    """Register (once) a curated display font; fall back to a safe font."""
    if name in _REG_DISPLAY:
        return _REG_DISPLAY[name]
    path = _DISPLAY_FONT_FILES.get(name, "")
    try:
        pdfmetrics.registerFont(TTFont(name, path))
        _REG_DISPLAY[name] = name
    except Exception:
        _REG_DISPLAY[name] = fallback
    return _REG_DISPLAY[name]


# theme (from detect_theme) → curated interior identity.
#   accent  : primary subject colour  ·  light : soft tint for tip boxes
#   motif   : niche glyph  ·  palette : harmonised family that ROTATES per chapter
# The per-chapter palette keeps every chapter in the subject's colour world
# (resin/craft → ocean-teals, fitness → reds/charcoal, nature → greens…).
_THEME_DESIGN = {
    "craft":    {"accent": "#0E7C7B", "light": "#E7F3F2", "motif": "❈",
                 "palette": ["#0E6E6E", "#146C8E", "#2A7F62", "#3E5C76", "#1D7A7A", "#2E6E8E"]},
    "nature":   {"accent": "#2D6A4F", "light": "#EAF3EE", "motif": "❋",
                 "palette": ["#2D6A4F", "#40916C", "#5E7E3E", "#3A7D44", "#557A46", "#4E8069"]},
    "ocean":    {"accent": "#146C8E", "light": "#E7F2F6", "motif": "≈",
                 "palette": ["#146C8E", "#1B7FA8", "#2A9D8F", "#3E6E8E", "#1D6E7E", "#2E8EA4"]},
    "food":     {"accent": "#B23A2E", "light": "#F7ECE6", "motif": "❀",
                 "palette": ["#B23A2E", "#C05640", "#B5652E", "#A6432E", "#8E3B2E", "#C79A3B"]},
    "fitness":  {"accent": "#C0392B", "light": "#F4EAE8", "motif": "★",
                 "palette": ["#C0392B", "#2C3E50", "#A63A2E", "#8E2E2E", "#3E4A5C", "#B5482E"]},
    "wellness": {"accent": "#4E8069", "light": "#ECF3EF", "motif": "❁",
                 "palette": ["#4E8069", "#5B8A72", "#6A9C86", "#3E7A64", "#5E8E7A", "#4A7C8E"]},
    "vintage":  {"accent": "#7B5E3B", "light": "#F4EFE4", "motif": "❧",
                 "palette": ["#7B5E3B", "#8E6E4A", "#A0522D", "#6E4E2E", "#9C7A4A", "#7A5E3E"]},
    "stars":    {"accent": "#3B3A6B", "light": "#ECEBF6", "motif": "✦",
                 "palette": ["#3B3A6B", "#5E4E8A", "#7A4E8E", "#4A4063", "#6A5AA0", "#5A4E7C"]},
    "geometry": {"accent": "#2C3E50", "light": "#EAEEF2", "motif": "◆",
                 "palette": ["#2C3E50", "#1F4E79", "#3E5C76", "#2A5D8E", "#34495E", "#3A6A9C"]},
    "business": {"accent": "#1F4E79", "light": "#E9F0F7", "motif": "◆",
                 "palette": ["#1F4E79", "#2C3E50", "#3E5C76", "#2A5D8E", "#34495E", "#26619C"]},
    "music":    {"accent": "#7A2E8E", "light": "#F1E9F3", "motif": "♫",
                 "palette": ["#7A2E8E", "#5E4E8A", "#8E3B6E", "#4A4063", "#9C3A7A", "#6A5AA0"]},
    "animals":  {"accent": "#A0522D", "light": "#F4ECE4", "motif": "✦",
                 "palette": ["#A0522D", "#8E6E4A", "#7B5E3B", "#9C6E3A", "#6E5E3E", "#A67A4A"]},
    "religion": {"accent": "#7B3F2E", "light": "#F4ECE2", "motif": "†",
                 "palette": ["#7B3F2E", "#9C6B3A", "#5A3A2E", "#8E5A2E", "#6E4A3A", "#A67A4A"]},
    "education":{"accent": "#1F5C8B", "light": "#E9F1F7", "motif": "◆",
                 "palette": ["#1F5C8B", "#2A7FB0", "#2C3E50", "#3E6E8E", "#1D6E7E", "#2E8EA4"]},
    "stories":  {"accent": "#4A3B2E", "light": "#F3EDE2", "motif": "✦",
                 "palette": ["#4A3B2E", "#7B5E3B", "#3E4A5C", "#6E4A3A", "#5A4E3E", "#8E6E4A"]},
    "default":  {"accent": "#1A3A5C", "light": "#EAEFF4", "motif": "✦",
                 "palette": ["#1A3A5C", "#1F4E79", "#2C3E50", "#3E5C76", "#2A5D8E", "#34495E"]},
}


# Unicode-capable symbol font for religious / special glyphs (reportlab's built-in
# Helvetica has no ☪ ✡ ☸ ॐ) — registered once, used to draw the motif only.
_UNI_SYM = None
for _usp in ("/Library/Fonts/Arial Unicode.ttf",
             "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
             "/System/Library/Fonts/Apple Symbols.ttf",
             "/System/Library/Fonts/Supplemental/Arial.ttf"):
    try:
        pdfmetrics.registerFont(TTFont("UniSym", _usp))
        _UNI_SYM = "UniSym"
        break
    except Exception:
        continue


def _religion_symbol(niche: str) -> str:
    """Pick the symbol of the ACTUAL religion treated (not a default cross)."""
    nl = (niche or "").lower()
    if any(w in nl for w in ("islam", "muslim", "quran", "qur'an", "allah",
                             "ramadan", "hadith", "sunnah")):
        return "☪"
    if any(w in nl for w in ("judaism", "jewish", "torah", "hebrew", "kabbalah",
                             "shabbat", "synagogue", "rabbi")):
        return "✡"
    if any(w in nl for w in ("buddhis", "zen", "dharma", "nirvana")):
        return "☸"
    if any(w in nl for w in ("hindu", "vedic", "bhagavad", "sanskrit")):
        return "ॐ"
    if any(w in nl for w in ("bible", "christ", "jesus", "gospel", "catholic",
                             "psalm", "christian")):
        return "†"
    return "✦"   # generic spirituality (no explicit religion → neutral)


def _niche_design(listing: Dict) -> Dict:
    """Resolve the subject → a curated PRO interior identity (colors/font/motif)."""
    niche = listing.get("niche", "") or ""
    try:
        from modules.creation.niche_themes import detect_theme
        theme = detect_theme(niche).get("name", "default")
    except Exception:
        theme = "default"
    d = _THEME_DESIGN.get(theme, _THEME_DESIGN["default"])
    if theme == "religion":
        d = {**d, "motif": _religion_symbol(niche)}   # adaptive religious symbol
    return {
        "theme":       theme,
        "accent":      colors.HexColor(d["accent"]),
        "light":       colors.HexColor(d["light"]),
        "motif":       d["motif"],
        "palette":     [colors.HexColor(h) for h in d["palette"]],
        "title_font":  _reg_display("ArialBold"),          # bold modern banner title
        "num_font":    _reg_display("DINCond", "Helvetica-Bold"),  # oversized number
    }


def _tint(color, amount: float = 0.90):
    """Return a very light tint of a color (mix toward white by `amount`)."""
    r, g, b = color.red, color.green, color.blue
    return colors.Color(r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)


class _ChapterOpener(Flowable):
    """PRO 'bold modern' chapter opener: a full-width coloured block with a
    motif + CHAPTER N eyebrow, a big sans-serif title, and an oversized ghost
    number. The colour is per-chapter (niche-harmonised rotation)."""

    def __init__(self, num: int, title: str, content_w: float, color,
                 title_font: str, num_font: str, motif: str,
                 eyebrow: Optional[str] = None):
        Flowable.__init__(self)
        self.num = num
        self.eyebrow = eyebrow
        self.title = str(title or "")
        self.cw = content_w
        self.color = color
        self.tfont = title_font
        self.nfont = num_font
        self.motif = motif
        self._size = 19
        self._lines: List[str] = []
        self._h = 0

    def _wrap_title(self, width):
        maxw = width * 0.72                       # leave room for the ghost number
        words, lines, cur = self.title.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if pdfmetrics.stringWidth(t, self.tfont, self._size) <= maxw or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        return lines or [self.title]

    def wrap(self, avail_w, avail_h):
        self.cw = avail_w
        self._lines = self._wrap_title(avail_w)
        lh = self._size + 5
        self._h = max(40 + len(self._lines) * lh + 16, 1.35 * IN)
        return (avail_w, self._h)

    def draw(self):
        c = self.canv
        h, cw = self._h, self.cw
        c.setFillColor(self.color)
        c.rect(0, 0, cw, h, fill=1, stroke=0)
        # oversized semi-transparent ghost number, bottom-right
        c.setFillColor(colors.Color(1, 1, 1, 0.18))
        c.setFont(self.nfont, 86)
        c.drawRightString(cw - 14, 12, f"{self.num:02d}")
        # eyebrow — draw the motif with a Unicode font (so ☪ ✡ ☸ render), then text
        c.setFillColor(colors.white)
        eye = self.eyebrow or f"CHAPTER {self.num}"
        if _UNI_SYM and self.motif:
            c.setFont(_UNI_SYM, 8.5)
            c.drawString(16, h - 20, self.motif)
            mw = c.stringWidth(self.motif, _UNI_SYM, 8.5)
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(16 + mw + 6, h - 20, eye)
        else:
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(16, h - 20, f"{self.motif}  {eye}")
        # title
        c.setFont(self.tfont, self._size)
        lh = self._size + 5
        y = h - 42
        for ln in self._lines:
            c.drawString(16, y, ln)
            y -= lh


def _chapter_opener(num, title, content_w, design, color, eyebrow=None):
    return _ChapterOpener(num, title, content_w, color,
                          design["title_font"], design["num_font"], design["motif"],
                          eyebrow=eyebrow)


def _st(pal: Dict, design: Optional[Dict] = None):
    accent = design["accent"] if design else pal.get("accent", _DARK)
    tfont = design["title_font"] if design else "Helvetica-Bold"
    return {
        "title": ParagraphStyle("HCTitle", fontName=tfont, fontSize=17,
                                textColor=accent, leading=21, spaceAfter=4),
        "intro": ParagraphStyle("HCIntro", fontName="Helvetica", fontSize=10.5,
                                textColor=_MUTE, leading=14, spaceAfter=8),
        "h2": ParagraphStyle("HCH2", fontName=tfont, fontSize=12.5,
                             textColor=accent, leading=16, spaceBefore=11, spaceAfter=4),
        "body": ParagraphStyle("HCBody", fontName="Helvetica", fontSize=10.5,
                               textColor=_BODY, leading=15, spaceAfter=6),
        "ing": ParagraphStyle("HCIng", fontName="Helvetica", fontSize=10,
                              textColor=_BODY, leading=14, spaceAfter=3),
        "step": ParagraphStyle("HCStep", fontName="Helvetica", fontSize=10.5,
                               textColor=_BODY, leading=15, spaceAfter=5),
        "tip": ParagraphStyle("HCTip", fontName="Helvetica", fontSize=9.5,
                              textColor=_BODY, leading=13),
        "badge": ParagraphStyle("HCBadge", fontName="Helvetica-Bold", fontSize=9,
                                textColor=_DARK, alignment=TA_CENTER, leading=11),
        "badge_lab": ParagraphStyle("HCBadgeL", fontName="Helvetica", fontSize=7.5,
                                    textColor=_MUTE, alignment=TA_CENTER, leading=9),
        "nut_val": ParagraphStyle("HCNutV", fontName="Helvetica-Bold", fontSize=10,
                                  textColor=_DARK, alignment=TA_CENTER, leading=12),
        "nut_lab": ParagraphStyle("HCNutL", fontName="Helvetica", fontSize=7,
                                  textColor=_MUTE, alignment=TA_CENTER, leading=9),
        "fact": ParagraphStyle("HCFact", fontName="Helvetica", fontSize=11,
                               textColor=_BODY, leading=16, spaceAfter=7,
                               leftIndent=14, firstLineIndent=-14),
    }


def _tip_box(text: str, content_w: float, st, design: Optional[Dict] = None) -> Table:
    # strip a leading "Pro tip:" the model sometimes includes → avoid duplication
    _t = re.sub(r"^\s*pro\s*tip\s*:?\s*", "", str(text), flags=re.IGNORECASE)
    inner = Paragraph(f"<b>Pro tip:</b> {_t}", st["tip"])
    bg = design["light"] if design else _TIP_BG
    bar = design["accent"] if design else colors.HexColor("#D8D2C0")
    t = Table([[inner]], colWidths=[content_w])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("BOX",           (0, 0), (-1, -1), 0.7, colors.HexColor("#D8D2C0")),
        ("LINEBEFORE",    (0, 0), (0, -1), 3.5, bar),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _nutrition_panel(nut: Dict, content_w: float, st, accent) -> Table:
    """Per-serving nutrition strip. The niche's KEY nutrient cell is highlighted
    in the accent color — it's the whole promise of the niche."""
    def _v(x, suf=""):
        if x in (None, "", "—"):
            return "—"
        return f"{x}{suf}"
    cells_data = [
        (_v(nut.get("calories")), "CALORIES"),
        (_v(nut.get("protein_g"), "g"), "PROTEIN"),
        (_v(nut.get("carbs_g"), "g"), "CARBS"),
        (_v(nut.get("fat_g"), "g"), "FAT"),
    ]
    key_lab = str(nut.get("key_nutrient_label") or "").upper()
    key_val = str(nut.get("key_nutrient_value") or "")
    has_key = bool(key_lab and key_val)
    if has_key:
        cells_data.append((key_val, key_lab))
    ncol = len(cells_data)
    vals = [Paragraph(v, st["nut_val"]) for v, _ in cells_data]
    labs = [Paragraph(l, st["nut_lab"]) for _, l in cells_data]
    t = Table([vals, labs], colWidths=[content_w / ncol] * ncol)
    style = [
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#F3F6F4")),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CFD8D2")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.4, colors.HexColor("#E0E6E2")),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING",    (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
    ]
    if has_key:  # highlight the key-nutrient column
        style += [
            ("BACKGROUND", (ncol - 1, 0), (ncol - 1, -1), accent),
            ("TEXTCOLOR",  (ncol - 1, 0), (ncol - 1, -1), colors.white),
        ]
    t.setStyle(TableStyle(style))
    return t


def _checkbox_row(text: str, col_w: float, st) -> Table:
    """A real empty checkbox (drawn as a bordered mini-cell) + item text — the
    standard-14 PDF fonts have no ballot-box glyph, so we draw one."""
    box = Table([[""]], colWidths=[9], rowHeights=[9])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#7A7A72")),
    ]))
    row = Table([[box, Paragraph(text, st["ing"])]], colWidths=[16, col_w - 16])
    row.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (0, 0), 0),
        ("LEFTPADDING",   (1, 0), (1, 0), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return row


def _section_banner(text: str, content_w: float, accent) -> Table:
    """A solid accent bar used to open bonus / facts sections — pro look."""
    p = ParagraphStyle("HCBanner", fontName="Helvetica-Bold", fontSize=13,
                       textColor=colors.white, leading=16, alignment=TA_LEFT)
    t = Table([[Paragraph(text, p)]], colWidths=[content_w])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), accent),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _cookbook_design(listing: Dict) -> Dict:
    """Niche design for cookbooks — warm/food default instead of neutral navy."""
    design = _niche_design(listing)
    if design["theme"] == "default":
        _f = _THEME_DESIGN["food"]
        design = {**design, "theme": "food",
                  "accent": colors.HexColor(_f["accent"]),
                  "light": colors.HexColor(_f["light"]),
                  "palette": [colors.HexColor(h) for h in _f["palette"]],
                  "motif": _f["motif"]}
    return design


def render_technique_section(diagrams: List[Dict], listing: Dict, pal: Dict,
                             styles: Dict, content_w: float, content_h: float) -> List:
    """A 'Techniques & How-To' reference section (cookbooks): a banner followed by
    the code-drawn infographics / illustration. Rendered between bonus & recipes."""
    if not diagrams:
        return []
    design = _cookbook_design(listing)
    st = _st(pal, design)
    accent = design["accent"]
    elems: List = [_section_banner("Techniques & How-To", content_w, accent),
                   Spacer(1, 10)]
    for spec in diagrams:
        dia = _render_diagram(spec, content_w, design, st, listing)
        if dia is not None:
            elems.append(dia)
            elems.append(Spacer(1, 10))
    elems.append(PageBreak())
    return elems


# ── RECIPES ──────────────────────────────────────────────────────────────────
def render_recipe_pages(recipes: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                        content_w: float, content_h: float) -> List:
    design = _cookbook_design(listing)  # warm/food default for cookbooks
    st = _st(pal, design)
    accent = design["accent"]           # single niche accent (no per-recipe churn)
    elems: List = []

    for i, r in enumerate(recipes, 1):
        block: List = []
        # Style-4 coloured recipe header (niche accent), eyebrow = RECIPE i · CAT
        cat = str(r.get("category", "")).strip()
        head_lbl = f"RECIPE {i} OF {len(recipes)}"
        if cat:
            head_lbl += f"  ·  {cat.upper()}"
        block.append(_chapter_opener(i, str(r.get("title", "")), content_w,
                                     design, accent, eyebrow=head_lbl))
        block.append(Spacer(1, 8))
        # Dish photo right under the title. Color unless the listing opts into a
        # grayscale (cheaper-to-print) interior.
        _gray = not listing.get("color_interior", True)
        img = _item_image(r.get("_image", ""), content_w, grayscale=_gray)
        if img is not None:
            block.append(img)
            block.append(Spacer(1, 6))
        if r.get("intro"):
            block.append(Paragraph(str(r["intro"]), st["intro"]))

        # Badge row: servings / prep / cook / difficulty
        badges = [
            (str(r.get("servings", "—")), "SERVINGS"),
            (str(r.get("prep_time", "—")), "PREP"),
            (str(r.get("cook_time", "—")), "COOK"),
            (str(r.get("difficulty", "Easy")), "LEVEL"),
        ]
        cells = [[Paragraph(v, st["badge"]) for v, _ in badges],
                 [Paragraph(l, st["badge_lab"]) for _, l in badges]]
        bt = Table(cells, colWidths=[content_w / 4] * 4)
        bt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), _BADGE_BG),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("INNERGRID",     (0, 0), (-1, 0), 0.5, colors.HexColor("#DDDDDD")),
            ("TOPPADDING",    (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
            ("TOPPADDING",    (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ]))
        block.append(bt)
        # Nutrition strip (per serving) — the niche's key nutrient is highlighted.
        nut = r.get("nutrition") or {}
        if any(nut.get(k) not in (None, "", "—") for k in
               ("calories", "protein_g", "carbs_g", "fat_g", "key_nutrient_value")):
            block.append(Spacer(1, 5))
            block.append(_nutrition_panel(nut, content_w, st, accent))
            block.append(Paragraph("Per serving (approx.)", st["badge_lab"]))
        block.append(Spacer(1, 10))
        elems.append(KeepTogether(block))

        # Ingredients: compact boxed panel with 2 internal columns (short, fits
        # anywhere). Steps: full-width flowables that split across pages —
        # a single 2-column Table can't split and pushed everything to page 2.
        ings = [str(x) for x in (r.get("ingredients") or [])]
        half = (len(ings) + 1) // 2
        left_col = [Paragraph(f"• {x}", st["ing"]) for x in ings[:half]]
        right_col = [Paragraph(f"• {x}", st["ing"]) for x in ings[half:]]
        ing_tbl = Table([[left_col, right_col]],
                        colWidths=[content_w / 2 - 8, content_w / 2 - 8])
        ing_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND",    (0, 0), (-1, -1), _BADGE_BG),
            ("BOX",           (0, 0), (-1, -1), 0.6, colors.HexColor("#D5D5CD")),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elems.append(KeepTogether([Paragraph("INGREDIENTS", st["h2"]), ing_tbl]))
        elems.append(Spacer(1, 8))

        elems.append(Paragraph("INSTRUCTIONS", st["h2"]))
        for k, step in enumerate(r.get("steps") or [], 1):
            elems.append(Paragraph(f"<b>{k}.</b> {step}", st["step"]))

        if r.get("tip"):
            elems.append(Spacer(1, 10))
            elems.append(_tip_box(str(r["tip"]), content_w, st, design))
        elems.append(PageBreak())
    return elems


# ── GUIDE (how_to) ───────────────────────────────────────────────────────────
def _render_diagram(spec: Dict, content_w: float, design: Dict, st, listing: Dict):
    """Render one diagram spec: a code-drawn infographic, OR (type=illustration)
    an AI image with a caption. Returns a flowable/KeepTogether or None."""
    t = str(spec.get("type", "")).lower().strip()
    if t == "illustration" and spec.get("_image"):
        _gray = not listing.get("color_interior", True)
        img = _item_image(spec["_image"], content_w, max_h=3.4 * IN, grayscale=_gray)
        if img is None:
            return None
        cap_st = ParagraphStyle("HCDiaCap", fontName="Helvetica-Oblique", fontSize=9,
                                textColor=_MUTE, leading=12, alignment=TA_CENTER,
                                spaceBefore=3)
        title = str(spec.get("title") or "")
        cap = str(spec.get("caption") or "")
        block = [img]
        if title:
            block.append(Paragraph(f"<b>{title}.</b> {cap}" if cap else f"<b>{title}</b>",
                                   cap_st))
        return KeepTogether(block)
    # code-drawn infographic
    try:
        from modules.creation.highcontent.infographic import build_infographic
        return build_infographic(spec, content_w, design)
    except Exception:
        return None


def render_guide_pages(guide: Dict, listing: Dict, pal: Dict, styles: Dict,
                       content_w: float, content_h: float) -> List:
    design = _niche_design(listing)
    st = _st(pal, design)
    palette = design["palette"]
    elems: List = []
    chapters = guide.get("chapters") or []
    # explanatory diagrams (code-drawn infographics), grouped by chapter index
    diagrams = listing.get("_diagrams") or guide.get("diagrams") or []
    _by_chapter: Dict[int, List] = {}
    for _spec in diagrams:
        try:
            _by_chapter.setdefault(int(_spec.get("chapter", 0)), []).append(_spec)
        except Exception:
            continue

    for i, c in enumerate(chapters, 1):
        # per-chapter colour, rotating within the niche-harmonised family
        ch_color = palette[(i - 1) % len(palette)]
        ch_design = {**design, "accent": ch_color, "light": _tint(ch_color)}
        # section heading tinted to this chapter's colour (clean bold sans)
        h2 = ParagraphStyle(f"HCH2_{i}", fontName="Helvetica-Bold", fontSize=12.5,
                            textColor=ch_color, leading=16, spaceBefore=11, spaceAfter=4)

        head: List = []
        head.append(_chapter_opener(i, str(c.get("title", "")), content_w,
                                    design, ch_color))
        head.append(Spacer(1, 10))
        if c.get("intro"):
            head.append(Paragraph(str(c["intro"]), st["intro"]))
        _gray = not listing.get("color_interior", True)
        img = _item_image(c.get("_image", ""), content_w, max_h=3.5 * IN, grayscale=_gray)
        if img is not None:
            head.append(img)
            head.append(Spacer(1, 6))
        elems.append(KeepTogether(head))

        for sec in (c.get("sections") or []):
            sec_block: List = []
            if sec.get("heading"):
                sec_block.append(Paragraph(str(sec["heading"]), h2))
            if sec.get("body"):
                sec_block.append(Paragraph(str(sec["body"]), st["body"]))
            elems.append(KeepTogether(sec_block[:2]) if len(sec_block) <= 2 else sec_block)
            for k, step in enumerate(sec.get("steps") or [], 1):
                elems.append(Paragraph(f"<b>Step {k}.</b> {step}", st["step"]))

        if c.get("tip"):
            elems.append(Spacer(1, 8))
            elems.append(_tip_box(str(c["tip"]), content_w, st, ch_design))

        # explanatory diagrams for this chapter (infographic or AI illustration)
        for spec in _by_chapter.get(i, []):
            _dia = _render_diagram(spec, content_w, ch_design, st, listing)
            if _dia is not None:
                elems.append(Spacer(1, 10))
                elems.append(_dia)

        elems.append(PageBreak())
    return elems


# ── ANECDOTES / short true stories (adult, captivating) ──────────────────────
def render_anecdotes_pages(anecdotes: Dict, listing: Dict, pal: Dict, styles: Dict,
                           content_w: float, content_h: float) -> List:
    """Adult anecdote collection: coloured Style-4 part openers + elegant story
    cards (intriguing title + short true story), niche-coloured per part."""
    design = _niche_design(listing)
    st = _st(pal, design)
    palette = design["palette"]
    elems: List = []
    for i, sec in enumerate(anecdotes.get("sections", []) or [], 1):
        col = palette[(i - 1) % len(palette)]
        elems.append(_chapter_opener(i, str(sec.get("title", "")), content_w,
                                     design, col, eyebrow=f"PART {i}"))
        elems.append(Spacer(1, 10))
        h_st = ParagraphStyle(f"AnTitle{i}", fontName=design["title_font"], fontSize=12.5,
                              textColor=col, leading=16, spaceBefore=10, spaceAfter=3)
        for an in (sec.get("anecdotes") or []):
            title = str(an.get("title", "")).strip()
            story = str(an.get("story", "")).strip()
            if not story:
                continue
            block: List = []
            if title:
                block.append(Paragraph(title, h_st))
            block.append(Paragraph(story, st["body"]))
            elems.append(KeepTogether(block) if len(block) <= 2 else block)
        elems.append(PageBreak())
    return elems


# ── BONUS front-matter (recipe books) ────────────────────────────────────────
def render_bonus_pages(bonus: Dict, listing: Dict, pal: Dict, styles: Dict,
                       content_w: float, content_h: float) -> List:
    """Intro + foods to favor/limit + 7-day meal plan + categorized shopping
    list. Rendered BEFORE the recipes as a professional 'quick start'."""
    st = _st(pal)
    accent = pal.get("accent", _DARK)
    elems: List = []
    if not bonus:
        return elems

    # 1. Intro
    if bonus.get("intro_paragraphs"):
        elems.append(_section_banner(
            str(bonus.get("intro_title") or "Quick Start Guide"), content_w, accent))
        elems.append(Spacer(1, 8))
        for para in bonus.get("intro_paragraphs") or []:
            elems.append(Paragraph(str(para), st["body"]))

    # 2. Eat more / eat less two-column panel
    eat_more = [str(x) for x in (bonus.get("eat_more") or [])]
    eat_less = [str(x) for x in (bonus.get("eat_less") or [])]
    if eat_more or eat_less:
        elems.append(Spacer(1, 8))
        left = [Paragraph("<b>✓ Enjoy freely</b>", st["body"])] + \
               [Paragraph(f"• {x}", st["ing"]) for x in eat_more]
        right = [Paragraph("<b>✕ Limit / avoid</b>", st["body"])] + \
                [Paragraph(f"• {x}", st["ing"]) for x in eat_less]
        panel = Table([[left, right]],
                      colWidths=[content_w / 2 - 6, content_w / 2 - 6])
        panel.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND",    (0, 0), (0, -1), colors.HexColor("#F0F6F0")),
            ("BACKGROUND",    (1, 0), (1, -1), colors.HexColor("#FBF1F1")),
            ("BOX",           (0, 0), (-1, -1), 0.6, colors.HexColor("#D5D5CD")),
            ("INNERGRID",     (0, 0), (-1, -1), 0.6, colors.HexColor("#D5D5CD")),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elems.append(panel)
    # Only break to a fresh page if the intro/eat section actually rendered —
    # otherwise we'd emit a blank leading page.
    if elems:
        elems.append(PageBreak())

    # 3. 7-day meal plan table
    plan = bonus.get("meal_plan") or []
    if plan:
        elems.append(_section_banner("Your 7-Day Meal Plan", content_w, accent))
        elems.append(Spacer(1, 8))
        hdr = ["Day", "Breakfast", "Lunch", "Dinner", "Snack"]
        cell = ParagraphStyle("HCPlan", fontName="Helvetica", fontSize=8.5,
                              textColor=_BODY, leading=11)
        hcell = ParagraphStyle("HCPlanH", fontName="Helvetica-Bold", fontSize=8.5,
                               textColor=colors.white, leading=11)
        rows = [[Paragraph(h, hcell) for h in hdr]]
        for d in plan:
            rows.append([
                Paragraph(f"<b>{d.get('day','')}</b>", cell),
                Paragraph(str(d.get("breakfast", "")), cell),
                Paragraph(str(d.get("lunch", "")), cell),
                Paragraph(str(d.get("dinner", "")), cell),
                Paragraph(str(d.get("snack", "")), cell),
            ])
        cw = content_w
        plan_tbl = Table(rows, colWidths=[cw*0.10, cw*0.225, cw*0.225, cw*0.225, cw*0.225])
        plan_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), accent),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F0")]),
            ("GRID",         (0, 0), (-1, -1), 0.4, colors.HexColor("#D5D5CD")),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ]))
        elems.append(plan_tbl)
        elems.append(PageBreak())

    # 4. Categorized shopping list
    shop = bonus.get("shopping_list") or []
    if shop:
        elems.append(_section_banner("Shopping List", content_w, accent))
        elems.append(Spacer(1, 8))
        blocks = []
        for grp in shop:
            col = [Paragraph(str(grp.get("category", "")).upper(), st["h2"])]
            for it in (grp.get("items") or []):
                col.append(_checkbox_row(str(it), content_w / 2 - 6, st))
            blocks.append(col)
        # 2 columns of category blocks
        for j in range(0, len(blocks), 2):
            pair = blocks[j:j + 2]
            if len(pair) == 1:
                pair.append([])
            row = Table([[pair[0], pair[1]]],
                        colWidths=[content_w / 2 - 6, content_w / 2 - 6])
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            elems.append(row)
            elems.append(Spacer(1, 4))
        elems.append(PageBreak())
    return elems


# ── FACTS book ───────────────────────────────────────────────────────────────
def render_facts_pages(facts: Dict, listing: Dict, pal: Dict, styles: Dict,
                       content_w: float, content_h: float) -> List:
    """KIDS-STYLE fun-facts layout: an illustrated section opener + big colorful
    fun-fact cards (one fact per card, friendly large type). Designed to read like
    a real children's book and to breathe across the page."""
    elems: List = []
    _gray = not listing.get("color_interior", True)
    sections = facts.get("sections") or []

    # Rotating section-opener band colors (kid palette).
    opener_st = ParagraphStyle("KidOpen", fontName=_KID_FONT, fontSize=22,
                               textColor=colors.white, alignment=TA_CENTER, leading=26)
    num_st = ParagraphStyle("KidOpenN", fontName=_KID_FONT, fontSize=12,
                            textColor=colors.white, alignment=TA_CENTER, leading=14)
    intro_st = ParagraphStyle("KidIntro", fontName="Helvetica-Oblique", fontSize=12,
                              textColor=_KID_INK, alignment=TA_CENTER, leading=16)

    for i, sec in enumerate(sections, 1):
        band_bg = _KID_CARDS[(i - 1) % len(_KID_CARDS)][1]
        # ── Section opener: colored title band + big illustration ──────────
        opener: List = []
        band = Table([[Paragraph(f"CHAPTER {i}", num_st)],
                      [Paragraph(str(sec.get("title", "")).upper(), opener_st)]],
                     colWidths=[content_w])
        band.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(band_bg)),
            ("ROUNDEDCORNERS", [18, 18, 18, 18]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 14),
            ("TOPPADDING", (0, 1), (-1, 1), 2),
        ]))
        opener.append(band)
        opener.append(Spacer(1, 12))
        img = _item_image(sec.get("_image", ""), content_w, max_h=4.2 * IN, grayscale=_gray)
        if img is not None:
            opener.append(img)
        opener.append(Spacer(1, 10))
        opener.append(Paragraph("Get ready for some amazing facts!", intro_st))
        opener.append(Spacer(1, 14))
        elems.append(KeepTogether(opener))

        # ── Fun-fact cards ────────────────────────────────────────────────
        for k, fact in enumerate(sec.get("facts") or [], 1):
            elems.append(_kids_fact_card(k, str(fact), content_w, k - 1))
            elems.append(Spacer(1, 9))
        elems.append(PageBreak())
    return elems
