"""
Puzzle book engine — 9 algorithmic puzzle types.

Each generator returns deterministic puzzles seeded by (niche_slug, volume,
puzzle_index) so two books with the same params never duplicate, but a
re-render of the SAME book reproduces identical content. This is the core
anti-duplication property of algorithmic puzzles: every puzzle is unique by
construction.

Public API per puzzle module:
  - generate(n, difficulty, seed) → List[Dict]  (puzzle data structures)
  - render_pages(puzzles, palette, styles)      → List[reportlab flowables]
  - render_solutions(puzzles, palette, styles)  → List[reportlab flowables]
"""
from typing import Dict, List, Callable, Any

from . import mazes, wordsearch, sudoku, cryptogram, logic_grid
from . import nonogram, kakuro, kenken, dot_to_dot

# Registry — single source of truth for valid puzzle types
PUZZLE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "mazes": {
        "module": mazes,
        "label": "Mazes",
        "needs_solutions": True,
        "puzzles_per_page": 1,
        "default_difficulty": "medium",
    },
    "wordsearch": {
        "module": wordsearch,
        "label": "Word Search",
        "needs_solutions": True,
        "puzzles_per_page": 1,
        "default_difficulty": "medium",
    },
    "sudoku": {
        "module": sudoku,
        "label": "Sudoku",
        "needs_solutions": True,
        "puzzles_per_page": 2,
        "default_difficulty": "medium",
    },
    "cryptogram": {
        "module": cryptogram,
        "label": "Cryptogram",
        "needs_solutions": True,
        "puzzles_per_page": 1,
        "default_difficulty": "medium",
    },
    "logic_grid": {
        "module": logic_grid,
        "label": "Logic Grid Puzzles",
        "needs_solutions": True,
        "puzzles_per_page": 1,
        "default_difficulty": "medium",
    },
    "nonogram": {
        "module": nonogram,
        "label": "Nonograms (Picross)",
        "needs_solutions": True,
        "puzzles_per_page": 1,
        "default_difficulty": "medium",
    },
    "kakuro": {
        "module": kakuro,
        "label": "Kakuro",
        "needs_solutions": True,
        "puzzles_per_page": 1,
        "default_difficulty": "medium",
    },
    "kenken": {
        "module": kenken,
        "label": "KenKen",
        "needs_solutions": True,
        "puzzles_per_page": 2,
        "default_difficulty": "medium",
    },
    "dot_to_dot": {
        "module": dot_to_dot,
        "label": "Dot-to-Dot",
        "needs_solutions": False,
        "puzzles_per_page": 1,
        "default_difficulty": "medium",
    },
}


def get_puzzle_module(puzzle_type: str):
    """Returns the module for a puzzle type, or raises KeyError."""
    return PUZZLE_REGISTRY[puzzle_type]["module"]


def list_puzzle_types() -> List[str]:
    return list(PUZZLE_REGISTRY.keys())


def puzzle_label(puzzle_type: str) -> str:
    return PUZZLE_REGISTRY.get(puzzle_type, {}).get("label", puzzle_type)
