"""
Market Intelligence — Amazon best-sellers + trend extraction.

Scrapes top results for KDP browse categories and extracts:
  - price stats (avg/min/max)
  - page count stats
  - title patterns (length, common words)
  - cover color trends (dominant palettes)
  - keyword overlap (what most winners share)

Results cached for 7 days per category to avoid hammering Amazon.
"""
import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


CACHE_TTL_DAYS = 7


def _cache_path(learning_dir: Path, category_key: str) -> Path:
    safe = re.sub(r"[^a-z0-9_]+", "_", category_key.lower())
    d = Path(learning_dir) / "market_intel"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def is_fresh(learning_dir: Path, category_key: str, ttl_days: int = CACHE_TTL_DAYS) -> bool:
    p = _cache_path(learning_dir, category_key)
    if not p.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    return age < timedelta(days=ttl_days)


def load_cached(learning_dir: Path, category_key: str) -> Optional[Dict]:
    p = _cache_path(learning_dir, category_key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cached(learning_dir: Path, category_key: str, data: Dict) -> None:
    p = _cache_path(learning_dir, category_key)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def scrape_category(
    category_search: str,
    n_books: int = 20,
    status_cb=None,
) -> List[Dict]:
    """
    Uses AmazonScraper to fetch top results for a category-style search.
    Returns list of product dicts.
    """
    def s(m):
        if status_cb: status_cb(m)
    try:
        from modules.research.scraper import AmazonScraper
    except Exception as e:
        logger.warning(f"Scraper unavailable: {e}")
        return []
    s(f"🌐 Scraping top {n_books} pour '{category_search}'…")
    with AmazonScraper() as sc:
        products = sc.search_books(keyword=category_search, max_results=n_books)
    s(f"✅ {len(products)} produits scrapés")
    return products


def analyze_products(products: List[Dict]) -> Dict:
    """Extract trends from a list of scraped products."""
    if not products:
        return {}
    # Prices
    prices = [p.get("price", 0) for p in products if p.get("price", 0) > 0]
    avg_price = round(sum(prices) / max(len(prices), 1), 2)
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0
    # Reviews (competition proxy)
    reviews = [p.get("reviews", 0) for p in products]
    avg_reviews = round(sum(reviews) / max(len(reviews), 1), 0)
    # Title patterns
    titles = [(p.get("title") or "") for p in products]
    title_lens = [len(t) for t in titles if t]
    avg_title_len = round(sum(title_lens) / max(len(title_lens), 1), 0)
    word_counts: Counter = Counter()
    for t in titles:
        for w in re.findall(r"\b[A-Za-z]{4,}\b", t):
            wl = w.lower()
            if wl not in {"with","from","your","their","this","that","into","over"}:
                word_counts[wl] += 1
    # Sponsored share (saturation indicator)
    sponsored = sum(1 for p in products if p.get("sponsored"))
    return {
        "n_products":         len(products),
        "avg_price":          avg_price,
        "min_price":          min_price,
        "max_price":          max_price,
        "avg_reviews":        avg_reviews,
        "avg_title_length":   avg_title_len,
        "top_title_words":    word_counts.most_common(15),
        "sponsored_count":    sponsored,
        "saturation_pct":     round(sponsored / max(len(products), 1) * 100, 0),
        "scraped_at":         datetime.now().isoformat(timespec="seconds"),
    }


def market_brief(learning_dir: Path, category_key: str, force_refresh: bool = False,
                 status_cb=None) -> Dict:
    """End-to-end: returns the cached brief OR scrapes if stale/missing."""
    if not force_refresh and is_fresh(learning_dir, category_key):
        cached = load_cached(learning_dir, category_key)
        if cached:
            return cached
    products = scrape_category(category_key, n_books=20, status_cb=status_cb)
    analysis = analyze_products(products)
    analysis["category_key"] = category_key
    save_cached(learning_dir, category_key, analysis)
    return analysis
