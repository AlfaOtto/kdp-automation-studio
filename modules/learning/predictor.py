"""
Predictive quality estimator — uses past true_quality scores to predict
how a new (niche, variant, theme, palette, typo) combination will perform.

Used BEFORE generation to:
  - warn user if prediction is low
  - suggest a better (variant, theme) for the niche
  - shape the strategy module's explore/exploit balance
"""
import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.learning.feedback     import load_all_feedback
from modules.learning.events       import load_events
from modules.learning.multi_signal import compute_true_quality

logger = logging.getLogger(__name__)


def _key(variant: Optional[str], theme: Optional[str]) -> str:
    return f"{variant or '_'}|{theme or '_'}"


def build_combo_index(learning_dir: Path) -> Dict[str, List[float]]:
    """
    Returns a dict: "variant|theme" → list of true_quality scores observed.
    Used to predict how a new (variant, theme) combo will perform.
    """
    feedbacks = load_all_feedback(learning_dir)
    # Aggregate by (variant, theme) using true_quality
    by_combo: Dict[str, List[float]] = defaultdict(list)
    seen_slugs = set()
    for f in feedbacks:
        slug = (f.get("niche") or "").lower().replace(" ", "-")
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        variant = f.get("variant_id")
        theme   = f.get("theme_name")
        if not variant and not theme:
            continue
        tq = compute_true_quality(learning_dir, slug)
        by_combo[_key(variant, theme)].append(tq.true_score)
    return dict(by_combo)


def predict(
    learning_dir: Path,
    variant:      Optional[str] = None,
    theme:        Optional[str] = None,
    default:      float = 50.0,
) -> Tuple[float, float, int]:
    """
    Predicts the true_quality (0-100) for a new book with given (variant, theme).
    Returns (predicted_score, confidence_0_to_1, n_observations).

    Strategy:
      - If exact (variant, theme) has data → use its mean
      - Else fallback to marginal mean (variant only, theme only)
      - Else fallback to overall mean
      - Confidence scales with sqrt(n_obs / 5) up to 1.0
    """
    idx = build_combo_index(learning_dir)
    exact_key  = _key(variant, theme)
    if exact_key in idx and len(idx[exact_key]) >= 1:
        scores = idx[exact_key]
        return (
            sum(scores) / len(scores),
            min(1.0, math.sqrt(len(scores) / 5)),
            len(scores),
        )

    # Fallback to marginals
    variant_scores: List[float] = []
    theme_scores:   List[float] = []
    for k, scores in idx.items():
        v, t = k.split("|")
        if variant and v == variant:
            variant_scores.extend(scores)
        if theme and t == theme:
            theme_scores.extend(scores)
    marginals = variant_scores + theme_scores
    if marginals:
        return (
            sum(marginals) / len(marginals),
            min(0.6, math.sqrt(len(marginals) / 10)),
            len(marginals),
        )

    # Overall fallback
    all_scores = [s for scores in idx.values() for s in scores]
    if all_scores:
        return (
            sum(all_scores) / len(all_scores),
            0.2,
            len(all_scores),
        )
    return default, 0.0, 0


def best_combo_for_niche(
    learning_dir: Path,
    theme:        Optional[str] = None,
    available_variants: Optional[List[str]] = None,
) -> Optional[Tuple[str, float]]:
    """
    Returns (best_variant, predicted_score) for a given theme.
    Picks the variant with the highest predicted true_quality.
    """
    idx = build_combo_index(learning_dir)
    if not idx:
        return None
    candidates = []
    if available_variants is None:
        # Auto-discover variants from observations
        available_variants = list({k.split("|")[0] for k in idx})
    for v in available_variants:
        if v == "_":
            continue
        score, conf, n = predict(learning_dir, variant=v, theme=theme)
        if n > 0:
            candidates.append((v, score, conf, n))
    if not candidates:
        return None
    # Sort by score × confidence (avoid recommending an untested variant)
    candidates.sort(key=lambda x: -x[1] * x[2])
    return candidates[0][0], candidates[0][1]
