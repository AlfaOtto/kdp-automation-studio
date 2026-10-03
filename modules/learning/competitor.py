"""
Competitor analysis — extracts patterns from scan results.

For each niche, analyses the top-performing competitor books and produces
actionable insights:
  - Title patterns (avg length, structure, common words)
  - Price sweet spot
  - Review distribution
  - Dominant color palette from competitor covers (via Pillow)
  - Common keywords in titles

These insights are saved per-niche and injected into:
  - Claude listing prompts ("competitors avg 65 char titles, use words X/Y")
  - gpt-image-2 cover prompts ("dominant niche palette: earthy browns + greens")
"""
import json
import logging
import re
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def insights_file(learning_dir: Path) -> Path:
    learning_dir.mkdir(parents=True, exist_ok=True)
    return learning_dir / "niche_insights.json"


def _load_all_insights(learning_dir: Path) -> Dict[str, Dict]:
    path = insights_file(learning_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load insights: {e}")
        return {}


def _save_all_insights(learning_dir: Path, data: Dict) -> None:
    path = insights_file(learning_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_insights(learning_dir: Path, niche: str) -> Optional[Dict]:
    """Returns saved insights for a niche, or None."""
    data = _load_all_insights(learning_dir)
    return data.get(niche.lower().strip())


# ── Cover image color extraction ──────────────────────────────────────────────

def _fetch_image_colors(image_url: str, k: int = 3, timeout: int = 5) -> List[Tuple[int, int, int]]:
    """
    Downloads a cover thumbnail and extracts up to k dominant colors.
    Returns a list of (r, g, b) tuples sorted by frequency.
    Returns [] on any failure.
    """
    try:
        import requests
        from PIL import Image
    except ImportError:
        return []
    if not image_url or not image_url.startswith("http"):
        return []

    try:
        resp = requests.get(image_url, timeout=timeout)
        if resp.status_code != 200:
            return []
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        # Resize for speed; quantize to k+2 colors then pick top k
        img = img.resize((80, 120))
        quant = img.quantize(colors=k + 2, kmeans=1)
        palette = quant.getpalette()
        counts = sorted(quant.getcolors(), reverse=True)
        out: List[Tuple[int, int, int]] = []
        for count, idx in counts[:k]:
            r, g, b = palette[idx*3], palette[idx*3+1], palette[idx*3+2]
            out.append((r, g, b))
        return out
    except Exception as e:
        logger.debug(f"Color fetch failed for {image_url}: {e}")
        return []


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _classify_color(rgb: Tuple[int, int, int]) -> str:
    """Tags a color into a coarse family for prompts: earth/cool/warm/dark/light/vibrant."""
    r, g, b = rgb
    avg = (r + g + b) / 3
    # Dark / Light first
    if avg < 60:    return "dark"
    if avg > 210:   return "light"
    # Hue families
    mx, mn = max(r, g, b), min(r, g, b)
    sat = (mx - mn) / max(mx, 1)
    if sat < 0.18:
        return "neutral"
    if r > g and r > b:
        return "warm-red" if g > b else "warm-pink"
    if g > r and g > b:
        return "earth-green" if r + b < 220 else "fresh-green"
    if b > r and b > g:
        return "cool-blue"
    if r > 180 and g > 130 and b < 100:
        return "earth-warm"
    return "neutral"


# ── Title pattern analysis ────────────────────────────────────────────────────

_STOP_WORDS = {
    "the","a","an","of","and","or","for","to","in","on","with","your",
    "this","that","is","are","was","be","by","at","as","you","my","i",
}


def _analyze_titles(products: List[Dict]) -> Dict:
    """Stats on competitor titles: avg/median length, common words, colon-use."""
    titles = [p.get("title", "").strip() for p in products if p.get("title")]
    if not titles:
        return {"avg_len": 0, "with_colon_pct": 0, "top_words": []}

    lens = [len(t) for t in titles]
    avg_len = sum(lens) / len(lens)
    with_colon = sum(1 for t in titles if ":" in t)

    word_counts: Counter = Counter()
    for t in titles:
        for w in re.findall(r"\b[a-zA-Z]{4,}\b", t.lower()):
            if w not in _STOP_WORDS:
                word_counts[w] += 1

    return {
        "n_titles":       len(titles),
        "avg_len":        round(avg_len, 1),
        "min_len":        min(lens),
        "max_len":        max(lens),
        "with_colon_pct": round(100 * with_colon / len(titles), 1),
        "top_words":      word_counts.most_common(8),
    }


# ── Master analyzer ───────────────────────────────────────────────────────────

def analyze_niche(
    learning_dir: Path,
    niche: str,
    products: List[Dict],
    max_covers: int = 5,
    fetch_images: bool = True,
) -> Dict:
    """
    Builds a complete insights dict for one niche from its competitor products.
    Saves to disk and returns the dict.

    `products` should be the scraper's output list with at least:
      title, price, reviews, rating, image_url
    """
    niche_key = niche.lower().strip()

    # Sort by social proof (reviews × rating) to take the actual top performers
    ranked = sorted(
        products,
        key=lambda p: (p.get("reviews", 0) or 0) * max(p.get("rating", 0) or 0, 0.1),
        reverse=True,
    )
    top = ranked[: max(max_covers, 5)]

    title_stats = _analyze_titles(top)

    # Price sweet spot
    prices = [p.get("price", 0) for p in top if 0 < (p.get("price", 0) or 0) < 50]
    price_stats = {}
    if prices:
        price_stats = {
            "n": len(prices),
            "avg":    round(sum(prices) / len(prices), 2),
            "min":    round(min(prices), 2),
            "max":    round(max(prices), 2),
        }

    # Reviews & ratings (saturation indicator)
    reviews_list = [p.get("reviews", 0) or 0 for p in top]
    avg_reviews  = round(sum(reviews_list) / max(len(reviews_list), 1))

    # Cover color extraction (top max_covers)
    color_hexes: List[str]    = []
    color_families: Counter   = Counter()
    if fetch_images:
        for p in top[:max_covers]:
            url = p.get("image_url", "")
            if not url:
                continue
            cols = _fetch_image_colors(url, k=2)
            for c in cols:
                color_hexes.append(_rgb_to_hex(c))
                color_families[_classify_color(c)] += 1

    insights = {
        "niche":           niche,
        "n_competitors":   len(top),
        "title_stats":     title_stats,
        "price_stats":     price_stats,
        "avg_reviews":     avg_reviews,
        "color_hexes":     color_hexes[:8],
        "color_families":  color_families.most_common(4),
        "analyzed_at":     __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }

    # Persist
    all_data = _load_all_insights(learning_dir)
    all_data[niche_key] = insights
    _save_all_insights(learning_dir, all_data)

    return insights


def insights_summary_for_prompt(insights: Dict) -> str:
    """Returns a concise summary to inject into Claude listing prompts."""
    if not insights:
        return ""
    parts = []
    ts = insights.get("title_stats", {})
    if ts.get("avg_len"):
        parts.append(f"Competitor titles in this niche average {ts['avg_len']:.0f} characters")
    if ts.get("with_colon_pct", 0) > 40:
        parts.append(f"{ts['with_colon_pct']:.0f}% use 'Main Title: Subtitle' structure")
    tw = ts.get("top_words", [])
    if tw:
        words = [w for w, _ in tw[:5]]
        parts.append(f"frequent words: {', '.join(words)}")
    ps = insights.get("price_stats", {})
    if ps.get("avg"):
        parts.append(f"average price ${ps['avg']:.2f}")
    if not parts:
        return ""
    return "COMPETITOR INSIGHTS: " + "; ".join(parts) + "."


def color_hint_for_cover(insights: Dict) -> str:
    """Returns a color palette hint to inject into gpt-image-2 prompts."""
    if not insights:
        return ""
    families = insights.get("color_families", [])
    if not families:
        return ""
    family_names = [f for f, _ in families[:2]]
    family_to_phrase = {
        "earth-warm":   "earthy browns and warm ochres",
        "earth-green":  "earthy greens and forest tones",
        "warm-red":     "warm reds and terracotta",
        "warm-pink":    "warm pinks and rose tones",
        "fresh-green":  "fresh greens and botanical accents",
        "cool-blue":    "cool blues and ocean tones",
        "dark":         "deep dark tones with contrast",
        "light":        "light airy palette with soft pastels",
        "neutral":      "neutral muted tones",
    }
    phrases = [family_to_phrase.get(f, f) for f in family_names]
    return f"Top competitors use {' and '.join(phrases)}. Match this palette family"
