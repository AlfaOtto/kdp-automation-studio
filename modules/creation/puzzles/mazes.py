"""
Maze generator — recursive backtracker.
Each maze is a perfect maze (exactly one path between any two cells).
Difficulty controls grid size : easy 10×10, medium 15×15, hard 21×21, expert 27×27.
"""
from typing import Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus.flowables import Flowable
from reportlab.platypus import Spacer, PageBreak, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from ._common import rng_for, puzzle_header, normalize_difficulties, solutions_banner, is_large_print


# PORTRAIT grids (w < h) matching the ~0.66 aspect of a 6x9 content area, so
# the maze FILLS the page instead of leaving the bottom 40% blank. Taller grids
# also raise the difficulty/value naturally.
DIFFICULTY_GRID = {
    "easy":   (12, 18),
    "medium": (16, 24),
    "hard":   (20, 30),
    "expert": (26, 39),
}


def _carve_maze(w: int, h: int, rng) -> List[List[int]]:
    """
    Returns walls grid: cell[y][x] = bitmask of open passages
    Bit 0=N, 1=E, 2=S, 3=W. Start carving from (0, 0).
    """
    cells = [[0 for _ in range(w)] for _ in range(h)]
    visited = [[False] * w for _ in range(h)]
    stack = [(0, 0)]
    visited[0][0] = True
    DIRS = [(0, -1, 0, 2), (1, 0, 1, 3), (0, 1, 2, 0), (-1, 0, 3, 1)]
    while stack:
        x, y = stack[-1]
        unvisited = []
        for dx, dy, bit, opposite in DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx]:
                unvisited.append((nx, ny, bit, opposite))
        if not unvisited:
            stack.pop()
            continue
        nx, ny, bit, opp = rng.choice(unvisited)
        cells[y][x] |= (1 << bit)
        cells[ny][nx] |= (1 << opp)
        visited[ny][nx] = True
        stack.append((nx, ny))
    return cells


def _solve(cells: List[List[int]]) -> List[Tuple[int, int]]:
    """Returns the solution path from (0,0) to (w-1, h-1) using BFS."""
    h = len(cells)
    w = len(cells[0])
    DIRS = [(0, -1, 0), (1, 0, 1), (0, 1, 2), (-1, 0, 3)]
    parent = {(0, 0): None}
    queue = [(0, 0)]
    target = (w - 1, h - 1)
    while queue:
        x, y = queue.pop(0)
        if (x, y) == target:
            break
        for dx, dy, bit in DIRS:
            if cells[y][x] & (1 << bit):
                nx, ny = x + dx, y + dy
                if (nx, ny) not in parent:
                    parent[(nx, ny)] = (x, y)
                    queue.append((nx, ny))
    if target not in parent:
        return []
    path = []
    node = target
    while node is not None:
        path.append(node)
        node = parent[node]
    return list(reversed(path))


def generate(n: int, difficulty: str, niche: str, volume: int = 1) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    """Generate n mazes with stable seeds."""
    out = []
    for i in range(n):
        d_i = difficulties[i]
        w, h = DIFFICULTY_GRID.get(d_i, DIFFICULTY_GRID["medium"])
        rng = rng_for(niche, volume, i)
        cells = _carve_maze(w, h, rng)
        out.append({
            "kind": "maze",
            "w": w, "h": h,
            "cells": cells,
            "solution": _solve(cells),
            "difficulty": d_i,
        })
    return out


# ── Flowable: draws the maze grid ────────────────────────────────────────────

class _MazeFlowable(Flowable):
    def __init__(self, puzzle: Dict, max_w: float, max_h: float,
                 show_solution: bool = False, stroke_pt: float = 1.2):
        super().__init__()
        self.puzzle = puzzle
        self.max_w  = max_w
        self.max_h  = max_h
        self.show_solution = show_solution
        self.stroke_pt = stroke_pt
        cell = min(max_w / puzzle["w"], max_h / puzzle["h"])
        self.cell = cell
        self.width  = cell * puzzle["w"]
        self.height = cell * puzzle["h"]

    def draw(self):
        c = self.canv
        cells = self.puzzle["cells"]
        w, h, cs = self.puzzle["w"], self.puzzle["h"], self.cell
        c.setLineWidth(self.stroke_pt)
        c.setStrokeColorRGB(0, 0, 0)
        # Outer border
        c.rect(0, 0, w * cs, h * cs, stroke=1, fill=0)
        # Open the entrance (top-left top wall) and exit (bottom-right bottom)
        # Bottom-right exit
        c.setStrokeColorRGB(1, 1, 1)
        c.setLineWidth(self.stroke_pt + 0.6)
        c.line((w - 1) * cs + cs * 0.15, 0, w * cs - cs * 0.15, 0)
        # Top-left entrance
        c.line(cs * 0.15, h * cs, cs * 0.85, h * cs)
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(self.stroke_pt)
        # Inner walls
        for y in range(h):
            for x in range(w):
                cell_mask = cells[y][x]
                gx, gy = x * cs, (h - 1 - y) * cs
                # We need to draw walls that DO NOT have a passage
                # E wall (between (x,y) and (x+1,y))
                if x < w - 1 and not (cell_mask & 0b0010):
                    c.line(gx + cs, gy, gx + cs, gy + cs)
                # S wall (between (x,y) and (x,y+1))
                if y < h - 1 and not (cell_mask & 0b0100):
                    c.line(gx, gy, gx + cs, gy)
        # Solution path
        if self.show_solution and self.puzzle.get("solution"):
            c.setStrokeColorRGB(0.85, 0.25, 0.25)
            c.setLineWidth(max(self.stroke_pt + 0.5, 1.6))
            path = self.puzzle["solution"]
            for (x1, y1), (x2, y2) in zip(path, path[1:]):
                cx1 = x1 * cs + cs / 2
                cy1 = (h - 1 - y1) * cs + cs / 2
                cx2 = x2 * cs + cs / 2
                cy2 = (h - 1 - y2) * cs + cs / 2
                c.line(cx1, cy1, cx2, cy2)
            c.setStrokeColorRGB(0, 0, 0)


# ── Render: one maze per page ───────────────────────────────────────────────

def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    """Render each maze on its own page."""
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    stroke = 1.6 if large else 1.2
    for i, p in enumerate(puzzles, 1):
        elems.extend(puzzle_header(i, total, p["difficulty"], "Maze", pal, styles,
                                   avail_w=content_w))
        # Reserve ~0.55in for the header row, use the rest for the maze.
        max_w = content_w
        max_h = content_h - 0.55 * IN
        elems.append(_MazeFlowable(p, max_w, max_h, show_solution=False,
                                   stroke_pt=stroke))
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    """6 small solved mazes per page."""
    elems = solutions_banner("Maze", pal, styles)
    cap_style = ParagraphStyle("SolCap", fontName="Helvetica-Bold",
                               fontSize=9, alignment=TA_CENTER, leading=11)
    per_page = 6
    cols = 2
    rows_per_page = per_page // cols
    cell_w = content_w / cols - 0.15 * IN
    cell_h = (content_h - 0.6 * IN) / rows_per_page - 0.2 * IN

    from reportlab.platypus import Table, TableStyle
    for batch_start in range(0, len(puzzles), per_page):
        batch = puzzles[batch_start:batch_start + per_page]
        rows = []
        for r in range(rows_per_page):
            row_cells = []
            for c in range(cols):
                idx = r * cols + c
                if idx >= len(batch):
                    row_cells.append("")
                    continue
                p = batch[idx]
                num = batch_start + idx + 1
                mini = _MazeFlowable(p, cell_w, cell_h - 0.25 * IN,
                                     show_solution=True, stroke_pt=0.5)
                row_cells.append([Paragraph(f"Maze #{num}", cap_style), mini])
            rows.append(row_cells)
        tbl = Table(rows, colWidths=[content_w / cols] * cols)
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elems.append(tbl)
        elems.append(PageBreak())
    return elems
