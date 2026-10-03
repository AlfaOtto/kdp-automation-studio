"""
Style variants for anti-duplicate batch creation.

Each variant carries a distinct visual + editorial signature so that 5 books
created in the same session don't trigger KDP's duplicate-content detection:

  - palette       → unique accent colors per book
  - fonts         → serif vs sans-serif rotation
  - symbol        → ornamental glyph (✦ ◈ ❋ ★ etc.)
  - cover_art_hint → distinct art style sent to gpt-image-2
  - tone          → Claude's writing voice for the listing
  - title_style   → structural variation for titles

Cycle through these in order: variant 1 → 2 → 3 → ...  Once 8 variants are
used, restart from 1 (but at that point your 9th book is a different niche
and will already feel completely different).
"""
from typing import Dict, List


STYLE_VARIANTS: List[Dict] = [
    # ─── 1. Warm Classic ───────────────────────────────────────────────
    {
        "id": "warm-classic",
        "palette": {
            "accent":  "#8B4A2B",
            "accent2": "#C28B6F",
            "light":   "#FAF3EE",
        },
        "fonts": {
            "body":    "Times-Roman",
            "heading": "Helvetica-Bold",
            "italic":  "Times-Italic",
        },
        "symbol": "✦",
        "cover_art_hint": (
            "warm earth tones, soft watercolor textures, vintage aesthetic, "
            "hand-drawn botanical feel, parchment background"
        ),
        "tone": "warm, inviting, and personal",
        "title_style": "evocative and emotional, with a poetic phrase",
    },

    # ─── 2. Modern Cool ────────────────────────────────────────────────
    {
        "id": "modern-cool",
        "palette": {
            "accent":  "#2A4858",
            "accent2": "#5B7E91",
            "light":   "#EEF3F6",
        },
        "fonts": {
            "body":    "Helvetica",
            "heading": "Helvetica-Bold",
            "italic":  "Helvetica-Oblique",
        },
        "symbol": "◈",
        "cover_art_hint": (
            "modern minimalist design, cool muted blues and slate grays, "
            "geometric and clean, Scandinavian editorial style"
        ),
        "tone": "modern, confident, and direct",
        "title_style": "punchy and benefit-driven, with a strong promise",
    },

    # ─── 3. Botanical Natural ──────────────────────────────────────────
    {
        "id": "botanical-natural",
        "palette": {
            "accent":  "#3C5A3A",
            "accent2": "#6F9168",
            "light":   "#EFF5EE",
        },
        "fonts": {
            "body":    "Times-Roman",
            "heading": "Helvetica-Bold",
            "italic":  "Times-Italic",
        },
        "symbol": "❋",
        "cover_art_hint": (
            "detailed botanical illustration, forest greens with moss and bark "
            "accents, naturalist field-guide style, leafy ornamental details"
        ),
        "tone": "thoughtful, grounded, and observational",
        "title_style": "descriptive and field-guide-like, with specific imagery",
    },

    # ─── 4. Bold Vibrant ───────────────────────────────────────────────
    {
        "id": "bold-vibrant",
        "palette": {
            "accent":  "#A02C5C",
            "accent2": "#D86CA0",
            "light":   "#FBEDF3",
        },
        "fonts": {
            "body":    "Helvetica",
            "heading": "Helvetica-Bold",
            "italic":  "Helvetica-Oblique",
        },
        "symbol": "★",
        "cover_art_hint": (
            "bold vibrant colors, energetic composition, pop-art influenced, "
            "high contrast, magazine-cover energy"
        ),
        "tone": "bold, energetic, and empowering",
        "title_style": "loud and exclamatory, with action verbs and intensity",
    },

    # ─── 5. Monochrome Elegant ─────────────────────────────────────────
    {
        "id": "monochrome-elegant",
        "palette": {
            "accent":  "#2D2D2D",
            "accent2": "#666666",
            "light":   "#F0F0F0",
        },
        "fonts": {
            "body":    "Times-Roman",
            "heading": "Times-Bold",
            "italic":  "Times-Italic",
        },
        "symbol": "❧",
        "cover_art_hint": (
            "elegant black and white photography, refined high-end typography, "
            "fine art aesthetic, sophisticated minimalism, gallery-quality"
        ),
        "tone": "elegant, refined, and contemplative",
        "title_style": "sophisticated and understated, with literary phrasing",
    },

    # ─── 6. Pastel Dreamy ──────────────────────────────────────────────
    {
        "id": "pastel-dreamy",
        "palette": {
            "accent":  "#6B5B95",
            "accent2": "#A18FC0",
            "light":   "#F4F0F9",
        },
        "fonts": {
            "body":    "Times-Roman",
            "heading": "Helvetica-Bold",
            "italic":  "Times-Italic",
        },
        "symbol": "❈",
        "cover_art_hint": (
            "pastel dreamlike palette, soft lavenders and dusty pinks, "
            "ethereal atmosphere, gentle pastel watercolor wash"
        ),
        "tone": "dreamy, gentle, and reflective",
        "title_style": "soft and whispered, with sensory and dreamy language",
    },

    # ─── 7. Nordic Clean ───────────────────────────────────────────────
    {
        "id": "nordic-clean",
        "palette": {
            "accent":  "#1F4068",
            "accent2": "#62828F",
            "light":   "#F0F2F5",
        },
        "fonts": {
            "body":    "Helvetica",
            "heading": "Helvetica-Bold",
            "italic":  "Helvetica-Oblique",
        },
        "symbol": "◆",
        "cover_art_hint": (
            "Scandinavian minimalist design, navy and ice blue palette, "
            "geometric simplicity, lots of negative space, magazine-grade layout"
        ),
        "tone": "calm, structured, and intentional",
        "title_style": "minimal and structured, with crisp clarity",
    },

    # ─── 8. Sunset Warm ────────────────────────────────────────────────
    {
        "id": "sunset-warm",
        "palette": {
            "accent":  "#C2522B",
            "accent2": "#E8916C",
            "light":   "#FDF1EB",
        },
        "fonts": {
            "body":    "Times-Roman",
            "heading": "Helvetica-Bold",
            "italic":  "Times-Italic",
        },
        "symbol": "✿",
        "cover_art_hint": (
            "warm sunset gradient, orange and golden hour tones with deep pinks, "
            "soft cinematic lighting, romantic golden-hour mood"
        ),
        "tone": "uplifting, hopeful, and golden",
        "title_style": "uplifting and aspirational, with imagery of light and warmth",
    },
]


def get_variant(index: int) -> Dict:
    """Returns the variant at position `index` (wraps around the list)."""
    return STYLE_VARIANTS[index % len(STYLE_VARIANTS)]


def variant_count() -> int:
    return len(STYLE_VARIANTS)


def variant_for_niche(niche: str) -> Dict:
    """
    Returns a deterministic-but-distinct variant based on the niche name.
    Used for single-product batches so the same niche always gets the same
    style (consistent re-runs) but different niches get different styles.
    """
    import hashlib
    h = int(hashlib.md5((niche or "x").encode("utf-8")).hexdigest()[:8], 16)
    return STYLE_VARIANTS[h % len(STYLE_VARIANTS)]
