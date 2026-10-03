"""
Edit-based learning — extracts patterns from how the user EDITS the listings
Claude generates. Strong signal: edits are explicit corrections.

Patterns detected:
  - shorten_titles      : user consistently makes titles shorter
  - lengthen_titles     : user makes them longer
  - add_numbers         : user adds digits (e.g. "50 Designs")
  - remove_numbers      : user removes digits
  - capitalize_more     : user makes titles MORE UPPERCASE
  - remove_filler_words : user removes "Ultimate", "Complete", "Amazing", etc.
  - shorten_subtitles   : same for subtitles
  - bold_descriptions   : user adds <b> in descriptions
"""
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from modules.learning.events import load_events

logger = logging.getLogger(__name__)


_FILLER_WORDS = {
    "ultimate", "complete", "amazing", "incredible", "essential",
    "best", "perfect", "comprehensive", "definitive", "extraordinary",
    "remarkable", "exceptional", "outstanding",
}


def extract_edit_patterns(learning_dir: Path) -> Dict[str, int]:
    """Returns a Counter of pattern_name → count across all edits."""
    edits = [e for e in load_events(learning_dir) if e.get("kind") == "listing_edit"]
    patterns: Counter = Counter()
    for e in edits:
        before = (e.get("before") or "").strip()
        after  = (e.get("after") or "").strip()
        field  = e.get("field", "")
        if not before or not after:
            continue

        delta = len(after) - len(before)
        # Title patterns
        if field == "title":
            if delta < -10:    patterns["shorten_titles"] += 1
            elif delta > 10:   patterns["lengthen_titles"] += 1
            before_nums = bool(re.search(r"\d", before))
            after_nums  = bool(re.search(r"\d", after))
            if not before_nums and after_nums: patterns["add_numbers_title"] += 1
            if before_nums and not after_nums: patterns["remove_numbers_title"] += 1
            b_upper = sum(1 for c in before if c.isupper())
            a_upper = sum(1 for c in after  if c.isupper())
            if a_upper > b_upper * 1.5: patterns["capitalize_more_title"] += 1
            for w in _FILLER_WORDS:
                if w in before.lower() and w not in after.lower():
                    patterns[f"remove_filler:{w}"] += 1
        elif field == "subtitle":
            if delta < -10:    patterns["shorten_subtitles"] += 1
            elif delta > 10:   patterns["lengthen_subtitles"] += 1
            if not bool(re.search(r"\d", before)) and bool(re.search(r"\d", after)):
                patterns["add_numbers_subtitle"] += 1
        elif field == "description":
            if "<b>" not in before and "<b>" in after:
                patterns["bold_descriptions"] += 1
            if delta < -50:    patterns["shorten_descriptions"] += 1

    return dict(patterns)


def patterns_for_prompt(learning_dir: Path, min_count: int = 2) -> str:
    """
    Returns a plain-text block to inject into Claude prompts so future
    generations pre-emptively follow the user's edit conventions.
    Only includes patterns observed at least `min_count` times.
    """
    p = extract_edit_patterns(learning_dir)
    if not p:
        return ""
    rules = []
    if p.get("shorten_titles", 0) >= min_count:
        rules.append(f"- User consistently SHORTENS titles ({p['shorten_titles']}× edits). "
                     f"Keep titles under 60 chars.")
    if p.get("lengthen_titles", 0) >= min_count:
        rules.append(f"- User EXTENDS titles ({p['lengthen_titles']}× edits). "
                     f"Aim for 80-150 chars.")
    if p.get("add_numbers_title", 0) >= min_count:
        rules.append(f"- User often ADDS a NUMBER to titles ({p['add_numbers_title']}× edits). "
                     f"Include a concrete count (e.g. '50 Pages', '100 Prompts').")
    if p.get("remove_numbers_title", 0) >= min_count:
        rules.append("- User REMOVES numbers from titles — avoid digits in title.")
    if p.get("capitalize_more_title", 0) >= min_count:
        rules.append("- User CAPITALIZES title words — use Title Case rigorously.")
    filler_removals = [k for k in p if k.startswith("remove_filler:") and p[k] >= min_count]
    if filler_removals:
        words = [k.split(":", 1)[1] for k in filler_removals]
        rules.append(f"- User REMOVES filler words : {', '.join(words)} — avoid them.")
    if p.get("bold_descriptions", 0) >= min_count:
        rules.append("- User ADDS <b> tags to descriptions — use bold for key benefits.")
    if p.get("shorten_descriptions", 0) >= min_count:
        rules.append("- User SHORTENS descriptions — keep them tight, ~1500-2000 chars.")
    if not rules:
        return ""
    return "LEARNED EDIT CONVENTIONS (from your past corrections):\n" + "\n".join(rules)
