"""
Interior duplication fingerprint
=================================
Amazon's 2025-2026 algorithm flags books whose interiors look too similar to
existing titles in the catalog. To stay clear of suppression, we generate a
structural fingerprint of every book we produce and refuse near-collisions
within the SAME niche.

Fingerprint inputs (cheap, no PDF parsing) :
  - product_type
  - sorted tuple of (section_type, page_count) per section
  - style variant id
  - theme name (font / color recipe)
  - first 3 words of every section title (audience signal)

Two books in the same niche colliding on fingerprint → caller should pick a
different (variant, theme) combo before continuing.
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FINGERPRINT_FILE = "interior_fingerprints.json"


def _section_key(sec: Dict) -> Tuple[str, int, str]:
    t = (sec.get("type") or "content").lower()
    p = int(sec.get("pages") or 0)
    title_words = (sec.get("title") or "").lower().split()[:3]
    return (t, p, " ".join(title_words))


def compute_fingerprint(listing: Dict, style_variant_id: str = "",
                        theme_name: str = "") -> str:
    """Returns a stable 16-char hex hash of the book's structural identity."""
    payload = {
        "product_type": listing.get("product_type", ""),
        "page_count":   int(listing.get("page_count") or 0),
        "sections":     [_section_key(s) for s in listing.get("content_sections", [])],
        "variant":      style_variant_id or "",
        "theme":        theme_name or "",
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def load_fingerprints(learning_dir: Path) -> Dict[str, List[Dict]]:
    """Returns {niche_slug : [ {fingerprint, slug, ts, variant, theme}, ... ]}."""
    p = Path(learning_dir) / FINGERPRINT_FILE
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Fingerprint store unreadable: {e}")
        return {}


def save_fingerprint(learning_dir: Path, niche: str, slug: str,
                     fingerprint: str, variant: str = "", theme: str = "") -> None:
    """Append a fingerprint entry for niche → niche-keyed list."""
    from datetime import datetime
    store = load_fingerprints(learning_dir)
    niche_key = (niche or "").lower().strip()
    entry = {
        "fingerprint": fingerprint,
        "slug":        slug,
        "ts":          datetime.now().isoformat(),
        "variant":     variant,
        "theme":       theme,
    }
    store.setdefault(niche_key, []).append(entry)
    # Keep the last 50 per niche
    store[niche_key] = store[niche_key][-50:]
    try:
        path = Path(learning_dir) / FINGERPRINT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not persist fingerprint: {e}")


def is_collision(learning_dir: Path, niche: str, fingerprint: str) -> Optional[Dict]:
    """Returns the colliding existing entry, or None."""
    store = load_fingerprints(learning_dir)
    for entry in store.get((niche or "").lower().strip(), []):
        if entry.get("fingerprint") == fingerprint:
            return entry
    return None


def suggest_alternate_combo(learning_dir: Path, niche: str,
                            variants_pool: List[str],
                            themes_pool: List[str]) -> Tuple[str, str]:
    """
    Picks a (variant, theme) combo that has NOT been used for this niche yet.
    Returns ("", "") if the pools are exhausted — caller should still proceed.
    """
    store = load_fingerprints(learning_dir)
    used = {(e.get("variant", ""), e.get("theme", ""))
            for e in store.get((niche or "").lower().strip(), [])}
    for v in variants_pool:
        for t in themes_pool:
            if (v, t) not in used:
                return v, t
    return "", ""
