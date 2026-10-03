"""
Sudoku 9×9 generator with unique-solution validation.
Difficulty controls how many cells are revealed (clues):
  easy=40-45, medium=32-36, hard=27-30, expert=22-25.
"""
from typing import Dict, List, Optional, Tuple
import copy

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus import Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.platypus.flowables import Flowable
from reportlab.lib.styles import ParagraphStyle

from ._common import rng_for, puzzle_header, normalize_difficulties, solutions_banner, is_large_print


CLUE_RANGE = {
    "easy":   (40, 45),
    "medium": (32, 36),
    "hard":   (27, 30),
    "expert": (22, 25),
}


# ── Solver / Generator ──────────────────────────────────────────────────────

def _is_valid(b, r, c, v):
    if any(b[r][i] == v for i in range(9)): return False
    if any(b[i][c] == v for i in range(9)): return False
    br, bc = 3 * (r // 3), 3 * (c // 3)
    for i in range(br, br + 3):
        for j in range(bc, bc + 3):
            if b[i][j] == v:
                return False
    return True


def _solve_count(b, limit: int = 2) -> int:
    """Counts solutions up to `limit`. Used for uniqueness check."""
    for r in range(9):
        for c in range(9):
            if b[r][c] == 0:
                count = 0
                for v in range(1, 10):
                    if _is_valid(b, r, c, v):
                        b[r][c] = v
                        count += _solve_count(b, limit - count)
                        b[r][c] = 0
                        if count >= limit:
                            return count
                return count
    return 1


def _generate_full(rng) -> List[List[int]]:
    """Generate a fully solved 9×9 grid."""
    board = [[0] * 9 for _ in range(9)]
    nums = list(range(1, 10))

    def fill(idx: int) -> bool:
        if idx == 81:
            return True
        r, c = divmod(idx, 9)
        rng.shuffle(nums)
        for v in nums:
            if _is_valid(board, r, c, v):
                board[r][c] = v
                if fill(idx + 1):
                    return True
                board[r][c] = 0
        return False

    fill(0)
    return board


def _dig_holes(full, target_clues: int, rng) -> List[List[int]]:
    """Remove cells while preserving unique solution."""
    puzzle = [row[:] for row in full]
    cells = [(r, c) for r in range(9) for c in range(9)]
    rng.shuffle(cells)
    clues = 81
    for r, c in cells:
        if clues <= target_clues:
            break
        backup = puzzle[r][c]
        puzzle[r][c] = 0
        # Uniqueness check
        if _solve_count([row[:] for row in puzzle], limit=2) != 1:
            puzzle[r][c] = backup
        else:
            clues -= 1
    return puzzle


def generate(n: int, difficulty: str, niche: str, volume: int = 1) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    out = []
    for i in range(n):
        d_i = difficulties[i]
        lo, hi = CLUE_RANGE.get(d_i, CLUE_RANGE["medium"])
        rng = rng_for(niche, volume, i)
        full = _generate_full(rng)
        target = rng.randint(lo, hi)
        puzzle = _dig_holes(full, target, rng)
        out.append({
            "kind": "sudoku",
            "puzzle": puzzle,
            "solution": full,
            "difficulty": d_i,
        })
    return out


# ── Render ──────────────────────────────────────────────────────────────────

class _SudokuFlowable(Flowable):
    def __init__(self, grid: List[List[int]], side: float, font_size: float):
        super().__init__()
        self.grid = grid
        self.width = side
        self.height = side
        self.font_size = font_size

    def draw(self):
        c = self.canv
        cs = self.width / 9
        # Cells
        c.setStrokeColorRGB(0.55, 0.55, 0.55)
        c.setLineWidth(0.3)
        for i in range(10):
            x = i * cs
            c.line(x, 0, x, self.width)
            c.line(0, x, self.width, x)
        # 3×3 borders
        c.setLineWidth(1.5)
        c.setStrokeColorRGB(0, 0, 0)
        for i in range(0, 10, 3):
            x = i * cs
            c.line(x, 0, x, self.width)
            c.line(0, x, self.width, x)
        # Numbers
        c.setFont("Helvetica-Bold", self.font_size)
        c.setFillColorRGB(0, 0, 0)
        for r in range(9):
            for col in range(9):
                v = self.grid[r][col]
                if v == 0:
                    continue
                gx = col * cs + cs / 2
                gy = (8 - r) * cs + (cs - self.font_size) / 2 + 1
                c.drawCentredString(gx, gy, str(v))


def _sudoku_block(grid: List[List[int]], max_side: float, font_size: float):
    return _SudokuFlowable(grid, max_side, font_size)


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    per_page = 1 if large else 2

    for batch_start in range(0, len(puzzles), per_page):
        batch = puzzles[batch_start:batch_start + per_page]
        for j, p in enumerate(batch):
            num = batch_start + j + 1
            elems.extend(puzzle_header(num, total, p["difficulty"], "Sudoku", pal, styles,
                                       avail_w=content_w))
            if per_page == 1:
                side = min(content_w, content_h - 1.5 * IN)
                font_size = 22
            else:
                side = min(content_w, (content_h - 2.0 * IN) / 2 * 1.05, 4.2 * IN)
                font_size = 16
            elems.append(_sudoku_block(p["puzzle"], side, font_size))
            elems.append(Spacer(1, 8))
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    elems = solutions_banner("Sudoku", pal, styles)
    per_page = 4
    cols = 2
    cell_w = content_w / cols
    cap_style = ParagraphStyle("SkSolCap", fontName="Helvetica-Bold",
                               fontSize=10, leading=12, alignment=0)
    for batch_start in range(0, len(puzzles), per_page):
        batch = puzzles[batch_start:batch_start + per_page]
        rows = []
        for r in range(0, per_page, cols):
            row_cells = []
            for cc in range(cols):
                idx = r + cc
                if idx >= len(batch):
                    row_cells.append("")
                    continue
                p = batch[idx]
                num = batch_start + idx + 1
                mini = _SudokuFlowable(p["solution"], cell_w - 0.3 * IN, 9)
                row_cells.append([Paragraph(f"#{num}", cap_style), mini])
            rows.append(row_cells)
        tbl = Table(rows, colWidths=[cell_w] * cols)
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elems.append(tbl)
        elems.append(PageBreak())
    return elems
