"""
Nonogram (Picross) generator.
Generate a random binary picture, derive the row/column clue counts.
Difficulty controls size: easy=8×8, medium=10×10, hard=15×15, expert=20×20.
"""
from typing import Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus import Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.platypus.flowables import Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from ._common import rng_for, puzzle_header, normalize_difficulties, solutions_banner, is_large_print, puzzle_value_filler


DIFFICULTY_SIZE = {
    "easy":   (8, 0.50),
    "medium": (10, 0.50),
    "hard":   (15, 0.45),
    "expert": (20, 0.45),
}


def _runs(line: List[int]) -> List[int]:
    out, cur = [], 0
    for v in line:
        if v:
            cur += 1
        else:
            if cur:
                out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out or [0]


def generate(n: int, difficulty: str, niche: str, volume: int = 1) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    out = []
    for i in range(n):
        d_i = difficulties[i]
        size, density = DIFFICULTY_SIZE.get(d_i, DIFFICULTY_SIZE["medium"])
        rng = rng_for(niche, volume, i)
        grid = [[1 if rng.random() < density else 0 for _ in range(size)]
                for _ in range(size)]
        rows = [_runs(grid[r]) for r in range(size)]
        cols = [_runs([grid[r][c] for r in range(size)]) for c in range(size)]
        out.append({
            "kind":       "nonogram",
            "size":       size,
            "solution":   grid,
            "rows":       rows,
            "cols":       cols,
            "difficulty": d_i,
        })
    return out


class _NonoFlowable(Flowable):
    def __init__(self, puzzle: Dict, cell: float, show_solution: bool = False):
        super().__init__()
        self.puzzle = puzzle
        self.cell = cell
        max_row_len = max(len(r) for r in puzzle["rows"])
        max_col_len = max(len(c) for c in puzzle["cols"])
        self.row_clue_w = max_row_len * cell * 0.6 + 4
        self.col_clue_h = max_col_len * cell * 0.6 + 4
        self.width  = self.row_clue_w + puzzle["size"] * cell
        self.height = self.col_clue_h + puzzle["size"] * cell
        self.show_solution = show_solution

    def draw(self):
        c = self.canv
        n = self.puzzle["size"]
        cs = self.cell
        # Grid origin in canvas space — clues on top and left
        gx0 = self.row_clue_w
        gy0 = 0  # grid bottom

        # Cells (with optional fill for solution)
        if self.show_solution:
            for r in range(n):
                for col in range(n):
                    if self.puzzle["solution"][r][col]:
                        cx = gx0 + col * cs
                        cy = gy0 + (n - 1 - r) * cs
                        c.setFillColorRGB(0.15, 0.15, 0.15)
                        c.rect(cx, cy, cs, cs, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)

        # Grid lines
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.setLineWidth(0.3)
        for i in range(n + 1):
            c.line(gx0, gy0 + i * cs, gx0 + n * cs, gy0 + i * cs)
            c.line(gx0 + i * cs, gy0, gx0 + i * cs, gy0 + n * cs)
        # 5×5 thick lines
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(1.0)
        for i in range(0, n + 1, 5):
            c.line(gx0, gy0 + i * cs, gx0 + n * cs, gy0 + i * cs)
            c.line(gx0 + i * cs, gy0, gx0 + i * cs, gy0 + n * cs)

        # Row clues (right-aligned, on the left of the grid)
        c.setFont("Helvetica", max(cs * 0.45, 6))
        for r in range(n):
            clues = self.puzzle["rows"][r]
            text = " ".join(str(v) for v in clues)
            y = gy0 + (n - 1 - r) * cs + cs / 2 - 3
            c.drawRightString(gx0 - 2, y, text)

        # Col clues (centered, on top of the grid)
        for col in range(n):
            clues = self.puzzle["cols"][col]
            x = gx0 + col * cs + cs / 2
            for k, v in enumerate(reversed(clues)):
                y = gy0 + n * cs + 2 + k * cs * 0.55
                c.drawCentredString(x, y, str(v))


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    for i, p in enumerate(puzzles, 1):
        elems.extend(puzzle_header(i, total, p["difficulty"], "Nonogram", pal, styles,
                                   avail_w=content_w))
        # Maximize: clues take ~30% extra around the grid, so the drawn block is
        # ~size*1.3 cells. Size the cell so that block fills the width (and ≤62%
        # height), then fill the rest of the page with a tip + work area.
        span = p["size"] * 1.3
        cell = min(content_w / span, (content_h * 0.62) / span)
        if large:
            cell *= 1.1
        elems.append(_NonoFlowable(p, cell, show_solution=False))
        used_h = cell * span + 0.55 * IN
        elems.extend(puzzle_value_filler(content_w, content_h, used_h, "Nonogram", pal))
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    elems = solutions_banner("Nonogram", pal, styles)
    cap_st = ParagraphStyle("NoSol", fontName="Helvetica-Bold",
                             fontSize=10, alignment=TA_CENTER, spaceAfter=4)
    per_page = 4
    for batch_start in range(0, len(puzzles), per_page):
        batch = puzzles[batch_start:batch_start + per_page]
        rows = []
        for r in range(0, per_page, 2):
            row_cells = []
            for cc in range(2):
                idx = r + cc
                if idx >= len(batch):
                    row_cells.append("")
                    continue
                p = batch[idx]
                num = batch_start + idx + 1
                cell = min(content_w * 0.3 / p["size"], 0.20 * IN)
                row_cells.append([Paragraph(f"#{num}", cap_st),
                                  _NonoFlowable(p, cell, show_solution=True)])
            rows.append(row_cells)
        tbl = Table(rows, colWidths=[content_w / 2] * 2)
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
                                  ("TOPPADDING", (0, 0), (-1, -1), 8),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        elems.append(tbl)
        elems.append(PageBreak())
    return elems
