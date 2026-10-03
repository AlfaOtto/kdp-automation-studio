"""
KenKen generator.
Builds an n×n Latin square (each row/col contains 1..n exactly once),
groups cells into "cages" of 1-4 cells, and assigns an arithmetic
operation + target to each cage (sum, product, diff, quotient).

Difficulty: easy=4×4, medium=5×5, hard=6×6, expert=7×7.
"""
from typing import Dict, List, Tuple
import math

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus import Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.platypus.flowables import Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from ._common import rng_for, puzzle_header, normalize_difficulties, solutions_banner, is_large_print, puzzle_value_filler


DIFFICULTY_SIZE = {
    "easy":   4,
    "medium": 5,
    "hard":   6,
    "expert": 7,
}


def _latin_square(n: int, rng) -> List[List[int]]:
    base = [[(i + j) % n + 1 for j in range(n)] for i in range(n)]
    # Shuffle rows and columns
    rows = list(range(n))
    cols = list(range(n))
    rng.shuffle(rows)
    rng.shuffle(cols)
    return [[base[rows[i]][cols[j]] for j in range(n)] for i in range(n)]


def _build_cages(grid: List[List[int]], rng) -> List[Dict]:
    """Group adjacent cells into cages of 1-4 cells."""
    n = len(grid)
    assigned = [[None] * n for _ in range(n)]
    cages = []
    cage_id = 0
    cells = [(r, c) for r in range(n) for c in range(n)]
    rng.shuffle(cells)
    for r, c in cells:
        if assigned[r][c] is not None:
            continue
        # Start a new cage; randomly grow it up to 4 cells via adjacent BFS
        target_size = rng.choice([1, 2, 2, 3, 3, 4])
        cage_cells = [(r, c)]
        assigned[r][c] = cage_id
        frontier = [(r, c)]
        while frontier and len(cage_cells) < target_size:
            x, y = frontier.pop(0)
            neighbours = [(x + dx, y + dy) for dx, dy in
                          [(-1, 0), (1, 0), (0, -1), (0, 1)]
                          if 0 <= x + dx < n and 0 <= y + dy < n
                          and assigned[x + dx][y + dy] is None]
            rng.shuffle(neighbours)
            for nx, ny in neighbours:
                if len(cage_cells) >= target_size:
                    break
                assigned[nx][ny] = cage_id
                cage_cells.append((nx, ny))
                frontier.append((nx, ny))
        values = [grid[rr][cc] for rr, cc in cage_cells]
        # Operation
        if len(cage_cells) == 1:
            op = "="
            target = values[0]
        else:
            choices = ["+", "*"]
            if len(cage_cells) == 2:
                a, b = sorted(values, reverse=True)
                if a % b == 0:
                    choices.extend(["/"])
                choices.append("-")
            op = rng.choice(choices)
            if op == "+":
                target = sum(values)
            elif op == "*":
                target = 1
                for v in values: target *= v
            elif op == "-":
                target = max(values) - min(values)
            elif op == "/":
                a, b = sorted(values, reverse=True)
                target = a // b
        cages.append({"id": cage_id, "cells": cage_cells, "op": op, "target": target})
        cage_id += 1
    return cages


def generate(n: int, difficulty: str, niche: str, volume: int = 1) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    out = []
    for i in range(n):
        d_i = difficulties[i]
        size = DIFFICULTY_SIZE.get(d_i, DIFFICULTY_SIZE["medium"])
        rng = rng_for(niche, volume, i)
        solution = _latin_square(size, rng)
        cages = _build_cages(solution, rng)
        out.append({
            "kind":       "kenken",
            "size":       size,
            "solution":   solution,
            "cages":      cages,
            "difficulty": d_i,
        })
    return out


class _KenKenFlowable(Flowable):
    def __init__(self, puzzle: Dict, cell: float, show_solution: bool = False):
        super().__init__()
        self.puzzle = puzzle
        self.cell = cell
        n = puzzle["size"]
        self.width = cell * n
        self.height = cell * n
        self.show_solution = show_solution
        # Index cell → cage_id and clue
        self.cell_cage = {}
        self.cage_clue_cell = {}
        for cage in puzzle["cages"]:
            for (r, c) in cage["cells"]:
                self.cell_cage[(r, c)] = cage["id"]
            # Top-left cell of cage gets the clue
            top_left = min(cage["cells"], key=lambda x: (x[0], x[1]))
            self.cage_clue_cell[cage["id"]] = top_left
        self.cage_by_id = {c["id"]: c for c in puzzle["cages"]}

    def draw(self):
        c = self.canv
        n = self.puzzle["size"]
        cs = self.cell
        # Light grid lines first
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.setLineWidth(0.3)
        for i in range(n + 1):
            x = i * cs
            c.line(x, 0, x, n * cs)
            c.line(0, x, n * cs, x)
        # Thick cage borders: where adjacent cells belong to different cages
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(1.5)
        for r in range(n):
            for col in range(n):
                gx, gy = col * cs, (n - 1 - r) * cs
                cid = self.cell_cage[(r, col)]
                # Right border
                if col == n - 1 or self.cell_cage[(r, col + 1)] != cid:
                    c.line(gx + cs, gy, gx + cs, gy + cs)
                # Top border
                if r == 0 or self.cell_cage[(r - 1, col)] != cid:
                    c.line(gx, gy + cs, gx + cs, gy + cs)
                # Left border
                if col == 0 or self.cell_cage[(r, col - 1)] != cid:
                    c.line(gx, gy, gx, gy + cs)
                # Bottom border
                if r == n - 1 or self.cell_cage[(r + 1, col)] != cid:
                    c.line(gx, gy, gx + cs, gy)
        # Clue text in top-left of each cage
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", cs * 0.22)
        for cid, (r, col) in self.cage_clue_cell.items():
            cage = self.cage_by_id[cid]
            gx, gy = col * cs, (n - 1 - r) * cs
            if cage["op"] == "=":
                txt = str(cage["target"])
            else:
                txt = f"{cage['target']}{cage['op']}"
            c.drawString(gx + cs * 0.06, gy + cs - cs * 0.28, txt)
        # Solution numbers
        if self.show_solution:
            c.setFont("Helvetica-Bold", cs * 0.45)
            for r in range(n):
                for col in range(n):
                    gx, gy = col * cs, (n - 1 - r) * cs
                    c.drawCentredString(gx + cs / 2,
                                        gy + cs / 2 - cs * 0.18,
                                        str(self.puzzle["solution"][r][col]))


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    per_page = 1 if (large or puzzles[0]["size"] >= 6) else 2

    for batch_start in range(0, len(puzzles), per_page):
        batch = puzzles[batch_start:batch_start + per_page]
        for j, p in enumerate(batch):
            num = batch_start + j + 1
            elems.extend(puzzle_header(num, total, p["difficulty"], "KenKen", pal, styles,
                                       avail_w=content_w))
            if per_page == 1:
                # Maximize grid (full width, ≤62% height) + fill rest with value
                cell = min(content_w / p["size"], (content_h * 0.62) / p["size"])
                elems.append(_KenKenFlowable(p, cell, show_solution=False))
                used_h = cell * p["size"] + 0.55 * IN
                elems.extend(puzzle_value_filler(content_w, content_h, used_h, "KenKen", pal))
            else:
                cell = min(content_w / p["size"], (content_h - 2.0 * IN) / 2 / p["size"], 0.55 * IN)
                elems.append(_KenKenFlowable(p, cell, show_solution=False))
                elems.append(Spacer(1, 8))
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    elems = solutions_banner("KenKen", pal, styles)
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
                cell = min(content_w * 0.4 / p["size"], 0.30 * IN)
                row_cells.append([Paragraph(f"#{num}", cap),
                                  _KenKenFlowable(p, cell, show_solution=True)])
            rows.append(row_cells)
        tbl = Table(rows, colWidths=[content_w / 2] * 2)
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
                                  ("TOPPADDING", (0, 0), (-1, -1), 8),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        elems.append(tbl)
        elems.append(PageBreak())
    return elems
