"""
Pattern extraction & proactive insights for the learning system.

Goes BEYOND raw 👍/👎 — extracts WHY books win or lose by analyzing:

  - Title patterns of winners vs losers (length, colon, numbers, words)
  - Cover palette schemes that get published
  - Variants that win in specific (theme × product_type) combinations
  - Quality-score correlation: do users prefer high-validator-score books?
  - Common failure modes: shared patterns across thumbs-down feedback

Output: a list of human-readable insights the bot can surface proactively
in the UI ("⚡ Your last 3 thumbs-up all had warm-classic palette — locking it in")
and inject into Claude prompts for next-batch generation.
"""
import json
import logging
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.learning.feedback import load_all_feedback

logger = logging.getLogger(__name__)


# Rating weights
_W = {"published": 3.0, "up": 1.0, "neutral": 0.0, "down": -2.0}
WIN_RATINGS  = {"up", "published"}
LOSE_RATINGS = {"down"}


@dataclass
class Insight:
    code:        str            # stable id, e.g. 'winning_palette_lock'
    severity:    str            # 'strong' | 'medium' | 'weak'
    icon:        str            # 1-2 char emoji for UI
    message:     str            # human sentence
    action:      str = ""       # what the bot will do about it (or empty)
    confidence:  float = 0.0    # 0-1


def _latest_per_product(entries: List[Dict]) -> List[Dict]:
    seen: Dict[str, Dict] = {}
    for e in entries:
        pid = e.get("product_id")
        if pid:
            seen[pid] = e
    return list(seen.values())


def _ratio_significant(n_pos: int, n_total: int, min_n: int = 3) -> bool:
    """Heuristic: ratio is meaningful if we have at least min_n samples."""
    return n_total >= min_n and n_pos / max(n_total, 1) >= 0.6


def extract_title_patterns(entries: List[Dict]) -> Dict[str, Dict]:
    """
    Analyzes title features in winning vs losing books.
    Returns:
      {
        'avg_winner_title_len': int,
        'colon_win_rate': float,
        'number_win_rate': float,
        'top_winner_words': [(word, n), ...]
      }
    """
    winners = [e for e in entries if e.get("rating") in WIN_RATINGS]
    losers  = [e for e in entries if e.get("rating") in LOSE_RATINGS]

    def lens(group):
        ls = [len(e.get("title", "")) for e in group if e.get("title")]
        return statistics.median(ls) if ls else 0

    def feature_rate(group, predicate):
        if not group:
            return 0.0
        return sum(1 for e in group if predicate(e.get("title", ""))) / len(group)

    win_words = Counter()
    for e in winners:
        for w in re.findall(r"\b[A-Za-z]{4,}\b", e.get("title", "")):
            if w.lower() not in {"with", "from", "your", "their", "this", "that"}:
                win_words[w.lower()] += 1

    return {
        "n_winners":            len(winners),
        "n_losers":             len(losers),
        "median_winner_len":    lens(winners),
        "median_loser_len":     lens(losers),
        "colon_win_rate":       feature_rate(winners, lambda t: ":" in t),
        "colon_lose_rate":      feature_rate(losers,  lambda t: ":" in t),
        "number_win_rate":      feature_rate(winners, lambda t: bool(re.search(r"\d", t))),
        "top_winner_words":     win_words.most_common(8),
    }


def extract_variant_dominance(entries: List[Dict]) -> Dict[str, Tuple[int, int, float]]:
    """
    For each variant_id, returns (n_total, n_wins, win_rate).
    Filters out variants with <2 observations (noise).
    """
    by_variant: Dict[str, List[Dict]] = defaultdict(list)
    for e in entries:
        v = e.get("variant_id")
        if v:
            by_variant[v].append(e)
    out = {}
    for v, group in by_variant.items():
        if len(group) < 2:
            continue
        wins = sum(1 for e in group if e.get("rating") in WIN_RATINGS)
        out[v] = (len(group), wins, wins / len(group))
    return out


def extract_theme_preferences(entries: List[Dict]) -> Dict[str, Tuple[int, int]]:
    """For each theme, return (n_total, n_wins). Themes with strong signal first."""
    by_theme: Dict[str, List[Dict]] = defaultdict(list)
    for e in entries:
        t = e.get("theme_name")
        if t:
            by_theme[t].append(e)
    out = {}
    for t, group in by_theme.items():
        if len(group) < 2:
            continue
        wins = sum(1 for e in group if e.get("rating") in WIN_RATINGS)
        out[t] = (len(group), wins)
    return out


def extract_loss_patterns(entries: List[Dict]) -> List[Tuple[str, int]]:
    """Find shared features among thumbs-down books (variant, theme, word)."""
    losers = [e for e in entries if e.get("rating") in LOSE_RATINGS]
    if len(losers) < 2:
        return []
    features: Counter = Counter()
    for e in losers:
        if e.get("variant_id"):
            features[f"variant:{e['variant_id']}"] += 1
        if e.get("theme_name"):
            features[f"theme:{e['theme_name']}"] += 1
        if e.get("product_type"):
            features[f"type:{e['product_type']}"] += 1
        # Title features
        title = e.get("title", "")
        if ":" in title: features["title:has-colon"] += 1
        if re.search(r"\d", title): features["title:has-number"] += 1
        if len(title) > 100: features["title:very-long"] += 1
    # Return only features that appear in ≥50% of losers
    threshold = max(2, len(losers) // 2)
    return [(f, n) for f, n in features.most_common() if n >= threshold]


def generate_insights(learning_dir: Path) -> List[Insight]:
    """Main entry: returns a prioritized list of insights for the UI."""
    entries = _latest_per_product(load_all_feedback(learning_dir))
    insights: List[Insight] = []

    if not entries:
        return [Insight(
            code="no_feedback", severity="weak", icon="ℹ️",
            message="Aucun feedback encore — note tes premiers livres avec 👍/👎/✅ "
                    "pour que le bot apprenne tes préférences.",
        )]

    # ── Variant dominance ────────────────────────────────────────────────
    var_stats = extract_variant_dominance(entries)
    if var_stats:
        sorted_vars = sorted(var_stats.items(), key=lambda x: -x[1][2])
        top_v, (n, wins, rate) = sorted_vars[0]
        if rate >= 0.75 and n >= 3:
            insights.append(Insight(
                code="winning_variant_lock", severity="strong", icon="🏆",
                message=f"Variant **{top_v}** : {wins}/{n} validés "
                        f"({int(rate * 100)}% win rate). C'est ton style gagnant.",
                action="Le bot le proposera en priorité pour les prochaines niches similaires.",
                confidence=min(1.0, rate * (n / 5)),
            ))
        # Worst variant
        if len(sorted_vars) > 1:
            worst_v, (n_w, wins_w, rate_w) = sorted_vars[-1]
            if rate_w < 0.25 and n_w >= 3:
                insights.append(Insight(
                    code="losing_variant_avoid", severity="medium", icon="🚫",
                    message=f"Variant **{worst_v}** : {wins_w}/{n_w} validés "
                            f"({int(rate_w * 100)}%). Le bot l'évitera.",
                    confidence=1 - rate_w,
                ))

    # ── Theme preferences ───────────────────────────────────────────────
    theme_stats = extract_theme_preferences(entries)
    for t, (n, wins) in sorted(theme_stats.items(), key=lambda x: -x[1][1])[:1]:
        if wins >= 2 and wins / n >= 0.7:
            insights.append(Insight(
                code="theme_winning", severity="medium", icon="🎯",
                message=f"Thème **{t}** : {wins}/{n} validés. Bonne fit niche.",
                confidence=wins / n,
            ))

    # ── Title patterns ──────────────────────────────────────────────────
    title_p = extract_title_patterns(entries)
    if title_p["n_winners"] >= 3:
        # Detect significant colon difference
        if title_p["colon_win_rate"] - title_p["colon_lose_rate"] >= 0.4:
            insights.append(Insight(
                code="title_colon_works", severity="medium", icon="✍️",
                message=f"Les titres avec '**:**' (sous-titre) marchent : "
                        f"{int(title_p['colon_win_rate']*100)}% vs "
                        f"{int(title_p['colon_lose_rate']*100)}% chez les rejets.",
                action="Le bot poussera vers ce format dans les prompts Claude.",
                confidence=0.7,
            ))
        # Top winning words
        if title_p["top_winner_words"]:
            top_words = [w for w, _ in title_p["top_winner_words"][:5]]
            insights.append(Insight(
                code="winner_vocabulary", severity="weak", icon="📝",
                message=f"Mots récurrents dans tes succès : " +
                        ", ".join(f"`{w}`" for w in top_words),
                confidence=0.5,
            ))

    # ── Loss patterns ───────────────────────────────────────────────────
    loss_p = extract_loss_patterns(entries)
    if loss_p:
        top_lf, count = loss_p[0]
        insights.append(Insight(
            code="shared_loss_pattern", severity="strong", icon="⚠️",
            message=f"**Tes derniers rejets partagent** : `{top_lf}` "
                    f"({count}× sur tes 👎). Le bot évitera ce pattern.",
            confidence=min(1.0, count / 3),
        ))

    # ── Volume signal ────────────────────────────────────────────────────
    n_total = len(entries)
    n_pub = sum(1 for e in entries if e.get("rating") == "published")
    if n_pub >= 5:
        insights.append(Insight(
            code="momentum", severity="weak", icon="🚀",
            message=f"**{n_pub} livres publiés** — le bot a maintenant assez de "
                    f"données pour des prédictions fiables.",
            confidence=min(1.0, n_pub / 10),
        ))
    elif n_total < 3:
        insights.append(Insight(
            code="early_days", severity="weak", icon="🌱",
            message=f"Seulement {n_total} feedback(s) — le bot apprend encore. "
                    "Continue à noter pour des suggestions plus précises.",
        ))

    return sorted(insights, key=lambda i: -i.confidence)


def insights_for_prompt(learning_dir: Path) -> str:
    """
    Returns a concise multi-line block to inject into Claude prompts.
    Used by content_generator and cover_generator to bias generations.
    """
    insights = generate_insights(learning_dir)
    if not insights:
        return ""
    strong = [i for i in insights if i.severity == "strong"]
    if not strong:
        return ""
    lines = ["LEARNED USER PREFERENCES (from real feedback):"]
    for i in strong[:3]:
        # Strip markdown for plaintext injection
        clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", i.message)
        clean = re.sub(r"`([^`]+)`", r"\1", clean)
        lines.append(f"  - {clean}")
    lines.append("Lean toward these patterns; do not violate them.")
    return "\n".join(lines)


def write_memory_snapshot(learning_dir: Path, memory_file: Optional[Path] = None) -> Path:
    """
    Periodically write a digest of insights into the project's MEMORY.md so
    future Claude sessions inherit the learned context without re-reading
    all feedback.
    """
    insights = generate_insights(learning_dir)
    if not insights:
        return None
    if memory_file is None:
        memory_file = (
            Path(__file__).resolve().parents[2] / "output" /
            "learning" / "learning_insights.md"
        )
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# KDP Learning System Insights",
        f"_Last updated: {datetime.now().isoformat(timespec='seconds')}_",
        "",
        "## Current learned preferences",
        "",
    ]
    for i in insights:
        lines.append(f"- {i.icon} **{i.code}** (conf {i.confidence:.2f}): {i.message}")
        if i.action:
            lines.append(f"  → {i.action}")
    memory_file.write_text("\n".join(lines), encoding="utf-8")
    return memory_file
