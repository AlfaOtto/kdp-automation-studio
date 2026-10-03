"""
Interior template presets per sub-niche
========================================
Instead of one generic interior look across all books, this module picks a
"preset" that biases the page layout, decoration density, and typography
choices toward what works in a specific sub-niche.

A preset is a lightweight dict :
  - ornament_density : "low" | "medium" | "high"
  - corner_motif     : True/False (decorative corner flourishes)
  - section_banner   : "minimal" | "framed" | "stripe"
  - line_style       : "solid" | "dotted" | "lined"
  - prompts_per_page : int (journal-style books)
  - mood_tracker     : True/False
  - quote_pages_pct  : 0-1 (% of pages that get a centered quote)

The pdf_interior renderer can read `listing.get('_preset')` to vary its
output. Falls back to "default" silently when the niche doesn't match.
"""
from typing import Dict, Optional

DEFAULT_PRESET: Dict = {
    "name":             "default",
    "ornament_density": "medium",
    "corner_motif":     True,
    "section_banner":   "framed",
    "line_style":       "solid",
    "prompts_per_page": 1,
    "mood_tracker":     True,
    "quote_pages_pct":  0.05,
    # Pool of planner layouts to rotate for this preset. Layout names map to
    # PLANNER_LAYOUT_REGISTRY in modules/creation/pdf_interior.py.
    # Default = all 4 generic layouts.
    "daily_layouts":    ["a", "b", "c", "d"],
}

# Each preset is a partial override merged on top of DEFAULT_PRESET.
PRESETS: Dict[str, Dict] = {
    # ── Wellness / mental health journals ────────────────────────────────
    "wellness_calm": {
        "name": "wellness_calm",
        "ornament_density": "low",
        "section_banner":   "minimal",
        "line_style":       "dotted",
        "quote_pages_pct":  0.08,
        # Mostly wellness-focused dailies, occasional generic for variety
        "daily_layouts":    ["wellness", "wellness", "a", "wellness", "b"],
    },
    # ── Productivity / planners pro ──────────────────────────────────────
    "productivity_clean": {
        "name": "productivity_clean",
        "ornament_density": "low",
        "corner_motif":     False,
        "section_banner":   "stripe",
        "line_style":       "lined",
        "mood_tracker":     False,
        "quote_pages_pct":  0.02,
        # Pomodoro/focus heavy + 3-block + habit-heavy
        "daily_layouts":    ["focus", "c", "focus", "d", "b"],
    },
    # ── Spiritual / esoteric ─────────────────────────────────────────────
    "mystic_lush": {
        "name": "mystic_lush",
        "ornament_density": "high",
        "section_banner":   "framed",
        "line_style":       "solid",
        "quote_pages_pct":  0.12,
        "daily_layouts":    ["wellness", "a", "d", "a"],
    },
    # ── Hobby logs (sketch + table) ──────────────────────────────────────
    "hobby_field": {
        "name": "hobby_field",
        "ornament_density": "low",
        "section_banner":   "stripe",
        "line_style":       "solid",
        "mood_tracker":     False,
    },
    # ── Kids ─────────────────────────────────────────────────────────────
    "kids_playful": {
        "name": "kids_playful",
        "ornament_density": "high",
        "corner_motif":     True,
        "section_banner":   "framed",
        "line_style":       "solid",
        "mood_tracker":     False,
    },
    # ── Medical / health trackers ────────────────────────────────────────
    "medical_clean": {
        "name": "medical_clean",
        "ornament_density": "low",
        "corner_motif":     False,
        "section_banner":   "stripe",
        "line_style":       "lined",
        "mood_tracker":     False,
        "quote_pages_pct":  0.00,
        # Wellness layout adapts very well to symptom-tracker style books
        "daily_layouts":    ["wellness", "a", "wellness"],
    },
    # ── Quiz / trivia ────────────────────────────────────────────────────
    "trivia_bold": {
        "name": "trivia_bold",
        "ornament_density": "medium",
        "section_banner":   "framed",
        "line_style":       "solid",
        "mood_tracker":     False,
        "quote_pages_pct":  0.00,
    },
    # ── Adult coloring ───────────────────────────────────────────────────
    "coloring_minimal_frames": {
        "name": "coloring_minimal_frames",
        "ornament_density": "low",
        "corner_motif":     False,
        "section_banner":   "minimal",
        "mood_tracker":     False,
        "quote_pages_pct":  0.00,
    },
    # ── Puzzles (generic) ────────────────────────────────────────────────
    "puzzle_clean": {
        "name": "puzzle_clean",
        "ornament_density": "low",
        "corner_motif":     False,
        "section_banner":   "stripe",
        "line_style":       "solid",
        "mood_tracker":     False,
        "quote_pages_pct":  0.00,
    },
    # ── Large-print seniors (puzzles + journals) ─────────────────────────
    "large_print_seniors": {
        "name": "large_print_seniors",
        "ornament_density": "low",
        "corner_motif":     False,
        "section_banner":   "minimal",
        "line_style":       "lined",
        "mood_tracker":     False,
        "quote_pages_pct":  0.00,
        "large_print":      True,
        # Keep clean classic layout — seniors prefer predictability
        "daily_layouts":    ["a"],
    },
}


# Keyword → preset selector. First match wins.
_NICHE_RULES = [
    # Large-print seniors wins over everything else if both signals match.
    (("large print", "seniors", "elderly", "dementia",
      "low vision", "easy on the eyes"),
     "large_print_seniors"),

    # Puzzles before more generic patterns so puzzle_clean wins.
    (("maze", "sudoku", "kakuro", "kenken", "nonogram", "picross",
      "cryptogram", "word search", "wordsearch", "logic puzzle",
      "dot to dot", "dot-to-dot", "brain teaser", "puzzle book",
      "activity book", "brain games"),
     "puzzle_clean"),

    (("anxiety", "depression", "trauma", "ptsd", "grief", "healing",
      "self care", "self-care", "mindfulness", "gratitude", "calm"),
     "wellness_calm"),

    (("planner", "productivity", "etsy", "freelance", "entrepreneur",
      "marketing", "consultant", "business"),
     "productivity_clean"),

    (("manifestation", "tarot", "witch", "spell", "ritual", "chakra",
      "moon", "astrology", "spirit", "shadow work"),
     "mystic_lush"),

    (("fishing", "hunting", "beekeep", "aquarium", "garden",
      "vinyl", "trading card", "pokemon", "foraging", "rock climb",
      "sourdough", "brew", "ferment", "ham radio"),
     "hobby_field"),

    (("kids", "children", "toddler", "preschool", "boys", "girls",
      "ages 4", "ages 5", "ages 6", "ages 7", "ages 8"),
     "kids_playful"),

    (("symptom", "tracker", "cgm", "insulin", "blood pressure",
      "migraine", "fibro", "lupus", "ibs", "endometriosis",
      "cpap", "diabetes", "autoimmune"),
     "medical_clean"),

    (("trivia", "quiz", "would you rather", "never have i ever",
      "facts book", "conversation"),
     "trivia_bold"),

    (("coloring",),
     "coloring_minimal_frames"),
]


def pick_preset(niche: str) -> Dict:
    """Returns a complete preset dict (DEFAULT merged with sub-niche override)."""
    nl = (niche or "").lower()
    for triggers, preset_key in _NICHE_RULES:
        if any(t in nl for t in triggers):
            return {**DEFAULT_PRESET, **PRESETS[preset_key]}
    return dict(DEFAULT_PRESET)


def preset_summary(preset: Dict) -> str:
    """Compact one-line label for status logs."""
    return (
        f"{preset.get('name','default')} · ornament={preset.get('ornament_density','?')}"
        f" · banner={preset.get('section_banner','?')}"
        f" · lines={preset.get('line_style','?')}"
    )
