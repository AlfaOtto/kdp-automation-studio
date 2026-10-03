"""
User profile aggregator — turns raw feedback into actionable preferences.

The profile drives every future generation:
  - Which variants to bias toward
  - Which themes the user keeps publishing
  - Title patterns the user approves (length, structure, keywords)
  - Keywords that consistently appear in winning books

Profile is rebuilt from feedback.jsonl on demand (no caching needed for
hundreds of entries — fast enough).
"""
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from modules.learning.feedback import load_all_feedback

logger = logging.getLogger(__name__)

# How much weight each rating gets when scoring preferences
_RATING_WEIGHT = {
    "published":  3.0,   # strongest signal — actually shipped to KDP
    "up":         1.0,
    "neutral":    0.0,
    "down":      -2.0,   # strong negative
}


def _ranking_to_score(rating: str) -> float:
    return _RATING_WEIGHT.get(rating, 0.0)


def _latest_per_product(entries: List[Dict]) -> List[Dict]:
    """Keep only the latest rating per product_id."""
    seen: Dict[str, Dict] = {}
    for e in entries:
        pid = e.get("product_id")
        if pid:
            seen[pid] = e
    return list(seen.values())


def build_profile(learning_dir: Path) -> Dict:
    """
    Aggregates all feedback into a single profile dict.
    Returns:
      {
        "n_total":      int,          # total products with feedback
        "n_positive":   int,          # up + published
        "n_negative":   int,          # down
        "variant_scores": {variant_id: score, ...},
        "theme_scores":   {theme: score, ...},
        "product_type_scores": {type: score, ...},
        "title_avg_len":  float,      # avg title char length user approved
        "title_keywords": [(word, count), ...],
        "preferred_publishers": [(name, count), ...],
        "top_variant":    variant_id  or None,
        "top_theme":      theme       or None,
        "ready":          bool        # True if we have >= 3 ratings
      }
    """
    entries = _latest_per_product(load_all_feedback(learning_dir))

    profile = {
        "n_total":              len(entries),
        "n_positive":           0,
        "n_negative":           0,
        "variant_scores":       {},
        "theme_scores":         {},
        "product_type_scores":  {},
        "title_avg_len":        0.0,
        "title_keywords":       [],
        "preferred_publishers": [],
        "top_variant":          None,
        "top_theme":            None,
        "top_product_type":     None,
        "ready":                len(entries) >= 3,
    }

    if not entries:
        return profile

    title_lens: List[int]   = []
    title_words: Counter    = Counter()
    publishers: Counter     = Counter()
    variant_scores: Dict[str, float]   = {}
    theme_scores: Dict[str, float]     = {}
    ptype_scores: Dict[str, float]     = {}

    stop_words = {
        "the","a","an","of","and","or","for","to","in","on","with","your",
        "this","that","is","are","was","be","by","at","as","you","my","i",
    }

    for e in entries:
        rating = e.get("rating", "neutral")
        score = _ranking_to_score(rating)

        if score > 0:
            profile["n_positive"] += 1
        elif score < 0:
            profile["n_negative"] += 1

        # Variant
        v = e.get("variant_id")
        if v:
            variant_scores[v] = variant_scores.get(v, 0.0) + score

        # Theme
        t = e.get("theme_name")
        if t:
            theme_scores[t] = theme_scores.get(t, 0.0) + score

        # Product type
        pt = e.get("product_type")
        if pt:
            ptype_scores[pt] = ptype_scores.get(pt, 0.0) + score

        # Title patterns (only learn from positive signals)
        if score > 0 and e.get("title"):
            title = e["title"]
            title_lens.append(len(title))
            for word in re.findall(r"\b[a-zA-Z]{4,}\b", title.lower()):
                if word not in stop_words:
                    title_words[word] += 1

        # Publishers (positive signals)
        if score > 0 and e.get("publisher"):
            publishers[e["publisher"]] += 1

    profile["variant_scores"]      = variant_scores
    profile["theme_scores"]        = theme_scores
    profile["product_type_scores"] = ptype_scores

    if variant_scores:
        profile["top_variant"] = max(variant_scores.items(), key=lambda kv: kv[1])[0]
    if theme_scores:
        profile["top_theme"]   = max(theme_scores.items(), key=lambda kv: kv[1])[0]
    if ptype_scores:
        profile["top_product_type"] = max(ptype_scores.items(), key=lambda kv: kv[1])[0]

    if title_lens:
        profile["title_avg_len"] = round(sum(title_lens) / len(title_lens), 1)
    profile["title_keywords"]       = title_words.most_common(12)
    profile["preferred_publishers"] = publishers.most_common(5)

    return profile


def profile_summary_for_prompt(profile: Dict) -> str:
    """
    Returns a concise sentence injected into Claude/gpt-image prompts.
    Empty string if profile isn't ready yet.
    """
    if not profile.get("ready"):
        return ""

    parts = []
    if profile.get("title_avg_len"):
        parts.append(f"User's approved titles average {profile['title_avg_len']:.0f} characters")
    kws = [w for w, _ in profile.get("title_keywords", [])[:5]]
    if kws:
        parts.append(f"keywords frequent in their winning titles: {', '.join(kws)}")
    if profile.get("top_variant"):
        parts.append(f"user prefers '{profile['top_variant']}' visual style")
    if profile.get("preferred_publishers"):
        pubs = [p for p, _ in profile["preferred_publishers"][:2]]
        parts.append(f"likes publisher names like: {', '.join(pubs)}")

    if not parts:
        return ""
    return "USER PREFERENCES (from past wins): " + "; ".join(parts) + "."


def recommend_variant(profile: Dict, default_variant_id: str) -> str:
    """Returns the variant_id the user has approved most often (or default)."""
    scores = profile.get("variant_scores") or {}
    if not scores:
        return default_variant_id
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else default_variant_id


def approval_rate(profile: Dict, variant_id: str) -> Optional[float]:
    """Returns approval rate (0-1) for a specific variant, or None."""
    score = profile.get("variant_scores", {}).get(variant_id, 0.0)
    # Rough estimate: positive score / 3 (since published=3)
    if profile["n_positive"] + profile["n_negative"] < 2:
        return None
    if score <= 0:
        return 0.0
    return min(1.0, score / max(3.0, profile["n_positive"]))
