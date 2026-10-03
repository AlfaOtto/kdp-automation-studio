"""
Active learning strategy — the layer that turns the user's profile into
real decisions about which variant to use for the next product.

Implements:
  4. Auto-apply preferred variant  — pick what won most often
  5. Epsilon-greedy explore/exploit — 20% of the time, try something new
  6. Confidence score              — quantify the bot's belief
  8. Cross-niche learning          — leverage theme + product_type history,
                                      not just exact niche matches

(7. Regenerate-on-feedback is wired in app.py UI.)
"""
import logging
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.learning.feedback import load_all_feedback

logger = logging.getLogger(__name__)


# Weight per rating (mirrors profile.py for consistency)
_W = {"published": 3.0, "up": 1.0, "neutral": 0.0, "down": -2.0}

EPSILON = 0.20  # exploration rate (20% chance to try a non-top variant)


def _latest_per_product(entries: List[Dict]) -> List[Dict]:
    seen: Dict[str, Dict] = {}
    for e in entries:
        pid = e.get("product_id")
        if pid:
            seen[pid] = e
    return list(seen.values())


def _score_variants(
    entries: List[Dict],
    filter_fn=None,
) -> Dict[str, Dict[str, float]]:
    """
    Returns {variant_id: {"score": float, "n": int, "wins": int, "losses": int}}.
    filter_fn(entry) -> bool lets us scope to a sub-population (e.g., same theme).
    """
    out: Dict[str, Dict[str, float]] = {}
    for e in entries:
        if filter_fn and not filter_fn(e):
            continue
        v = e.get("variant_id")
        if not v:
            continue
        rating = e.get("rating", "neutral")
        sc = _W.get(rating, 0.0)
        bucket = out.setdefault(v, {"score": 0.0, "n": 0, "wins": 0, "losses": 0})
        bucket["score"] += sc
        bucket["n"]    += 1
        if sc > 0: bucket["wins"]   += 1
        if sc < 0: bucket["losses"] += 1
    return out


def _confidence(score_dict: Dict[str, float]) -> float:
    """
    Computes a 0..1 confidence for the top variant.
    Based on:
      - sample size (n) — more data → higher confidence
      - separation     — top score vs average of others
    Returns 0.0 when no data.
    """
    if not score_dict:
        return 0.0
    n_total = sum(b["n"] for b in score_dict.values())
    if n_total == 0:
        return 0.0

    items = sorted(score_dict.items(), key=lambda kv: kv[1]["score"], reverse=True)
    top    = items[0][1]
    others = [v for _, v in items[1:]]

    # Sample confidence — capped logistic curve on total observations
    # 0 obs → 0, 3 obs → ~0.5, 10 obs → ~0.85, 30 obs → ~0.98
    import math
    sample_conf = 1 - math.exp(-n_total / 6)

    # Separation — how clearly the top variant beats others
    if not others:
        sep_conf = 0.7
    else:
        top_score    = top["score"]
        avg_others   = sum(o["score"] for o in others) / len(others)
        gap = top_score - avg_others
        sep_conf = 1 - math.exp(-max(gap, 0) / 4)

    # Weighted blend
    return round(0.65 * sample_conf + 0.35 * sep_conf, 3)


def choose_variant_for_niche(
    learning_dir: Path,
    niche: str,
    product_type: str,
    theme_name: Optional[str],
    available_variants: List[Dict],
    epsilon: float = EPSILON,
    explore: bool = True,
    excluded_variant_ids: Optional[List[str]] = None,
) -> Tuple[Dict, float, str]:
    """
    Active-learning variant selector.

    Decision tree (most to least specific):
      A. Same product_type + same theme history (cross-niche learning)
      B. Same product_type history
      C. Same theme history
      D. Global history
      E. Hash fallback (deterministic from niche)

    Returns:
      (variant_dict, confidence_0_1, decision_reason)
    """
    excluded_variant_ids = set(excluded_variant_ids or [])

    # Load feedback
    entries = _latest_per_product(load_all_feedback(learning_dir))
    if not entries:
        return _hash_fallback(niche, available_variants, excluded_variant_ids), 0.0, "hash (no history)"

    # ── Build scoped score dicts (most specific to least) ──────────────────
    layers = [
        ("type+theme",
         lambda e: e.get("product_type") == product_type and e.get("theme_name") == theme_name),
        ("same-type",
         lambda e: e.get("product_type") == product_type),
        ("same-theme",
         lambda e: e.get("theme_name") == theme_name) if theme_name else None,
        ("global",
         lambda e: True),
    ]
    layers = [l for l in layers if l is not None]

    chosen_scope: Optional[str] = None
    chosen_scores: Dict[str, Dict[str, float]] = {}
    chosen_n = 0

    for scope_name, fn in layers:
        scores = _score_variants(entries, fn)
        # Need at least 2 entries with variants tagged to be worth using
        n_in_scope = sum(b["n"] for b in scores.values())
        if n_in_scope >= 2:
            chosen_scope  = scope_name
            chosen_scores = scores
            chosen_n      = n_in_scope
            break

    if not chosen_scores:
        return _hash_fallback(niche, available_variants, excluded_variant_ids), 0.0, "hash (no signal)"

    conf = _confidence(chosen_scores)

    # ── Exploration : ε of the time, pick a non-top variant ───────────────
    sorted_variants = sorted(
        chosen_scores.items(),
        key=lambda kv: kv[1]["score"],
        reverse=True,
    )
    available_ids = [v["id"] for v in available_variants if v["id"] not in excluded_variant_ids]
    if not available_ids:
        # All excluded → fallback to all
        available_ids = [v["id"] for v in available_variants]

    # Try the top variants in order until we find one that's available
    top_choice = None
    for vid, _ in sorted_variants:
        if vid in available_ids:
            top_choice = vid
            break

    if top_choice is None:
        return _hash_fallback(niche, available_variants, excluded_variant_ids), conf, f"hash (no top in scope: {chosen_scope})"

    # Decide explore vs exploit
    explore_now = explore and random.random() < epsilon and len(available_ids) > 1
    if explore_now:
        # Pick a random variant that ISN'T the top choice
        candidates = [v for v in available_ids if v != top_choice]
        chosen_id = random.choice(candidates) if candidates else top_choice
        reason = f"explore ({chosen_scope}, ε={epsilon:.0%})"
    else:
        chosen_id = top_choice
        reason = f"exploit ({chosen_scope}, n={chosen_n})"

    variant = next((v for v in available_variants if v["id"] == chosen_id),
                   available_variants[0])
    return variant, conf, reason


def _hash_fallback(
    niche: str,
    available_variants: List[Dict],
    excluded: set,
) -> Dict:
    """Deterministic fallback when no learning signal is available."""
    import hashlib
    candidates = [v for v in available_variants if v["id"] not in excluded]
    if not candidates:
        candidates = available_variants
    h = int(hashlib.md5((niche or "x").encode("utf-8")).hexdigest()[:8], 16)
    return candidates[h % len(candidates)]


def get_variant_stats(learning_dir: Path) -> Dict[str, Dict[str, float]]:
    """Returns full variant score dict for the Intelligence tab."""
    entries = _latest_per_product(load_all_feedback(learning_dir))
    return _score_variants(entries)


def estimate_approval_probability(
    learning_dir: Path,
    variant_id: str,
    product_type: Optional[str] = None,
    theme_name: Optional[str] = None,
) -> Tuple[float, int]:
    """
    Returns (probability_0_1, n_observations) that the user will approve
    this variant — scoped to similar past products (same type + theme).
    """
    entries = _latest_per_product(load_all_feedback(learning_dir))

    def matches(e):
        if e.get("variant_id") != variant_id:
            return False
        if product_type and e.get("product_type") != product_type:
            return False
        if theme_name and e.get("theme_name") != theme_name:
            return False
        return True

    matching = [e for e in entries if matches(e)]

    # If too few specific matches, broaden to any product with this variant
    if len(matching) < 2:
        matching = [e for e in entries if e.get("variant_id") == variant_id]

    if not matching:
        return (0.5, 0)   # neutral prior when no data

    # Probability = positive / (positive + negative + 0.5 for neutral)
    pos = sum(1 for e in matching if _W.get(e.get("rating"), 0) > 0)
    neg = sum(1 for e in matching if _W.get(e.get("rating"), 0) < 0)
    neu = len(matching) - pos - neg

    # Laplace smoothing to avoid 0% / 100% with tiny n
    prob = (pos + 1.0) / (pos + neg + neu + 2.0)
    return (round(prob, 3), len(matching))
