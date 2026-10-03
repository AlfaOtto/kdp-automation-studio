"""
Auto-improvement layer — beyond auto_fix.py which only patches issues.

Auto-improve PROACTIVELY regenerates assets to push the quality score higher,
even if no critical issue exists. Use cases:

  - improve_cover : if cover visual score is mediocre (saturation low,
                    contrast low, brightness off), regen up to N times
                    and KEEP THE BEST (highest validator score).
  - improve_interior : regenerate interior up to N times if page count
                       mismatches or thin content. Keep best.
"""
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ImproveResult:
    asset:           str       # 'cover' | 'interior'
    n_attempts:      int
    initial_score:   int
    best_score:      int
    kept_attempt:    int
    history:         list      # list of (attempt, score, summary)


def _score_cover_quality(folder: Path) -> Tuple[int, str]:
    """Returns (visual_score_0_100, summary_str) for the cover only."""
    from modules.quality.visual import analyze_cover
    cover = folder / "cover.pdf"
    if not cover.exists():
        return 0, "missing"
    v = analyze_cover(cover)
    if not v.rendered:
        return 0, "unreadable"
    # Weighted score: brightness centered around 100-180, contrast >=40, sat >=0.25
    score = 100
    # Brightness penalty (best around 100-180)
    if v.brightness < 50 or v.brightness > 220:
        score -= 25
    elif v.brightness < 80 or v.brightness > 200:
        score -= 10
    # Contrast penalty
    if v.contrast < 30:
        score -= 25
    elif v.contrast < 45:
        score -= 10
    # Saturation
    if v.dominant_sat < 0.20:
        score -= 20
    elif v.dominant_sat < 0.35:
        score -= 8
    # Hue variance
    if v.color_variance < 0.20:
        score -= 10
    score = max(0, min(100, score))
    summary = (
        f"brightness={v.brightness:.0f} contrast={v.contrast:.0f} "
        f"sat={v.dominant_sat:.2f} hues={v.color_variance:.2f}"
    )
    return score, summary


def improve_cover(
    product_folder: Path,
    anthropic_key:  str,
    openai_key:     str,
    learning_dir:   Optional[Path] = None,
    max_attempts:   int = 3,
    min_target:     int = 75,
    status_cb:      Optional[Callable[[str], None]] = None,
    force:          bool = True,
) -> ImproveResult:
    """
    Regenerate cover up to max_attempts times, keep the visually highest-scoring.

    `force=True` (default for UI clicks) : always run all attempts, ignore the
                  early-exit even if initial score is already high — the user
                  explicitly asked, so the design improvements (gradient fade,
                  font diversity, new typo strategy) must be applied.
    `force=False` : skip if score already ≥ min_target (for batch contexts).
    """
    def s(msg):
        if status_cb: status_cb(msg)

    product_folder = Path(product_folder)
    cover = product_folder / "cover.pdf"
    backup_dir = product_folder / ".cover_candidates"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Baseline
    init_score, init_summary = _score_cover_quality(product_folder)
    s(f"📊 Score visuel actuel : {init_score}/100 ({init_summary})")

    history: list = [(0, init_score, init_summary)]
    best_score = init_score
    best_idx = 0
    # Save initial as candidate_0 (so user can compare in A/B view)
    if cover.exists():
        shutil.copy(cover, backup_dir / "candidate_0.pdf")

    if init_score >= min_target and not force:
        s(f"✅ Score déjà ≥{min_target} — pas besoin de régénérer (force=False)")
        return ImproveResult("cover", 0, init_score, init_score, 0, history)
    if init_score >= min_target and force:
        s(f"ℹ️ Score déjà bon ({init_score}) — régénération forcée pour appliquer "
          f"les améliorations design (gradient fade, fonts, typo strategy)")

    from modules.creation.batch import regenerate_cover_only

    for attempt in range(1, max_attempts + 1):
        s(f"🎨 Tentative {attempt}/{max_attempts} de régénération…")
        try:
            regenerate_cover_only(
                product_dir   = product_folder,
                anthropic_key = anthropic_key,
                openai_key    = openai_key,
                status_cb     = lambda m: None,
                learning_dir  = learning_dir,
                free_style    = True,
            )
        except Exception as e:
            s(f"   ⚠️ Régen #{attempt} échouée : {e}")
            continue
        score, summary = _score_cover_quality(product_folder)
        history.append((attempt, score, summary))
        s(f"   → score #{attempt} : {score}/100 ({summary})")
        # Save candidate
        if cover.exists():
            shutil.copy(cover, backup_dir / f"candidate_{attempt}.pdf")
        if score > best_score:
            best_score = score
            best_idx = attempt
            s(f"   🏆 Nouveau meilleur : #{attempt} ({score}/100)")
        if score >= min_target:
            s(f"   ✅ Cible {min_target} atteinte — arrêt")
            break

    # Restore the best candidate as the active cover
    best_candidate = backup_dir / f"candidate_{best_idx}.pdf"
    if best_candidate.exists():
        shutil.copy(best_candidate, cover)
        s(f"💾 Cover #{best_idx} restauré (score {best_score}/100)")

    return ImproveResult("cover", attempt if 'attempt' in dir() else 0,
                         init_score, best_score, best_idx, history)


def get_candidate_paths(product_folder: Path) -> List[Path]:
    """Returns the saved cover candidates so user can pick manually (F mode)."""
    folder = Path(product_folder) / ".cover_candidates"
    if not folder.exists():
        return []
    return sorted(folder.glob("candidate_*.pdf"),
                  key=lambda p: int(p.stem.split("_")[1]))


def use_candidate(product_folder: Path, candidate_idx: int) -> bool:
    """Promote a specific candidate to be the active cover.pdf."""
    folder = Path(product_folder)
    candidate = folder / ".cover_candidates" / f"candidate_{candidate_idx}.pdf"
    if not candidate.exists():
        return False
    shutil.copy(candidate, folder / "cover.pdf")
    return True
