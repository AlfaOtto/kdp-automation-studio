"""
Predictive Recommender — what to generate NEXT.

Combines:
  - predictor.predict() : predicted true_quality for (variant, theme)
  - crème scan history : niches you analyzed with their competition score
  - market intel (if cached) : trending categories
  - transfer.transfer_suggestions : winning patterns from similar themes

Output: ranked list of (niche, predicted_score, competition, variant_to_use, rationale).
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from modules.learning.predictor import predict, best_combo_for_niche
from modules.learning.transfer  import transfer_suggestions

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    niche:            str
    predicted_score:  float       # 0-100 expected true_quality
    competition:      int         # 0-100, lower is less competitive
    confidence:       float       # 0-1
    variant_to_use:   Optional[str]
    theme_to_use:     Optional[str]
    rationale:        str


def _load_creme_history(history_dir: Path) -> List[Dict]:
    """Load all crème scan results, flatten niche records."""
    out = []
    p = Path(history_dir)
    if not p.exists():
        return out
    for f in p.glob("creme_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            creme = data.get("creme") or data.get("all_results") or []
            for n in creme:
                if isinstance(n, dict) and n.get("keyword"):
                    out.append(n)
        except Exception:
            continue
    return out


def recommend_next_niches(
    learning_dir: Path,
    history_dir:  Path,
    n: int = 10,
    min_predicted: float = 60.0,
) -> List[Recommendation]:
    """
    Score every niche from past crème scans by predicted quality × competition.
    Returns top N opportunities.
    """
    candidates = _load_creme_history(history_dir)
    if not candidates:
        return []

    # Dedupe by keyword (keep best creme_score)
    by_kw: Dict[str, Dict] = {}
    for c in candidates:
        kw = c.get("keyword", "")
        prev = by_kw.get(kw)
        if not prev or c.get("creme_score", 0) > prev.get("creme_score", 0):
            by_kw[kw] = c

    try:
        from modules.creation.niche_themes import detect_theme
    except Exception:
        detect_theme = None

    recs: List[Recommendation] = []
    for kw, c in by_kw.items():
        theme = None
        if detect_theme:
            try:
                theme = detect_theme(kw).get("name")
            except Exception:
                pass
        # Predict quality from our history
        pred_score, conf, n_obs = predict(learning_dir, theme=theme)
        # Competition: lower avg_reviews = less competitive (we want LOW)
        avg_reviews = c.get("avg_reviews", 100)
        competition = min(100, int(avg_reviews))
        if pred_score < min_predicted:
            continue
        best = best_combo_for_niche(learning_dir, theme=theme)
        variant = best[0] if best else None
        # Composite score: high predicted × low competition × creme_score
        creme_score = c.get("creme_score", c.get("overall", 50))
        composite = (
            pred_score * 0.40
            + (100 - competition) * 0.30
            + creme_score * 0.30
        )
        rationale_parts = [
            f"creme {creme_score:.0f}",
            f"avg_reviews {avg_reviews}",
        ]
        if n_obs:
            rationale_parts.append(f"pred conf {int(conf*100)}% (n={n_obs})")
        if best:
            rationale_parts.append(f"best variant: {variant}")
        rationale = " · ".join(rationale_parts)
        recs.append(Recommendation(
            niche=kw, predicted_score=round(pred_score, 1),
            competition=competition, confidence=conf,
            variant_to_use=variant, theme_to_use=theme,
            rationale=rationale,
        ))
        # Track composite for sorting
        recs[-1]._composite = composite   # type: ignore

    recs.sort(key=lambda r: -getattr(r, "_composite", 0))
    return recs[:n]


def daily_action_list(
    learning_dir: Path,
    history_dir:  Path,
    n_to_generate: int = 5,
) -> Dict:
    """Returns a structured action list for the user."""
    recs = recommend_next_niches(learning_dir, history_dir, n=n_to_generate)
    return {
        "to_generate": recs,
        "n":           len(recs),
        "summary":     (f"{len(recs)} niches recommandées pour aujourd'hui."
                        if recs else "Pas assez de données — lance d'abord un scan Crème + note tes 1ers livres."),
    }
