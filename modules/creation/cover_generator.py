"""
KDP Cover Generator — DALL-E 3 + Pillow + ReportLab
Produces a professional full-wrap KDP cover PDF.

Dimensions (B&W cream paper):
  Spine width  = page_count × 0.002252 inches
  Full width   = 0.125 (bleed) + 6 (back) + spine + 6 (front) + 0.125 (bleed)
  Full height  = 9 + 0.125 (top bleed) + 0.125 (bottom bleed) = 9.25 inches
"""
import io
import logging
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

logger = logging.getLogger(__name__)

DPI        = 300
BLEED      = 0.125   # inches
PAGE_W_IN  = 6.0     # legacy — overridden by listing.trim_size if present
PAGE_H_IN  = 9.0
SPINE_PER_PAGE = 0.002252  # legacy — overridden by paper_type


# ── Artistic font pools for the cover (macOS system fonts) ───────────────────
# Picked at random per cover for variety. Each tuple = (regular_path, bold_path).
_SUP = "/System/Library/Fonts/Supplemental/"
_SYS = "/System/Library/Fonts/"

# ── Expanded font pool — 40 curated typefaces for cover diversity ───────────
# Organized by typographic category. Indices are STABLE (only append, never reorder).
_DISPLAY_FONT_POOL = [
    # ── SERIF — ELEGANT EDITORIAL (0-12) ──
    (_SUP + "Baskerville.ttc",                _SUP + "Baskerville.ttc"),                # 0  Baskerville classic
    (_SUP + "Didot.ttc",                      _SUP + "Didot.ttc"),                      # 1  Didot high-fashion
    (_SUP + "Bodoni 72.ttc",                  _SUP + "Bodoni 72.ttc"),                  # 2  Bodoni 72
    (_SUP + "Bodoni 72 Smallcaps Book.ttf",   _SUP + "Bodoni 72 Smallcaps Book.ttf"),   # 3  Bodoni Smallcaps
    (_SUP + "Bodoni 72 OS.ttc",               _SUP + "Bodoni 72 OS.ttc"),               # 4  Bodoni Old Style
    (_SUP + "BigCaslon.ttf",                  _SUP + "BigCaslon.ttf"),                  # 5  Big Caslon
    (_SUP + "Hoefler Text.ttc",               _SUP + "Hoefler Text.ttc"),               # 6  Hoefler Text
    (_SUP + "Cochin.ttc",                     _SUP + "Cochin.ttc"),                     # 7  Cochin French
    (_SUP + "Athelas.ttc",                    _SUP + "Athelas.ttc"),                    # 8  Athelas modern
    (_SUP + "Charter.ttc",                    _SUP + "Charter.ttc"),                    # 9  Charter readable
    (_SUP + "Iowan Old Style.ttc",            _SUP + "Iowan Old Style.ttc"),            # 10 Iowan vintage
    (_SUP + "Georgia.ttf",                    _SUP + "Georgia Bold.ttf"),               # 11 Georgia
    (_SUP + "PTSerif.ttc",                    _SUP + "PTSerif.ttc"),                    # 12 PT Serif

    # ── SERIF — SLAB / DECORATIVE (13-15) ──
    (_SUP + "Rockwell.ttc",                   _SUP + "Rockwell.ttc"),                   # 13 Rockwell slab
    (_SUP + "SuperClarendon.ttc",             _SUP + "SuperClarendon.ttc"),             # 14 Super Clarendon
    (_SUP + "AmericanTypewriter.ttc",         _SUP + "AmericanTypewriter.ttc"),         # 15 American Typewriter

    # ── SANS — MODERN MINIMAL (16-25) ──
    (_SUP + "Futura.ttc",                     _SUP + "Futura.ttc"),                     # 16 Futura geometric
    (_SUP + "GillSans.ttc",                   _SUP + "GillSans.ttc"),                   # 17 Gill Sans humanist
    (_SYS + "Avenir.ttc",                     _SYS + "Avenir.ttc"),                     # 18 Avenir premium
    (_SYS + "Avenir Next.ttc",                _SYS + "Avenir Next.ttc"),                # 19 Avenir Next
    (_SYS + "Avenir Next Condensed.ttc",      _SYS + "Avenir Next Condensed.ttc"),      # 20 Avenir Condensed
    (_SYS + "HelveticaNeue.ttc",              _SYS + "HelveticaNeue.ttc"),              # 21 Helvetica Neue
    (_SUP + "PTSans.ttc",                     _SUP + "PTSans.ttc"),                     # 22 PT Sans
    (_SUP + "Seravek.ttc",                    _SUP + "Seravek.ttc"),                    # 23 Seravek modern
    (_SUP + "Trebuchet MS.ttf",               _SUP + "Trebuchet MS Bold.ttf"),          # 24 Trebuchet
    (_SUP + "Verdana.ttf",                    _SUP + "Verdana Bold.ttf"),               # 25 Verdana wide

    # ── SANS — BOLD DISPLAY (26-31) ──
    (_SUP + "Impact.ttf",                     _SUP + "Impact.ttf"),                     # 26 Impact heavy
    (_SUP + "Arial Black.ttf",                _SUP + "Arial Black.ttf"),                # 27 Arial Black
    (_SUP + "DIN Alternate Bold.ttf",         _SUP + "DIN Alternate Bold.ttf"),         # 28 DIN Alternate
    (_SUP + "DIN Condensed Bold.ttf",         _SUP + "DIN Condensed Bold.ttf"),         # 29 DIN Condensed
    (_SUP + "Arial Rounded Bold.ttf",         _SUP + "Arial Rounded Bold.ttf"),         # 30 Arial Rounded
    (_SUP + "Phosphate.ttc",                  _SUP + "Phosphate.ttc"),                  # 31 Phosphate stencil

    # ── SCRIPT — CURSIVE / CALLIGRAPHIC (32-36) ──
    (_SUP + "SnellRoundhand.ttc",             _SUP + "SnellRoundhand.ttc"),             # 32 Snell Roundhand
    (_SUP + "Apple Chancery.ttf",             _SUP + "Apple Chancery.ttf"),             # 33 Apple Chancery
    (_SUP + "Savoye LET.ttc",                 _SUP + "Savoye LET.ttc"),                 # 34 Savoye elegant
    (_SUP + "Zapfino.ttf",                    _SUP + "Zapfino.ttf"),                    # 35 Zapfino ornate
    (_SUP + "Corsiva.ttc",                    _SUP + "Corsiva.ttc"),                    # 36 Monotype Corsiva

    # ── HAND-DRAWN / MARKER (37-42) ──
    (_SUP + "Chalkduster.ttf",                _SUP + "Chalkduster.ttf"),                # 37 Chalkduster
    (_SUP + "Chalkboard.ttc",                 _SUP + "Chalkboard.ttc"),                 # 38 Chalkboard
    (_SUP + "Bradley Hand Bold.ttf",          _SUP + "Bradley Hand Bold.ttf"),          # 39 Bradley Hand
    (_SUP + "Brush Script.ttf",               _SUP + "Brush Script.ttf"),               # 40 Brush Script
    (_SUP + "SignPainter.ttc",                _SUP + "SignPainter.ttc"),                # 41 Sign Painter
    (_SYS + "MarkerFelt.ttc",                 _SYS + "MarkerFelt.ttc"),                 # 42 Marker Felt

    # ── DECORATIVE / FANTASY / VINTAGE (43-48) ──
    (_SUP + "Copperplate.ttc",                _SUP + "Copperplate.ttc"),                # 43 Copperplate engraved
    (_SUP + "Academy Engraved LET Fonts.ttf", _SUP + "Academy Engraved LET Fonts.ttf"), # 44 Academy Engraved
    (_SUP + "Trattatello.ttf",                _SUP + "Trattatello.ttf"),                # 45 Trattatello medieval
    (_SUP + "Luminari.ttf",                   _SUP + "Luminari.ttf"),                   # 46 Luminari fantasy
    (_SUP + "Papyrus.ttc",                    _SUP + "Papyrus.ttc"),                    # 47 Papyrus historical
    (_SUP + "Herculanum.ttf",                 _SUP + "Herculanum.ttf"),                 # 48 Herculanum Roman
]


# Category indices (stable references used by font strategy)
_SERIF_EDITORIAL   = list(range(0, 13))   # 0-12
_SERIF_DECORATIVE  = list(range(13, 16))  # 13-15 (slab/typewriter)
_SANS_MINIMAL      = list(range(16, 26))  # 16-25
_SANS_BOLD         = list(range(26, 32))  # 26-31
_SCRIPT_CURSIVE    = list(range(32, 37))  # 32-36
_HAND_MARKER       = list(range(37, 43))  # 37-42
_DECORATIVE_FANTASY = list(range(43, 49)) # 43-48


# Niche-keyword → preferred font index subset (still random within the subset)
_NICHE_FONT_AFFINITY = {
    "kids":     [38, 39, 41, 42, 30, 17, 33],                  # marker/hand/chalk/rounded
    "horror":   [26, 27, 5, 11, 45, 46, 47, 48],              # impact + slab + medieval/fantasy
    "vintage":  [1, 2, 3, 4, 5, 6, 7, 10, 11, 13, 14, 15, 43, 44],  # didot/bodoni/serif/slab/engraved
    "elegant":  [0, 1, 2, 4, 6, 7, 8, 9, 32, 33, 34, 43, 44], # editorial + script + engraved
    "modern":   [16, 17, 18, 19, 20, 21, 22, 23, 24],         # full sans-modern pool
    "bold":     [26, 27, 28, 29, 30, 31, 5, 13, 14],          # impact + DIN + slab
    "script":   [32, 33, 34, 35, 36, 40, 41],                 # all script + brush + sign-painter
    "art":      [6, 7, 8, 32, 33, 36, 37, 38, 41, 43],        # refined + script + hand + engraved
    "fantasy":  [45, 46, 47, 48, 5, 32, 35],                  # medieval + Roman + ornate
    "spiritual":[33, 35, 36, 47, 32, 8, 11],                  # script + papyrus + serif
    "cooking":  [10, 11, 13, 15, 24, 8],                      # iowan + slab + typewriter + readable
    "fitness":  [26, 27, 28, 29, 22, 17],                     # bold sans + DIN
    "tech":     [16, 19, 20, 21, 22, 28, 29],                 # geometric + condensed
    "romance":  [33, 34, 35, 36, 2, 6, 8],                    # script + delicate serif
    "music":    [26, 27, 29, 31, 41, 40, 14],                 # impact + stencil + sign-painter
}


_NICHE_MARKERS = {
    "kids":      ["kid", "child", "toddler", "baby", "girl", "boy", "preschool", "kindergarten"],
    "horror":    ["horror", "ghost", "haunted", "paranormal", "occult", "creep", "macabre", "dark"],
    "vintage":   ["vintage", "antique", "victorian", "retro", "classic", "1900", "1800", "old"],
    "elegant":   ["wedding", "luxury", "gourmet", "wine", "tea", "fine", "premium", "boutique"],
    "modern":    ["modern", "minimalist", "design", "startup", "productivity", "agile", "lean"],
    "bold":      ["sport", "fitness", "gym", "extreme", "warrior", "champion"],
    "script":    ["calligraphy", "diary", "love", "poetry", "wedding", "anniversary"],
    "art":       ["art", "color", "draw", "sketch", "mandala", "zentangle", "creative", "paint"],
    "fantasy":   ["dragon", "magic", "wizard", "myth", "legend", "fairy", "knight"],
    "spiritual": ["spirit", "yoga", "meditat", "mindful", "tarot", "moon", "manifest", "chakra"],
    "cooking":   ["recipe", "cook", "kitchen", "bake", "food", "chef"],
    "fitness":   ["fitness", "gym", "running", "workout", "training", "exercise"],
    "tech":      ["tech", "code", "coding", "developer", "engineer", "ai", "ml"],
    "romance":   ["romance", "love", "passion", "couple", "date"],
    "music":     ["music", "rock", "metal", "hip", "rap", "jazz", "vinyl", "guitar", "drum"],
    "journal":   ["journal", "notebook", "log", "diary", "planner"],
}


# ── Named font catalogue for the UI title-font picker ───────────────────────
# Maps a human-friendly label → index in _DISPLAY_FONT_POOL. Curated subset of
# the most cover-worthy faces, grouped by style. Used by the "Police du titre"
# dropdown in the Fine-tune cover panel. Indices must stay valid against
# _DISPLAY_FONT_POOL above.
TITLE_FONT_CHOICES = {
    "✨ Auto (selon niche)":        None,
    "— Serif élégant —":           -1,   # disabled separator
    "Baskerville (classique)":     0,
    "Didot (haute couture)":       1,
    "Bodoni 72":                   2,
    "Big Caslon":                  5,
    "Hoefler Text":                6,
    "Georgia":                     11,
    "— Slab / Vintage —":          -1,
    "Rockwell (slab)":             13,
    "Super Clarendon":             14,
    "American Typewriter":         15,
    "— Sans moderne —":            -1,
    "Futura (géométrique)":        16,
    "Gill Sans":                   17,
    "Avenir Next":                 19,
    "Helvetica Neue":              21,
    "— Bold / Impact —":           -1,
    "Impact (lourd)":              26,
    "Arial Black":                 27,
    "DIN Condensed":               29,
    "Phosphate (stencil)":         31,
    "— Script / Cursive —":        -1,
    "Snell Roundhand":             32,
    "Apple Chancery":              33,
    "Savoye (mariage)":            34,
    "Zapfino (ornemental)":        35,
    "— Hand / Marker —":           -1,
    "Chalkboard":                  38,
    "Bradley Hand":                39,
    "Marker Felt":                 42,
    "— Fantasy / Vintage —":       -1,
    "Copperplate (gravé)":         43,
    "Trattatello (médiéval)":      45,
    "Luminari (fantasy)":          46,
    "Papyrus":                     47,
    "Herculanum (romain)":         48,
}


def _resolve_title_font(choice) -> Optional[Tuple[str, str]]:
    """
    Resolve a UI title-font choice (label string OR raw index) to a
    (regular_path, bold_path) tuple. Returns None for 'auto' / invalid /
    separator so the caller falls back to the strategy pool.
    """
    if choice is None or choice == "":
        return None
    idx = None
    # Accept a label from TITLE_FONT_CHOICES, or a direct int index
    if isinstance(choice, str):
        if choice in TITLE_FONT_CHOICES:
            idx = TITLE_FONT_CHOICES[choice]
        elif choice.isdigit():
            idx = int(choice)
    elif isinstance(choice, (int, float)):
        idx = int(choice)
    if idx is None or idx < 0 or idx >= len(_DISPLAY_FONT_POOL):
        return None
    return _DISPLAY_FONT_POOL[idx]


def _detect_font_affinity(niche: str) -> Optional[List[int]]:
    """Returns the font index pool matching the niche, or None for free pick."""
    nl = (niche or "").lower()
    for key, idxs in _NICHE_FONT_AFFINITY.items():
        if any(m in nl for m in _NICHE_MARKERS.get(key, [])):
            return idxs
    return None


def _pick_cover_font_pair(niche: str) -> Tuple[str, str]:
    """Random artistic font pair, biased toward niche-appropriate fonts."""
    import random as _random
    candidates_idx = _detect_font_affinity(niche)
    if candidates_idx:
        idx = _random.choice(candidates_idx)
    else:
        idx = _random.randrange(len(_DISPLAY_FONT_POOL))
    return _DISPLAY_FONT_POOL[idx]


# ── Dimension helpers ─────────────────────────────────────────────────────────

def cover_dims(
    page_count: int,
    trim_w: float = PAGE_W_IN,
    trim_h: float = PAGE_H_IN,
    paper_type: str = "white",
    binding: str = "paperback",
) -> Dict:
    """
    Returns all KDP cover dimensions following the OFFICIAL Amazon spec.
    Uses modules.creation.kdp_specs.compute_cover_dims() for exact formula.
    Accepts arbitrary trim sizes + paper type + binding (paperback/hardcover).
    """
    from modules.creation.kdp_specs import compute_cover_dims
    return compute_cover_dims(page_count, trim_w, trim_h, paper_type, binding)


# ── DALL-E prompt builder ─────────────────────────────────────────────────────

_STYLE_MAP = {
    "journal": (
        "moody, aesthetic, cinematic photograph-style book cover illustration. "
        "Rich textures, elegant typography-friendly negative space at top and bottom."
    ),
    "log": (
        "detailed, professional field-guide illustration style. "
        "Nature-inspired, earthy tones, botanical or scientific feel."
    ),
    "quiz": (
        "bold, graphic, eye-catching pop-art style illustration. "
        "High contrast, vibrant colors, dynamic composition."
    ),
    "planner": (
        "clean, modern, minimalist design. Soft colors, "
        "geometric elements, professional yet approachable."
    ),
    "coloring": (
        "vibrant, colorful and inviting coloring-book COVER illustration. "
        "Show a few beautifully COLORED sample motifs from the book against a clean bright background — "
        "cheerful, polished and eye-catching, professional coloring-book cover aesthetic with "
        "rich saturated colors. This is the printed COVER, so it must be in FULL COLOR, "
        "NOT black-and-white line art."
    ),
}

_FREE_STYLE_HINTS = [
    "moody cinematic photography with rich golden-hour lighting and a hero subject filling the frame",
    "elegant flat illustration with bold geometric shapes and a confident limited color palette",
    "luxurious watercolor and ink illustration with delicate textures and refined typography space",
    "modern editorial cover with high-contrast central subject and dramatic negative space",
    "vintage etching / antique field-guide aesthetic with detailed engraved illustration",
    "bold pop-art illustration with vibrant saturated colors and graphic composition",
    "soft pastel hand-painted illustration with dreamy atmosphere and inviting warmth",
    "premium minimalist cover with a single iconic centred subject and clean negative space",
    "rich oil-painting style illustration with painterly brush strokes and depth",
    "contemporary digital illustration with bold gradients, subtle grain, and modern design language",
    "vintage poster art style with stylised subject, period-correct palette, and timeless feel",
    "ethereal mixed-media collage with layered textures and a striking focal subject",
    "art-nouveau inspired illustration with elegant flowing lines and ornamental details",
    "japanese ukiyo-e woodblock print aesthetic with bold outlines and traditional palette",
    "scandinavian folk-art style with stylised motifs and earthy harmonious colors",
    "art-deco geometric illustration with metallic accents and symmetrical composition",
    "dreamy surrealist illustration blending realistic and fantastical elements",
    "bold linocut / block-print style with high contrast and confident hand-carved feel",
    "lush botanical illustration with detailed flora and natural color harmony",
    "moody chiaroscuro painting with dramatic shadow and a single illuminated subject",
    "playful collage with cut-paper textures and a charming hand-made aesthetic",
    "graphic-novel cover style with bold panels, expressive subject, and confident inking",
    "dreamy gouache painting with matte finish and rich layered color",
    "indie zine aesthetic with hand-drawn linework and slightly imperfect charm",
]


def _style_hints_for_niche(niche: str) -> List[str]:
    """
    Returns a niche-appropriate subset of style hints — but always wide enough
    to give the AI freedom. Falls back to the full pool if no keywords match.
    """
    nl = (niche or "").lower()
    bias_map = {
        ("kid", "child", "toddler", "baby"):       [5, 6, 14, 20, 23],            # bright + playful + collage + zine
        ("horror", "ghost", "occult", "haunted"):  [0, 4, 17, 18, 19],            # moody + etching + dramatic
        ("vintage", "antique", "victorian"):       [4, 10, 12, 13, 17, 18, 22],   # etching + nouveau + ukiyo-e + linocut
        ("wedding", "luxury", "gourmet"):          [2, 7, 8, 9, 15, 22],          # watercolor + minimalist + oil + deco
        ("mandala", "zentangle", "yoga", "spirit"):[2, 12, 13, 14, 18, 21],       # watercolor + nouveau + ukiyo-e + folk
        ("nature", "garden", "plant", "forest"):   [2, 4, 14, 18, 21],            # watercolor + etching + folk + botanical
        ("travel", "explore", "map"):              [0, 3, 9, 10, 22],             # cinematic + digital + poster + graphic-novel
        ("sport", "fitness", "gym"):               [5, 9, 15, 17, 21],            # pop-art + digital + deco + linocut
        ("art", "color", "draw", "sketch"):        [2, 8, 11, 22, 23],            # watercolor + oil + collage + gouache
        ("planner", "productivity", "business"):   [1, 3, 7, 9, 15],              # flat + editorial + minimalist + digital + deco
        ("food", "recipe", "cook"):                [2, 6, 8, 11, 18, 21],         # watercolor + pastel + oil + collage + linocut
        ("music", "rock", "hip", "rap"):           [5, 9, 11, 17, 21],            # pop-art + digital + collage + dramatic
    }
    for keys, idxs in bias_map.items():
        if any(k in nl for k in keys):
            # Mix: 70% biased + 30% wildcard for surprise
            import random as _random
            biased = [_FREE_STYLE_HINTS[i] for i in idxs]
            wildcards = _random.sample(_FREE_STYLE_HINTS, min(3, len(_FREE_STYLE_HINTS)))
            return biased + wildcards
    return _FREE_STYLE_HINTS


_COLORING_COVER_COMPOSITIONS = [
    "the central illustration is half-finished — the LEFT side is fully colored in vibrant rich colors "
    "while the RIGHT side remains as black line art, like a 'before and after' coloring reveal. "
    "Show colored pencils or markers softly placed nearby",
    "the central illustration is partially colored from the center outward, with vibrant saturated color in the middle "
    "fading into pristine black line art at the edges, evoking the joy of coloring in progress",
    "a beautifully colored finished illustration in the upper portion paired with the same design as pristine line art below, "
    "framed elegantly to invite the reader to color it themselves",
    "the hero illustration is FULLY colored in vibrant artistic colors with subtle visible pencil-stroke texture, "
    "showcasing the gorgeous result this book can produce — surrounded by complementary colored details",
    "the central illustration is colored in rich watercolor washes that bleed softly into white space, "
    "with crisp black line-art details still visible — gallery-worthy art-book aesthetic",
]


def _coloring_cover_subject(listing: Dict) -> str:
    """Picks one concrete subject from the book's interior to feature on the cover."""
    import random as _random
    candidates = []
    for sec in listing.get("content_sections", []):
        if sec.get("type") in ("content", "qa", "tracker"):
            for it in sec.get("items", []):
                if isinstance(it, str) and 5 < len(it) < 80:
                    candidates.append(it.strip())
    if candidates:
        return _random.choice(candidates[:20])   # pick from first 20 to keep on-theme
    # Fallback: derive from niche
    niche = listing.get("niche", "")
    return f"a beautiful signature illustration from {niche}"


_COLORING_NICHE_ATMOSPHERE = [
    # (keyword triggers,  atmospheric directive)
    (("bioluminescent", "glow", "glowing", "deep sea", "abyss", "luminous"),
     "MOOD : magical deep-sea darkness with vivid BIOLUMINESCENT GLOW. Cool teal-blue-violet "
     "background with pops of cyan, neon green and electric pink lighting up the subject. "
     "The subject literally GLOWS against the deep dark water. Dark navy backdrop, glowing rim "
     "light on the marine creature, glow particles drifting in the water."),
    (("witch", "witchy", "spell", "ritual", "occult", "moon", "tarot"),
     "MOOD : witchy mystical atmosphere — deep midnight purples, indigo and gold, "
     "moonlight glow, candles, subtle starry sparkle in the background."),
    (("halloween", "spooky", "haunted", "ghost", "macabre", "gothic"),
     "MOOD : moody spooky atmosphere — deep purples, blacks, oranges, candlelight glow, "
     "gothic ornamental details, slightly mysterious."),
    (("dark academia",),
     "MOOD : dark academia — rich burgundy, forest green, antique gold, candlelight, "
     "old library texture in the background."),
    (("ocean", "underwater", "marine", "sea creature", "coral"),
     "MOOD : underwater scene — turquoise water gradients, sun rays piercing from above, "
     "schools of small fish or bubbles in the background."),
    (("space", "galaxy", "cosmic", "nebula", "celestial", "stars"),
     "MOOD : cosmic celestial — deep navy with nebula clouds, starry sky, soft glow halo "
     "around the subject."),
    (("forest", "woodland", "fairy", "enchanted"),
     "MOOD : enchanted forest — emerald greens, dappled golden light filtering through "
     "leaves, mossy textures, magical sparkles."),
    (("kid", "child", "toddler", "preschool", "baby", "girls", "boys"),
     "MOOD : bright cheerful playful — primary colors and pastels, sunny daylight, "
     "friendly and approachable."),
    (("flower", "botanical", "garden", "bloom"),
     "MOOD : lush botanical — saturated florals, soft natural light, garden setting, "
     "harmonious pastel-to-jewel-tone palette."),
    (("mandala", "zen", "meditation"),
     "MOOD : zen — calm pastel palette, soft symmetric composition, meditative."),
]


def _coloring_niche_atmosphere(niche: str) -> str:
    """Return a niche-specific atmospheric directive for the cover."""
    n = (niche or "").lower()
    for triggers, atmosphere in _COLORING_NICHE_ATMOSPHERE:
        if any(t in n for t in triggers):
            return atmosphere
    return ""


def _build_coloring_cover_prompt(
    listing: Dict, color_hint: str, design_hint: str, free_style: bool,
) -> str:
    """Art-directed coloring book cover: features one real interior subject,
    partially or fully colored in a competitor-aware palette."""
    import random as _random
    niche       = listing["niche"]
    subject     = _coloring_cover_subject(listing)
    composition = _random.choice(_COLORING_COVER_COMPOSITIONS)
    atmosphere  = _coloring_niche_atmosphere(niche)

    # Detect kids vs adult to set the right vibe
    kids_markers = ["kid", "child", "toddler", "preschool", "baby", "girls", "boys"]
    is_kids = any(k in niche.lower() for k in kids_markers)
    vibe = (
        "cheerful, playful, bright primary and pastel colors, friendly and approachable, "
        "suitable for children — a happy joyful coloring book cover"
        if is_kids else
        "elegant, sophisticated, rich jewel tones and harmonious palette, gallery-quality, "
        "appealing to adults seeking mindful relaxation — a premium adult coloring book cover"
    )

    # Adult coloring books benefit from richer era + medium hints than kids
    if is_kids:
        medium = "playful gouache illustration with chunky shapes and clear outlines"
        era    = "warm picture-book sensibility, mid-century children's book feel"
        light  = "soft directional daylight, no harsh contrasts"
    else:
        medium = "richly textured gouache or screen-printed poster illustration with grainy overlay"
        era    = ("with refined art-nouveau decorative influence" if _random.random() < 0.5
                  else "with contemporary indie-bookstore-poster sensibility")
        light  = "elegant chiaroscuro with a single warm key light and velvety shadows"

    return (
        f"PROFESSIONAL COLORING BOOK COVER for an Amazon KDP book on '{niche}'.\n\n"
        f"FEATURED SUBJECT (most important) : {subject}. Render it LARGE, anatomically "
        f"accurate, instantly recognisable as exactly that subject. The buyer must see "
        f"the thumbnail and INSTANTLY know what creature/scene this book is about.\n\n"
        f"COMPOSITION : {composition}.\n"
        f"LIGHTING : {light}.\n"
        f"VIBE : {vibe}\n"
        f"{atmosphere}\n\n"
        f"MEDIUM : {medium}, {era}.\n\n"
        f"{color_hint}{design_hint}\n\n"
        "CRITICAL :\n"
        "- The cover is FULLY COLOURED (NOT black-and-white line art — line art lives "
        "inside the book only).\n"
        "- The subject MUST visually match the niche EXACTLY — for an ocean book show "
        "real ocean creatures, for a flower book show real flowers, etc.\n"
        "- High-quality painterly finish, not generic AI render.\n\n"
        "TECHNICAL & QUALITY :\n"
        "- Fill the FULL SQUARE FRAME edge-to-edge, no borders.\n"
        "- Rich harmonised palette : 4-6 sophisticated colours with ONE punchy accent.\n"
        "- Sharp anatomical detail in the subject — visible texture, hand-illustrated feel.\n"
        "- 300 DPI print-ready.\n\n"
        "ABSOLUTE EXCLUSIONS :\n"
        "- ZERO text, words, letters, numbers, signatures, watermarks (text added in post).\n"
        "- NO generic AI render look (no plastic skin, no symmetric stock face, "
        "no gradient-only background, no stock composition).\n"
        "- NO copyrighted characters, mascots, trademarks, celebrity likenesses.\n"
        "- NO violence, no gore, no sexual content.\n"
        "- NO unrelated abstract art — the subject must clearly represent the niche.\n\n"
        "BENCHMARK : the cover of a flagship indie publisher's coloring-book bestseller — "
        "a buyer scrolling Amazon must INSTANTLY know what's inside from the imagery alone."
    )


# ── Cover-image direction (CONTENT-FIRST, not abstract art) ──────────────────
# Goal : the cover image MUST visually represent what the book is about.
# A beekeeper log → show actual bees / hives. An AI tracker → show real
# devices / dashboards / robots. NEVER a generic abstract gouache painting.

_COMPOSITION_BANK = [
    "single strong hero subject filling the centre of the frame, with the niche-specific objects clearly visible and recognisable at a glance",
    "the subject placed slightly off-centre using rule-of-thirds, with related niche items in the surrounding space giving context",
    "close-up framing of the subject from a slightly low angle, making it feel important and grounded",
    "the subject in the foreground with a clean simple background that doesn't compete for attention",
    "the subject is shown mid-action or in use, telling a small story about what the book is for",
    "a clean isometric arrangement of the niche's actual tools, objects, or characters laid out clearly",
]

_LIGHTING_BANK = [
    "natural daylight with soft shadows — looks real and inviting",
    "warm directional light that highlights the textures of the subject",
    "clean studio lighting with crisp edges and balanced shadows",
    "soft window light that gives the scene a calm, premium feel",
    "bright even lighting that keeps every important detail readable",
    "subtle dramatic side-lighting that adds depth without darkness",
]

_MOOD_BANK = [
    "inviting and trustworthy — the buyer instantly understands the book's purpose",
    "warm and approachable, like a friend recommending the book",
    "confident and premium without being intimidating",
    "calm and focused — perfect for a serious useful book",
    "energetic and motivating, showing the buyer the outcome they want",
    "modern and clean, like a well-designed lifestyle product",
]

_RENDER_STYLE_BANK = [
    "modern detailed illustration with realistic proportions and clear recognisable objects",
    "polished 3D-render look with soft lighting and subtle materials — feels like a product shot",
    "premium digital painting that shows real objects in their real context, not abstract shapes",
    "clean vector illustration with rich gradients and depth — bright, sharp, contemporary",
    "stylised photo-real illustration that emphasises the niche's hero objects",
    "high-quality semi-realistic illustration with confident detail in the subject and clean background",
]


def _niche_subject_directive(niche: str, product_type: str) -> str:
    """
    Returns a content-first instruction telling the model WHAT to actually draw.
    Maps niches → real subjects (no abstract art).
    """
    n = (niche or "").lower()
    # Domain → concrete subject mapping. First match wins.
    if any(w in n for w in ("ai ", "automation", "machine learning", "ml ", "chatbot",
                              "prompt", "workflow", "llm")):
        return ("show a friendly modern robot / AI assistant with a clean dashboard or tablet, "
                "with clear icons of charts, checkmarks, gears — premium tech aesthetic")
    if any(w in n for w in ("bee", "hive", "apiary", "honey")):
        return "show realistic honeybees and a wooden bee hive with honeycomb and a beekeeper smoker"
    if any(w in n for w in ("fish", "angl", "tackle")):
        return "show a real fish breaching water, fishing rod and lure visible, lake or stream backdrop"
    if any(w in n for w in ("garden", "plant", "botanic", "herb")):
        return "show real plants, leaves, flowers, gardening tools — botanical accuracy"
    if any(w in n for w in ("dog", "puppy", "canine", "train")):
        return "show a real friendly dog mid-pose with leash or training clicker, natural setting"
    if any(w in n for w in ("cat", "kitten", "feline")):
        return "show a real cat in a natural pose, soft warm setting"
    if any(w in n for w in ("ufo", "alien", "paranormal", "cryptid")):
        return "show a stylised UFO silhouette over a night sky landscape with stars and subtle mystery"
    if any(w in n for w in ("wine", "sommelier", "vino", "vineyard", "tasting")):
        return "show a wine glass with red or white wine, a bottle, grapes or cork — elegant cellar aesthetic"
    if any(w in n for w in ("whisky", "whiskey", "scotch", "bourbon", "cigar")):
        return "show a glass of amber spirit, ice cubes, a bottle in soft warm light — premium lifestyle"
    if any(w in n for w in ("coffee", "espresso", "barista")):
        return "show a cup of coffee with crema, beans, a moka pot or french press — cosy café aesthetic"
    if any(w in n for w in ("recipe", "cook", "kitchen", "baking", "food", "meal")):
        return "show real ingredients and kitchen objects (bowl, whisk, herbs) in a clean styled flat-lay"
    if any(w in n for w in ("workout", "fitness", "gym", "training", "muscle", "exercise")):
        return "show a real person mid-exercise or a clean arrangement of dumbbells, mat, water bottle"
    if any(w in n for w in ("anxiety", "depression", "mental", "mindful", "calm",
                              "stress", "self care", "self-care", "therapy")):
        return ("show a calming scene: a person journaling at a window, plants and tea, "
                "soft pastel light — wellness lifestyle aesthetic")
    if any(w in n for w in ("planner", "productivity", "etsy", "freelance", "business",
                              "entrepreneur")):
        return ("show a clean modern desk flat-lay : open planner, pen, coffee, laptop, "
                "plant — productivity lifestyle aesthetic")
    if any(w in n for w in ("trivia", "quiz", "question")):
        return ("show stylised quiz props : a giant question mark, lightbulb moment, "
                "playing cards or game-show vibe — fun energetic")
    if any(w in n for w in ("maze",)):
        return "show an actual maze pattern viewed from above with subtle path lines"
    if any(w in n for w in ("sudoku", "crossword", "logic puzzle", "kakuro", "kenken")):
        return "show a stylised puzzle grid (numbers / letters in clean cells) with pencil and eraser"
    if any(w in n for w in ("crypto", "cipher")):
        return "show a stylised alphabet substitution chart with elegant typography"
    if any(w in n for w in ("astrology", "tarot", "moon", "manifestation", "witch", "ritual",
                              "spell", "chakra", "esoteric", "shadow work")):
        return "show mystical elements: moon phases, tarot cards, crystals, candles — soft mystical aesthetic"
    if any(w in n for w in ("color", "colouring", "coloring")):
        return ("show a vibrant fully-colored version of the book's main illustration subject "
                "(the line art lives inside the book — the cover is finished color)")
    if any(w in n for w in ("kids", "child", "boys", "girls", "toddler")):
        return "show friendly cartoon characters or playful objects matching the book's theme"
    # Fallback : generic but still content-first
    return (f"show real, recognisable visual elements directly related to the niche '{niche}' — "
            "concrete objects, scenes or people that instantly tell the buyer what the book is about")


def _pick_art_direction(rng=None) -> str:
    """Return a content-first art-direction sentence (composition / lighting / mood / render)."""
    import random as _random
    if rng is None:
        rng = _random
    parts = [
        rng.choice(_COMPOSITION_BANK),
        rng.choice(_LIGHTING_BANK),
        rng.choice(_MOOD_BANK),
        rng.choice(_RENDER_STYLE_BANK),
    ]
    return ". ".join(parts) + "."


def build_dalle_prompt(
    listing: Dict,
    style_variant: Optional[Dict] = None,
    learning_dir=None,
    free_style: bool = False,
) -> str:
    niche        = listing["niche"]
    product_type = listing.get("product_type", "journal")

    # ── Competitor color hint (from scan analysis) ────────────────────────
    color_hint = ""
    if learning_dir is not None:
        try:
            from modules.learning.competitor import get_insights, color_hint_for_cover
            insights = get_insights(learning_dir, niche)
            ch = color_hint_for_cover(insights)
            if ch:
                color_hint = f" {ch}."
        except Exception as e:
            logger.debug(f"Cover color hint skipped: {e}")

    # ── Design directives from sample analysis ────────────────────────────
    design_hint = ""
    if learning_dir is not None:
        try:
            from modules.learning.sample_reader import (
                get_sample_insights, compute_design_directives,
            )
            si = get_sample_insights(learning_dir, niche)
            if si:
                directives = compute_design_directives(si)
                cov = directives["cover"]
                bits = []
                if cov.get("ambition") == "world-class":
                    bits.append("World-class magazine-cover quality — must exceed every competitor in this niche")
                else:
                    bits.append("Premium high-end book cover, visibly superior to typical KDP books in this niche")
                if cov.get("typography_emphasis"):
                    bits.append(cov["typography_emphasis"])
                if cov.get("composition_hint"):
                    bits.append(cov["composition_hint"])
                if cov.get("palette_hint"):
                    bits.append(f"palette inspired by '{cov['palette_hint']}'")
                design_hint = " " + ". ".join(bits) + "."
        except Exception as e:
            logger.debug(f"Cover design directives skipped: {e}")

    # ── Coloring books: dedicated art-directed prompt with real subject ──
    if product_type == "coloring":
        return _build_coloring_cover_prompt(listing, color_hint, design_hint, free_style)

    if free_style:
        # Niche-aware random pick from a wide pool (no rigid defaults)
        import random as _random
        style = _random.choice(_style_hints_for_niche(niche))
    elif style_variant and style_variant.get("cover_art_hint"):
        # Variant suggestion + still add a random extra hint for variety
        import random as _random
        extra = _random.choice(_style_hints_for_niche(niche))
        style = f"{style_variant['cover_art_hint']}, with an additional {extra}"
    else:
        # No variant locked → niche-aware pool, not hardcoded default
        import random as _random
        style = _random.choice(_style_hints_for_niche(niche))

    # Content-first art direction (4 axes : composition / lighting / mood / render)
    art_direction    = _pick_art_direction()
    subject_directive = _niche_subject_directive(niche, product_type)

    return (
        f"PROFESSIONAL BOOK COVER ILLUSTRATION for an Amazon KDP {product_type} "
        f"book on the niche '{niche}'.\n\n"
        f"WHAT TO DRAW (most important) — {subject_directive}. "
        f"The cover image MUST visually represent the actual content of the book — "
        f"someone glancing at the thumbnail should instantly know it's about '{niche}'. "
        f"NEVER an abstract painting, NEVER unrelated decorative art.\n\n"
        f"ART DIRECTION : {art_direction}\n\n"
        f"VISUAL STYLE LAYER : {style}.{color_hint}{design_hint}\n\n"
        "TECHNICAL & QUALITY :\n"
        "- Fill the FULL SQUARE FRAME edge-to-edge, no white borders, no margins.\n"
        "- Sharp focus on the hero subject, clean recognisable details.\n"
        "- Confident harmonised palette : 3-5 colours, ONE punchy accent — "
        "never washed out, never neon-saturated.\n"
        "- 300 DPI print-ready.\n\n"
        "ABSOLUTE EXCLUSIONS :\n"
        "- ZERO text, words, letters, numbers, captions, signatures, watermarks, "
        "logos anywhere in the image (text added in post).\n"
        "- NO generic AI-look : no plastic skin, no symmetric stock face, "
        "no flat gradient-only background.\n"
        "- NO real living people's likenesses, NO copyrighted characters, mascots, "
        "trademarks, celebrity faces, recognisable brands.\n"
        "- NO violence, no gore, no sexual content.\n"
        "- NO abstract art that doesn't represent the actual book content.\n\n"
        "BENCHMARK : the cover should look like a professional published book cover "
        "where the buyer immediately understands what's inside from the imagery alone."
    )


# ── DALL-E image fetcher ──────────────────────────────────────────────────────

def _img_from_response(resp) -> Image.Image:
    """Extracts a PIL Image from an OpenAI images.generate response (URL or b64_json)."""
    import base64, requests as _req
    item = resp.data[0]
    # gpt-image-1 returns b64_json by default; dall-e-* return URL
    if getattr(item, "b64_json", None):
        data = base64.b64decode(item.b64_json)
    elif getattr(item, "url", None):
        data = _req.get(item.url, timeout=30).content
    else:
        raise ValueError("Response has neither b64_json nor url")
    return Image.open(io.BytesIO(data)).convert("RGB")


def fetch_dalle_image(prompt: str, openai_key: str, status_cb=None) -> Image.Image:
    """
    Tries image models in order of preference. Hardened against transient OpenAI
    failures (rate limits, 503s, network hiccups) and smart-skips entire model
    families on timeout (no point retrying the same broken endpoint).

    Wall-clock budget : ~3 min worst-case (was 18 min before the smart-skip).
    """
    import openai
    import time as _time
    # 200s timeout: gpt-image-2 at high quality + portrait 1024x1536 takes
    # ~120-150s (measured 141s). The old 90s budget killed the best model
    # mid-generation → black placeholder. Give it room to finish.
    client = openai.OpenAI(api_key=openai_key, timeout=200.0, max_retries=0)

    def _say(msg):
        if status_cb: status_cb(msg)

    # PORTRAIT 1024x1536 = ratio 0.667 = EXACT 6:9 book-cover aspect.
    # Square 1024x1024 was being STRETCHED into the tall front face → blurry,
    # distorted renders. Portrait source gives the upscaler far more vertical
    # detail and ImageOps.fit crops without distortion (see compose_cover).
    #
    # Order = best quality first. gpt-image-2 high is the top model (~141s);
    # gpt-image-1 high is the RELIABLE fallback (~37s, still good) so we never
    # fall all the way to a black placeholder when gpt-image-2 is overloaded.
    attempts = [
        ("gpt-image-2-2026-04-21", dict(size="1024x1536", quality="high")),
        ("gpt-image-2",            dict(size="1024x1536", quality="high")),
        ("gpt-image-1",            dict(size="1024x1536", quality="high")),
    ]

    last_err = None
    started = _time.time()

    for model, kwargs in attempts:
        t0 = _time.time()
        try:
            _say(f"🎨 Génération image ({model})...")
            resp = client.images.generate(model=model, prompt=prompt[:4000], n=1, **kwargs)
            img  = _img_from_response(resp)
            elapsed_s = int(_time.time() - t0)
            _say(f"✅ Image générée avec {model} en {elapsed_s}s")
            return img
        except Exception as e:
            last_err = e
            err_str  = str(e)
            err_type = type(e).__name__
            elapsed_s = int(_time.time() - t0)
            total_s   = int(_time.time() - started)

            if "rate" in err_str.lower() or "429" in err_str:
                _say(f"⚠️ {model} : rate-limit OpenAI ({elapsed_s}s) — essai suivant...")
            elif "timeout" in err_str.lower() or err_type == "APITimeoutError":
                _say(f"⚠️ {model} : timeout ({elapsed_s}s) — essai suivant...")
            elif "model_not_found" in err_str or "does not exist" in err_str:
                _say(f"⏭️ {model} : modèle indisponible — essai suivant...")
            elif "billing" in err_str.lower() or "insufficient_quota" in err_str:
                _say(f"❌ {model} : quota OpenAI épuisé — STOP")
                raise RuntimeError(f"OpenAI quota exhausted: {err_str[:200]}") from e
            elif "invalid_api_key" in err_str or "Incorrect API key" in err_str:
                _say(f"❌ Clé OpenAI invalide — STOP")
                raise RuntimeError(f"OpenAI API key invalid: {err_str[:200]}") from e
            else:
                _say(f"⚠️ {model} ({err_type}) : {err_str[:120]}")
            logger.warning(f"{model} failed after {elapsed_s}s (total {total_s}s): {e}")

    total = int(_time.time() - started)
    _say(f"⚠️ Tous les modèles indisponibles après {total}s "
         f"(dernier : {type(last_err).__name__}) — placeholder utilisé")
    return _make_placeholder_cover()


def _make_placeholder_cover() -> Image.Image:
    """Generates a clean gradient placeholder when DALL-E is unavailable."""
    w, h = 1024, 1536  # portrait, matches the real generation aspect
    img  = Image.new("RGB", (w, h), (20, 35, 60))
    draw = ImageDraw.Draw(img)
    # Simple vertical gradient overlay
    for y in range(h):
        alpha = int(40 * (1 - y / h))
        draw.line([(0, y), (w, y)], fill=(alpha, alpha + 10, alpha + 20))
    # Tag so callers know NOT to cache this (otherwise fine-tune reuses the
    # black image forever — the persistent "cover noir" bug).
    img.is_placeholder = True
    return img


# ── Text overlay helpers ──────────────────────────────────────────────────────

def _get_font(size: int, bold: bool = False,
              preferred_path: Optional[str] = None) -> ImageFont.FreeTypeFont:
    """
    Returns a Pillow font. If preferred_path is given (e.g., a theme font),
    tries that first before falling back to generic system fonts.
    """
    candidates = []
    if preferred_path:
        candidates.append(preferred_path)

    candidates += [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue

    return ImageFont.load_default()


def _rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """Pure-Python RGB→HSV. r/g/b are 0-255. Returns (h°, s, v) where s, v ∈ [0, 1]."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    mx = max(rf, gf, bf)
    mn = min(rf, gf, bf)
    d  = mx - mn
    if d == 0:
        h = 0.0
    elif mx == rf:
        h = (60 * ((gf - bf) / d) + 360) % 360
    elif mx == gf:
        h = 60 * ((bf - rf) / d) + 120
    else:
        h = 60 * ((rf - gf) / d) + 240
    s = 0.0 if mx == 0 else d / mx
    return h, s, mx


def _dominant_color(img: Image.Image) -> Tuple[int, int, int]:
    """
    Returns the most representative SATURATED color in the image — not the
    corner average. Uses Pillow's adaptive palette quantization to find the
    top colors, then picks the one with the highest saturation×frequency
    score (filtering out near-white, near-black, and near-gray).
    """
    try:
        # Quantize to 16 representative colors
        small = img.convert("RGB").resize((150, 150), Image.LANCZOS)
        pal_img = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        palette = pal_img.getpalette() or []
        color_counts = pal_img.getcolors() or []   # [(count, palette_index), ...]
        if not color_counts or not palette:
            return (90, 90, 110)

        best = None
        best_score = -1.0
        for count, idx in color_counts:
            base = idx * 3
            r, g, b = palette[base], palette[base + 1], palette[base + 2]
            h, s, v = _rgb_to_hsv(r, g, b)
            # Filter out near-white, near-black, near-gray
            if v > 0.94 and s < 0.10:    # too white
                continue
            if v < 0.10:                  # too black
                continue
            if s < 0.15:                  # too gray
                continue
            # Score = saturation × log(frequency) × mid-brightness preference
            import math
            freq_factor   = math.log1p(count)
            bright_factor = 1.0 - abs(v - 0.55) * 0.6   # peak near v=0.55
            score = s * freq_factor * bright_factor
            if score > best_score:
                best_score = score
                best = (r, g, b)

        if best is None:
            # All filtered out → fall back to the most frequent non-white
            color_counts.sort(reverse=True)
            for count, idx in color_counts:
                base = idx * 3
                r, g, b = palette[base], palette[base + 1], palette[base + 2]
                if not (r > 240 and g > 240 and b > 240):
                    return (r, g, b)
            return (90, 90, 110)
        return best
    except Exception as e:
        logger.debug(f"_dominant_color fallback: {e}")
        return (90, 90, 110)


def _hsv_to_rgb(h_deg: float, sat: float, val: float) -> Tuple[int, int, int]:
    """HSV→RGB. h_deg ∈ [0, 360), sat/val ∈ [0, 1]. Returns (r, g, b) 0-255."""
    h_deg = h_deg % 360
    c = val * sat
    x = c * (1 - abs(((h_deg / 60) % 2) - 1))
    m = val - c
    if   h_deg < 60:  r, g, b = c, x, 0
    elif h_deg < 120: r, g, b = x, c, 0
    elif h_deg < 180: r, g, b = 0, c, x
    elif h_deg < 240: r, g, b = 0, x, c
    elif h_deg < 300: r, g, b = x, 0, c
    else:             r, g, b = c, 0, x
    return (int(round((r + m) * 255)),
            int(round((g + m) * 255)),
            int(round((b + m) * 255)))


# ── 5 color-harmony schemes (color-theory based) ──────────────────────────────
# Each scheme returns a tuple of (band_h_offset, back_h_offset, spine_h_offset, stripe_h_offset).
# h_offset is added to the hero hue (in degrees) → derives related colors.
_HARMONY_SCHEMES = {
    # Same hue, varied brightness/saturation — cleanest, safest
    "monochromatic":        (0,    0,    0,    0),
    # Adjacent hues (±30°) — soft, natural harmony
    "analogous":            (0,    -30,  -45,  +30),
    # Opposite on the wheel (180°) — vibrant contrast
    "complementary":        (0,    +180, 0,    +180),
    # Two hues equidistant from the complement (150° / 210°) — balanced energy
    "split_complementary":  (0,    +150, 0,    +210),
    # Three hues 120° apart — playful, dynamic
    "triadic":              (0,    +120, -120, +120),
    # Four hues forming a rectangle (0°, 60°, 180°, 240°) — rich, sophisticated
    "tetradic":             (0,    +60,  +180, +240),
    # Soft pastel variant — same hue but pushed lighter and desaturated
    "pastel_mono":          (0,    0,    0,    0),
    # Vintage variant — same hue but pushed darker and warmer
    "vintage_mono":         (0,    -15,  -25,  +15),
}


_UNIFORM_BACK = True   # user pref: back cover = band color exactly (no harmony shift)


# ── 24 curated palettes from real publishing (Penguin/Knopf/Random House style) ──
# Format: name → {band, spine, stripe} as RGB tuples + list of niche tag keys.
# When chosen, back = band (per _UNIFORM_BACK). Stripe is the accent flourish.
_CURATED_PALETTES = [
    # ── EDITORIAL CLASSIC ──
    ("deep_navy_cream",    {"band": (28, 42, 72),   "spine": (18, 28, 50),   "stripe": (220, 210, 180)}, ["literary","editorial","journal","vintage"]),
    ("burgundy_gold",      {"band": (96, 28, 36),   "spine": (60, 18, 22),   "stripe": (200, 165, 110)}, ["literary","luxury","wine","editorial"]),
    ("forest_ivory",       {"band": (42, 78, 56),   "spine": (28, 52, 38),   "stripe": (235, 225, 200)}, ["nature","wellness","garden","journal"]),
    ("charcoal_blush",     {"band": (60, 60, 68),   "spine": (38, 38, 44),   "stripe": (230, 195, 195)}, ["minimal","modern","editorial"]),
    # ── VIBRANT MODERN ──
    ("electric_coral",     {"band": (220, 90, 80),  "spine": (160, 60, 55),  "stripe": (255, 220, 130)}, ["travel","tropical","creative","sport"]),
    ("lavender_mustard",   {"band": (130, 110, 165),"spine": (88, 70, 120),  "stripe": (220, 180, 80)},  ["art","creative","kids"]),
    ("tangerine_navy",     {"band": (32, 50, 90),   "spine": (20, 32, 60),   "stripe": (240, 145, 60)},  ["business","sport","modern"]),
    ("sage_terracotta",    {"band": (140, 160, 130),"spine": (95, 115, 92),  "stripe": (200, 110, 80)},  ["wellness","cooking","nature"]),
    # ── DARK & MOODY ──
    ("midnight_crimson",   {"band": (20, 20, 35),   "spine": (10, 10, 20),   "stripe": (180, 35, 50)},   ["horror","thriller","mystery","dark"]),
    ("obsidian_emerald",   {"band": (15, 28, 25),   "spine": (8, 18, 16),    "stripe": (50, 165, 100)},  ["mystery","occult","fantasy"]),
    ("wine_smoke",         {"band": (75, 40, 55),   "spine": (50, 25, 38),   "stripe": (165, 160, 155)}, ["vintage","noir","literary"]),
    ("ink_gold",           {"band": (20, 30, 45),   "spine": (12, 18, 30),   "stripe": (200, 165, 95)},  ["fantasy","spiritual","editorial"]),
    # ── ROMANCE & SOFT ──
    ("rose_quartz",        {"band": (210, 160, 175),"spine": (160, 110, 130),"stripe": (245, 230, 220)}, ["romance","journal","wedding"]),
    ("lavender_dust",      {"band": (180, 165, 200),"spine": (130, 115, 155),"stripe": (220, 195, 200)}, ["spiritual","romance","feminine"]),
    ("champagne_blush",    {"band": (215, 185, 145),"spine": (165, 135, 100),"stripe": (245, 220, 200)}, ["luxury","wedding","gourmet"]),
    # ── NATURE ──
    ("forest_moss",        {"band": (62, 88, 60),   "spine": (40, 60, 40),   "stripe": (220, 210, 165)}, ["nature","garden","outdoors"]),
    ("ocean_sand",         {"band": (50, 105, 130), "spine": (32, 72, 95),   "stripe": (240, 215, 175)}, ["travel","ocean","beach"]),
    ("mountain_dusk",      {"band": (75, 88, 105),  "spine": (50, 60, 75),   "stripe": (220, 130, 90)},  ["outdoors","adventure","hiking"]),
    ("autumn_ochre",       {"band": (155, 95, 50),  "spine": (105, 65, 32),  "stripe": (240, 215, 165)}, ["vintage","cooking","autumn"]),
    # ── KIDS / FUN ──
    ("primary_pop",        {"band": (215, 45, 55),  "spine": (155, 30, 38),  "stripe": (245, 215, 75)},  ["kids","fun","comic"]),
    ("candy_bright",       {"band": (220, 70, 145), "spine": (165, 45, 105), "stripe": (110, 210, 220)}, ["kids","fun","whimsical"]),
    ("mint_lemon",         {"band": (130, 200, 175),"spine": (90, 150, 130), "stripe": (245, 225, 100)}, ["kids","fresh","spring"]),
    # ── EDGY / MUSIC ──
    ("neon_dark",          {"band": (18, 18, 22),   "spine": (8, 8, 12),     "stripe": (230, 50, 145)},  ["music","edgy","modern"]),
    # ── SPIRITUAL / MYSTICAL ──
    ("cosmic_violet",      {"band": (60, 35, 95),   "spine": (40, 22, 65),   "stripe": (200, 180, 220)}, ["spiritual","mystic","tarot"]),
]


def _pick_curated_palette(niche: str) -> Optional[Dict]:
    """Pick a curated palette biased to niche, or None for image-extraction mode."""
    import random as _r
    nl = (niche or "").lower()
    niche_markers = {
        "literary":  ["journal","diary","memoir","poetry","essay"],
        "editorial": ["journal","planner","notebook","log"],
        "luxury":    ["wedding","gourmet","wine","fine","luxury","premium"],
        "vintage":   ["vintage","retro","antique","classic","old","1800","1900"],
        "wellness":  ["wellness","yoga","mindful","health","meditat","spa"],
        "nature":    ["nature","garden","plant","forest","botanical"],
        "garden":    ["garden","plant","botanical","seed"],
        "travel":    ["travel","explore","adventure","road","trip"],
        "tropical":  ["tropical","beach","ocean","island","summer"],
        "ocean":     ["ocean","sea","fish","aquarium","beach","marine"],
        "beach":     ["beach","summer","tropical","seaside"],
        "outdoors":  ["camping","hike","trail","outdoor","fishing","hunting"],
        "adventure": ["adventure","explore","quest","journey"],
        "hiking":    ["hike","trail","mountain","peak"],
        "minimal":   ["minimal","clean","modern","simple"],
        "modern":    ["modern","tech","startup","productivity","design"],
        "creative":  ["art","color","draw","sketch","creative","craft"],
        "art":       ["art","paint","draw","sketch","studio"],
        "sport":     ["sport","fitness","gym","running","workout","extreme"],
        "business":  ["business","entrepreneur","sales","marketing","finance"],
        "cooking":   ["recipe","cook","kitchen","bake","food","chef","gourmet"],
        "horror":    ["horror","ghost","haunted","macabre","occult","dark"],
        "thriller":  ["thriller","crime","mystery","detective"],
        "mystery":   ["mystery","puzzle","crime","detective","secret"],
        "occult":    ["occult","witch","tarot","ritual","spell"],
        "dark":      ["dark","gothic","shadow","void","abyss"],
        "fantasy":   ["fantasy","dragon","magic","wizard","myth"],
        "noir":      ["noir","crime","detective","shadow"],
        "romance":   ["romance","love","passion","wedding","date"],
        "journal":   ["journal","diary","log","notebook","planner"],
        "wedding":   ["wedding","bride","anniversary","love"],
        "feminine":  ["girl","women","feminine","mom"],
        "spiritual": ["spiritual","yoga","meditat","mindful","manifest","chakra"],
        "mystic":    ["tarot","witch","ritual","moon","oracle"],
        "tarot":     ["tarot","oracle","card"],
        "kids":      ["kid","child","toddler","baby","girl","boy","preschool"],
        "fun":       ["fun","party","game","play"],
        "comic":     ["comic","cartoon","manga","anime"],
        "whimsical": ["whimsical","fairy","unicorn","magic"],
        "fresh":     ["fresh","clean","spring","new"],
        "spring":    ["spring","easter","bloom"],
        "music":     ["music","rock","metal","hip","rap","band","guitar"],
        "edgy":      ["punk","rebel","extreme","metal"],
        "autumn":    ["autumn","fall","harvest","pumpkin","thanksgiving"],
    }
    # Find matching tags from niche
    matched_tags = set()
    for tag, markers in niche_markers.items():
        if any(m in nl for m in markers):
            matched_tags.add(tag)

    # Filter palettes that share at least one tag with the niche
    matching_palettes = [
        (name, pal, tags) for name, pal, tags in _CURATED_PALETTES
        if matched_tags & set(tags)
    ]
    if matching_palettes:
        return dict(zip(("name","colors","tags"), _r.choice(matching_palettes)))
    return None   # no niche match → caller will use image extraction


def _harmonize_palette(
    dom: Tuple[int, int, int],
    scheme: Optional[str] = None,
) -> Dict[str, Tuple[int, int, int]]:
    """
    From a dominant hero color + a chosen harmony scheme, derives 4 colors:
      - 'band'    : the solid bottom band on the front
      - 'back'    : the back cover background
      - 'spine'   : the spine
      - 'stripe'  : the thin accent stripe between image and band

    `scheme` (random if None):
      monochromatic, analogous, complementary, split_complementary,
      triadic, tetradic, pastel_mono, vintage_mono
    """
    import random as _random
    if scheme is None or scheme not in _HARMONY_SCHEMES:
        scheme = _random.choice(list(_HARMONY_SCHEMES.keys()))

    h, s, v = _rgb_to_hsv(*dom)
    base_s = max(0.45, min(s, 0.85))

    band_off, back_off, spine_off, stripe_off = _HARMONY_SCHEMES[scheme]

    if scheme == "pastel_mono":
        # Lighter, softer palette
        band   = _hsv_to_rgb(h + band_off,   base_s * 0.55, 0.78)
        back   = _hsv_to_rgb(h + back_off,   base_s * 0.45, 0.88)
        spine  = _hsv_to_rgb(h + spine_off,  base_s * 0.65, 0.65)
        stripe = _hsv_to_rgb(h + stripe_off, base_s * 0.40, 0.92)
    elif scheme == "vintage_mono":
        # Darker, warmer, muted palette
        band   = _hsv_to_rgb(h + band_off,   base_s * 0.95, 0.42)
        back   = _hsv_to_rgb(h + back_off,   base_s * 0.85, 0.32)
        spine  = _hsv_to_rgb(h + spine_off,  base_s * 0.90, 0.24)
        stripe = _hsv_to_rgb(h + stripe_off, base_s * 0.65, 0.62)
    else:
        # Standard harmony: hero color → band; offset hues for back/spine/stripe
        band   = _hsv_to_rgb(h + band_off,   base_s,        0.55)
        back   = _hsv_to_rgb(h + back_off,   base_s * 0.85, 0.42)
        spine  = _hsv_to_rgb(h + spine_off,  base_s,        0.32)
        stripe = _hsv_to_rgb(h + stripe_off, base_s * 0.75, 0.78)

    # USER PREF: uniform back cover = exactly same color as band
    if _UNIFORM_BACK:
        back = band
        # spine slightly darker for depth, but same hue family
        spine = _hsv_to_rgb(h, base_s, 0.42)

    return {
        "band": band, "back": back, "spine": spine, "stripe": stripe,
        "_scheme": scheme,
    }


def _luminance(rgb: Tuple) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _text_color(bg_rgb: Tuple) -> Tuple:
    return (255, 255, 255) if _luminance(bg_rgb) < 128 else (20, 20, 20)


def _publisher_initials(publisher_name: str) -> str:
    """Extract up to 3 initials from a publisher name for the logo."""
    if not publisher_name:
        return "•"
    words = [w for w in publisher_name.split() if w and w[0].isalpha()]
    # Skip generic suffixes
    stop = {"press", "publishing", "publisher", "books", "house", "studio", "co", "ltd"}
    keep = [w for w in words if w.lower() not in stop] or words
    initials = "".join(w[0].upper() for w in keep[:3])
    return initials or "•"


def _draw_publisher_logo(
    draw: ImageDraw.Draw,
    cx: int, cy: int,
    publisher_name: str,
    fill_color: Tuple,
    accent_color: Tuple,
    size_px: int = 80,
    font_path: Optional[str] = None,
) -> None:
    """
    Draws a small circular publisher emblem with initials inside.
    Two concentric circles + small radial ticks = simple but elegant seal.
    """
    half = size_px // 2
    outer = (cx - half, cy - half, cx + half, cy + half)
    # Outer ring
    draw.ellipse(outer, outline=fill_color, width=max(2, size_px // 30))
    # Inner ring (decorative)
    inner_pad = max(4, size_px // 12)
    inner = (cx - half + inner_pad, cy - half + inner_pad,
             cx + half - inner_pad, cy + half - inner_pad)
    draw.ellipse(inner, outline=fill_color, width=1)

    # Small decorative ticks at top / bottom / left / right
    tick_len = max(3, size_px // 18)
    draw.line([(cx, cy - half - tick_len), (cx, cy - half + 1)],
              fill=fill_color, width=1)
    draw.line([(cx, cy + half - 1), (cx, cy + half + tick_len)],
              fill=fill_color, width=1)
    draw.line([(cx - half - tick_len, cy), (cx - half + 1, cy)],
              fill=fill_color, width=1)
    draw.line([(cx + half - 1, cy), (cx + half + tick_len, cy)],
              fill=fill_color, width=1)

    # Initials in the centre
    initials = _publisher_initials(publisher_name)
    font_sz  = int(size_px * 0.36) if len(initials) <= 2 else int(size_px * 0.28)
    font = _get_font(font_sz, bold=True, preferred_path=font_path)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2 - bbox[0], cy - th // 2 - bbox[1]),
              initials, font=font, fill=fill_color)


def _draw_wrapped_text(
    draw: ImageDraw.Draw,
    text: str,
    x: int, y: int,
    max_width: int,
    font: ImageFont.FreeTypeFont,
    fill: Tuple,
    line_spacing: int = 8,
    align: str = "center",
) -> int:
    """Draws text with word wrap. Returns the y position after text."""
    words   = text.split()
    lines   = []
    current = []

    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        if align == "center":
            draw.text((x - w // 2, y), line, font=font, fill=fill)
        else:
            draw.text((x, y), line, font=font, fill=fill)
        y += (bbox[3] - bbox[1]) + line_spacing

    return y


# ── Cover composer ────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Converts '#RRGGBB' to (r, g, b)."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ── Typography strategy per product type ──────────────────────────────────────
# Senior designer rules: each genre has a typographic identity.
#   editorial   → serif powerful title, italic subtitle, refined hierarchy
#   minimalist  → sans-serif balanced, generous spacing, equal weights
#   bold_pop    → display/decorative title, oversized, high impact at thumbnail
#   classic     → traditional serif/sans hybrid, conservative
TYPO_STRATEGIES = {
    "editorial": {
        "title_size_pct":    0.072,
        "subtitle_size_pct": 0.020,
        "title_caps":        False,
        "subtitle_italic":   True,
        "font_pool":         "serif",
    },
    "minimalist": {
        "title_size_pct":    0.055,
        "subtitle_size_pct": 0.022,
        "title_caps":        True,
        "subtitle_italic":   False,
        "font_pool":         "sans",
    },
    "bold_pop": {
        "title_size_pct":    0.090,
        "subtitle_size_pct": 0.024,
        "title_caps":        True,
        "subtitle_italic":   False,
        "font_pool":         "display",
    },
    "classic": {
        "title_size_pct":    0.062,
        "subtitle_size_pct": 0.020,
        "title_caps":        False,
        "subtitle_italic":   True,
        "font_pool":         "serif",
    },
}

PRODUCT_TO_STRATEGY = {
    "journal":       "editorial",
    "log":           "editorial",
    "planner":       "minimalist",
    "quiz":          "bold_pop",
    "trivia":        "bold_pop",
    "coloring":      "bold_pop",
    "puzzle":        "bold_pop",     # NEW (was missing → KeyError 'default')
    "activity_book": "bold_pop",     # NEW
    "default":       "classic",
}


def _typo_for_product(product_type: str) -> Dict:
    """Get typography strategy for a product type.
    Hardened against unknown product_type: always falls back to 'classic'
    even if PRODUCT_TO_STRATEGY is missing the key."""
    strat = PRODUCT_TO_STRATEGY.get(product_type, "classic")
    return TYPO_STRATEGIES.get(strat, TYPO_STRATEGIES["classic"])


def _font_for_strategy(pool: str, niche: str = "") -> Tuple[str, str]:
    """
    Pick a font pair matching the strategy's pool, intersected with niche
    affinity when both can be satisfied. Otherwise random pool member.

    Pool meanings:
      serif    → editorial serif (Baskerville/Didot/Bodoni/Iowan/etc.)
      sans     → modern minimal sans (Futura/Avenir/Helvetica/Seravek/etc.)
      display  → heavy bold display (Impact/DIN/Arial Black/Phosphate)
      script   → cursive/calligraphic
      hand     → marker/chalk/hand-drawn
      fantasy  → decorative/medieval/Roman
    """
    pool_map = {
        "serif":   _SERIF_EDITORIAL + _SERIF_DECORATIVE,
        "sans":    _SANS_MINIMAL,
        "display": _SANS_BOLD + _HAND_MARKER,    # bold + marker for impact
        "script":  _SCRIPT_CURSIVE,
        "hand":    _HAND_MARKER,
        "fantasy": _DECORATIVE_FANTASY + [5, 11],
    }
    candidates = pool_map.get(pool, _SERIF_EDITORIAL)

    # Try intersection with niche affinity for the best contextual fit
    niche_idx = _detect_font_affinity(niche)
    if niche_idx:
        overlap = [i for i in candidates if i in niche_idx]
        if overlap:
            candidates = overlap

    import random as _r
    idx = _r.choice(candidates)
    return _DISPLAY_FONT_POOL[idx]


_CATEGORY_TAGS = [
    "coloring book", "colouring book", "color book",
    "log book", "logbook",
    "trivia book", "quiz book", "puzzle book",
    "activity book", "workbook",
    "field guide", "field notes",
    "journal", "planner", "tracker", "notebook", "diary",
]


def _strip_category_tag(s: str) -> str:
    """Remove a trailing category tag (Coloring Book / Journal / Planner / etc.)."""
    if not s:
        return s
    s = s.strip()
    sl = s.lower()
    for tag in sorted(_CATEGORY_TAGS, key=len, reverse=True):
        if sl.endswith(" " + tag):
            return s[: len(s) - len(tag) - 1].strip()
        if sl == tag:
            return ""
    return s


def _extract_cover_title(raw_title: str):
    """
    Split a long KDP-listing title into (main_for_cover, remainder_as_subtitle).

    Strategy — apply in order, first match wins for the structural split :
      1. Split on " : " (Amazon convention)
      2. Split on " — " or " - " (em/en dash)
      3. Split on " | "
      4. Split on " for "   ← "Etsy Seller Daily Planner for Creative Entrepreneurs"
                              → main "Etsy Seller Daily Planner" + sub "Creative Entrepreneurs"
      5. Split on " with ", " by "
    THEN strip the category tag from the END of main ("Coloring Book", "Journal", ...)
    The format is visually obvious on the cover — no need to repeat it as text.

    Goal : cover always shows a TIGHT 2-5 word visual hook.
    """
    import re as _re
    if not raw_title:
        return "", ""
    t = raw_title.strip()

    main, sub = t, ""
    # 1. Colon split — Amazon convention
    if ":" in t:
        a, b = t.split(":", 1)
        main, sub = a.strip(), b.strip()
    # 2. Em / en / hyphen dash split (with spaces around)
    elif _re.search(r"\s+[—–-]\s+", t):
        m = _re.search(r"\s+[—–-]\s+", t)
        main, sub = t[:m.start()].strip(), t[m.end():].strip()
    # 3. Pipe split
    elif " | " in t:
        a, b = t.split(" | ", 1)
        main, sub = a.strip(), b.strip()
    # 4. " for " split (catches "...Planner for Working Moms")
    elif _re.search(r"\s+for\s+", t, _re.IGNORECASE) and \
         _re.search(r"\s+for\s+", t, _re.IGNORECASE).start() >= 10:
        m = _re.search(r"\s+for\s+", t, _re.IGNORECASE)
        main, sub = t[:m.start()].strip(), t[m.end():].strip()
    else:
        # 5. " with " or " by " split
        for sep in (" with ", " by "):
            if sep in t.lower():
                i = t.lower().index(sep)
                if i >= 10:
                    main, sub = t[:i].strip(), t[i + len(sep):].strip()
                    break
        else:
            # 6. Still too long → smart truncate at word boundary
            if len(t) > 32:
                cut = t.rfind(" ", 0, 32)
                if cut > 14:
                    main, sub = t[:cut].strip(), t[cut:].strip()

    # ── Final cleanup ───────────────────────────────────────────────
    # Strip category tag (Coloring Book / Journal / Planner / ...) from MAIN
    # ONLY when main is genuinely too long AND we keep at least 2 words after.
    # Goal: "Bioluminescent Ocean Coloring Book" (34c → strip → "Bioluminescent
    # Ocean" 2w ✓) but keep "Anxiety Journal" intact (only 15c).
    if len(main) >= 28:
        cleaned_main = _strip_category_tag(main)
        if cleaned_main and len(cleaned_main.split()) >= 2:
            main = cleaned_main

    # Drop junk trailing words from the derived subtitle
    if sub:
        junk = {"book", "books", "edition", "guide"}
        sub_words = sub.split()
        while sub_words and sub_words[-1].lower().strip(".,;:") in junk:
            sub_words.pop()
        sub = " ".join(sub_words)
    return main, sub


def _short_subtitle(text: str, max_words: int = 7, max_chars: int = 48) -> str:
    """
    Condenses a long subtitle into a short, clean tagline for the front cover.
    Strategy:
      1. Keep only the first clause (cut at the first comma / dash / semicolon).
      2. Cap to max_words words.
      3. Cap to max_chars characters at a word boundary.
    No mid-word ellipsis — a short complete phrase is better than a truncated one.
    """
    import re as _re
    if not text:
        return ""
    text = text.strip()
    # 1. First clause only (stop at the first natural break)
    clause = _re.split(r"\s*[,;—–-]\s+", text, maxsplit=1)[0].strip()
    if not clause:
        clause = text
    # 2. Word cap
    words = clause.split()
    if len(words) > max_words:
        clause = " ".join(words[:max_words])
    # 3. Char cap at word boundary
    if len(clause) > max_chars:
        cut = clause.rfind(" ", 0, max_chars)
        clause = clause[:cut if cut > 12 else max_chars].strip()
    return clause


def _readable_accent(back_color) -> Tuple[int, int, int]:
    """A heading/CTA accent that pops on the back colour: warm gold on dark
    backs, a deep warm tone on light backs."""
    return (245, 205, 120) if _luminance(back_color) < 125 else (150, 55, 25)


def _cta_text(listing: Dict) -> str:
    """A short call-to-action for the back-cover button, matched to the genre."""
    pt = str(listing.get("product_type", "")).lower()
    niche = (listing.get("niche", "") or "").lower()
    if listing.get("_facts") or "kids" in niche or "curious" in niche:
        return "START EXPLORING TODAY"
    if pt == "recipe_book":
        return "START COOKING TODAY"
    if pt == "how_to":
        return "START LEARNING TODAY"
    return "GET STARTED TODAY"


def _hc_front_region(F: Image.Image, region_w: int, region_h: int,
                     trim_w_px: int, pad_f: float = 0.10) -> Image.Image:
    """Hardcover front placement (case wrap). The front region = visible page
    (trim_w_px, on the hinge side) + the outer wrap on the far side. We:
      • scale the designed front F into the vertical SAFE band (so its baked-in
        text clears the KDP wrap/safe zone), preserving aspect;
      • CENTRE it on the VISIBLE PAGE (trim), not on the whole region — otherwise
        the print lands off-centre (the bug the previewer showed);
      • fill the exposed margins + the outer wrap by stretching F's edge rows/
        cols, so the photo still bleeds to every physical edge.
    Works for any front design (guide / cookbook / kids / botanical)."""
    F = F.convert("RGB")
    fh = max(1, int((1.0 - 2 * pad_f) * region_h))
    fw = max(1, int(F.width * fh / F.height))
    if fw > trim_w_px:                    # never wider than the visible page
        fw = trim_w_px
        fh = max(1, int(F.height * fw / F.width))
    Fr = F.resize((fw, fh), Image.LANCZOS)
    reg = Image.new("RGB", (region_w, region_h))
    x0 = max(0, (trim_w_px - fw) // 2)    # centre on the VISIBLE page (trim)
    y0 = (region_h - fh) // 2             # trim is centred vertically in the region
    reg.paste(Fr, (x0, y0))
    if y0 > 0:                            # extend top edge upward (into wrap)
        reg.paste(Fr.crop((0, 0, fw, 1)).resize((fw, y0)), (x0, 0))
    by2 = y0 + fh
    if by2 < region_h:                    # extend bottom edge downward (into wrap)
        reg.paste(Fr.crop((0, fh - 1, fw, fh)).resize((fw, region_h - by2)), (x0, by2))
    if x0 > 0:                            # extend left edge (hinge-side margin)
        reg.paste(reg.crop((x0, 0, x0 + 1, region_h)).resize((x0, region_h)), (0, 0))
    rx = x0 + fw
    if rx < region_w:                     # extend right edge outward (outer wrap)
        reg.paste(reg.crop((rx - 1, 0, rx, region_h)).resize((region_w - rx, region_h)), (rx, 0))
    return reg


def compose_cover(
    front_img: Image.Image,
    listing: Dict,
    page_count: int,
    style_variant: Optional[Dict] = None,
    overrides: Optional[Dict] = None,
    binding: str = "paperback",
) -> Image.Image:
    """
    Composes the full-wrap cover (back + spine + front) as a single PIL Image.
    Returns the full cover image at 300 DPI.

    Reads from listing (with fallbacks):
      - trim_size_w / trim_size_h : custom KDP trim (default 6×9)
      - paper_type : white / cream / groundwood / color (default white)
    """
    # Honour custom trim + paper from listing.json (NEW)
    trim_w     = float(listing.get("trim_size_w", PAGE_W_IN))
    trim_h     = float(listing.get("trim_size_h", PAGE_H_IN))
    paper_type = str(listing.get("paper_type", "white")).lower()
    dims    = cover_dims(page_count, trim_w=trim_w, trim_h=trim_h,
                         paper_type=paper_type, binding=binding)
    full_w  = dims["full_w_px"]
    full_h  = dims["full_h_px"]
    front_w = dims["front_w_px"]
    front_h = dims["front_h_px"]
    spine_w = dims["spine_w_px"]
    bleed   = dims["bleed_px"]
    hinge   = dims.get("hinge_px", 0)   # 0 for paperback → layout unchanged

    # Resize DALL-E image to front cover size
    front = front_img.resize((front_w, full_h), Image.LANCZOS)

    # ── Color sampling: extract the true SATURATED hero color from the AI image
    if style_variant and style_variant.get("palette", {}).get("accent"):
        dom_color = _hex_to_rgb(style_variant["palette"]["accent"])
    else:
        dom_color = _dominant_color(front_img)   # use the original (uncropped)

    # ── Palette selection — 3 sources, weighted ──────────────────────────
    # 60% : curated palette matching niche (if any)  → designer-quality coherence
    # 30% : image-extracted + harmony scheme         → image-coherent
    # 10% : random curated palette                   → surprise / explore
    import random as _r_pal
    curated = _pick_curated_palette(listing.get("niche", ""))
    roll = _r_pal.random()
    palette_source = "image"
    if curated and roll < 0.60:
        pal_colors = curated["colors"]
        back_color   = pal_colors["band"]   # back = band (uniform pref)
        spine_color  = pal_colors["spine"]
        band_rgb_h   = pal_colors["band"]
        stripe_rgb_h = pal_colors["stripe"]
        palette_source = f"curated:{curated['name']}"
    elif roll < 0.90:
        # Image-extracted with random harmony scheme
        pal = _harmonize_palette(dom_color)
        back_color   = pal["back"]
        spine_color  = pal["spine"]
        band_rgb_h   = pal["band"]
        stripe_rgb_h = pal["stripe"]
        palette_source = f"image-extract:{pal.get('_scheme', '?')}"
    else:
        # Random curated palette (any genre — surprise!)
        name, colors, tags = _r_pal.choice(_CURATED_PALETTES)
        back_color   = colors["band"]
        spine_color  = colors["spine"]
        band_rgb_h   = colors["band"]
        stripe_rgb_h = colors["stripe"]
        palette_source = f"random-curated:{name}"
    logger.info(f"Cover palette source: {palette_source}")

    # ── Color overrides ────────────────────────────────────────────────────
    # Lets the user force any hex colour for band / spine / back via UI picker.
    def _parse_hex(v):
        if not v: return None
        try:
            h = str(v).lstrip("#").strip()
            if len(h) == 6:
                return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        except Exception:
            pass
        return None
    _ovr_palette = overrides or {}
    _ov_band  = _parse_hex(_ovr_palette.get("band_color"))
    _ov_spine = _parse_hex(_ovr_palette.get("spine_color"))
    _ov_back  = _parse_hex(_ovr_palette.get("back_color"))
    if _ov_band:
        band_rgb_h = _ov_band
        back_color = _ov_band   # uniform pref: back defaults to band
    if _ov_spine:
        spine_color = _ov_spine
    if _ov_back:
        back_color = _ov_back   # explicit back overrides band-link

    # ── Back-cover typography: MUST stay 100% legible ────────────────────
    # The back title + blurb are body copy. Some artistic display fonts
    # (script / hand / engraved) render letters as empty "tofu" boxes at body
    # sizes → the back became unreadable. A clean book serif fixes it for good
    # (Georgia, with _get_font's Arial/Helvetica fallback if unavailable).
    art_reg  = "/System/Library/Fonts/Supplemental/Georgia.ttf"
    art_bold = "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
    # ── Niche-specific theme fonts ─────────────────────────────────────────
    from modules.creation.niche_themes import detect_theme, get_theme_fonts
    theme       = detect_theme(listing.get("niche", ""))
    theme_fonts = get_theme_fonts(theme.get("name", "default"))
    display_path = theme_fonts.get("display")
    body_path    = theme_fonts.get("body")
    bold_path    = theme_fonts.get("body_bold")

    # Create canvas
    canvas = Image.new("RGB", (full_w, full_h), back_color)

    # ── Back cover (left side) — harmonious soft vertical gradient ─────────
    # Top: lighter version of back_color → Bottom: pure back_color
    # This keeps the back tonally connected to the front image instead of going gray.
    top_color = tuple(min(255, int(c + (255 - c) * 0.15)) for c in back_color)
    back_img = Image.new("RGB", (front_w, full_h), back_color)
    bd = ImageDraw.Draw(back_img)
    for y in range(full_h):
        t = y / max(full_h - 1, 1)
        r = int(top_color[0] * (1 - t) + back_color[0] * t)
        g = int(top_color[1] * (1 - t) + back_color[1] * t)
        b = int(top_color[2] * (1 - t) + back_color[2] * t)
        bd.line([(0, y), (front_w, y)], fill=(r, g, b))

    # Niche watermark : a heavily faded, mirrored version of the front image
    # placed across the back cover for an editorial / luxury feel.
    # Opacity ~8% — visible only as a subtle texture, doesn't fight with text.
    try:
        wm_src = front_img.convert("RGB").resize(
            (int(front_w * 1.05), int(full_h * 0.95)), Image.LANCZOS
        )
        # Mirror horizontally so it doesn't look like a duplicate of the front
        wm_src = wm_src.transpose(Image.FLIP_LEFT_RIGHT)
        # Blend back_img with wm at low opacity (10%)
        wm_resized = wm_src.crop((0, 0, front_w, full_h))
        _wm_alpha = float((overrides or {}).get("back_watermark_alpha", 0.10))
        back_img = Image.blend(back_img, wm_resized,
                                alpha=max(0.0, min(0.30, _wm_alpha)))
    except Exception:
        pass   # graceful if image ops fail

    canvas.paste(back_img, (0, 0))
    # NB: the decorative frame is drawn LATER (after the description text)
    # so its bottom edge can hug the actual text — see frame block below.

    # Back cover text
    draw = ImageDraw.Draw(canvas)
    tc   = _text_color(back_color)
    bx   = bleed + front_w // 2   # center of back cover
    # Hardcover safe area is inset more (wrap): start the back text lower.
    by   = int(full_h * (0.155 if hinge > 0 else 0.12))

    # Back overrides
    _back_title_visible = bool((overrides or {}).get("back_title_visible", True))
    _back_desc_visible  = bool((overrides or {}).get("back_description_visible", True))
    _back_frame_visible = bool((overrides or {}).get("back_frame_visible", True))

    # ── Back cover — PREMIUM MARKETING LAYOUT ─────────────────────────────
    # Hook headline (accent) → short intro → "WHAT YOU'LL DISCOVER" + benefit
    # bullets with an accent lead-in → call-to-action button → publisher logo.
    # Inspired by best-selling non-fiction back covers. Barcode zone kept clear.
    import re, html as _html
    _ovb = overrides or {}
    back_accent = _parse_hex(_ovb.get("back_accent_hex")) or _readable_accent(back_color)
    left   = bleed + int(front_w * 0.10)
    text_w = int(front_w * 0.80)

    def _lh(font):
        try:
            a, dd = font.getmetrics(); return a + dd
        except Exception:
            return getattr(font, "size", 20)

    def _tw2(t, f):
        b = draw.textbbox((0, 0), t, font=f)
        return b[2] - b[0]

    # Parse description → headline, intro, benefit bullets
    _ls = [_html.unescape(re.sub(r"<[^>]+>", " ", p))
           for p in re.split(r"<br\s*/?>", listing.get("description", ""))]
    _ls = [re.sub(r"\s+", " ", p).strip() for p in _ls]
    _ls = [p for p in _ls if p]
    headline, intro, bullets = "", "", []
    for p in _ls:
        if p[:1] in ("•", "-", "*"):
            bullets.append(p.lstrip("•-* ").strip())
        elif p.endswith(":"):
            continue
        elif not headline and len(p) > 18:
            headline = p
        elif headline and not intro and len(p) > 18:
            intro = p
    bullets = [b for b in bullets if b][:4]
    if not headline:
        headline, _ = _extract_cover_title(listing["title"])
    _hm = re.search(r"[.!?]", headline)
    if _hm and _hm.end() <= 100:
        headline = headline[:_hm.end()]
    headline = headline.strip()[:100]
    if intro and len(intro) > 220:
        _c = intro[:220]; _e = max(_c.rfind(". "), _c.rfind("! "), _c.rfind("? "))
        intro = intro[:_e + 1] if _e > 100 else _c.rsplit(" ", 1)[0] + "."

    by = int(full_h * (0.15 if hinge > 0 else 0.115))

    # 1) Hook headline (accent, bold)
    if _back_title_visible and headline:
        hf = _get_font(int(full_h * 0.028), bold=True, preferred_path=art_bold)
        by = _draw_wrapped_text(draw, headline, left, by, text_w, hf, back_accent,
                                line_spacing=4, align="left")
        by += int(full_h * 0.020)

    # 2) Intro sentence (body)
    if _back_desc_visible and intro:
        nf = _get_font(int(full_h * 0.0175), preferred_path=art_reg)
        by = _draw_wrapped_text(draw, intro, left, by, text_w, nf, tc,
                                line_spacing=5, align="left")
        by += int(full_h * 0.024)

    # 3) "WHAT YOU'LL DISCOVER" + benefit bullets (accent lead-in + body)
    if _back_desc_visible and bullets:
        sf = _get_font(int(full_h * 0.016), bold=True, preferred_path=art_bold)
        draw.text((left, by), "WHAT YOU'LL DISCOVER", font=sf, fill=back_accent)
        by += _lh(sf) + int(full_h * 0.016)
        bf_b = _get_font(int(full_h * 0.0175), bold=True, preferred_path=art_bold)
        bf_r = _get_font(int(full_h * 0.0175), preferred_path=art_reg)
        line_h = _lh(bf_r) + int(full_h * 0.006)
        tx     = left + int(front_w * 0.035)
        maxw   = text_w - int(front_w * 0.035)
        for b in bullets:
            mk = int(full_h * 0.007)
            draw.ellipse([left, by + line_h // 3, left + mk, by + line_h // 3 + mk],
                         fill=back_accent)
            words = b.split()
            nlead = min(3, len(words))
            lead = " ".join(words[:nlead]); rest = words[nlead:]
            cx2 = tx
            draw.text((cx2, by), lead, font=bf_b, fill=back_accent)
            cx2 += _tw2(lead, bf_b)
            i = 0
            while i < len(rest):
                wd = " " + rest[i]
                ww = _tw2(wd, bf_r)
                if cx2 + ww <= tx + maxw:
                    draw.text((cx2, by), wd, font=bf_r, fill=tc); cx2 += ww; i += 1
                else:
                    break
            by += line_h
            line = []
            for wd in rest[i:]:
                if _tw2(" ".join(line + [wd]), bf_r) <= maxw:
                    line.append(wd)
                else:
                    draw.text((tx, by), " ".join(line), font=bf_r, fill=tc); by += line_h
                    line = [wd]
            if line:
                draw.text((tx, by), " ".join(line), font=bf_r, fill=tc); by += line_h
            by += int(full_h * 0.010)

    # 4) Call-to-action button (accent pill) — kept left of the barcode zone.
    #    Customisable via overrides: cta_visible (bool), cta_text (str).
    cta = "" if not _ovb.get("cta_visible", True) else \
        (str(_ovb.get("cta_text") or "").strip() or _cta_text(listing))
    if cta:
        cf = _get_font(int(full_h * 0.017), bold=True, preferred_path=art_bold)
        ph = int(full_h * 0.044)
        pw = min(_tw2(cta, cf) + int(front_w * 0.10), int(front_w * 0.52))
        cta_y = int(full_h * (0.66 if hinge > 0 else 0.70))
        pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle([0, 0, pw - 1, ph - 1],
                                               radius=ph // 2, fill=(*back_accent, 255))
        canvas.paste(pill, (left, cta_y), pill)
        draw = ImageDraw.Draw(canvas)
        cta_ink = (30, 25, 15) if _luminance(back_accent) > 140 else (255, 255, 255)
        draw.text((left + (pw - _tw2(cta, cf)) // 2, cta_y + int(ph * 0.24)),
                  cta, font=cf, fill=cta_ink)

    # ── Publisher logo + name — bottom-LEFT corner ────────────────────────
    # KDP overlays the barcode (~2×1.2 inches) in the bottom-RIGHT corner of
    # the back cover. We must keep all our content in the LEFT 60% of the
    # back to avoid being clipped by the barcode.
    publisher = listing.get("publisher_name", "")
    # Reserved barcode area (KDP spec): bottom-right ~2.4×1.4" with margin.
    # In pixels: ~720×420 at 300 DPI. We stay safely left of front_w * 0.55.
    safe_right_edge = int(front_w * 0.55)
    # Logo small, anchored bottom-left
    # Override : publisher_size_mult (0.5 → 2.0)
    logo_size = int(full_h * 0.045 *
                    float((overrides or {}).get("publisher_size_mult", 1.0)))
    logo_cx   = bleed + int(front_w * 0.12)       # ~12% from left
    logo_cy   = int(full_h * (0.845 if hinge > 0 else 0.88))   # hardcover: higher
    _draw_publisher_logo(
        draw, logo_cx, logo_cy, publisher,
        fill_color   = tc,
        accent_color = dom_color,
        size_px      = logo_size,
        font_path    = art_bold,
    )
    # Publisher name to the RIGHT of the logo, left-aligned, capped to safe zone
    pub_x      = logo_cx + logo_size // 2 + 12     # right of logo
    pub_y      = int(full_h * (0.840 if hinge > 0 else 0.875))
    pub_max_w  = safe_right_edge - pub_x
    font_pub   = _get_font(int(full_h * 0.014), bold=True, preferred_path=art_bold)
    if publisher and pub_max_w > 50:
        _draw_wrapped_text(
            draw, publisher.upper(), pub_x, pub_y,
            pub_max_w, font_pub, tc,
            line_spacing=2, align="left",
        )

    # ── Front cover — GRADIENT FADE LAYOUT (senior designer style) ───────
    # Image occupies the top ~75%, fading smoothly into the band color over
    # the bottom 20% of the image region. No hard horizontal line.
    # The band color is EXTRACTED from the image's bottom strip for natural
    # color continuity — image and band feel like ONE piece.
    front_x = bleed + front_w + spine_w + 2 * hinge   # +hinges for hardcover
    # Hardcover: paint the whole back-to-front middle band (hinge+spine+hinge)
    # with the spine colour so the hinge channels aren't left as back colour.
    if hinge > 0:
        ImageDraw.Draw(canvas).rectangle(
            [(bleed + front_w, 0), (front_x, full_h)], fill=spine_color)

    # Use band color as the entire front backdrop (will show through fade)
    band_rgb = band_rgb_h
    if _luminance(band_rgb) > 175:
        band_rgb = tuple(max(0, int(c * 0.55)) for c in band_rgb)

    # Paint band color across the WHOLE front area first
    ImageDraw.Draw(canvas).rectangle(
        [(front_x, 0), (front_x + front_w, full_h)], fill=band_rgb,
    )

    # Overrides — band_height_pct (0.20 → 0.40) controls how much of the cover
    # is text band vs. image. fade_strength (0.05 → 0.45) controls gradient.
    _ovr_front     = overrides or {}
    # High-content books supply a fully-designed commercial front (title + badges
    # baked in). When present we paste it over the front region and skip the
    # generic title/subtitle/publisher drawing below.
    _prerendered_front = _ovr_front.get("prerendered_front")
    _band_h_pct    = float(_ovr_front.get("band_height_pct", 0.30))    # = 1 - image_top_pct
    _image_top_pct = max(0.55, min(0.85, 1.0 - _band_h_pct))
    _fade_pct      = float(_ovr_front.get("fade_strength", 0.25))

    img_region_h = int(full_h * _image_top_pct)
    # CROP-TO-FILL (no distortion) instead of stretch. ImageOps.fit scales the
    # source to cover the region and center-crops the excess — preserves the
    # subject's true proportions (the old .resize() stretched faces/objects).
    # The bottom of the image fades into the band anyway, so a small center
    # crop is invisible.
    ai_resized = ImageOps.fit(
        front_img.convert("RGB"), (front_w, img_region_h),
        method=Image.LANCZOS, centering=(0.5, 0.4),
    )
    ai_rgba    = ai_resized.convert("RGBA")

    # Build vertical alpha mask: opaque at top, fades to transparent over
    # bottom `_fade_pct` of image region — so the band color blends in naturally.
    fade_h = int(img_region_h * max(0.05, min(0.45, _fade_pct)))
    fade_top_y = img_region_h - fade_h
    mask = Image.new("L", (front_w, img_region_h), 255)
    mask_draw = ImageDraw.Draw(mask)
    for y in range(fade_top_y, img_region_h):
        # Smooth ease-out fade: 255 at fade_top_y → 0 at img_region_h
        progress = (y - fade_top_y) / max(fade_h, 1)
        # Use cosine ease for smoother visual transition than linear
        import math as _m
        eased = (1 - _m.cos(_m.pi * progress)) / 2   # 0→1 smooth S-curve
        alpha = int(255 * (1 - eased))
        mask_draw.line([(0, y), (front_w, y)], fill=alpha)

    ai_rgba.putalpha(mask)

    # Composite onto canvas (band color shows through the fade)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(ai_rgba, dest=(front_x, 0))
    canvas = canvas_rgba.convert("RGB")

    # Pre-rendered commercial front (cookbook/guide) overpaints the whole front.
    if _prerendered_front is not None:
        try:
            _pf = ImageOps.fit(_prerendered_front.convert("RGB"),
                               (front_w, full_h), method=Image.LANCZOS)
            canvas.paste(_pf, (front_x, 0))
        except Exception as _pfe:
            logger.warning(f"prerendered front paste failed: {_pfe}")

    # HARDCOVER: re-place the front inside the safe band (text away from the
    # wide wrap) with the photo edge-extended to bleed — respects the KDP frame.
    if hinge > 0:
        try:
            _F = (_prerendered_front if _prerendered_front is not None
                  else front_img).convert("RGB")
            _region_w = full_w - front_x
            canvas.paste(_hc_front_region(_F, _region_w, full_h, front_w),
                         (front_x, 0))
        except Exception as _hfe:
            logger.warning(f"hardcover front safe-fit failed: {_hfe}")

    draw = ImageDraw.Draw(canvas)
    # NO MORE STRIPE SEPARATOR — gradient does the job
    # The "band region" for text starts at ~fade_top_y (where image fully fades out)
    band_h = full_h - fade_top_y

    cx = front_x + front_w // 2
    # Title colour override : "white" / "black" / "auto" (default white on band)
    _title_color = str((overrides or {}).get("title_color", "white")).lower()
    if _title_color == "black":
        tc = (0, 0, 0)
    elif _title_color == "auto":
        tc = _text_color(band_rgb if "band_rgb" in dir() else (40, 40, 40))
    else:
        tc = (255, 255, 255)

    # Main title — extract a SHORT punchy version for the cover.
    # The full title goes on KDP listing; the cover shows only the hook.
    raw_title = listing["title"]
    main_title, cover_subtitle_from_title = _extract_cover_title(raw_title)

    # Subtitle on cover:
    #   PRIORITY 1: text trimmed FROM the main title ("for X" / after ":" / "-" / "|")
    #   PRIORITY 2: listing.subtitle field (Claude-invented)
    if cover_subtitle_from_title:
        subtitle = _short_subtitle(cover_subtitle_from_title,
                                    max_words=12, max_chars=80)
    else:
        subtitle = (listing.get("subtitle") or "").strip()
        subtitle = _short_subtitle(subtitle, max_words=7, max_chars=48)

    # Designed front already carries the title/subtitle — suppress generic text.
    if _prerendered_front is not None:
        main_title = ""
        subtitle = ""

    # ── Typography strategy based on product type ────────────────────────
    product_type = listing.get("product_type", "default")
    strategy = _typo_for_product(product_type)
    # Choose fonts matching the strategy's pool (overrides niche-only pick)
    # Font pool override: lets the user force a specific typography family
    _font_pool_override = str((overrides or {}).get("font_pool", "")).lower().strip()
    _effective_pool = _font_pool_override if _font_pool_override in (
        "serif", "sans", "display", "script", "hand", "fantasy"
    ) else strategy["font_pool"]
    strat_reg, strat_bold = _font_for_strategy(_effective_pool,
                                               niche=listing.get("niche", ""))

    # EXACT title-font override (highest priority): the user can pick one
    # specific font for the TITLE from TITLE_FONT_CHOICES in the UI. Subtitle
    # and publisher keep the pool font for visual cohesion.
    _title_font_choice = (overrides or {}).get("title_font", None)
    _title_font_pair = _resolve_title_font(_title_font_choice)
    if _title_font_pair:
        title_reg, title_bold = _title_font_pair
    else:
        title_reg, title_bold = strat_reg, strat_bold

    # Title size: base from strategy + auto-shrink if too long.
    # Use BOTH word count AND char count — long single words (e.g. "CRYPTOGRAMS")
    # overflow at bold_pop sizes even with only 3 words.
    base_pct      = strategy["title_size_pct"]
    title_words   = len(main_title.split())
    title_chars   = len(main_title)
    # Char-based safety net (catches "INSPIRATIONAL QUOTE CRYPTOGRAMS" 31 chars)
    if title_chars >= 36:
        base_pct *= 0.58
    elif title_chars >= 28:
        base_pct *= 0.70
    elif title_chars >= 22:
        base_pct *= 0.82
    # Word-based shrink kept for short-word edge cases
    if title_words > 6:
        base_pct *= 0.85
    elif title_words > 4:
        base_pct *= 0.92
    # Apply override : title_size_mult (0.4 → 1.5)
    _ovr = overrides or {}
    title_font_sz = int(full_h * base_pct * float(_ovr.get("title_size_mult", 1.0)))

    title_text = main_title.upper() if strategy["title_caps"] else main_title

    # Place title HIGHER inside the band (near fade boundary) for visual unity
    # Override : title_y_offset_pct (-0.15 → +0.15, fraction of full_h, default 0)
    _y_off = int(full_h * float(_ovr.get("title_y_offset_pct", 0.0)))
    title_y = fade_top_y + int(band_h * 0.18) + _y_off
    font_t  = _get_font(title_font_sz, bold=True, preferred_path=title_bold)
    title_bottom = _draw_wrapped_text(
        draw, title_text, cx, title_y,
        int(front_w * 0.88), font_t, tc, line_spacing=5,
    )

    # Subtitle — short, clean tagline (strategy can italicize for editorial)
    # Overrides : subtitle_visible (bool, default True), subtitle_size_mult (0.5-1.5)
    _sub_visible = bool((overrides or {}).get("subtitle_visible", True))
    _sub_mult    = float((overrides or {}).get("subtitle_size_mult", 1.0))
    if _sub_visible and subtitle and title_bottom < full_h - int(band_h * 0.30):
        title_bottom += int(band_h * 0.04)
        sub_size = int(full_h * strategy["subtitle_size_pct"] * _sub_mult)
        # Italic font preference for editorial strategy
        sub_font_path = strat_reg
        font_sub = _get_font(sub_size, bold=False, preferred_path=sub_font_path)
        _draw_wrapped_text(
            draw, subtitle, cx, title_bottom,
            int(front_w * 0.84), font_sub, (235, 235, 235), line_spacing=3,
        )

    # Publisher name — small, very bottom, soft (NO horizontal rule = cleaner)
    if _prerendered_front is None:
        pub_y    = full_h - int(band_h * 0.14)
        pub_font = _get_font(int(full_h * 0.015), bold=False, preferred_path=strat_reg)
        _draw_wrapped_text(
            draw, listing.get("publisher_name", "").upper(),
            cx, pub_y, int(front_w * 0.78), pub_font, (200, 200, 200),
        )

    # ── Spine ───────────────────────────────────────────────────────────────
    # KDP requirement: spine text must stay AT LEAST 0.375" (9.6 mm) away from
    # both the top and bottom edges, otherwise the cover gets rejected.
    # We use 0.4" padding for safety + smart title truncation (split on " : ",
    # never "..." — pro covers prefer dropping a part rather than ellipsing).
    # Spine override : spine_visible (bool) + spine_text_color (white/black/auto)
    _spine_visible    = bool(_ovr.get("spine_visible", True))
    _spine_text_color = str(_ovr.get("spine_text_color", "white")).lower()
    if spine_w >= 40 and _spine_visible:
        spine_bg = spine_color
        spine_img = Image.new("RGB", (spine_w, full_h), spine_bg)

        # Smart title prep : use the SAME short cover-title for consistency
        spine_title, _ = _extract_cover_title(listing["title"])
        spine_title = spine_title[:80]   # absolute hard cap

        if _spine_text_color == "black":
            spine_text_rgb = (0, 0, 0)
        elif _spine_text_color == "auto":
            spine_text_rgb = _text_color(spine_bg)
        else:
            spine_text_rgb = (255, 255, 255)

        # 0.4" top/bottom padding in pixels
        # Override : spine_padding_in (0.375 min KDP, 0.4 default, up to 0.8)
        _spine_pad_in   = float(_ovr.get("spine_padding_in", 0.4))
        edge_pad_px     = int(_spine_pad_in * DPI)
        usable_text_len = max(50, full_h - 2 * edge_pad_px)

        # Iterate: shrink font, then if needed drop trailing words (no "..."!)
        spine_font_sz = max(12, min(spine_w - 4, 24))
        while True:
            f = _get_font(spine_font_sz, bold=True, preferred_path=art_bold)
            try:
                bbox = f.getbbox(spine_title)
                text_w = bbox[2] - bbox[0]
            except Exception:
                text_w = len(spine_title) * spine_font_sz * 0.55
            if text_w <= usable_text_len:
                break
            # First try to shrink the font (down to 9pt)
            if spine_font_sz > 9:
                spine_font_sz -= 1
                continue
            # Font already minimal — drop the LAST WORD (no ellipsis, looks pro)
            words = spine_title.split()
            if len(words) > 2:
                spine_title = " ".join(words[:-1])
                continue
            # Can't shrink further — just chop letters
            if len(spine_title) > 8:
                spine_title = spine_title[:-1].rstrip()
                continue
            break
        spine_font = _get_font(spine_font_sz, bold=True, preferred_path=art_bold)
        try:
            bbox = spine_font.getbbox(spine_title)
            text_w_final = bbox[2] - bbox[0]
        except Exception:
            text_w_final = len(spine_title) * spine_font_sz * 0.55

        # Draw centered on a strip of length full_h; rotation maps strip-X to spine-Y
        txt_img = Image.new("RGB", (full_h, spine_w + 10), spine_bg)
        td      = ImageDraw.Draw(txt_img)
        draw_x  = max(edge_pad_px, (full_h - int(text_w_final)) // 2)
        # Vertical centering inside the strip (spine width)
        # Get text height for vertical centering on the strip
        try:
            ascent, descent = spine_font.getmetrics()
            text_h = ascent + descent
        except Exception:
            text_h = spine_font_sz
        draw_y = max(2, (spine_w - text_h) // 2)
        td.text((draw_x, draw_y), spine_title, font=spine_font, fill=spine_text_rgb)

        txt_rot = txt_img.rotate(90, expand=True)
        sy = max(0, (full_h - txt_rot.size[1]) // 2)
        spine_img.paste(txt_rot.crop((0, 0, spine_w, min(txt_rot.size[1], full_h))), (0, sy))

        canvas.paste(spine_img, (bleed + front_w + hinge, 0))   # +hinge for hardcover

    return canvas


# ── PDF writer ────────────────────────────────────────────────────────────────

def _clamp_for_print_gamut(img: Image.Image) -> Image.Image:
    """
    Soft-clamp pure RGB extremes (≥250 on a single channel) that shift hard
    when KDP converts to CMYK for paperback printing (vivid blues → purple,
    bright reds → orange-brown, neon greens → muddy olive).

    Pro practice : keep all channels in [10, 245] for predictable print colour.
    """
    try:
        rgb = img.convert("RGB")
        return rgb.point(lambda v: max(10, min(245, v)))
    except Exception:
        return img


def save_cover_pdf(
    cover_img: Image.Image,
    output_path: str,
    page_count: int,
    trim_w: float = PAGE_W_IN,
    trim_h: float = PAGE_H_IN,
    paper_type: str = "white",
    binding: str = "paperback",
) -> str:
    """Saves the full-wrap cover image as a KDP-ready PDF, exact dims."""
    dims   = cover_dims(page_count, trim_w=trim_w, trim_h=trim_h,
                        paper_type=paper_type, binding=binding)
    w_in   = dims["full_w_in"]
    h_in   = dims["full_h_in"]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Pre-flight: clamp ultra-saturated RGB values that shift badly in KDP's
    # RGB→CMYK conversion. Pulls extreme channels back into safe printable gamut.
    cover_img = _clamp_for_print_gamut(cover_img)

    # Save image to buffer then wrap with ImageReader (required by ReportLab).
    # Embed sRGB ICC so KDP's print pipeline does a clean conversion.
    img_buf = io.BytesIO()
    save_kwargs = {"format": "JPEG", "quality": 95, "dpi": (DPI, DPI)}
    try:
        from PIL import ImageCms
        srgb_profile = ImageCms.createProfile("sRGB")
        save_kwargs["icc_profile"] = ImageCms.ImageCmsProfile(srgb_profile).tobytes()
    except Exception:
        pass
    cover_img.convert("RGB").save(img_buf, **save_kwargs)
    img_buf.seek(0)
    img_reader = ImageReader(img_buf)

    # Create PDF
    c = rl_canvas.Canvas(output_path, pagesize=(w_in * inch, h_in * inch))
    c.drawImage(
        img_reader,
        0, 0,
        width=w_in * inch, height=h_in * inch,
        preserveAspectRatio=False,
    )
    c.save()
    return output_path


# ── Master cover builder ──────────────────────────────────────────────────────

def generate_cover(
    listing: Dict,
    page_count: int,
    openai_key: str,
    output_path: str,
    status_cb=None,
    style_variant: Optional[Dict] = None,
    learning_dir=None,
    free_style: bool = False,
    anthropic_key: str = "",
    binding: str = "paperback",
    reuse_front_png: str = "",
    extra_overrides: Optional[Dict] = None,
) -> str:
    """
    End-to-end: DALL-E → compose → save PDF.
    `binding="hardcover"` produces a case-laminate wrap (wider wrap + hinges +
    thicker spine) instead of the paperback wrap.
    `extra_overrides` : caller cover tweaks merged last (cta_text, cta_visible,
    back_accent_hex, band/spine/back colours) — used by the UI back customiser.
    `reuse_front_png` : path to an existing front-art PNG to REUSE instead of
    calling DALL-E again (0 $ — used e.g. for the hardcover pass after the
    paperback cover already generated the art).
    style_variant tweaks the art style sent to gpt-image-2 for anti-duplicate.
    learning_dir lets the prompt pick up competitor color palette insights.
    `free_style=True` ignores variant palette → band colour is derived from the
    AI image itself and the style hint is randomised → each call gives a
    different cover for the same niche.
    Returns output_path.
    """
    # Reuse existing art (0 $) when asked and available — else generate via DALL-E.
    front_img = None
    if reuse_front_png and Path(reuse_front_png).exists():
        try:
            front_img = Image.open(reuse_front_png).convert("RGB")
            front_img.is_placeholder = False
            if status_cb:
                status_cb("♻️ Illustration réutilisée (0 $)")
        except Exception as _re:
            logger.debug(f"reuse_front_png failed: {_re}")
            front_img = None
    if front_img is None:
        prompt = build_dalle_prompt(
            listing, style_variant=style_variant, learning_dir=learning_dir,
            free_style=free_style,
        )
        front_img = fetch_dalle_image(prompt, openai_key, status_cb=status_cb)

    # Cache the raw AI image alongside the cover.pdf so we can RECOMPOSE
    # the cover later (fine-tuning title/spine/back) without re-calling DALL-E.
    # NEVER cache the placeholder — otherwise every later fine-tune/recompose
    # reuses the black gradient instead of a real image (the "cover noir" bug).
    if getattr(front_img, "is_placeholder", False):
        if status_cb:
            status_cb("⚠️ DALL-E indisponible — placeholder utilisé, PAS mis en cache "
                      "(relancez 'Auto-améliorer cover' plus tard).")
        logger.warning("DALL-E returned placeholder — skipping cache write so "
                       "fine-tune won't reuse the black image.")
    else:
        try:
            cache_path = Path(output_path).parent / ".cover_front.png"
            front_img.convert("RGB").save(cache_path, "PNG", optimize=True)
        except Exception as _e:
            logger.debug(f"Front-image cache write skipped: {_e}")

    if status_cb:
        status_cb("🖼️ Composition de la couverture complète (front + spine + back)...")

    # In free_style mode, drop the variant so compose_cover picks the band
    # colour from the AI image (varies every run).
    compose_variant = None if free_style else style_variant

    # LEARNED PREFERENCES — seed the user's recurring fine-tune choices (font,
    # title size, band height, colours…) as defaults so the bot reproduces
    # "your look" on every new cover. Built from cover_finetune events.
    learned_overrides = None
    if learning_dir:
        try:
            from modules.learning.events import cover_preferences
            pref = cover_preferences(learning_dir)
            if pref.get("ready") and pref.get("overrides"):
                learned_overrides = pref["overrides"]
                if status_cb:
                    status_cb(f"🧠 Préférences cover apprises appliquées : "
                              f"{', '.join(pref.get('notes', [])[:4])}")
        except Exception as _e:
            logger.debug(f"cover_preferences skipped: {_e}")

    # HIGH-CONTENT (cookbook / guide) → build a purely commercial front
    # (giant title + "N recipes" badge + benefit ribbon) from the food photo.
    _ptype = listing.get("product_type", "")
    if _ptype in ("recipe_book", "how_to") and not getattr(front_img, "is_placeholder", False):
        try:
            from modules.creation.cookbook_cover import (
                render_cookbook_front, render_kids_front, render_guide_front,
                render_botanical_front, render_anecdotes_front, _guide_palette)
            from modules.creation.highcontent.engine import (
                is_facts_niche, is_anecdotes_niche)
            from modules.creation.niche_themes import detect_theme as _dt
            _tw = float(listing.get("trim_size_w", PAGE_W_IN)) + 0.25
            _th = float(listing.get("trim_size_h", PAGE_H_IN)) + 0.25
            _guide_band = None
            # Competitor cover-design brief (cached per niche) → its accent drives
            # the high-content front colour + back/spine harmonisation.
            _brief_acc = None
            _brief_dark = None
            try:
                from modules.intelligence.cover_research import research_cover_design
                _ak = anthropic_key
                if not _ak:
                    from config import Config as _Cfg
                    _ak = getattr(_Cfg, "ANTHROPIC_API_KEY", "")
                _hb = research_cover_design(listing.get("niche", ""), _ptype, _ak,
                                            content_level="high-content",
                                            cache_dir=learning_dir, status_cb=status_cb)
                # NB: _parse_hex is local to compose_cover — use the module-level
                # _hex_to_rgb here so the brief accent actually reaches the front.
                _acc_hex = str((_hb or {}).get("accent") or "").strip()
                if len(_acc_hex.lstrip("#")) == 6:
                    try:
                        _brief_acc = _hex_to_rgb(_acc_hex)
                    except Exception:
                        _brief_acc = None
                # palette[0] = the deep, dark story colour (walnut/forest) → drives
                # the high-contrast title banner (brief: single dark banner behind title).
                _pal = (_hb or {}).get("palette") or []
                if _pal:
                    _dk_hex = str(_pal[0]).strip()
                    if len(_dk_hex.lstrip("#")) == 6:
                        try:
                            _brief_dark = _hex_to_rgb(_dk_hex)
                        except Exception:
                            _brief_dark = None
            except Exception as _be:
                logger.debug(f"cover brief skipped: {_be}")
            # Kids fun-facts → playful cover ; cookbooks → cookbook cover ;
            # how-to guides → niche-coloured premium guide cover.
            if is_facts_niche(listing.get("niche", "")) or listing.get("_facts"):
                designed = render_kids_front(
                    front_img, listing, int(_tw * DPI), int(_th * DPI))
                _msg = "🧒 Couverture enfant composée (titre ludique + badge fun facts)"
            elif listing.get("_anecdotes") or is_anecdotes_niche(listing.get("niche", "")):
                # Adult anecdotes/true-stories → jewel + ornate gold reference cover.
                _thm = _dt(listing.get("niche", "")).get("name", "stories")
                designed = render_anecdotes_front(
                    front_img, listing, int(_tw * DPI), int(_th * DPI), theme=_thm)
                _msg = "📜 Couverture anecdotes composée (jewel + cadre doré)"
                _guide_band = "#1e2a4a"      # jewel navy back
                _guide_spine = "#ceaa5c"     # gold spine
            elif _ptype == "recipe_book":
                designed = render_cookbook_front(
                    front_img, listing, int(_tw * DPI), int(_th * DPI))
                _msg = "🍳 Couverture commerciale composée (titre + badges)"
                if _brief_acc:   # harmonise back/spine to competitor palette
                    _guide_band = "#%02x%02x%02x" % _brief_acc
                    _guide_spine = "#%02x%02x%02x" % tuple(int(c * 0.7) for c in _brief_acc)
            elif _dt(listing.get("niche", "")).get("name") == "nature":
                # Gardening / nature guides → premium botanical/editorial cover.
                designed = render_botanical_front(
                    front_img, listing, int(_tw * DPI), int(_th * DPI))
                _msg = "🌿 Couverture botanique premium composée (crème + serif verte)"
                _acc = _guide_palette(listing.get("niche", ""))[0]
                # Homogeneous editorial look: CREAM back (dark text auto) to match
                # the cream front; GREEN spine (white text) to tie it together.
                _guide_band = "#f4eede"                       # cream back
                _guide_spine = "#%02x%02x%02x" % _acc          # green spine
            else:
                designed = render_guide_front(
                    front_img, listing, int(_tw * DPI), int(_th * DPI),
                    accent_override=_brief_acc, band_override=_brief_dark)
                _msg = "📘 Couverture guide composée (couleur concurrent + badges)"
                # Harmonise back/spine to the competitor accent (else niche colour).
                _acc = _brief_acc or _guide_palette(listing.get("niche", ""))[0]
                _guide_band = "#%02x%02x%02x" % _acc
                _guide_spine = "#%02x%02x%02x" % tuple(int(c * 0.7) for c in _acc)
            learned_overrides = dict(learned_overrides or {})
            learned_overrides["prerendered_front"] = designed
            if _guide_band:
                learned_overrides["band_color"] = _guide_band
                learned_overrides["spine_color"] = _guide_spine
            if status_cb:
                status_cb(_msg)
        except Exception as _cbe:
            logger.warning(f"designed front skipped: {_cbe}")

    # LOW-CONTENT (journals / coloring / puzzles / logs / planners) → a
    # competitor-informed front driven by a cached cover-design brief (niche-aware).
    if _ptype not in ("recipe_book", "how_to") and not getattr(front_img, "is_placeholder", False):
        try:
            from modules.creation.cookbook_cover import render_brief_front
            from modules.intelligence.cover_research import research_cover_design
            _ak = anthropic_key
            if not _ak:
                try:
                    from config import Config as _Cfg
                    _ak = getattr(_Cfg, "ANTHROPIC_API_KEY", "")
                except Exception:
                    _ak = ""
            brief = research_cover_design(
                listing.get("niche", ""), _ptype, _ak,
                content_level="low-content", cache_dir=learning_dir, status_cb=status_cb)
            if brief:
                _tw = float(listing.get("trim_size_w", PAGE_W_IN)) + 0.25
                _th = float(listing.get("trim_size_h", PAGE_H_IN)) + 0.25
                designed = render_brief_front(front_img, listing,
                                              int(_tw * DPI), int(_th * DPI), brief)
                learned_overrides = dict(learned_overrides or {})
                learned_overrides["prerendered_front"] = designed
                # Harmonise the back with the front's DOMINANT tone (palette[0]),
                # not the bright accent — a dark front needs a dark back.
                _pal = brief.get("palette") or []
                if _pal:
                    learned_overrides["band_color"] = _pal[0]
                if brief.get("accent"):
                    learned_overrides["spine_color"] = brief["accent"]
                if status_cb:
                    status_cb("🎨 Couverture low-content composée (brief concurrent)")
        except Exception as _le:
            logger.warning(f"brief front skipped: {_le}")

    # Merge caller-supplied cover overrides last (UI back-cover customisation:
    # cta_text, cta_visible, back_accent_hex, band/spine/back colours, …).
    if extra_overrides:
        learned_overrides = dict(learned_overrides or {})
        learned_overrides.update({k: v for k, v in extra_overrides.items()
                                  if v is not None})

    cover = compose_cover(front_img, listing, page_count,
                          style_variant=compose_variant,
                          overrides=learned_overrides, binding=binding)

    # Read custom trim/paper from listing for the PDF save (must match compose_cover)
    trim_w     = float(listing.get("trim_size_w", PAGE_W_IN))
    trim_h     = float(listing.get("trim_size_h", PAGE_H_IN))
    paper_type = str(listing.get("paper_type", "white")).lower()

    if status_cb:
        status_cb(f"💾 Export PDF couverture {binding} (KDP {trim_w}×{trim_h}in, "
                  f"{paper_type}, {page_count}p)...")

    save_cover_pdf(cover, output_path, page_count,
                   trim_w=trim_w, trim_h=trim_h, paper_type=paper_type, binding=binding)

    dims = cover_dims(page_count, trim_w=trim_w, trim_h=trim_h,
                      paper_type=paper_type, binding=binding)

    # ALSO save the FRONT cover as cover.png / cover.jpg (with title) — needed for
    # Booksprout, A+ mockups, Kindle, etc. PAPERBACK ONLY: the hardcover run must
    # NOT overwrite the paperback cover.png/cover.jpg (front art is identical).
    if binding != "hardcover":
        try:
            cw, ch = cover.size                       # full-wrap pixels
            scale_x = cw / dims["full_w_in"]
            scale_y = ch / dims["full_h_in"]
            fx0 = int(dims["front_x_in"] * scale_x)
            fy0 = int(dims["bleed_in"]   * scale_y)
            fx1 = int((dims["front_x_in"] + trim_w) * scale_x)
            fy1 = int((dims["bleed_in"]   + trim_h) * scale_y)
            _front = cover.convert("RGB").crop((fx0, fy0, fx1, fy1))
            front_png = Path(output_path).parent / "cover.png"
            _front.save(front_png, "PNG", optimize=True)
            # ALSO save the EBOOK cover as JPG — KDP/Kindle requires JPEG for the
            # ebook cover (PNG is rejected). This is the file to upload on Kindle.
            front_jpg = Path(output_path).parent / "cover.jpg"
            _front.save(front_jpg, "JPEG", quality=92, optimize=True)
        except Exception as _e:
            logger.debug(f"cover front export skipped: {_e}")

    if status_cb:
        status_cb(
            f"✅ Couverture {binding} créée → {Path(output_path).name} "
            f"({dims['full_w_in']:.3f}\" × {dims['full_h_in']:.3f}\" "
            f"| spine {dims['spine_in']:.4f}\")"
        )

    return output_path
