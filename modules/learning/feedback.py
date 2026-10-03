"""
Feedback persistence — saves user ratings (👍/👎/✅) per generated product.

Each entry captures the full context (niche, variant, theme, fonts, etc.)
so the profile aggregator can correlate decisions with style choices.

Stored as a single rolling JSONL file. Append-only for safety.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _ensure_dir(learning_dir: Path) -> Path:
    learning_dir.mkdir(parents=True, exist_ok=True)
    return learning_dir


def feedback_file(learning_dir: Path) -> Path:
    return _ensure_dir(learning_dir) / "feedback.jsonl"


def record_feedback(
    learning_dir: Path,
    *,
    product_id: str,          # unique id (e.g., niche + timestamp)
    niche: str,
    product_type: str,
    rating: str,              # "up", "down", "published", "neutral"
    variant_id: Optional[str] = None,
    theme_name: Optional[str] = None,
    title: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    publisher: Optional[str] = None,
    page_count: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict:
    """Appends a single feedback entry."""
    entry = {
        "ts":           datetime.now().isoformat(timespec="seconds"),
        "product_id":   product_id,
        "niche":        niche,
        "product_type": product_type,
        "rating":       rating,
        "variant_id":   variant_id,
        "theme_name":   theme_name,
        "title":        title,
        "keywords":     keywords or [],
        "publisher":    publisher,
        "page_count":   page_count,
        "notes":        notes,
    }
    path = feedback_file(learning_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"Feedback recorded: {product_id} → {rating}")
    return entry


def load_all_feedback(learning_dir: Path) -> List[Dict]:
    """Reads every feedback entry. Returns oldest → newest."""
    path = feedback_file(learning_dir)
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping malformed feedback line: {e}")
    return entries


def get_feedback_for_product(learning_dir: Path, product_id: str) -> Optional[str]:
    """Returns the latest rating for a given product_id (or None)."""
    entries = load_all_feedback(learning_dir)
    latest = None
    for e in entries:
        if e.get("product_id") == product_id:
            latest = e
    return latest.get("rating") if latest else None


def feedback_counts(learning_dir: Path) -> Dict[str, int]:
    """Returns counts of {up, down, published, neutral, total}."""
    entries = load_all_feedback(learning_dir)
    out = {"up": 0, "down": 0, "published": 0, "neutral": 0, "total": 0}
    # For each product, count only its latest rating
    latest_per_product: Dict[str, str] = {}
    for e in entries:
        pid = e.get("product_id") or ""
        latest_per_product[pid] = e.get("rating", "neutral")
    for rating in latest_per_product.values():
        out[rating] = out.get(rating, 0) + 1
        out["total"] += 1
    return out
