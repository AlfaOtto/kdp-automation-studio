"""
On-demand category generator — adds the `categories` field to an existing
listing.json that was created before the categories feature was added.

Calls Claude to suggest 3 real Amazon KDP browse categories based on the
listing's niche, title, and description, then writes them back to listing.json.
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _build_prompt(listing: Dict) -> str:
    return f"""You are an Amazon KDP categories expert.

Given the book below, return exactly 3 REAL Amazon KDP browse category paths
that best fit it. The first one is the PRIMARY (most relevant).

BOOK:
  Niche: {listing.get('niche', '?')}
  Title: {listing.get('title', '?')}
  Subtitle: {listing.get('subtitle', '?')}
  Type: {listing.get('product_type', '?')}
  Pages: {listing.get('page_count', '?')}

RULES:
- Each category is a REAL Amazon path: "Top > Sub > Sub-sub" (2-4 levels deep)
- Use Amazon's actual category tree — never invent fake paths
- Pick categories that have proven sales for this kind of book
- Examples of real KDP paths:
    "Crafts, Hobbies & Home > Crafts & Hobbies > Coloring Books for Grown-Ups"
    "Self-Help > Journal Writing"
    "Health, Fitness & Dieting > Diseases & Physical Ailments > Diabetes"
    "Humor & Entertainment > Puzzles & Games > Trivia"
    "Sports & Outdoors > Outdoor Recreation > Hunting & Fishing > Fishing"
    "Pets > Aquariums & Fish > Freshwater"

Return ONLY a JSON array — no markdown, no preamble:
[
  {{"path": "Most relevant top-level > sub > sub-sub", "primary": true}},
  {{"path": "Second relevant path", "primary": false}},
  {{"path": "Third relevant path", "primary": false}}
]"""


def _parse_categories(raw: str) -> List[Dict]:
    """Robust JSON array parse — strips markdown fences if any."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Extract the first JSON array
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array found in: {raw[:200]!r}")
    arr = json.loads(match.group())
    out = []
    for c in arr[:3]:
        if isinstance(c, dict) and c.get("path") and " > " in str(c["path"]):
            out.append({
                "path":    str(c["path"]).strip(),
                "primary": bool(c.get("primary", False)),
            })
        elif isinstance(c, str) and " > " in c:
            out.append({"path": c.strip(), "primary": False})
    if out and not any(c["primary"] for c in out):
        out[0]["primary"] = True
    return out[:3]


def generate_categories_for_listing(
    listing_path: Path,
    anthropic_key: str,
    status_cb=None,
) -> List[Dict]:
    """
    Load listing.json, ask Claude for 3 KDP categories, write back.
    Returns the new categories list.
    """
    listing_path = Path(listing_path)
    if not listing_path.exists():
        raise FileNotFoundError(f"listing.json not found: {listing_path}")

    with open(listing_path, "r", encoding="utf-8") as f:
        listing = json.load(f)

    def s(msg):
        if status_cb: status_cb(msg)

    s(f"🤖 Demande à Claude de proposer 3 catégories KDP pour « {listing.get('niche', '?')} »…")

    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(f"anthropic library not installed: {e}")

    client = anthropic.Anthropic(api_key=anthropic_key)
    prompt = _build_prompt(listing)

    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    categories = _parse_categories(raw)

    if not categories:
        raise ValueError(f"Claude returned no valid categories. Raw: {raw[:200]!r}")

    # Write back to listing.json
    listing["categories"] = categories
    with open(listing_path, "w", encoding="utf-8") as f:
        json.dump(listing, f, ensure_ascii=False, indent=2)

    s(f"✅ {len(categories)} catégories ajoutées au listing.json")
    for c in categories:
        mark = "⭐" if c.get("primary") else "▫️"
        s(f"   {mark} {c['path']}")

    return categories
