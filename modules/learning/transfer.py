"""
Cross-niche knowledge transfer — propagates winning patterns across niches
that share thematic similarity.

Example: if 'editorial + warm-classic' wins on journals, when user creates
a log book (different niche, same 'editorial' family) the bot proactively
suggests warm-classic.

Theme groups (from modules/creation/niche_themes.py) act as the bridge:
  - journals × log × planner   → "writing" family
  - quiz × trivia × puzzle      → "games" family
  - coloring × art × craft      → "creative" family
"""
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.learning.feedback     import load_all_feedback
from modules.learning.multi_signal import compute_true_quality

logger = logging.getLogger(__name__)


# Theme similarity groups: which theme families share design preferences
_THEME_FAMILIES = {
    "writing":  {"journal", "log", "planner", "diary", "notebook", "memoir"},
    "games":    {"quiz", "trivia", "puzzle", "crossword"},
    "creative": {"coloring", "art", "craft", "sketch", "draw"},
    "wellness": {"yoga", "meditation", "mindfulness", "spirit", "tarot"},
    "lifestyle":{"recipe", "cooking", "garden", "travel", "fashion"},
    "tech":     {"productivity", "business", "code", "tech", "startup"},
}


def _theme_family(theme: Optional[str]) -> Optional[str]:
    """Returns the family for a theme (or None if unknown)."""
    if not theme:
        return None
    t = theme.lower()
    for family, members in _THEME_FAMILIES.items():
        if any(m in t for m in members):
            return family
    return None


def winning_patterns_for_family(
    learning_dir: Path,
    family:       str,
    min_score:    float = 65.0,
) -> Dict:
    """
    Aggregates winning patterns from books in the same theme family.
    Returns a dict with:
      - top_variants : Counter of variant_id (most winning first)
      - top_themes   : Counter of theme_name within the family
      - n_wins       : number of contributing wins
      - avg_quality  : average true_quality among wins
    """
    feedbacks = load_all_feedback(learning_dir)
    variant_wins: Counter = Counter()
    theme_wins:   Counter = Counter()
    scores: List[float] = []
    seen = set()
    for f in feedbacks:
        slug = (f.get("niche") or "").lower().replace(" ", "-")
        if slug in seen:
            continue
        seen.add(slug)
        fam = _theme_family(f.get("theme_name"))
        if fam != family:
            continue
        tq = compute_true_quality(learning_dir, slug)
        if tq.true_score < min_score:
            continue
        if f.get("variant_id"):
            variant_wins[f["variant_id"]] += 1
        if f.get("theme_name"):
            theme_wins[f["theme_name"]] += 1
        scores.append(tq.true_score)

    return {
        "top_variants": variant_wins,
        "top_themes":   theme_wins,
        "n_wins":       len(scores),
        "avg_quality":  round(sum(scores) / len(scores), 1) if scores else 0,
    }


def transfer_suggestions(
    learning_dir: Path,
    target_theme: Optional[str],
) -> Dict:
    """
    For a new book with `target_theme`, returns suggestions from the same
    family of themes (cross-niche transfer).

    Result:
      {
        "family":         "writing",
        "best_variant":   "warm-classic",
        "best_theme":     "literary",
        "rationale":      "Based on 4 wins in writing family",
        "confidence":     0.65,
      }
    """
    family = _theme_family(target_theme)
    if not family:
        return {}
    patterns = winning_patterns_for_family(learning_dir, family)
    if patterns["n_wins"] < 2:
        return {}
    best_v = patterns["top_variants"].most_common(1)
    best_t = patterns["top_themes"].most_common(1)
    return {
        "family":       family,
        "best_variant": best_v[0][0] if best_v else None,
        "best_theme":   best_t[0][0] if best_t else None,
        "n_wins":       patterns["n_wins"],
        "avg_quality":  patterns["avg_quality"],
        "confidence":   min(1.0, patterns["n_wins"] / 5),
        "rationale":    (
            f"Based on {patterns['n_wins']} wins in '{family}' family "
            f"(avg quality {patterns['avg_quality']}/100)"
        ),
    }


def transfer_prompt(learning_dir: Path, target_theme: Optional[str]) -> str:
    """Plain-text injection for Claude prompts."""
    sug = transfer_suggestions(learning_dir, target_theme)
    if not sug:
        return ""
    lines = ["CROSS-NICHE TRANSFER (similar themes' winning patterns):"]
    if sug.get("best_variant"):
        lines.append(f"- Family '{sug['family']}' wins with variant '{sug['best_variant']}'")
    if sug.get("best_theme"):
        lines.append(f"- Theme '{sug['best_theme']}' dominates this family")
    lines.append(f"- Rationale: {sug['rationale']}")
    return "\n".join(lines)
