"""
Categories Optimizer — Module C
================================
For any niche, propose the 3 BEST KDP categories to publish in, with:

  1. Volume          : how many books sell weekly in this category
  2. Penetrability   : sales/day needed to enter top 100 (bestseller badge)
  3. Niche match     : semantic relevance to the book
  4. Concurrence     : avg reviews + avg BSR of top books

Strategy :
  a) Claude proposes 6-10 candidate KDP category paths from the niche
  b) For each, we scrape Amazon top results (via AmazonScraper) to gather BSR
     stats + review distribution + price
  c) Rank by composite "best-bet" score
  d) Return the top 3 with justification text

KDP rules : exactly 3 categories at publishing, 1 marked primary.
"""
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
#  Claude category-tree suggester
# ──────────────────────────────────────────────────────────────────────────────

def suggest_candidate_categories(niche: str, product_type: str,
                                  anthropic_key: str, n: int = 8,
                                  status_cb=None) -> List[Dict]:
    """
    Asks Claude for n candidate KDP category PATHS for this niche.
    Returns list of {path, search_keyword, rationale}.

    search_keyword is what we'll feed to AmazonScraper to gauge competition
    (since Amazon doesn't expose a direct "browse category" search).
    """
    if not anthropic_key or not niche:
        return []
    try:
        import anthropic
    except ImportError:
        return []

    # Product-type-aware category examples. A cookbook must NOT be pushed toward
    # "Journal Writing" — it belongs in Cookbooks, Food & Wine.
    pt = (product_type or "").lower()
    _nl = (niche or "").lower()
    _is_facts = any(m in _nl for m in ("facts for", "facts about", "fun facts", "for kids"))
    if pt == "recipe_book" or "cookbook" in _nl or "recipe" in _nl:
        _example_primary = "Cookbooks, Food & Wine > Special Diet > High Protein"
        _example_kw = "high protein cookbook"
        _paths = """  Cookbooks, Food & Wine > Special Diet > High Protein
  Cookbooks, Food & Wine > Special Diet > Low Carbohydrate
  Cookbooks, Food & Wine > Special Diet > Weight Loss
  Cookbooks, Food & Wine > Special Diet > Heart Healthy
  Cookbooks, Food & Wine > Special Diet > Diabetic & Sugar-Free
  Cookbooks, Food & Wine > Cooking Methods > Quick & Easy
  Cookbooks, Food & Wine > Cooking Methods > Frying
  Cookbooks, Food & Wine > Cooking by Ingredient > Meat & Poultry
  Cookbooks, Food & Wine > Cooking by Ingredient > Fish & Seafood
  Cookbooks, Food & Wine > Kitchen Appliances
  Cookbooks, Food & Wine > Main Courses & Side Dishes
  Health, Fitness & Dieting > Nutrition
  Health, Fitness & Dieting > Diets & Weight Loss > High Protein"""
    elif pt == "how_to" and _is_facts:
        _example_primary = "Children's Books > Education & Reference > Science, Nature & How It Works"
        _example_kw = "fun facts book for kids"
        _paths = """  Children's Books > Education & Reference > Science, Nature & How It Works
  Children's Books > Education & Reference > Reference
  Children's Books > Science, Nature & How It Works > How Things Work
  Children's Books > Geography & Cultures
  Humor & Entertainment > Puzzles & Games > Trivia"""
    elif pt == "how_to":
        # Guides — topic-dependent; give a broad but real set to choose from.
        _example_primary = "Crafts, Hobbies & Home > Gardening & Horticulture"
        _example_kw = "beginner how-to guide"
        _paths = """  Crafts, Hobbies & Home > Gardening & Horticulture > Techniques
  Crafts, Hobbies & Home > Pets & Animal Care > Dogs > Training
  Crafts, Hobbies & Home > Crafts & Hobbies > Needlecrafts & Textile Crafts
  Health, Fitness & Dieting > Exercise & Fitness
  Health, Fitness & Dieting > Alternative Medicine
  Sports & Outdoors > Individual Sports
  Self-Help > Personal Transformation
  Business & Money > Small Business & Entrepreneurship
  Home & Garden > How-to & Home Improvements"""
    else:
        _example_primary = "Self-Help > Journal Writing"
        _example_kw = "guided journal for women"
        _paths = """  Self-Help > Journal Writing
  Self-Help > Anxieties & Phobias
  Crafts, Hobbies & Home > Crafts & Hobbies > Coloring Books for Grown-Ups
  Children's Books > Activities, Crafts & Games > Activity Books > Coloring Books
  Health, Fitness & Dieting > Diseases & Physical Ailments > Diabetes
  Humor & Entertainment > Puzzles & Games > Trivia
  Humor & Entertainment > Puzzles & Games > Logic & Brain Teasers
  Sports & Outdoors > Outdoor Recreation > Hunting & Fishing > Fishing"""

    prompt = f"""You are a KDP category strategist with 15 years experience.

NICHE: "{niche}"
PRODUCT TYPE: {product_type}

Propose {n} REAL Amazon KDP browse-category paths where this book could
plausibly rank in the top 100 within 30-60 days. Order from BEST FIT to
BROADEST. Each path is 2-4 levels deep.

⚠️ The categories MUST fit the PRODUCT TYPE. A cookbook belongs in
"Cookbooks, Food & Wine", NOT in "Journal Writing" or "Crafts & Hobbies".
A how-to guide belongs in its topic's practical category, not a template category.

For each candidate, also give a `search_keyword` — a phrase a buyer would
type in Amazon to find this category's content. This is what the optimizer
will use to scrape competition stats.

Return STRICT JSON only:
[
  {{"path": "{_example_primary}",
    "search_keyword": "{_example_kw}",
    "rationale": "narrow sub-cat, top 100 is reachable with a few sales/day"}},
  ...
]

REAL KDP paths to reference for THIS product type (pick the best-fitting ones):
{_paths}

ENGLISH only. NEVER invent fake paths."""

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        if status_cb:
            status_cb(f"🧠 Claude propose {n} catégories candidates pour \"{niche}\"…")
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        out = []
        for item in data[:n]:
            if not isinstance(item, dict): continue
            path = str(item.get("path", "")).strip()
            kw   = str(item.get("search_keyword", "")).strip()
            rat  = str(item.get("rationale", "")).strip()
            if " > " in path and 5 < len(path) < 250 and kw:
                out.append({"path": path, "search_keyword": kw[:80], "rationale": rat[:200]})
        return out
    except Exception as e:
        logger.warning(f"suggest_candidate_categories failed: {e}")
        if status_cb:
            status_cb(f"⚠️ Suggestion candidates échouée : {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
#  Competition stats per candidate (live Amazon scrape)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_category_stats(search_keyword: str, n_results: int = 15,
                          enrich_bsr: bool = True,
                          status_cb=None) -> Dict:
    """
    Scrapes Amazon for `search_keyword` and gathers stats :
      - n_books          : how many books returned
      - avg_reviews      : average review count of top results
      - reviews_p25/p50/p75 : percentiles
      - low_review_pct   : % of top with ≤25 reviews (penetrability signal)
      - avg_price        : average paperback price
      - bsr_stats        : if enrich_bsr=True, avg BSR of top 5
    """
    from modules.research.scraper import AmazonScraper

    def s(msg):
        if status_cb: status_cb(msg)

    out = {
        "n_books": 0, "avg_reviews": 0, "low_review_pct": 0,
        "avg_price": 0, "bsr_stats": None,
        "search_keyword": search_keyword,
    }

    try:
        with AmazonScraper() as sc:
            s(f"🔬 Scraping \"{search_keyword}\"…")
            products = sc.search_books(keyword=search_keyword, max_results=n_results)
            if not products:
                s(f"⚠️ Pas de résultats pour \"{search_keyword}\"")
                return out
            non_sponsored = [p for p in products if not p.get("sponsored")][:10]
            if not non_sponsored:
                return out

            reviews = [int(p.get("reviews", 0) or 0) for p in non_sponsored]
            prices  = [float(p.get("price", 0) or 0) for p in non_sponsored
                       if (p.get("price") or 0) > 0]
            sorted_rv = sorted(reviews)
            n = len(sorted_rv)
            p25 = sorted_rv[n // 4]    if n >= 4 else (sorted_rv[0] if sorted_rv else 0)
            p50 = sorted_rv[n // 2]    if n >= 2 else (sorted_rv[0] if sorted_rv else 0)
            p75 = sorted_rv[3 * n // 4] if n >= 4 else (sorted_rv[-1] if sorted_rv else 0)
            avg_reviews = sum(reviews) / max(n, 1)
            avg_price   = sum(prices) / max(len(prices), 1) if prices else 0
            low_review_pct = sum(1 for r in reviews if r <= 25) / max(n, 1) * 100

            out.update({
                "n_books":          len(products),
                "avg_reviews":      int(avg_reviews),
                "reviews_p25":      p25,
                "reviews_p50":      p50,
                "reviews_p75":      p75,
                "low_review_pct":   round(low_review_pct, 1),
                "avg_price":        round(avg_price, 2),
            })

            if enrich_bsr:
                s("📊 Enrichissement BSR top 3…")
                try:
                    enriched = sc.enrich_with_bsr(non_sponsored[:3], sample_size=3)
                    bsrs = [p["bsr_main"] for p in enriched
                            if isinstance(p.get("bsr_main"), int)]
                    if bsrs:
                        out["bsr_stats"] = {
                            "min":  min(bsrs),
                            "avg":  int(sum(bsrs) / len(bsrs)),
                            "max":  max(bsrs),
                            "n":    len(bsrs),
                        }
                except Exception as e:
                    logger.debug(f"BSR enrichment skipped: {e}")
    except Exception as e:
        logger.warning(f"scrape_category_stats failed for '{search_keyword}': {e}")
        s(f"⚠️ Scrape échoué : {e}")
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Composite "best-bet" scoring
# ──────────────────────────────────────────────────────────────────────────────

def _penetrability_score(stats: Dict) -> float:
    """0-100. Higher = easier to enter top 100."""
    avg_r = stats.get("avg_reviews", 0)
    low_pct = stats.get("low_review_pct", 0)
    # Lower avg reviews + high % low-review books = easy to penetrate
    if avg_r <= 25:  base = 95
    elif avg_r <= 50: base = 85
    elif avg_r <= 100: base = 70
    elif avg_r <= 200: base = 50
    elif avg_r <= 500: base = 30
    else: base = 12
    # Boost if many low-review entries (indé already ranking)
    boost = low_pct * 0.15
    return min(100, base + boost)


def _volume_score(stats: Dict) -> float:
    """0-100. Higher = more sales activity in this category."""
    bsr_stats = stats.get("bsr_stats")
    if not bsr_stats:
        # Fallback : use avg_reviews as activity proxy
        avg_r = stats.get("avg_reviews", 0)
        return min(100, avg_r / 5)  # 500 reviews ≈ 100
    avg_bsr = bsr_stats.get("avg", 999999)
    if avg_bsr <= 10_000:  return 95
    if avg_bsr <= 50_000:  return 80
    if avg_bsr <= 100_000: return 65
    if avg_bsr <= 300_000: return 45
    if avg_bsr <= 1_000_000: return 25
    return 10


def _viable_price_score(stats: Dict) -> float:
    """0-100. Healthy paperback price range = 7-15$."""
    p = stats.get("avg_price", 0)
    if p == 0: return 50    # unknown
    if 6.99 <= p <= 14.99: return 100
    if 4.99 <= p <  6.99:  return 60
    if 15 <= p <= 25:      return 80
    return 30


def composite_category_score(stats: Dict, weights: Dict = None) -> Dict:
    """
    Combine penetrability + volume + viable price into a single 0-100 score.
    Returns {composite, penetrability, volume, price_viability}.
    """
    weights = weights or {"penetrability": 0.45, "volume": 0.35, "price": 0.20}
    pen  = _penetrability_score(stats)
    vol  = _volume_score(stats)
    pri  = _viable_price_score(stats)
    comp = round(pen * weights["penetrability"]
                  + vol * weights["volume"]
                  + pri * weights["price"], 1)
    return {
        "composite":      comp,
        "penetrability":  round(pen, 1),
        "volume":         round(vol, 1),
        "price_viability": round(pri, 1),
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Pipeline : suggest → scrape → rank
# ──────────────────────────────────────────────────────────────────────────────

def optimize_categories(niche: str, product_type: str, anthropic_key: str,
                        max_candidates: int = 8,
                        deep_bsr: bool = True,
                        status_cb=None) -> List[Dict]:
    """
    Full pipeline. Returns a ranked list (best-first) of candidate categories
    with stats + scores + a verdict string.

    Returns list of :
      {
        path, search_keyword, rationale,
        stats: {avg_reviews, p50, low_review_pct, avg_price, bsr_stats},
        scores: {composite, penetrability, volume, price_viability},
        verdict: "🥇 EXPLOITABLE — top 100 atteignable avec 2-3 ventes/jour"
      }
    """
    def s(msg):
        if status_cb: status_cb(msg)

    candidates = suggest_candidate_categories(
        niche, product_type, anthropic_key, n=max_candidates, status_cb=status_cb,
    )
    if not candidates:
        return []

    s(f"📋 {len(candidates)} candidats reçus → scrape stats Amazon...")
    results = []
    for i, c in enumerate(candidates, 1):
        s(f"🔬 [{i}/{len(candidates)}] {c['path'][:60]} (kw=\"{c['search_keyword']}\")")
        stats  = scrape_category_stats(c["search_keyword"], n_results=15,
                                        enrich_bsr=deep_bsr, status_cb=None)
        scores = composite_category_score(stats)
        comp   = scores["composite"]
        if   comp >= 75: verdict = "🥇 EXPLOITABLE — top 100 atteignable rapidement"
        elif comp >= 60: verdict = "✅ Bon choix — pénétrable avec effort modéré"
        elif comp >= 45: verdict = "🟡 Risqué — concurrence sérieuse"
        else:            verdict = "🔴 Difficile — éviter sauf si niche très ciblée"
        results.append({
            "path":            c["path"],
            "search_keyword":  c["search_keyword"],
            "rationale":       c["rationale"],
            "stats":           stats,
            "scores":          scores,
            "verdict":         verdict,
        })

    results.sort(key=lambda r: r["scores"]["composite"], reverse=True)
    s(f"✅ Top 3 catégories prêtes")
    return results


def auto_persist_top3(product_dir, results: List[Dict]) -> Optional[List[Dict]]:
    """
    Apply the top 3 categories to listing.json with first marked primary.
    Returns the new categories list or None if no listing.json.
    """
    from pathlib import Path
    p = Path(product_dir) / "listing.json"
    if not p.exists() or len(results) < 3:
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        top3 = []
        for i, r in enumerate(results[:3]):
            top3.append({"path": r["path"], "primary": (i == 0)})
        d["categories"] = top3
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        return top3
    except Exception as e:
        logger.warning(f"auto_persist_top3 failed: {e}")
        return None
