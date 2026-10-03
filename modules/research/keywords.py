"""
Keyword research using Amazon's autocomplete API.
No scraping required — this is a legitimate public endpoint.
"""
import time
import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)

AUTOCOMPLETE_URL = "https://completion.amazon.com/api/2017/suggestions"
MARKETPLACE_IDS = {
    "US": "ATVPDKIKX0DER",
    "UK": "A1F83G8C2ARO7P",
    "DE": "A1PA6795UKMFR9",
    "FR": "A13V1IB3VIYZZH",
    "IT": "APJ6JRA9NG5V4",
    "ES": "A1RKKUPIHCS9HS",
    "CA": "A2EUQ1WTGCTBG2",
    "JP": "A1VC38T7YXB528",
}


def get_keyword_suggestions(
    seed: str,
    region: str = "US",
    limit: int = 11,
) -> List[str]:
    """
    Get book keyword suggestions from Amazon autocomplete.
    Returns list of suggested keywords.
    """
    params = {
        "mid": MARKETPLACE_IDS.get(region, MARKETPLACE_IDS["US"]),
        "alias": "stripbooks",
        "prefix": seed,
        "event": "onKeyPress",
        "limit": limit,
        "b2b": 0,
        "fresh": 0,
        "ks": 80,
        "lop": "en_US",
    }

    try:
        resp = requests.get(AUTOCOMPLETE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return [s["value"] for s in data.get("suggestions", [])]
    except Exception as e:
        logger.error(f"Autocomplete error for '{seed}': {e}")
        return []


def expand_keywords(
    seed: str,
    region: str = "US",
    depth: int = 2,
    max_level2: int = 5,
) -> List[Dict]:
    """
    Expand a seed keyword into a tree of related keywords.
    depth=1: direct suggestions only
    depth=2: direct suggestions + suggestions of top results
    """
    seen = {}

    # Level 1
    level1 = get_keyword_suggestions(seed, region=region)
    for kw in level1:
        if kw not in seen:
            seen[kw] = {"keyword": kw, "source": seed, "level": 1}

    if depth < 2:
        return list(seen.values())

    # Level 2: expand top-level suggestions
    for kw in level1[:max_level2]:
        time.sleep(0.4)
        level2 = get_keyword_suggestions(kw, region=region, limit=6)
        for kw2 in level2:
            if kw2 not in seen:
                seen[kw2] = {"keyword": kw2, "source": kw, "level": 2}

    return list(seen.values())


def get_alphabet_suggestions(seed: str, region: str = "US") -> List[str]:
    """
    Generate suggestions by appending a-z to the seed keyword.
    Useful for discovering long-tail variations.
    """
    all_suggestions = []
    letters = "abcdefghijklmnopqrstuvwxyz"

    for letter in letters:
        query = f"{seed} {letter}"
        suggestions = get_keyword_suggestions(query, region=region, limit=5)
        all_suggestions.extend(suggestions)
        time.sleep(0.25)

    # Deduplicate preserving order
    seen = set()
    unique = []
    for s in all_suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return unique
