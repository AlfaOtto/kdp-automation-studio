"""
Keyword Research Pro — deep SEO keyword expansion + per-book editing.

Beyond the 7 listing keywords:
  - Pull Amazon autocomplete suggestions
  - Score each by competition (avg reviews) + intent (long-tail vs broad)
  - Rank by ROI (high-volume + low-competition wins)
  - Allow swapping/editing keywords on a specific book

Output: ranked list of (keyword, score, intent, volume_proxy).
"""
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class KeywordScore:
    keyword:   str
    score:     float        # 0-100 composite ROI
    intent:    str          # "broad" | "longtail" | "branded"
    n_words:   int
    volume:    int          # autocomplete rank proxy
    notes:     str = ""


# Words that signal a real BOOK/gift purchase intent (what a KDP seller targets)
_BOOK_INTENT_WORDS = {
    "book", "books", "journal", "journals", "notebook", "notebooks", "log",
    "logbook", "planner", "planners", "tracker", "diary", "diaries", "workbook",
    "coloring", "colouring", "puzzle", "puzzles", "activity", "sketchbook",
    "guide", "gift", "gifts", "for", "kids", "adults", "men", "women", "teens",
    "seniors", "boys", "girls", "beginners", "him", "her", "large", "print",
}

# Words that signal a PHYSICAL PRODUCT (not a book) — penalized for KDP sellers
_PRODUCT_NOISE_WORDS = {
    "yo-yo", "yoyo", "toy", "toys", "lamp", "light", "lights", "charger",
    "battery", "xbox", "ps4", "ps5", "cable", "case", "cover", "mount", "kit",
    "solar", "led", "lego", "badge", "sticker", "stickers", "shirt", "hoodie",
    "mug", "necklace", "ring", "watch", "watches", "coop", "feeder", "drone",
    "drones", "projector", "costume", "mask", "balloon", "blanket", "pillow",
    "backpack", "wallet", "keychain", "magnet", "poster",
}


def _classify_intent(kw: str) -> str:
    n_words = len(kw.split())
    if any(brand in kw.lower() for brand in
           ["amazon", "kindle", "kdp", "harry potter", "marvel", "disney"]):
        return "branded"
    if n_words >= 4:
        return "longtail"
    return "broad"


# Generic KDP format words — dropped when extracting the meaningful "root" of
# a seed so we expand on the SUBJECT, not on "log book / journal".
_GENERIC_SUFFIXES = {
    "book", "books", "log", "logbook", "journal", "journals", "notebook",
    "notebooks", "planner", "planners", "tracker", "trackers", "diary",
    "diaries", "workbook", "workbooks", "guide", "guides", "for", "the", "a",
    "insights", "record", "records",
}

# High-yield modifiers buyers actually type on Amazon KDP. Appended to the root
# to surface real long-tail demand.
_KDP_MODIFIERS = [
    "for adults", "for kids", "for men", "for women", "for beginners",
    "for teens", "for seniors", "for boys", "for girls", "large print",
    "gift", "gifts", "funny", "journal", "notebook", "log book", "planner",
    "tracker", "diary", "coloring book", "for him", "for her", "for women gifts",
]


def _extract_root(seed: str) -> str:
    """Meaningful core of a seed = drop trailing generic format words.
    'ufo insights log book' -> 'ufo'  ·  'anxiety relief journal' -> 'anxiety relief'
    """
    words = [w for w in seed.split() if w]
    while len(words) > 1 and words[-1] in _GENERIC_SUFFIXES:
        words.pop()
    # If we stripped everything meaningful, keep the first 1-2 content words
    if not words:
        words = seed.split()[:2]
    return " ".join(words)


def _prefixes(seed: str) -> List[str]:
    """Progressive prefixes of the seed (longest→shortest, >=1 word).
    'ufo insights log book' -> ['ufo insights log', 'ufo insights', 'ufo']
    Amazon autocomplete answers SHORT real prefixes, not the full long seed.
    """
    words = seed.split()
    out = []
    for k in range(len(words) - 1, 0, -1):
        out.append(" ".join(words[:k]))
    return out


def _gather_keywords_multi_source(seed: str, n_max: int = 40) -> List[Dict]:
    """
    Aggressive, root-aware keyword harvester. Amazon autocomplete returns almost
    nothing for a long specific seed like 'ufo insights log book', so we attack
    from many angles and, crucially, expand the ROOT subject ('ufo'):

      1. Direct autocomplete on the full seed (+ depth-2)
      2. Progressive prefixes of the seed (shorter prefixes get real answers)
      3. ROOT autocomplete + ROOT alphabet a-z (the highest-yield source)
      4. ROOT + every KDP modifier ('ufo for kids', 'ufo gift', 'ufo journal'…)
      5. Each individual word (len>=3 — this is what used to drop 'ufo'!)

    Each keyword tracks `hits` = how many independent sources surfaced it →
    a strong real-demand signal (multi-source = genuinely searched).

    Returns: list of dicts {keyword, source, level, hits} de-duplicated.
    """
    try:
        from modules.research.keywords import (
            get_keyword_suggestions, get_alphabet_suggestions, expand_keywords,
        )
    except Exception as e:
        logger.warning(f"keywords module unavailable: {e}")
        return []

    import time as _t
    seen: Dict[str, Dict] = {}
    seed = (seed or "").strip().lower()
    if not seed:
        return []
    root = _extract_root(seed)

    def _add(kw: str, source: str, level: int):
        kw = (kw or "").strip().lower()
        if not kw or kw == seed:
            return
        if kw in seen:
            seen[kw]["hits"] += 1            # multi-source = higher confidence
        else:
            seen[kw] = {"keyword": kw, "source": source, "level": level, "hits": 1}

    def _probe(prefix: str, source: str, level: int, limit: int = 10):
        try:
            for kw in get_keyword_suggestions(prefix, limit=limit):
                _add(kw, source, level)
        except Exception:
            pass

    # 1. Direct autocomplete on full seed (depth 2)
    try:
        for it in expand_keywords(seed, depth=2):
            kw = it.get("keyword") if isinstance(it, dict) else str(it)
            _add(kw, "autocomplete", it.get("level", 1) if isinstance(it, dict) else 1)
    except Exception as e:
        logger.warning(f"expand_keywords failed: {e}")

    # 2. Progressive prefixes — short prefixes actually return data
    for pref in _prefixes(seed):
        _probe(pref, "prefix", 1)
        _t.sleep(0.2)

    # 3a. Root direct autocomplete
    if root and root != seed:
        _probe(root, "root", 1, limit=11)
        _t.sleep(0.2)

    # 3b. Root alphabet a-z (highest-yield long-tail discovery)
    try:
        for kw in get_alphabet_suggestions(root):
            _add(kw, "root-alpha", 2)
            if len(seen) >= n_max * 3:
                break
    except Exception:
        pass

    # 4. Root + KDP modifiers (real buyer intent)
    for mod in _KDP_MODIFIERS:
        if len(seen) >= n_max * 3:
            break
        _probe(f"{root} {mod}", "modifier", 2, limit=5)
        _t.sleep(0.15)

    # 5. Single-word probes — len>=3 so 'ufo', 'log', 'cat' are INCLUDED
    for word in [w for w in seed.split() if len(w) >= 3]:
        if len(seen) >= n_max * 3:
            break
        _probe(word, f"word:{word}", 1, limit=10)
        _t.sleep(0.15)

    return list(seen.values())[:n_max * 3]


def expand_keywords_pro(seed_niche: str, depth: int = 2, n_max: int = 40) -> List[KeywordScore]:
    """
    Expand a seed via multi-source harvest + scoring.
    Works robustly even on long seeds where Amazon autocomplete returns nothing.
    """
    raw = _gather_keywords_multi_source(seed_niche, n_max=n_max)
    if not raw:
        return []

    root_words = set(_extract_root((seed_niche or "").lower()).split())

    # Pre-rank by hits (multi-source = real demand) so the strongest keywords
    # get the best rank_score, then keep the top n_max.
    raw_sorted = sorted(
        raw,
        key=lambda it: (it.get("hits", 1) if isinstance(it, dict) else 1),
        reverse=True,
    )

    out: List[KeywordScore] = []
    seen = set()
    for i, item in enumerate(raw_sorted[:n_max]):
        if isinstance(item, dict):
            kw_str = (item.get("keyword") or "").strip().lower()
            level  = item.get("level", 1)
            hits   = int(item.get("hits", 1))
        elif isinstance(item, str):
            kw_str = item.strip().lower()
            level, hits = 1, 1
        else:
            continue
        if not kw_str or kw_str in seen:
            continue
        seen.add(kw_str)
        intent  = _classify_intent(kw_str)
        n_words = len(kw_str.split())

        # Relevance: does this keyword share a word with the seed's root subject?
        # Penalize off-topic suggestions (the user's main complaint).
        kw_words = set(kw_str.split())
        relevant = bool(root_words & kw_words)
        relevance_bonus = 18 if relevant else -25

        # Book-buyer intent: a KDP seller wants book/gift keywords, not random
        # physical products ('ufo yo-yo', 'ufo xbox charger'). Boost keywords
        # carrying format/gift/audience words; penalize obvious product noise.
        book_intent  = bool(kw_words & _BOOK_INTENT_WORDS)
        product_noise = bool(kw_words & _PRODUCT_NOISE_WORDS)
        intent_bonus = (22 if book_intent else 0) - (28 if product_noise else 0)

        # Composite score:
        rank_score     = max(0, 100 - i * (100 / max(n_max, 1)))
        hits_bonus     = min(30, (hits - 1) * 12)   # multi-source demand signal
        longtail_bonus = 18 if intent == "longtail" else (0 if intent == "broad" else -10)
        length_bonus   = min(16, n_words * 4)
        level_bonus    = 8 if level == 1 else 4
        score = round(
            rank_score * 0.4 + hits_bonus + relevance_bonus + intent_bonus
            + longtail_bonus + length_bonus + level_bonus, 1
        )
        out.append(KeywordScore(
            keyword=kw_str, score=score, intent=intent, n_words=n_words,
            volume=max(1, n_max - i),
            notes=f"level={level} hits={hits} rel={'y' if relevant else 'n'}",
        ))
    out.sort(key=lambda x: -x.score)
    return out


def select_top_7(scored: List[KeywordScore],
                 max_chars: int = 50,
                 mix_intents: bool = True) -> List[str]:
    """
    Pick the best 7 keywords for a KDP listing.
    Bias toward a MIX of intents (don't all be long-tail).
    """
    chosen: List[str] = []
    if mix_intents:
        # 1-2 broad, 4-5 longtail
        for intent_target, max_pick in [("broad", 2), ("longtail", 4), ("branded", 1)]:
            picks = [k.keyword[:max_chars] for k in scored
                     if k.intent == intent_target and k.keyword not in chosen][:max_pick]
            chosen.extend(picks)
            if len(chosen) >= 7:
                break
    # Fill remaining slots with top scored
    for k in scored:
        if len(chosen) >= 7:
            break
        if k.keyword not in chosen:
            chosen.append(k.keyword[:max_chars])
    return chosen[:7]


def update_book_keywords(listing_json_path: Path,
                        new_keywords: List[str]) -> bool:
    """Write new keywords to listing.json for a specific book."""
    p = Path(listing_json_path)
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d["keywords"] = [k.strip()[:50] for k in new_keywords if k.strip()][:7]
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning(f"update_book_keywords failed: {e}")
        return False
