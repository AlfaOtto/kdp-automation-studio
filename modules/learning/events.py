"""
Multi-signal event log — captures everything beyond raw 👍/👎/✅:
  - cover_picked  : user chose a specific cover candidate from the A/B view
  - cover_regen   : user clicked "Regenerate cover" (signals dissatisfaction)
  - listing_edit  : user manually edited title/subtitle/description
  - auto_fix_used : user ran auto-fix on a book (signals quality issue)

All events are appended to learning_dir/events.jsonl — append-only, one JSON
per line, easily parsed and rotated.
"""
import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _events_path(learning_dir: Path) -> Path:
    p = Path(learning_dir) / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _append_event(learning_dir: Path, event: Dict[str, Any]) -> None:
    event = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        **event,
    }
    p = _events_path(learning_dir)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    logger.info(f"Event recorded: {event.get('kind', '?')} for {event.get('slug', '?')}")


# ── Public recorders ─────────────────────────────────────────────────────────

def record_cover_pick(
    learning_dir:    Path,
    slug:            str,
    candidate_idx:   int,
    palette_source:  Optional[str] = None,
    font_name:       Optional[str] = None,
    typo_strategy:   Optional[str] = None,
    score_visual:    Optional[int] = None,
) -> None:
    """Record that the user picked a specific cover candidate (strong positive)."""
    _append_event(learning_dir, {
        "kind":          "cover_picked",
        "slug":          slug,
        "candidate_idx": candidate_idx,
        "palette_source": palette_source,
        "font_name":     font_name,
        "typo_strategy": typo_strategy,
        "score_visual":  score_visual,
    })


def record_cover_regen(
    learning_dir:   Path,
    slug:           str,
    palette_before: Optional[str] = None,
    palette_after:  Optional[str] = None,
    force:          bool = False,
) -> None:
    """Record a cover regeneration (signals dissatisfaction with previous version)."""
    _append_event(learning_dir, {
        "kind":           "cover_regen",
        "slug":           slug,
        "palette_before": palette_before,
        "palette_after":  palette_after,
        "force":          force,
    })


def record_listing_edit(
    learning_dir: Path,
    slug:         str,
    field:        str,
    before:       str,
    after:        str,
) -> None:
    """Record a manual edit to title/subtitle/description (high-signal correction)."""
    if before == after:
        return
    _append_event(learning_dir, {
        "kind":      "listing_edit",
        "slug":      slug,
        "field":     field,
        "before":    before[:500],
        "after":     after[:500],
        "delta_len": len(after) - len(before),
    })


def record_auto_fix(
    learning_dir: Path,
    slug:         str,
    strategies:   List[str],
    n_success:    int,
    n_failure:    int,
) -> None:
    """Record an auto-fix run (signals listing/PDF quality issue)."""
    _append_event(learning_dir, {
        "kind":       "auto_fix_used",
        "slug":       slug,
        "strategies": strategies,
        "n_success":  n_success,
        "n_failure":  n_failure,
    })


def record_cover_finetune(
    learning_dir: Path,
    slug:         str,
    overrides:    Dict[str, Any],
) -> None:
    """
    Record the EXACT cover overrides the user applied via the Fine-tune panel.
    This is a strong design-preference signal: the user is hand-tuning the cover
    to their taste (font, title size, band height, colours…). These get
    aggregated into cover_preferences() and seeded as defaults into future
    cover generation, so the bot 'learns your look'.
    """
    # Only keep the meaningful (non-default) knobs to avoid noise
    keep = {}
    for k, v in (overrides or {}).items():
        if v in (None, "", 1.0, 0.0, False):
            continue
        keep[k] = v
    if not keep:
        return
    _append_event(learning_dir, {
        "kind":      "cover_finetune",
        "slug":      slug,
        "overrides": keep,
    })


# ── Reader ──────────────────────────────────────────────────────────────────

def load_events(learning_dir: Path, kind: Optional[str] = None) -> List[Dict]:
    """Load all events (optionally filtered by kind). Order: oldest first."""
    p = _events_path(learning_dir)
    if not p.exists():
        return []
    events = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if not kind or e.get("kind") == kind:
                    events.append(e)
            except Exception:
                continue
    return events


def events_for_slug(learning_dir: Path, slug: str) -> List[Dict]:
    """All events recorded for a specific product slug."""
    return [e for e in load_events(learning_dir) if e.get("slug") == slug]


def event_counts(learning_dir: Path) -> Dict[str, int]:
    """Aggregate counts by event kind — for UI dashboards."""
    out: Dict[str, int] = {}
    for e in load_events(learning_dir):
        k = e.get("kind", "unknown")
        out[k] = out.get(k, 0) + 1
    return out


def cover_preferences(learning_dir: Path, min_signals: int = 3) -> Dict[str, Any]:
    """
    Learn the user's recurring cover-design preferences from their fine-tune
    history. Returns a dict of overrides to SEED into future cover generation
    as smart defaults, plus metadata.

    Strategy:
      - Categorical knobs (title_font, font_pool, *_color, *_visible) → most
        frequently chosen value, if it dominates.
      - Numeric knobs (title_size_mult, band_height_pct, fade_strength,
        spine_padding_in, …) → median of the chosen values.

    Only returns a preference once it has been seen >= `min_signals` times,
    so a single experiment doesn't become a permanent default.
    """
    from collections import Counter, defaultdict
    import statistics

    events = load_events(learning_dir, kind="cover_finetune")
    if len(events) < min_signals:
        return {"ready": False, "n_signals": len(events), "overrides": {}}

    categorical = defaultdict(Counter)
    numeric     = defaultdict(list)
    NUMERIC_KEYS = {
        "title_size_mult", "title_y_offset_pct", "subtitle_size_mult",
        "band_height_pct", "fade_strength", "spine_padding_in",
        "publisher_size_mult", "back_watermark_alpha",
    }

    for e in events:
        for k, v in (e.get("overrides") or {}).items():
            if k in NUMERIC_KEYS:
                try:
                    numeric[k].append(float(v))
                except (TypeError, ValueError):
                    continue
            else:
                categorical[k][str(v)] += 1

    overrides: Dict[str, Any] = {}
    notes: List[str] = []

    # Categorical: keep a value only if it's chosen in >= 50% of its appearances
    for k, counter in categorical.items():
        total = sum(counter.values())
        if total < min_signals:
            continue
        val, cnt = counter.most_common(1)[0]
        if cnt / total >= 0.5:
            overrides[k] = val
            notes.append(f"{k}={val} ({cnt}/{total}×)")

    # Numeric: median if we have enough samples
    for k, vals in numeric.items():
        if len(vals) >= min_signals:
            med = round(statistics.median(vals), 3)
            overrides[k] = med
            notes.append(f"{k}~{med} (n={len(vals)})")

    return {
        "ready": bool(overrides),
        "n_signals": len(events),
        "overrides": overrides,
        "notes": notes,
    }
