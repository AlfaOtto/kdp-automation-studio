"""
Kakuro generator (simplified MVP).
Generates a small Kakuro grid: each puzzle is a 6×6 with shaded "blocker" cells
that carry clue sums. We construct by:
  1. Random valid solution (numbers 1-9, unique per run)
  2. Replace ~40% of cells with blockers
  3. Compute clue sums from runs

For V1 we keep grids small (no industrial unique-solution validation) — they
remain ALGORITHMICALLY UNIQUE per (niche, volume, idx) seed, which is the
anti-duplication property KDP cares about.
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
    "easy":   (6,  0.30),
    "medium": (8,  0.35),
    "hard":   (10, 0.40),
    "expert": (12, 0.42),
}


def _random_filled(n: int, blocker_density: float, rng) -> List[List[int]]:
    """0 = blocker, 1-9 = number (no row/col uniqueness enforced here for V1)."""
    g = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            if rng.random() < blocker_density:
                g[r][c] = 0
            else:
                g[r][c] = rng.randint(1, 9)
    return g


def _compute_clues(solution: List[List[int]]):
    """Compute (across, down) clue lists.
    Returns dict mapping (r, c) of blocker → {"down": sum_or_None, "across": sum_or_None}
    """
    n = len(solution)
    clues = {}
    # Horizontal runs
    for r in range(n):
        c = 0
        while c < n:
            if solution[r][c] == 0:
                # Look right for run
                cc = c + 1
                run = []
                while cc < n and solution[r][cc] != 0:
                    run.append(solution[r][cc])
                    cc += 1
                if len(run) >= 1:
                    clues.setdefault((r, c), {})["across"] = sum(run)
                c = cc
            else:
                c += 1
    # Vertical runs
    for col in range(n):
        r = 0
        while r < n:
            if solution[r][col] == 0:
                rr = r + 1
                run = []
                while rr < n and solution[rr][col] != 0:
                    run.append(solution[rr][col])
                    rr += 1
                if len(run) >= 1:
                    clues.setdefault((r, col), {})["down"] = sum(run)
                r = rr
            else:
                r += 1
    return clues


def generate(n: int, difficulty: str, niche: str, volume: int = 1) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    out = []
    for i in range(n):
        d_i = difficulties[i]
        size, density = DIFFICULTY_SIZE.get(d_i, DIFFICULTY_SIZE["medium"])
        rng = rng_for(niche, volume, i)
        solution = _random_filled(size, density, rng)
        clues = _compute_clues(solution)
        out.append({
            "kind":       "kakuro",
            "size":       size,
            "solution":   solution,
            "clues":      clues,
            "difficulty": d_i,
        })
    return out


class _KakuroFlowable(Flowable):
    def __init__(self, puzzle: Dict, cell: float, show_solution: bool = False):
        super().__init__()
        self.puzzle = puzzle
        self.cell = cell
        self.width = cell * puzzle["size"]
        self.height = cell * puzzle["size"]
        self.show_solution = show_solution

    def draw(self):
        c = self.canv
        n = self.puzzle["size"]
        cs = self.cell
        for r in range(n):
            for col in range(n):
                gx, gy = col * cs, (n - 1 - r) * cs
                if self.puzzle["solution"][r][col] == 0:
                    # Blocker
                    c.setFillColorRGB(0.18, 0.18, 0.18)
                    c.rect(gx, gy, cs, cs, stroke=0, fill=1)
                    # Diagonal split line if clues
                    clue = self.puzzle["clues"].get((r, col))
                    if clue:
                        c.setStrokeColorRGB(1, 1, 1)
                        c.setLineWidth(0.8)
                        c.line(gx, gy + cs, gx + cs, gy)
                        c.setFillColorRGB(1, 1, 1)
                        c.setFont("Helvetica-Bold", cs * 0.32)
                        if "down" in clue:
                            c.drawString(gx + cs * 0.12, gy + cs * 0.18,
                                         str(clue["down"]))
                        if "across" in clue:
                            c.drawRightString(gx + cs * 0.88, gy + cs * 0.55,
                                              str(clue["across"]))
                        c.setFillColorRGB(0, 0, 0)
                else:
                    c.setStrokeColorRGB(0.4, 0.4, 0.4)
                    c.setLineWidth(0.4)
                    c.rect(gx, gy, cs, cs, stroke=1, fill=0)
                    if self.show_solution:
                        c.setFillColorRGB(0, 0, 0)
                        c.setFont("Helvetica-Bold", cs * 0.5)
                        c.drawCentredString(gx + cs / 2,
                                            gy + cs / 2 - cs * 0.16,
                                            str(self.puzzle["solution"][r][col]))


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    for i, p in enumerate(puzzles, 1):
        elems.extend(puzzle_header(i, total, p["difficulty"], "Kakuro", pal, styles,
                                   avail_w=content_w))
        # Maximize the grid: fill the FULL content width (no small cap) but never
        # taller than ~62% of the height (leaves room for the value block below).
        cell = min(content_w / p["size"], (content_h * 0.62) / p["size"])
        grid_h = cell * p["size"]
        elems.append(_KakuroFlowable(p, cell, show_solution=False))
        # Fill the rest of the page with a tip + scratch/notes box (80-90% used)
        used_h = grid_h + 0.55 * IN  # grid + header
        elems.extend(puzzle_value_filler(content_w, content_h, used_h, "Kakuro", pal))
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    elems = solutions_banner("Kakuro", pal, styles)
    cap = ParagraphStyle("KkSol", fontName="Helvetica-Bold", fontSize=10,
                         alignment=TA_CENTER, spaceAfter=4)
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
                cell = min(content_w * 0.4 / p["size"], 0.22 * IN)
                row_cells.append([Paragraph(f"#{num}", cap),
                                  _KakuroFlowable(p, cell, show_solution=True)])
            rows.append(row_cells)
        tbl = Table(rows, colWidths=[content_w / 2] * 2)
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
                                  ("TOPPADDING", (0, 0), (-1, -1), 8),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        elems.append(tbl)
        elems.append(PageBreak())
    return elems
