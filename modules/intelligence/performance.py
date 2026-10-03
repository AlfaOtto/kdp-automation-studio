"""
Self-Performance Dashboard — your historical metrics.

Time-series + leaderboards built from feedback + events + multi_signal.
Powers the "Your evolution" tab in Intelligence.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.learning.feedback     import load_all_feedback
from modules.learning.events       import load_events
from modules.learning.multi_signal import compute_true_quality

logger = logging.getLogger(__name__)


@dataclass
class PerformancePoint:
    date:           str        # ISO date
    n_generated:    int
    n_published:    int
    avg_quality:    float
    win_rate:       float


def _bucket_by_week(items: List[Dict], key: str = "ts") -> Dict[str, List[Dict]]:
    """Group by ISO week (YYYY-WW)."""
    out: Dict[str, List[Dict]] = defaultdict(list)
    for it in items:
        ts = it.get(key) or ""
        try:
            d = datetime.fromisoformat(ts[:19])
            wk = d.strftime("%Y-W%V")
            out[wk].append(it)
        except Exception:
            continue
    return out


def weekly_performance(learning_dir: Path, n_weeks: int = 8) -> List[PerformancePoint]:
    """Compute performance for the last N weeks."""
    feedbacks = load_all_feedback(learning_dir)
    by_week = _bucket_by_week(feedbacks)
    out: List[PerformancePoint] = []
    # Last N weeks, latest first
    cutoff = datetime.now() - timedelta(weeks=n_weeks)
    weeks_to_show = sorted([wk for wk in by_week if wk >= cutoff.strftime("%Y-W%V")],
                            reverse=True)
    for wk in weeks_to_show[:n_weeks]:
        entries = by_week.get(wk, [])
        n_pub = sum(1 for e in entries if e.get("rating") == "published")
        n_pos = sum(1 for e in entries if e.get("rating") in ("up", "published"))
        n_total = len(entries)
        win_rate = (n_pos / n_total) if n_total else 0
        # Approximate quality from feedback alone (validator might not be cached)
        # We'll average the true_quality of these books
        scores: List[float] = []
        for e in entries:
            slug = (e.get("niche") or "").lower().replace(" ", "-")
            if slug:
                tq = compute_true_quality(learning_dir, slug)
                scores.append(tq.true_score)
        avg_q = round(sum(scores) / len(scores), 1) if scores else 0
        out.append(PerformancePoint(
            date=wk, n_generated=n_total, n_published=n_pub,
            avg_quality=avg_q, win_rate=round(win_rate * 100, 1),
        ))
    return sorted(out, key=lambda p: p.date)


def best_book(learning_dir: Path) -> Optional[Dict]:
    """Returns the highest true_quality book ever (with metadata)."""
    feedbacks = load_all_feedback(learning_dir)
    if not feedbacks:
        return None
    best = None
    best_score = -1
    for f in feedbacks:
        slug = (f.get("niche") or "").lower().replace(" ", "-")
        if not slug:
            continue
        tq = compute_true_quality(learning_dir, slug)
        if tq.true_score > best_score:
            best_score = tq.true_score
            best = {"slug": slug, "title": f.get("title", slug),
                    "score": tq.true_score, "rating": f.get("rating"),
                    "variant": f.get("variant_id"), "theme": f.get("theme_name")}
    return best


def overall_kpis(learning_dir: Path) -> Dict:
    """Top-line metrics for the intelligence overview."""
    feedbacks = load_all_feedback(learning_dir)
    events    = load_events(learning_dir)
    n_books = len(feedbacks)
    n_pub   = sum(1 for f in feedbacks if f.get("rating") == "published")
    n_up    = sum(1 for f in feedbacks if f.get("rating") == "up")
    n_down  = sum(1 for f in feedbacks if f.get("rating") == "down")
    win_rate = (n_pub + n_up) / max(n_books, 1)
    n_regens = sum(1 for e in events if e.get("kind") == "cover_regen")
    n_picks  = sum(1 for e in events if e.get("kind") == "cover_picked")
    n_edits  = sum(1 for e in events if e.get("kind") == "listing_edit")
    # Average true_quality across all books
    scores = []
    for f in feedbacks:
        slug = (f.get("niche") or "").lower().replace(" ", "-")
        if slug:
            scores.append(compute_true_quality(learning_dir, slug).true_score)
    avg_quality = round(sum(scores) / max(len(scores), 1), 1) if scores else 0
    return {
        "n_books":     n_books,
        "n_published": n_pub,
        "n_up":        n_up,
        "n_down":      n_down,
        "win_rate":    round(win_rate * 100, 1),
        "avg_quality": avg_quality,
        "n_regens":    n_regens,
        "n_picks":     n_picks,
        "n_edits":     n_edits,
    }


def loss_patterns(learning_dir: Path) -> Dict:
    """Find common patterns in books rated 👎 — what to avoid."""
    feedbacks = load_all_feedback(learning_dir)
    losers = [f for f in feedbacks if f.get("rating") == "down"]
    if len(losers) < 2:
        return {}
    variants  = defaultdict(int)
    themes    = defaultdict(int)
    publishers= defaultdict(int)
    for f in losers:
        if f.get("variant_id"):  variants[f["variant_id"]] += 1
        if f.get("theme_name"):  themes[f["theme_name"]] += 1
        if f.get("publisher"):   publishers[f["publisher"]] += 1
    return {
        "losing_variants":   sorted(variants.items(),  key=lambda x: -x[1])[:5],
        "losing_themes":     sorted(themes.items(),    key=lambda x: -x[1])[:5],
        "losing_publishers": sorted(publishers.items(),key=lambda x: -x[1])[:5],
        "n_losers":          len(losers),
    }
