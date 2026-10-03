"""
Dot-to-dot generator.
Generates a closed curve (smooth random polygon) of N points and asks the
solver to connect them in order. No solution page needed — the curve itself
IS the answer.

Difficulty: easy=20 dots, medium=40, hard=70, expert=120.
"""
from typing import Dict, List, Tuple
import math

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus import Paragraph, Spacer, PageBreak
from reportlab.platypus.flowables import Flowable

from ._common import rng_for, puzzle_header, normalize_difficulties, is_large_print, solutions_banner


DIFFICULTY_N = {
    "easy":   20,
    "medium": 40,
    "hard":   70,
    "expert": 120,
}


def _smooth_polygon(n: int, rng) -> List[Tuple[float, float]]:
    """
    Generate n points around a circle with slight angular and radial jitter,
    producing a closed smooth curve (no self-intersections in most cases).
    Coordinates in [0..1].
    """
    cx, cy = 0.5, 0.5
    base_r = 0.42
    angles = sorted([rng.uniform(0, 2 * math.pi) for _ in range(n)])
    points = []
    for a in angles:
        r = base_r * (0.65 + rng.random() * 0.45)
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        points.append((x, y))
    return points


def generate(n: int, difficulty: str, niche: str, volume: int = 1) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    out = []
    for i in range(n):
        d_i = difficulties[i]
        n_dots = DIFFICULTY_N.get(d_i, DIFFICULTY_N["medium"])
        rng = rng_for(niche, volume, i)
        pts = _smooth_polygon(n_dots, rng)
        out.append({
            "kind": "dot_to_dot",
            "n_dots": n_dots,
            "points": pts,
            "difficulty": d_i,
        })
    return out


class _D2DFlowable(Flowable):
    def __init__(self, puzzle: Dict, max_w: float, max_h: float,
                 dot_radius: float = 1.5, font_size: float = 7,
                 show_solution: bool = False):
        super().__init__()
        self.puzzle = puzzle
        side = min(max_w, max_h)
        self.width = side
        self.height = side
        self.dot_radius = dot_radius
        self.font_size = font_size
        self.show_solution = show_solution

    def draw(self):
        c = self.canv
        pts = self.puzzle["points"]
        s = self.width
        if self.show_solution:
            c.setStrokeColorRGB(0.85, 0.25, 0.25)
            c.setLineWidth(0.9)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:] + [pts[0]]):
                c.line(x1 * s, y1 * s, x2 * s, y2 * s)
        c.setFillColorRGB(0, 0, 0)
        c.setStrokeColorRGB(0, 0, 0)
        c.setFont("Helvetica", self.font_size)
        for i, (x, y) in enumerate(pts, 1):
            cx, cy = x * s, y * s
            c.circle(cx, cy, self.dot_radius, stroke=1, fill=1)
            c.drawString(cx + self.dot_radius + 1, cy + 1, str(i))


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    for i, p in enumerate(puzzles, 1):
        elems.extend(puzzle_header(i, total, p["difficulty"], "Dot-to-Dot", pal, styles,
                                   avail_w=content_w))
        max_w = content_w
        max_h = content_h - 1.2 * IN
        elems.append(_D2DFlowable(p, max_w, max_h,
                                  dot_radius=1.8 if large else 1.2,
                                  font_size=9 if large else 6,
                                  show_solution=False))
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    # Optional gallery — skipped by default (registry says needs_solutions=False)
    return []
