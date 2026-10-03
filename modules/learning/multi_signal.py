"""
Multi-signal quality fusion — produces a single "true_quality" 0-100 per book
by combining 5 independent signals:

  1. User feedback (👍 / 👎 / ✅ published)        weight: 35
  2. Validator quality score                       weight: 25
  3. Time to publish (faster = better)             weight: 15
  4. Number of auto-fixes used (more = worse)      weight: -15
  5. Number of cover regenerations (more = worse)  weight: -10

Final true_quality = clamped(weighted_sum, 0, 100)

This score is the input for:
  - profile / variant ranking
  - predictive estimator (predicts true_quality before generating)
  - cross-niche knowledge transfer (high-true_quality patterns are spread)
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from modules.learning.feedback import load_all_feedback
from modules.learning.events   import load_events, events_for_slug

logger = logging.getLogger(__name__)


@dataclass
class TrueQuality:
    slug:               str
    true_score:         float            # 0-100
    feedback_score:     float            # raw rating contribution
    validator_score:    Optional[int]    # 0-100 from validator
    time_to_publish_d:  Optional[float]  # days
    n_auto_fixes:       int
    n_cover_regens:     int


# Per-rating contribution (additive to baseline 50)
_RATING_BONUS = {
    "published":  +35,
    "up":         +20,
    "neutral":     0,
    "down":       -25,
}


def _latest_feedback_for(slug: str, feedbacks: list) -> Optional[Dict]:
    """Returns the latest feedback for a product slug (matched by niche/product_id)."""
    matching = [f for f in feedbacks
                if (slug in (f.get("product_id") or "")
                    or slug in (f.get("niche") or "").lower().replace(" ", "-"))]
    if not matching:
        return None
    matching.sort(key=lambda f: f.get("ts") or "", reverse=True)
    return matching[0]


import functools
import time as _time


_TQ_CACHE: Dict[str, tuple] = {}   # slug → (TrueQuality, expiry_ts)
_TQ_TTL = 60   # seconds


def _cached_tq(slug: str) -> Optional["TrueQuality"]:
    item = _TQ_CACHE.get(slug)
    if item and item[1] > _time.time():
        return item[0]
    return None


def _store_tq(slug: str, tq: "TrueQuality") -> None:
    _TQ_CACHE[slug] = (tq, _time.time() + _TQ_TTL)


def compute_true_quality(
    learning_dir:    Path,
    slug:            str,
    validator_score: Optional[int] = None,
) -> TrueQuality:
    # Fast path: in-memory cache (60s TTL)
    if validator_score is None:
        cached = _cached_tq(slug)
        if cached:
            return cached
    """
    Compute fused 0-100 quality score for a single product.

    `validator_score` can be passed in to avoid re-running validation.
    If omitted, we'll try to load the product folder and validate on-the-fly.
    """
    feedbacks = load_all_feedback(learning_dir)
    fb = _latest_feedback_for(slug, feedbacks)
    events = events_for_slug(learning_dir, slug)

    # ── Signal 1: feedback ────────────────────────────────────────────
    feedback_score = 50.0   # neutral baseline
    if fb:
        feedback_score += _RATING_BONUS.get(fb.get("rating"), 0)

    # ── Signal 2: validator score ─────────────────────────────────────
    if validator_score is None:
        try:
            from pathlib import Path as _P
            from modules.quality.validator import validate_product
            folder = _P.home() / "Desktop" / "KDP" / slug
            if not folder.exists():
                folder = _P.home() / "Desktop" / "KDP" / "published" / slug
            if folder.exists():
                v = validate_product(folder)
                validator_score = v.score
        except Exception:
            validator_score = None

    # ── Signal 3: time to publish ─────────────────────────────────────
    time_to_publish_d: Optional[float] = None
    if fb and fb.get("rating") == "published":
        published_at = fb.get("ts")
        # Try to infer creation time from product folder
        try:
            from datetime import datetime
            from pathlib import Path as _P
            for base in (_P.home() / "Desktop" / "KDP" / slug,
                         _P.home() / "Desktop" / "KDP" / "published" / slug):
                if base.exists() and (base / "listing.json").exists():
                    created = datetime.fromtimestamp((base / "listing.json").stat().st_mtime)
                    if published_at:
                        pub = datetime.fromisoformat(published_at[:19])
                        time_to_publish_d = (pub - created).total_seconds() / 86400.0
                    break
        except Exception:
            pass

    # ── Signals 4, 5: event counts ────────────────────────────────────
    n_auto_fixes  = sum(1 for e in events if e.get("kind") == "auto_fix_used")
    n_cover_regen = sum(1 for e in events if e.get("kind") == "cover_regen")
    n_cover_pick  = sum(1 for e in events if e.get("kind") == "cover_picked")

    # ── Weighted fusion ───────────────────────────────────────────────
    # All on a 0-100 scale before weighting
    parts = []
    parts.append(("feedback",   feedback_score,                          0.35))
    if validator_score is not None:
        parts.append(("validator", float(validator_score),               0.25))
    # Time to publish: 0 days = 100, 14+ days = 0
    if time_to_publish_d is not None:
        ttp_score = max(0, 100 - (time_to_publish_d / 14.0) * 100)
        parts.append(("time_to_pub", ttp_score,                          0.15))
    # Penalties (subtract from 100)
    fix_penalty   = max(0, 100 - n_auto_fixes  * 25)   # 4 fixes = 0
    regen_penalty = max(0, 100 - n_cover_regen * 20)   # 5 regens = 0
    pick_bonus    = min(100, 50 + n_cover_pick * 15)   # picks are positive
    parts.append(("auto_fix_penalty",   fix_penalty,    0.10))
    parts.append(("cover_regen_pen.",   regen_penalty,  0.08))
    parts.append(("cover_pick_bonus",   pick_bonus,     0.07))

    total_weight = sum(w for _, _, w in parts)
    if total_weight == 0:
        true_score = 50.0
    else:
        true_score = sum(s * w for _, s, w in parts) / total_weight

    true_score = max(0.0, min(100.0, true_score))

    result = TrueQuality(
        slug              = slug,
        true_score        = round(true_score, 1),
        feedback_score    = feedback_score,
        validator_score   = validator_score,
        time_to_publish_d = (round(time_to_publish_d, 1)
                             if time_to_publish_d is not None else None),
        n_auto_fixes      = n_auto_fixes,
        n_cover_regens    = n_cover_regen,
    )
    _store_tq(slug, result)
    return result


def all_true_qualities(learning_dir: Path, slugs: list) -> Dict[str, TrueQuality]:
    """Batch compute true_quality for a list of product slugs."""
    return {s: compute_true_quality(learning_dir, s) for s in slugs}
