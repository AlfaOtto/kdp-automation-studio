"""
Activity Book combo — mixes 3-5 puzzle types in one volume.
Used when product_type == "activity_book" or when listing.puzzle_types is a list.

Strategy: divide target page count across selected types, generate each set,
interleave them so the reader switches rhythm every few pages.

Default mix (if user picks "Ultimate Brain Health" style):
  Sudoku 40% / Word Search 25% / Crossword-style cryptogram 15% / Mazes 10% / Logic 10%
"""
from typing import Dict, List, Optional

from . import (mazes, wordsearch, sudoku, cryptogram, logic_grid,
                nonogram, kakuro, kenken, dot_to_dot)


DEFAULT_MIX = {
    "sudoku":     0.40,
    "wordsearch": 0.25,
    "cryptogram": 0.15,
    "mazes":      0.10,
    "logic_grid": 0.10,
}

PUZZLE_MODULES = {
    "mazes":      mazes,
    "wordsearch": wordsearch,
    "sudoku":     sudoku,
    "cryptogram": cryptogram,
    "logic_grid": logic_grid,
    "nonogram":   nonogram,
    "kakuro":     kakuro,
    "kenken":     kenken,
    "dot_to_dot": dot_to_dot,
}


def plan_mix(total_puzzles: int, mix: Optional[Dict[str, float]] = None) -> Dict[str, int]:
    """Distribute total_puzzles across types according to mix percentages."""
    mix = mix or DEFAULT_MIX
    counts = {k: max(2, int(round(total_puzzles * v))) for k, v in mix.items()}
    # Normalize to total
    diff = total_puzzles - sum(counts.values())
    if diff != 0:
        # Push diff into the largest bucket
        biggest = max(counts, key=counts.get)
        counts[biggest] = max(2, counts[biggest] + diff)
    return counts


def generate_combo(total_puzzles: int, difficulty: str, niche: str,
                   mix: Optional[Dict[str, float]] = None,
                   volume: int = 1, anthropic_key: str = "") -> List[Dict]:
    """
    Returns a list of (puzzle_type, [puzzles]) tuples for the activity book.
    Order is the order the sections will appear in the book.
    """
    plan = plan_mix(total_puzzles, mix)
    out = []
    for ptype, n in plan.items():
        if n <= 0:
            continue
        mod = PUZZLE_MODULES[ptype]
        if ptype in ("wordsearch", "cryptogram"):
            pzs = mod.generate(n, difficulty, niche, volume=volume,
                               anthropic_key=anthropic_key)
        else:
            pzs = mod.generate(n, difficulty, niche, volume=volume)
        out.append((ptype, pzs))
    return out
