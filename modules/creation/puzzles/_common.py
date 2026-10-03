"""
Shared utilities for puzzle generators :
  - deterministic RNG seeding
  - difficulty enum
  - solutions section flowables
  - large-print mode helpers
  - shared header/footer page elements

All puzzle modules import from here to avoid duplication.
"""
import hashlib
import random
from typing import Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import inch as IN
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
)


DIFFICULTIES = ("easy", "medium", "hard", "expert")

# Difficulty curves : maps "mode" → function that returns the per-puzzle difficulty.
# Pro KDP puzzle books almost always use the "gradient" curve (easy → hard
# progression) which keeps buyers engaged page after page.

def normalize_difficulties(difficulty, n: int, base: str = "medium") -> List[str]:
    """
    Normalize a difficulty argument into a per-puzzle list of length n.
    Accepts :
      - "easy" / "medium" / "hard" / "expert"  → constant
      - "gradient" / "mixed" / "warmup"        → curve
      - list[str] of any length                → cycled to length n
    """
    if isinstance(difficulty, (list, tuple)):
        if not difficulty:
            return [base] * n
        seq = [str(d) for d in difficulty]
        if len(seq) >= n:
            return seq[:n]
        out = []
        for i in range(n):
            out.append(seq[i % len(seq)])
        return out
    if isinstance(difficulty, str):
        d = difficulty.lower().strip()
        if d in DIFFICULTIES:
            return [d] * n
        if d in ("gradient", "mixed", "warmup", "single"):
            return difficulty_curve(d, n, base=base)
    return [base] * n


def difficulty_curve(mode: str, n_puzzles: int, base: str = "medium") -> List[str]:
    """
    Returns a list of n_puzzles difficulties following the chosen curve.

    Modes :
      - "single"   : all puzzles use `base` difficulty
      - "gradient" : smooth easy → expert progression (book starts gentle,
                      ends ultra-hard — pro bestseller pattern)
      - "mixed"    : random mix from the 4 levels (variety)
      - "warmup"   : first 20% easy, then base, last 10% one tier harder
    """
    if mode == "single":
        return [base] * n_puzzles
    if mode == "gradient":
        # 25% easy → 30% medium → 30% hard → 15% expert
        e  = max(1, int(n_puzzles * 0.25))
        m  = max(1, int(n_puzzles * 0.30))
        h  = max(1, int(n_puzzles * 0.30))
        ex = n_puzzles - e - m - h
        return (["easy"] * e + ["medium"] * m + ["hard"] * h
                + ["expert"] * max(0, ex))
    if mode == "warmup":
        n_warm = max(2, int(n_puzzles * 0.20))
        n_hard = max(1, int(n_puzzles * 0.10))
        body   = n_puzzles - n_warm - n_hard
        order  = ("easy", "medium", "hard", "expert")
        bi     = order.index(base) if base in order else 1
        hard_lvl = order[min(bi + 1, len(order) - 1)]
        return (["easy"] * n_warm + [base] * body + [hard_lvl] * n_hard)
    if mode == "mixed":
        import random as _r
        seq = []
        for _ in range(n_puzzles):
            seq.append(_r.choice(DIFFICULTIES))
        return seq
    # fallback : single
    return [base] * n_puzzles


def seed_for(niche: str, volume: int, puzzle_index: int) -> int:
    """
    Deterministic seed: same (niche, volume, idx) → same puzzle every render.
    Different (niche, volume) → different puzzle set across books.
    """
    key = f"{niche}|{volume}|{puzzle_index}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def rng_for(niche: str, volume: int, puzzle_index: int) -> random.Random:
    return random.Random(seed_for(niche, volume, puzzle_index))


def is_large_print(listing: Dict) -> bool:
    """Detect whether this listing wants large-print rendering."""
    if not isinstance(listing, dict):
        return False
    if listing.get("large_print"):
        return True
    text = " ".join([
        str(listing.get("title", "")),
        str(listing.get("subtitle", "")),
        str(listing.get("niche", "")),
    ]).lower()
    markers = ("large print", "seniors", "elderly", "dementia",
               "low vision", "easy on the eyes")
    return any(m in text for m in markers)


# ── Difficulty styling per puzzle ────────────────────────────────────────────

def difficulty_label(d: str) -> str:
    """Stars only (compact). Kept for backward-compat."""
    return {"easy": "★", "medium": "★★", "hard": "★★★", "expert": "★★★★"}.get(d, d)


def difficulty_label_text(d: str) -> str:
    """Text + stars, much clearer for the reader (e.g. 'EASY ★')."""
    return {
        "easy":   "EASY ★",
        "medium": "MEDIUM ★★",
        "hard":   "HARD ★★★",
        "expert": "EXPERT ★★★★",
    }.get(d, d.upper())


# ── Page header showing puzzle number + difficulty ───────────────────────────

def puzzle_header(
    puzzle_num: int,
    total: int,
    difficulty: str,
    label: str,
    pal: Dict,
    styles: Dict,
    avail_w: float = None,
) -> List:
    """Compact header above each puzzle.

    `avail_w` = usable content width in points. When provided, the 2-column
    header is sized to fit it exactly (60% title / 40% difficulty) so it never
    overflows and clips the first letter (the old fixed 5.5in table cut the
    'M' of 'Maze' on narrow 6x9 pages).
    """
    accent = pal.get("accent", colors.HexColor("#1A252F"))
    diff_str = difficulty_label_text(difficulty)

    head_style = ParagraphStyle(
        f"PzHead{puzzle_num}",
        fontName="Helvetica-Bold", fontSize=11,
        textColor=accent, alignment=TA_LEFT, leading=13, spaceAfter=2,
    )
    right_style = ParagraphStyle(
        f"PzDiff{puzzle_num}",
        fontName="Helvetica", fontSize=10,
        textColor=accent, alignment=TA_RIGHT, leading=12,
    )
    # Default to a safe 6x9 usable width if caller didn't pass one.
    _w = avail_w if avail_w and avail_w > 0 else 4.5 * IN
    col0 = _w * 0.58
    col1 = _w * 0.42
    row = Table(
        [[Paragraph(f"{label} #{puzzle_num} <font size=9>of {total}</font>", head_style),
          Paragraph(f"<b>{diff_str}</b>", right_style)]],
        colWidths=[col0, col1],
    )
    row.setStyle(TableStyle([
        ("LINEBELOW",     (0, 0), (-1, -1), 0.6, accent),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
    ]))
    return [row, Spacer(1, 6)]


# ── Solutions section banner ─────────────────────────────────────────────────

def solutions_banner(label: str, pal: Dict, styles: Dict) -> List:
    """Title page that introduces the Solutions section at end of book."""
    title_st = ParagraphStyle(
        "SolBanner",
        fontName="Helvetica-Bold", fontSize=28,
        textColor=pal.get("accent", colors.HexColor("#1A252F")),
        alignment=TA_CENTER, leading=34, spaceAfter=14,
    )
    sub_st = ParagraphStyle(
        "SolBannerSub",
        fontName="Helvetica", fontSize=12,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER, leading=15,
    )
    return [
        Spacer(1, 2.4 * IN),
        Paragraph("SOLUTIONS", title_st),
        Paragraph(f"{label} answer key", sub_st),
        Spacer(1, 0.3 * IN),
        HRFlowable(width="40%", thickness=1.0,
                   color=pal.get("accent", colors.HexColor("#1A252F"))),
        PageBreak(),
    ]


# ── Helper to size the puzzle drawing area inside available CONTENT ─────────

def usable_grid_size(content_w: float, content_h: float,
                     header_h: float = 0.5 * IN,
                     footer_h: float = 0.4 * IN) -> Tuple[float, float]:
    """Returns (w, h) for the actual puzzle drawing region after header/footer."""
    return content_w, max(content_h - header_h - footer_h, 2.0 * IN)


# ── Page-fill value block (tip + scratch/notes area) ─────────────────────────
# Square grids (kakuro/sudoku/kenken/nonogram) only fill ~50% of a portrait
# page. We fill the rest with a "how to play" tip + a scratch/notes box, so the
# page reaches 80-90% used AND gains real buyer value (work area + guidance).

from reportlab.platypus.flowables import Flowable


_TIP_BY_LABEL = {
    "Kakuro":  "Tip: each run of white cells sums to the clue. No digit repeats inside a run.",
    "Sudoku":  "Tip: every row, column and box must contain 1-9 with no repeats.",
    "KenKen":  "Tip: fill each row & column with 1-N; each cage must hit its target with the given operation.",
    "Nonogram":"Tip: the numbers tell you the runs of filled cells in each row & column.",
}


class _ScratchBox(Flowable):
    """A light, rounded 'work area' box with a faint dotted grid + label.
    Sized to fill the leftover vertical space below a puzzle."""
    def __init__(self, width: float, height: float, label: str,
                 accent=colors.HexColor("#1A252F")):
        super().__init__()
        self.width = width
        self.height = max(height, 0.6 * IN)
        self.label = label
        self.accent = accent

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        # Outer rounded rect
        c.setStrokeColor(colors.HexColor("#999999"))
        c.setLineWidth(0.8)
        c.roundRect(0, 0, w, h, 6, stroke=1, fill=0)
        # Label tab — regular weight + darker so it RENDERS in KDP preview/print
        # (Helvetica-Oblique in light grey was invisible in the KDP previewer)
        c.setFillColor(colors.HexColor("#444444"))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(9, h - 14, self.label)
        # Faint dotted guide lines (scratch grid) — #DDDDDD prints faintly but
        # stays visible (pure #EEE washed out in KDP preview)
        c.setStrokeColor(colors.HexColor("#DDDDDD"))
        c.setLineWidth(0.5)
        c.setDash(1, 4)
        step = 0.28 * IN
        y = step
        while y < h - 16:
            c.line(8, y, w - 8, y)
            y += step
        c.setDash()


def puzzle_value_filler(content_w: float, content_h: float, used_h: float,
                        label: str, pal: Dict,
                        extra_tip: str = "") -> List:
    """
    Returns flowables to append AFTER a puzzle grid so the page fills 80-90%:
      1. a one-line solving tip (guidance = buyer value)
      2. a scratch/notes box filling the remaining vertical space

    `used_h` = height already consumed by header + grid (in points).
    Falls back gracefully (returns just a tip) when little space remains.
    """
    accent = pal.get("accent", colors.HexColor("#1A252F"))
    elems: List = []

    tip = extra_tip or _TIP_BY_LABEL.get(label, "Tip: take your time and use the work area below for notes.")
    # Regular weight + dark text so it renders in KDP preview AND prints clearly
    # (Helvetica-Oblique in light grey was invisible in the KDP previewer).
    tip_st = ParagraphStyle(
        "PzTip", fontName="Helvetica", fontSize=9.5,
        textColor=colors.HexColor("#222222"), alignment=TA_LEFT,
        leading=12, spaceBefore=10, spaceAfter=6,
    )
    # Bold the "Tip:" prefix for scannability
    tip_html = tip.replace("Tip:", "<b>Tip:</b>", 1) if tip.startswith("Tip:") else f"<b>Tip:</b> {tip}"
    elems.append(Paragraph(tip_html, tip_st))

    # Remaining space = content_h - used_h - tip(~0.35in) - small gap
    remaining = content_h - used_h - 0.55 * IN
    if remaining >= 1.0 * IN:
        elems.append(_ScratchBox(content_w, remaining, "Work area / Notes", accent))
    return elems
