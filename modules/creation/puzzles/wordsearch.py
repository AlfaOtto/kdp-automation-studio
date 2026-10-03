"""
Word Search generator.
Words placed in 8 directions (incl. reverse) in a square grid.
Words come from Claude (themed per niche) or from a fallback bank.
Difficulty: easy=12×12 / 10 words, medium=15×15 / 14, hard=18×18 / 18, expert=22×22 / 24.
"""
from typing import Dict, List, Tuple, Optional
import logging
import string

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus import Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.platypus.flowables import Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from ._common import rng_for, puzzle_header, normalize_difficulties, solutions_banner, is_large_print, puzzle_value_filler

logger = logging.getLogger(__name__)


DIFFICULTY_PARAMS = {
    "easy":   {"size": 12, "n_words": 10, "directions": 4},   # horiz + vert only, no reverse
    "medium": {"size": 15, "n_words": 14, "directions": 8},   # all 8 + reverse
    "hard":   {"size": 18, "n_words": 18, "directions": 8},
    "expert": {"size": 22, "n_words": 24, "directions": 8},
}

# 8 direction vectors (dy, dx)
DIRS_8 = [(0, 1), (0, -1), (1, 0), (-1, 0),
          (1, 1), (-1, -1), (1, -1), (-1, 1)]
DIRS_4 = [(0, 1), (1, 0)]  # easy: no reverse


# ── Word bank fallback (used if Claude not available) ───────────────────────
_FALLBACK_BANK = [
    "FOREST", "RIVER", "MOUNTAIN", "VALLEY", "OCEAN", "DESERT", "CANYON",
    "MEADOW", "GLACIER", "ISLAND", "VOLCANO", "WATERFALL", "PRAIRIE", "JUNGLE",
    "TUNDRA", "REEF", "PLATEAU", "LAGOON", "FJORD", "ESTUARY", "DELTA",
    "PENINSULA", "ARCHIPELAGO", "STEPPE", "SAVANNA",
]


def _claude_word_bank(theme: str, n: int, anthropic_key: str) -> List[str]:
    """Ask Claude for a themed word list. Returns uppercase, length 3-12."""
    if not anthropic_key or not theme:
        return []
    try:
        import anthropic, re
        client = anthropic.Anthropic(api_key=anthropic_key)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content":
                f"Give me exactly {n} single English words related to '{theme}'. "
                "Each word must be 3-12 letters, ALL CAPS, alphabetical letters only "
                "(no hyphens, spaces, digits, or accents). Return the words one per line, "
                "no numbering, no explanation."}],
        )
        words = []
        for ln in msg.content[0].text.splitlines():
            w = re.sub(r"[^A-Za-z]", "", ln).upper()
            if 3 <= len(w) <= 12:
                words.append(w)
        return words[:n]
    except Exception as e:
        logger.warning(f"Claude word bank failed for '{theme}': {e}")
        return []


def _place_words(size: int, words: List[str], directions: List, rng) -> Tuple[List[List[str]], List[Dict]]:
    """Try to place words on a size×size grid. Returns (grid, placements)."""
    grid = [["" for _ in range(size)] for _ in range(size)]
    placements = []
    for word in words:
        placed = False
        attempts = 0
        while attempts < 200 and not placed:
            attempts += 1
            dy, dx = rng.choice(directions)
            length = len(word)
            if dy == 0:
                y_max, x_max = size, size - length
            elif dx == 0:
                y_max, x_max = size - length, size
            else:
                y_max = size - length if dy > 0 else length - 1
                x_max = size - length if dx > 0 else length - 1
            if y_max <= 0 or x_max <= 0:
                continue
            y = rng.randrange(max(1, y_max))
            x = rng.randrange(max(1, x_max))
            # Check fit
            ok = True
            cells = []
            for k, ch in enumerate(word):
                ry, rx = y + dy * k, x + dx * k
                if not (0 <= ry < size and 0 <= rx < size):
                    ok = False
                    break
                cur = grid[ry][rx]
                if cur and cur != ch:
                    ok = False
                    break
                cells.append((ry, rx, ch))
            if not ok:
                continue
            for ry, rx, ch in cells:
                grid[ry][rx] = ch
            placements.append({"word": word, "cells": [(c[0], c[1]) for c in cells]})
            placed = True
        if not placed:
            logger.debug(f"wordsearch: could not place '{word}'")
    # Fill empties with random letters
    for y in range(size):
        for x in range(size):
            if not grid[y][x]:
                grid[y][x] = rng.choice(string.ascii_uppercase)
    return grid, placements


def generate(n: int, difficulty: str, niche: str, volume: int = 1,
             anthropic_key: str = "", themes: Optional[List[str]] = None) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    out = []
    themes = themes or [niche] * n
    for i in range(n):
        d_i = difficulties[i]
        params = DIFFICULTY_PARAMS.get(d_i, DIFFICULTY_PARAMS["medium"])
        # directions depends on THIS puzzle's difficulty — must be inside the loop
        directions = DIRS_8 if params["directions"] == 8 else DIRS_4
        rng = rng_for(niche, volume, i)
        theme = themes[i % len(themes)] if themes else niche
        words = _claude_word_bank(theme, params["n_words"] + 4, anthropic_key)
        if len(words) < params["n_words"]:
            # Fallback bank
            bank = list(_FALLBACK_BANK)
            rng.shuffle(bank)
            words = (words + bank)[: params["n_words"] + 4]
        rng.shuffle(words)
        # Sort by length desc — longer first improves packing
        words = sorted(words[: params["n_words"] + 4], key=len, reverse=True)
        grid, placements = _place_words(params["size"], words, directions, rng)
        placed_words = [p["word"] for p in placements]
        out.append({
            "kind": "wordsearch",
            "size": params["size"],
            "grid": grid,
            "placements": placements,
            "words": placed_words,
            "difficulty": d_i,
            "theme": theme,
        })
    return out


# ── Flowable: draws the letter grid ────────────────────────────────────────

class _GridFlowable(Flowable):
    def __init__(self, puzzle: Dict, max_w: float, font_size: float,
                 highlight_solution: bool = False):
        super().__init__()
        self.puzzle = puzzle
        self.font_size = font_size
        self.highlight = highlight_solution
        n = puzzle["size"]
        cell = min(max_w / n, 0.4 * IN)
        self.cell = cell
        self.width = cell * n
        self.height = cell * n

    def draw(self):
        c = self.canv
        n = self.puzzle["size"]
        cs = self.cell
        # Highlight solution cells
        if self.highlight:
            c.setFillColorRGB(0.92, 0.95, 1.0)
            c.setStrokeColorRGB(1, 1, 1)
            for p in self.puzzle.get("placements", []):
                for (y, x) in p["cells"]:
                    gx, gy = x * cs, (n - 1 - y) * cs
                    c.rect(gx, gy, cs, cs, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
        # Letters
        c.setFont("Helvetica-Bold", self.font_size)
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.setLineWidth(0.3)
        c.rect(0, 0, n * cs, n * cs, stroke=1, fill=0)
        for y in range(n):
            for x in range(n):
                gx = x * cs + cs / 2
                gy = (n - 1 - y) * cs + (cs - self.font_size) / 2 + 1
                c.drawCentredString(gx, gy, self.puzzle["grid"][y][x])


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    word_style = ParagraphStyle(
        "WSWords", fontName="Helvetica", fontSize=11 if large else 9,
        leading=14 if large else 11, alignment=TA_LEFT,
    )
    for i, p in enumerate(puzzles, 1):
        elems.extend(puzzle_header(i, total, p["difficulty"], "Word Search", pal, styles,
                                   avail_w=content_w))
        if p.get("theme"):
            theme_st = ParagraphStyle(
                "WSTheme", fontName="Helvetica-Oblique", fontSize=10,
                textColor=colors.HexColor("#555555"), alignment=TA_LEFT, spaceAfter=4,
            )
            elems.append(Paragraph(f"Theme: <b>{p['theme'].title()}</b>", theme_st))
        font_size = 16 if large else 12
        # Bigger grid: fill the width, cap at ~62% height (large print = bigger
        # letters for seniors, and the page no longer looks half-empty).
        grid_max_w = min(content_w, content_h * 0.62)
        elems.append(_GridFlowable(p, grid_max_w, font_size, highlight_solution=False))
        elems.append(Spacer(1, 12))
        # Word bank below — header + grid
        wb_st = ParagraphStyle("WSFind", fontName="Helvetica-Bold", fontSize=11 if large else 10,
                               textColor=pal.get("accent", colors.HexColor("#1A252F")),
                               spaceAfter=4)
        elems.append(Paragraph("Find these words:", wb_st))
        word_cols = 4 if not large else 3
        words = sorted(p["words"])
        rows = []
        for r in range(0, len(words), word_cols):
            rows.append(words[r:r + word_cols] + [""] * (word_cols - len(words[r:r + word_cols])))
        tbl = Table(rows, colWidths=[content_w / word_cols] * word_cols)
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 12 if large else 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ]))
        elems.append(tbl)
        # Fill the rest of the page with a tip + scratch/notes area
        n_word_rows = (len(words) + word_cols - 1) // word_cols
        used_h = 0.95 * IN + grid_max_w + 0.4 * IN + n_word_rows * (0.26 * IN if large else 0.20 * IN)
        elems.extend(puzzle_value_filler(content_w, content_h, used_h, "Word Search", pal,
                                         extra_tip="Tip: words can run forwards, backwards, "
                                                   "across, down and diagonally. Circle each one you find."))
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    elems = solutions_banner("Word Search", pal, styles)
    per_page = 4
    for batch_start in range(0, len(puzzles), per_page):
        batch = puzzles[batch_start:batch_start + per_page]
        for j, p in enumerate(batch):
            num = batch_start + j + 1
            head_st = ParagraphStyle(f"WSSolHead{num}", fontName="Helvetica-Bold",
                                     fontSize=10, leading=12, spaceAfter=2)
            elems.append(Paragraph(f"Word Search #{num}", head_st))
            elems.append(_GridFlowable(p, content_w * 0.42, 8,
                                       highlight_solution=True))
            elems.append(Spacer(1, 8))
        elems.append(PageBreak())
    return elems
