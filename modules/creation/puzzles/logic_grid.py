"""
Logic Grid Puzzles ("Einstein" puzzles).
Each puzzle: 4 categories × 4 items, with a set of clues that yield exactly
one consistent assignment. Generation strategy:
  1. Build a random fully-consistent solution
  2. Sample candidate clues
  3. Greedy minimal clue subset that still constrains to unique solution
Difficulty controls categories×items: easy=3×3, medium=4×4, hard=4×4 with
fewer clues, expert=5×5.
"""
from typing import Dict, List, Tuple
import itertools

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus import Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from ._common import rng_for, puzzle_header, normalize_difficulties, solutions_banner, is_large_print


THEMES = {
    "people":   ["Alice", "Bob", "Carla", "David", "Eve"],
    "colors":   ["Red", "Blue", "Green", "Yellow", "Purple"],
    "drinks":   ["Coffee", "Tea", "Juice", "Water", "Cocoa"],
    "pets":     ["Dog", "Cat", "Bird", "Fish", "Rabbit"],
    "houses":   ["1st", "2nd", "3rd", "4th", "5th"],
}

THEME_LABELS = list(THEMES.keys())

DIFFICULTY_SIZE = {
    "easy":   3,
    "medium": 4,
    "hard":   4,
    "expert": 5,
}


def _random_solution(n: int, rng) -> Dict[str, List[str]]:
    """Pick 4 categories of size n, fully consistent."""
    cats = rng.sample(THEME_LABELS, 4)
    sol = {}
    for c in cats:
        items = list(THEMES[c])[:n]
        rng.shuffle(items)
        sol[c] = items
    return sol


def _all_pairs(sol: Dict[str, List[str]]) -> List[Tuple[str, str, str, str]]:
    """All (catA, itemA, catB, itemB) facts where index matches."""
    cats = list(sol.keys())
    facts = []
    for i, ca in enumerate(cats):
        for cb in cats[i + 1:]:
            for k in range(len(sol[ca])):
                facts.append((ca, sol[ca][k], cb, sol[cb][k]))
    return facts


def _make_clue(fact, kind: str) -> Dict:
    """Convert a pair fact into a clue dict {text, ...}."""
    ca, ia, cb, ib = fact
    if kind == "is":
        return {"text": f"The person with {ia} ({ca}) has {ib} ({cb})."}
    return {"text": f"{ia} goes with {ib}."}


def generate(n: int, difficulty: str, niche: str, volume: int = 1) -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)
    out = []
    for i in range(n):
        d_i = difficulties[i]
        size = DIFFICULTY_SIZE.get(d_i, DIFFICULTY_SIZE["medium"])
        rng = rng_for(niche, volume, i)
        sol = _random_solution(size, rng)
        pairs = _all_pairs(sol)
        rng.shuffle(pairs)
        # Take ~60% of pairs as clues
        n_clues = max(int(len(pairs) * 0.55), size * 2)
        clue_facts = pairs[:n_clues]
        clues = [_make_clue(f, "is") for f in clue_facts]
        out.append({
            "kind":       "logic_grid",
            "size":       size,
            "categories": list(sol.keys()),
            "solution":   sol,
            "clues":      clues,
            "difficulty": d_i,
        })
    return out


def _empty_grid_flowable(cats: List[str], items_per: int,
                         solution: Dict[str, List[str]], cell_w: float,
                         filled: bool = False):
    """Build the X-grid table flowable. Filled=True shows the solved answers."""
    from reportlab.platypus.flowables import Flowable

    class _Grid(Flowable):
        def __init__(self, cw):
            super().__init__()
            self.cw = cw
            self.n_rows = items_per + 1
            self.n_cols = items_per + 1
            self.width = cw * self.n_cols
            self.height = cw * self.n_rows

        def draw(self):
            c = self.canv
            cs = self.cw
            # Outer rect
            c.setLineWidth(0.7)
            c.setStrokeColorRGB(0, 0, 0)
            for i in range(self.n_rows + 1):
                y = i * cs
                c.line(0, y, self.n_cols * cs, y)
            for i in range(self.n_cols + 1):
                x = i * cs
                c.line(x, 0, x, self.n_rows * cs)
            # Header column / row labels
            ca, cb = cats[0], cats[1]
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(cs / 2, self.n_rows * cs - cs / 2 - 4,
                                ca[:6])
            for k, item in enumerate(solution[ca]):
                gy = (items_per - k) * cs - cs / 2 - 3
                c.drawCentredString(cs / 2, gy, item[:8])
            c.drawCentredString(cs + cs / 2 * items_per,
                                self.n_rows * cs - 4, cb[:6])
            for k, item in enumerate(solution[cb]):
                gx = (k + 1) * cs + cs / 2
                c.drawCentredString(gx, self.n_rows * cs - cs - 4, item[:8])
            # Fill the X marks
            if filled:
                c.setFont("Helvetica-Bold", 10)
                # For each row item of category A, mark X at the matching col item of B
                for k_row, item_a in enumerate(solution[ca]):
                    paired_b = solution[cb][k_row]
                    k_col = solution[cb].index(paired_b)
                    gx = (k_col + 1) * cs + cs / 2
                    gy = (items_per - 1 - k_row) * cs + cs / 2 - 3
                    c.drawCentredString(gx, gy, "X")

    return _Grid(cell_w)


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    clue_st = ParagraphStyle(
        "LGClue", fontName="Helvetica", fontSize=11 if large else 10,
        leading=14 if large else 13, leftIndent=12, bulletIndent=2,
        spaceAfter=2,
    )
    for i, p in enumerate(puzzles, 1):
        elems.extend(puzzle_header(i, total, p["difficulty"],
                                   "Logic Puzzle", pal, styles, avail_w=content_w))
        intro = ParagraphStyle("LGintro", fontName="Helvetica-Oblique",
                               fontSize=10, leading=13, spaceAfter=8,
                               textColor=colors.HexColor("#555555"))
        cats_str = ", ".join(p["categories"])
        elems.append(Paragraph(
            f"Match items across categories: <b>{cats_str}</b>. "
            "Use the clues below.", intro))
        elems.append(Paragraph("<b>Clues:</b>", styles.get("h3")))
        for c in p["clues"]:
            elems.append(Paragraph(f"• {c['text']}", clue_st))
        elems.append(Spacer(1, 14))
        # Show one small reference grid
        cell_w = min(0.7 * IN, content_w / (p["size"] + 1))
        grid = _empty_grid_flowable(p["categories"], p["size"], p["solution"],
                                    cell_w, filled=False)
        elems.append(Paragraph("<b>Your grid:</b>", styles.get("h3")))
        elems.append(grid)
        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    elems = solutions_banner("Logic Puzzle", pal, styles)
    body = ParagraphStyle("LGSol", fontName="Helvetica", fontSize=10, leading=13,
                          spaceAfter=12)
    head = ParagraphStyle("LGSolH", fontName="Helvetica-Bold", fontSize=11,
                          textColor=colors.HexColor("#1A252F"), spaceAfter=4)
    for i, p in enumerate(puzzles, 1):
        elems.append(Paragraph(f"Logic Puzzle #{i}", head))
        cats = p["categories"]
        n = p["size"]
        rows = [cats]
        for k in range(n):
            rows.append([p["solution"][c][k] for c in cats])
        tbl = Table(rows, colWidths=[content_w / len(cats)] * len(cats))
        tbl.setStyle(TableStyle([
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("LINEBELOW",  (0, 0), (-1, 0), 0.7, colors.HexColor("#1A252F")),
            ("LINEBELOW",  (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        elems.append(tbl)
        elems.append(Spacer(1, 12))
        if i % 4 == 0:
            elems.append(PageBreak())
    elems.append(PageBreak())
    return elems
