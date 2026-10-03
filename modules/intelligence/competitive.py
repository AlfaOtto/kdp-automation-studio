"""
Competitive Deep Intelligence — for a given niche, returns a brief :
  - top 5 competitors (title, price, reviews, BSR)
  - title patterns they share
  - cover style trends (dominant colors)
  - keyword overlap
  - description length stats

Used to brief Claude before generating a book in a hot niche.
"""
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def competitive_brief(niche: str, n_results: int = 10, status_cb=None) -> Dict:
    """End-to-end: scrape + analyze + structured brief for Claude."""
    def s(m):
        if status_cb: status_cb(m)
    try:
        from modules.research.scraper import AmazonScraper
    except Exception as e:
        return {"error": f"Scraper unavailable: {e}"}

    s(f"🔍 Analyse compétitive pour : '{niche}'")
    with AmazonScraper() as sc:
        products = sc.search_books(keyword=niche, max_results=n_results)
        # BSR enrichment for top 3 only (expensive)
        enriched = sc.enrich_with_bsr(products[:3], sample_size=3)
    s(f"✅ {len(products)} produits + {len(enriched)} BSR")

    ns = [p for p in products if not p.get("sponsored")]
    if not ns:
        return {"error": "Aucun produit non sponsorisé trouvé"}

    # ── Aggregate stats ─────────────────────────────────────────────────
    prices = [p.get("price", 0) for p in ns if p.get("price", 0) > 0]
    reviews = [p.get("reviews", 0) for p in ns]
    titles = [(p.get("title") or "") for p in ns]

    # Title pattern analysis
    title_lens = [len(t) for t in titles if t]
    word_counts: Counter = Counter()
    for t in titles:
        for w in re.findall(r"\b[A-Za-z]{4,}\b", t):
            wl = w.lower()
            if wl not in {"with","from","your","their","this","that","kindle"}:
                word_counts[wl] += 1

    # Colon usage (Amazon style convention: "Main Title: Subtitle Here")
    colon_count = sum(1 for t in titles if ":" in t)

    return {
        "niche":             niche,
        "n_competitors":     len(ns),
        "price_stats": {
            "avg":  round(sum(prices) / max(len(prices), 1), 2),
            "min":  min(prices) if prices else 0,
            "max":  max(prices) if prices else 0,
        },
        "reviews_stats": {
            "avg":  round(sum(reviews) / max(len(reviews), 1), 0),
            "max":  max(reviews) if reviews else 0,
        },
        "title_stats": {
            "avg_length":     round(sum(title_lens) / max(len(title_lens), 1), 0),
            "uses_colon_pct": round(colon_count / max(len(titles), 1) * 100, 0),
        },
        "common_words":      word_counts.most_common(15),
        "top_competitors":   [
            {"title": p.get("title", "")[:80], "price": p.get("price", 0),
             "reviews": p.get("reviews", 0),
             "bsr": next((e.get("bsr_main") for e in enriched
                          if e.get("asin") == p.get("asin")), None)}
            for p in ns[:5]
        ],
    }


def brief_for_prompt(brief: Dict) -> str:
    """Render the brief as a text block for Claude prompts."""
    if not brief or brief.get("error"):
        return ""
    parts = [f"COMPETITIVE BRIEF for '{brief.get('niche', '?')}':"]
    ps = brief.get("price_stats", {})
    if ps:
        parts.append(f"- Competitor price range: ${ps.get('min', 0)}-${ps.get('max', 0)} "
                     f"(avg ${ps.get('avg', 0)})")
    ts = brief.get("title_stats", {})
    if ts:
        parts.append(f"- Title length avg: {ts.get('avg_length', 0)} chars")
        if ts.get("uses_colon_pct", 0) >= 60:
            parts.append(f"- {ts['uses_colon_pct']}% of winners use 'Title: Subtitle' format")
    words = brief.get("common_words", [])
    if words:
        top_words = [w for w, _ in words[:8]]
        parts.append(f"- Frequent winner words: {', '.join(top_words)}")
    parts.append("Beat the competition: include the format, exceed avg specs.")
    return "\n".join(parts)
