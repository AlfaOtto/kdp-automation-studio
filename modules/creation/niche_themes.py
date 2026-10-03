"""
Niche-aware decorative themes for interior PDFs.

Detects the niche category from keywords and returns:
  - icons    : a list of PDF-safe Unicode glyphs (sprinkled in section banners)
  - keywords : trigger words that match this theme
  - banner_emoji : the strongest symbol for big banners

All glyphs are BMP (Basic Multilingual Plane) so they render in Helvetica/Times
without needing custom font embedding.
"""
from typing import Dict, List

NICHE_THEMES: Dict[str, Dict] = {
    "music": {
        "icons":   ["♪", "♫", "♬", "♩", "♭", "♮", "♯"],
        "banner":  "♫",
        "keywords": [
            "music", "song", "rap", "hip hop", "jazz", "rock", "metal",
            "pop", "vinyl", "guitar", "drum", "concert", "band", "lyrics",
            "album", "playlist", "dj", "beat", "audio",
        ],
    },
    "nature": {
        "icons":   ["❋", "✿", "❀", "✾", "⚘", "❉", "❊"],
        "banner":  "❋",
        "keywords": [
            "nature", "forest", "garden", "plant", "flower", "tree",
            "botanical", "leaf", "wildflower", "herb", "mushroom",
            "foraging", "ecology", "wildlife", "outdoor",
        ],
    },
    "stars": {
        "icons":   ["★", "☆", "✦", "✧", "✨", "✩"],
        "banner":  "✦",
        "keywords": [
            "star", "astronomy", "celestial", "cosmic", "galaxy",
            "zodiac", "constellation", "horoscope", "moon", "lunar",
            "manifestation", "dreams", "magic", "witchcraft", "spiritual",
        ],
    },
    "geometry": {
        "icons":   ["◆", "◇", "◈", "▲", "△", "■", "□", "●", "○"],
        "banner":  "◆",
        "keywords": [
            "geometric", "abstract", "minimalist", "modern", "design",
            "pattern", "architecture", "math", "engineering",
        ],
    },
    "ocean": {
        "icons":   ["≈", "∽", "◐", "◓", "○", "❀"],
        "banner":  "≈",
        "keywords": [
            "ocean", "sea", "fish", "marine", "beach", "wave", "boat",
            "sailing", "scuba", "diving", "coral", "shell", "mermaid",
        ],
    },
    "animals": {
        "icons":   ["✦", "◐", "❋", "✧"],
        "banner":  "✦",
        "keywords": [
            "cat", "dog", "bird", "horse", "rabbit", "pet", "animal",
            "wildlife", "zoo", "puppy", "kitten", "birdwatching",
        ],
    },
    "food": {
        "icons":   ["✿", "◆", "❀"],
        "banner":  "❀",
        "keywords": [
            "food", "recipe", "cooking", "baking", "kitchen", "tea",
            "coffee", "wine", "cocktail", "dessert", "chef",
        ],
    },
    "fitness": {
        "icons":   ["★", "◆", "▲", "✦"],
        "banner":  "★",
        "keywords": [
            "fitness", "workout", "yoga", "running", "gym", "weight",
            "training", "muscle", "cardio", "stretch", "pilates",
        ],
    },
    "vintage": {
        "icons":   ["❧", "❦", "✦", "❈", "☙"],
        "banner":  "❧",
        "keywords": [
            "vintage", "retro", "classic", "antique", "victorian",
            "70s", "80s", "90s", "60s", "nostalgia", "old",
        ],
    },
    "wellness": {
        "icons":   ["✿", "❀", "✦", "◐", "◯"],
        "banner":  "✿",
        "keywords": [
            "gratitude", "mindful", "meditation", "self-care", "wellness",
            "healing", "chakra", "energy", "vibe", "manifest",
            "therapy", "anxiety", "depression", "growth",
        ],
    },
    "horror": {
        "icons":   ["✦", "◆", "❈", "✧"],
        "banner":  "✦",
        "keywords": [
            "horror", "creepy", "scary", "dark", "goth", "vampire",
            "ghost", "haunted", "paranormal", "spooky", "thriller",
            "villain", "dark academia",
        ],
    },
    "planner": {
        "icons":   ["◆", "◇", "▣", "□", "■"],
        "banner":  "◆",
        "keywords": [
            "planner", "daily", "weekly", "monthly", "schedule",
            "agenda", "calendar", "appointment", "to-do", "todo",
            "task", "productivity", "time-block", "habit", "habits",
            "tracker", "tracking",
        ],
    },
    "health": {
        "icons":   ["✿", "❀", "◐", "❋", "✦"],
        "banner":  "❀",
        "keywords": [
            "health", "symptom", "symptoms", "medical", "medication",
            "pain", "headache", "migraine", "blood pressure",
            "blood sugar", "diabetes", "weight", "sleep", "menstrual",
            "period", "fertility", "pregnancy", "doctor", "appointment",
            "therapy", "recovery", "diet", "wellbeing",
            # Chronic / specific conditions
            "autoimmune", "chronic", "flare", "lupus", "arthritis",
            "fibromyalgia", "ibs", "crohn", "endometriosis",
            "asthma", "allergy", "anxiety", "depression",
            "mental health", "ptsd", "adhd", "autism",
        ],
    },
    "education": {
        "icons":   ["◈", "❋", "★", "✦", "◆"],
        "banner":  "◈",
        "keywords": [
            "study", "school", "homework", "academic", "college",
            "university", "student", "exam", "notes", "lecture",
            "research", "math", "science", "biology", "chemistry",
            "physics", "language", "education", "vocabulary",
            "kindergarten", "elementary",
        ],
    },
    "finance": {
        "icons":   ["◆", "◈", "▣", "★", "◇"],
        "banner":  "◆",
        "keywords": [
            "budget", "finance", "money", "expense", "income",
            "saving", "investment", "debt", "bills", "tax",
            "accounting", "ledger", "cash flow", "wealth",
        ],
    },
    "craft": {
        "icons":   ["❋", "✿", "❈", "✦", "❉"],
        "banner":  "❈",
        "keywords": [
            "craft", "knitting", "crochet", "sewing", "embroidery",
            "quilting", "scrapbook", "diy", "handmade", "pottery",
            "woodworking", "calligraphy", "drawing", "sketch",
            "art", "painting", "watercolor",
            # Handmade products that involve recipes/formulas
            "soap", "candle", "jewelry", "leather", "macrame",
            "weaving", "metalwork", "ceramic", "glass", "resin",
            "perfume", "beauty product", "cosmetic", "lotion",
        ],
    },
    "gaming": {
        "icons":   ["◆", "★", "✦", "◈", "▲"],
        "banner":  "◆",
        "keywords": [
            "gaming", "rpg", "dnd", "dungeons", "dragons",
            "minecraft", "fortnite", "pokemon", "chess", "puzzle",
            "videogame", "esports", "speedrun",
        ],
    },
    "kids": {
        "icons":   ["★", "✿", "❀", "✦", "◐"],
        "banner":  "★",
        "keywords": [
            "kids", "children", "child", "toddler", "baby",
            "preschool", "alphabet", "abc",
        ],
    },
    "travel": {
        "icons":   ["✦", "◆", "▲", "❋", "◐"],
        "banner":  "✦",
        "keywords": [
            "travel", "vacation", "trip", "journey", "adventure",
            "hiking", "camping", "backpacking", "road trip",
            "passport", "tourism", "explore",
        ],
    },
    "religion": {
        "icons":   ["✝", "☩", "✟", "❖", "✦"],
        "banner":  "✝",
        "keywords": [
            "bible", "prayer", "devotional", "christian", "catholic", "faith",
            "scripture", "god", "jesus", "gospel", "psalms", "worship",
            "quran", "qur'an", "islam", "islamic", "muslim", "ramadan", "hadith",
            "sunnah", "allah", "buddhism", "buddhist", "zen", "dharma",
            "torah", "jewish", "judaism", "hebrew", "synagogue", "rabbi", "kabbalah",
            "hindu", "vedic", "bhagavad", "spiritual growth", "stoicism",
            "gratitude practice", "religion", "meditation and mindfulness",
        ],
    },
    "education": {
        "icons":   ["✎", "✏", "❏", "◆", "✦"],
        "banner":  "✎",
        "keywords": [
            "learn", "learning", "study", "study skills", "student", "language",
            "spanish", "french", "german", "italian", "grammar", "vocabulary",
            "public speaking", "memory", "exam", "test prep", "how to learn",
            "calligraphy", "coding", "excel", "education", "tutorial",
        ],
    },
    "stories": {
        "icons":   ["❝", "❞", "✦", "❖", "❧"],
        "banner":  "❧",
        "keywords": [
            "anecdotes", "true stories", "short stories", "tales", "history stories",
            "fascinating", "mind blowing", "strange but true", "unbelievable",
            "interesting facts for adults", "little known", "trivia for adults",
        ],
    },
    "default": {
        "icons":   ["✦", "❋", "◆", "❈", "✿"],
        "banner":  "✦",
        "keywords": [],
    },
}


def detect_theme(niche: str) -> Dict:
    """
    Returns the matching theme dict for a niche string.

    Scoring strategy (most-specific-wins):
      score = (# matched keywords)² × 1000
            + sum(length of each matched keyword)
            + theme_priority_bonus

    The squared count strongly rewards themes that match MANY keywords.
    For ties (same number of matches), longer matched keywords win.
    A small priority bonus disambiguates "subcategory vs general category"
    (e.g. craft is more specific than food when both have 1 match).
    """
    nl = (niche or "").lower()

    # Higher priority = preferred when tied. Specific subcategories first.
    _PRIORITY = {
        "religion":  9,   # explicit religious terms (bible/prayer) beat study/planner
        "horror":    8,
        "health":    8,   # health gets top priority — autoimmune > planner
        "stories":   7,   # anecdotes/true-stories beat generic themes
        "craft":     7,   # craft > vintage (the product matters more than aesthetic)
        "stars":     7,
        "gaming":    6,
        "kids":      6,
        "vintage":   5,   # vintage is often stylistic — yields to product themes
        "travel":    5,
        "education": 5,
        "finance":   5,
        "fitness":   5,
        "music":     4,
        "nature":    4,
        "animals":   4,
        "ocean":     4,
        "planner":   3,   # planner is very generic — yields to specific niches
        "food":      3,
        "wellness":  3,
        "geometry":  2,
    }

    best_match = None
    best_score = 0

    for theme_name, theme in NICHE_THEMES.items():
        if theme_name == "default":
            continue
        matched_kws = [kw for kw in theme["keywords"] if kw in nl]
        n = len(matched_kws)
        if n == 0:
            continue
        score = (n * n) * 1000 + sum(len(kw) for kw in matched_kws) + _PRIORITY.get(theme_name, 0) * 15
        if score > best_score:
            best_score = score
            best_match = theme_name

    if best_match:
        return {**NICHE_THEMES[best_match], "name": best_match}
    return {**NICHE_THEMES["default"], "name": "default"}


def get_section_icon(niche: str, section_index: int = 0) -> str:
    """Returns one icon from the theme, rotating through the list per section."""
    theme = detect_theme(niche)
    icons = theme["icons"]
    return icons[section_index % len(icons)]


# ── Vector shape drawer (font-independent, always renders) ────────────────────

# Each theme gets a unique drawing function that paints a niche-specific
# shape on a ReportLab canvas. No font dependency = no missing-glyph boxes.

def draw_theme_shape(canvas, cx: float, cy: float, size: float,
                     theme_name: str, fill_color, stroke_color=None):
    """
    Draws a niche-themed vector shape centered at (cx, cy).
    `size` is the bounding-box half-width in points.
    """
    import math
    c = canvas
    c.saveState()
    c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        c.setLineWidth(1.5)

    drawer = _THEME_DRAWERS.get(theme_name, _draw_star)
    drawer(c, cx, cy, size)
    c.restoreState()


def _draw_star(c, cx, cy, r):
    """5-point filled star — default / horror / fitness."""
    import math
    pts = []
    inner = r * 0.42
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else inner
        pts.append((cx + rad * math.cos(angle), cy + rad * math.sin(angle)))
    p = c.beginPath()
    p.moveTo(*pts[0])
    for pt in pts[1:]:
        p.lineTo(*pt)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _draw_music_note(c, cx, cy, r):
    """Eighth note: flag + stem + filled oval head."""
    import math
    # Note head (filled ellipse, rotated slightly)
    head_w = r * 0.55
    head_h = r * 0.40
    c.saveState()
    c.translate(cx - r * 0.15, cy - r * 0.45)
    c.rotate(-15)
    c.ellipse(-head_w, -head_h, head_w, head_h, fill=1, stroke=0)
    c.restoreState()
    # Stem
    c.setLineWidth(r * 0.10)
    c.line(cx + r * 0.30, cy - r * 0.30, cx + r * 0.30, cy + r * 0.75)
    # Flag (a curved line approximated as bezier)
    p = c.beginPath()
    p.moveTo(cx + r * 0.30, cy + r * 0.75)
    p.curveTo(cx + r * 0.80, cy + r * 0.55,
              cx + r * 0.80, cy + r * 0.20,
              cx + r * 0.55, cy + r * 0.00)
    c.setLineWidth(r * 0.18)
    c.drawPath(p, fill=0, stroke=1)


def _draw_leaf(c, cx, cy, r):
    """Stylized leaf (almond shape) — nature/wellness/food."""
    p = c.beginPath()
    # Almond / leaf shape via two cubic beziers
    p.moveTo(cx, cy - r)                              # bottom point
    p.curveTo(cx + r * 1.0, cy - r * 0.6,             # right control 1
              cx + r * 1.0, cy + r * 0.6,             # right control 2
              cx, cy + r)                             # top point
    p.curveTo(cx - r * 1.0, cy + r * 0.6,             # left control 1
              cx - r * 1.0, cy - r * 0.6,             # left control 2
              cx, cy - r)                             # back to start
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    # Central vein (line)
    c.setStrokeColor((1, 1, 1, 0.6))
    c.setLineWidth(r * 0.06)
    c.line(cx, cy - r * 0.9, cx, cy + r * 0.9)


def _draw_diamond(c, cx, cy, r):
    """Diamond / rhombus — geometry / minimalist."""
    p = c.beginPath()
    p.moveTo(cx, cy + r)
    p.lineTo(cx + r, cy)
    p.lineTo(cx, cy - r)
    p.lineTo(cx - r, cy)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _draw_wave(c, cx, cy, r):
    """Triple wave — ocean."""
    import math
    c.setLineWidth(r * 0.16)
    for i, dy in enumerate([-r * 0.5, 0, r * 0.5]):
        p = c.beginPath()
        steps = 30
        for j in range(steps + 1):
            x = cx - r + (2 * r) * (j / steps)
            y = cy + dy + math.sin(j / steps * 2 * math.pi) * r * 0.18
            if j == 0:
                p.moveTo(x, y)
            else:
                p.lineTo(x, y)
        c.drawPath(p, fill=0, stroke=1)


def _draw_paw(c, cx, cy, r):
    """Paw print — animals."""
    # Main pad
    c.ellipse(cx - r * 0.50, cy - r * 0.50,
              cx + r * 0.50, cy + r * 0.15, fill=1, stroke=0)
    # 4 toe beans
    for tx, ty in [(-0.55, 0.45), (-0.20, 0.65), (0.20, 0.65), (0.55, 0.45)]:
        c.ellipse(cx + r * tx - r * 0.20, cy + r * ty - r * 0.20,
                  cx + r * tx + r * 0.20, cy + r * ty + r * 0.20,
                  fill=1, stroke=0)


def _draw_dumbbell(c, cx, cy, r):
    """Stylized dumbbell — fitness."""
    bar_w = r * 1.4
    bar_h = r * 0.18
    weight_w = r * 0.30
    weight_h = r * 0.85
    # Bar
    c.rect(cx - bar_w / 2, cy - bar_h / 2, bar_w, bar_h, fill=1, stroke=0)
    # Left weight
    c.rect(cx - bar_w / 2 - weight_w, cy - weight_h / 2,
           weight_w, weight_h, fill=1, stroke=0)
    # Right weight
    c.rect(cx + bar_w / 2, cy - weight_h / 2,
           weight_w, weight_h, fill=1, stroke=0)


def _draw_ornament_flourish(c, cx, cy, r):
    """Victorian flourish (concentric ring + dot pattern) — vintage."""
    c.setStrokeColor(c._fillColorObj)
    c.setLineWidth(r * 0.06)
    # Outer ring
    c.circle(cx, cy, r * 0.95, fill=0, stroke=1)
    # Inner ring
    c.circle(cx, cy, r * 0.60, fill=0, stroke=1)
    # Center dot
    c.circle(cx, cy, r * 0.18, fill=1, stroke=0)
    # 4 small dots at compass points
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        c.circle(cx + dx * r * 1.05, cy + dy * r * 1.05, r * 0.10, fill=1, stroke=0)


def _draw_circle_sun(c, cx, cy, r):
    """Sun-with-rays — stars/cosmic."""
    import math
    c.circle(cx, cy, r * 0.50, fill=1, stroke=0)
    # 12 rays
    c.setStrokeColor(c._fillColorObj)
    c.setLineWidth(r * 0.08)
    for i in range(12):
        angle = i * math.pi / 6
        x1 = cx + math.cos(angle) * r * 0.65
        y1 = cy + math.sin(angle) * r * 0.65
        x2 = cx + math.cos(angle) * r * 0.95
        y2 = cy + math.sin(angle) * r * 0.95
        c.line(x1, y1, x2, y2)


# ── Theme-specific typography ─────────────────────────────────────────────────

# Each theme has a curated font recipe: display (titles), body, body-bold, italic.
# Paths target macOS system fonts (most reliable .ttf files). The interior PDF
# and the cover both consult this map. If a file doesn't exist on the system,
# fallbacks (Georgia / Helvetica) are used automatically.
_FONT_DIR = "/System/Library/Fonts/Supplemental/"

THEME_FONTS = {
    "music": {
        "display":   _FONT_DIR + "Impact.ttf",
        "body":      _FONT_DIR + "Trebuchet MS.ttf",
        "body_bold": _FONT_DIR + "Trebuchet MS Bold.ttf",
        "italic":    _FONT_DIR + "Trebuchet MS Italic.ttf",
        "label":     "Impact + Trebuchet (urbain bold)",
    },
    "nature": {
        "display":   _FONT_DIR + "BigCaslon.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Big Caslon + Georgia (naturaliste)",
    },
    "stars": {
        "display":   _FONT_DIR + "Bodoni 72 Smallcaps Book.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Bodoni 72 SC + Georgia (magique)",
    },
    "geometry": {
        "display":   _FONT_DIR + "Tahoma Bold.ttf",
        "body":      "/System/Library/Fonts/Geneva.ttf",
        "body_bold": _FONT_DIR + "Arial Bold.ttf",
        "italic":    _FONT_DIR + "Arial Italic.ttf",
        "label":     "Tahoma Bold + Geneva (minimaliste)",
    },
    "vintage": {
        "display":   _FONT_DIR + "Bodoni 72 Smallcaps Book.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Bodoni 72 + Georgia (antique)",
    },
    "horror": {
        # Big Caslon is dramatic serif that holds up at long-title lengths
        # (Herculanum was too stylized for full book titles)
        "display":   _FONT_DIR + "BigCaslon.ttf",
        "body":      _FONT_DIR + "Times New Roman.ttf",
        "body_bold": _FONT_DIR + "Times New Roman Bold.ttf",
        "italic":    _FONT_DIR + "Times New Roman Italic.ttf",
        "label":     "Big Caslon + Times (gothique dramatique)",
    },
    "wellness": {
        "display":   _FONT_DIR + "Georgia Bold.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Georgia (doux humaniste)",
    },
    "ocean": {
        "display":   _FONT_DIR + "Trebuchet MS Bold.ttf",
        "body":      _FONT_DIR + "Trebuchet MS.ttf",
        "body_bold": _FONT_DIR + "Trebuchet MS Bold.ttf",
        "italic":    _FONT_DIR + "Trebuchet MS Italic.ttf",
        "label":     "Trebuchet (léger fluide)",
    },
    "animals": {
        "display":   _FONT_DIR + "Trebuchet MS Bold.ttf",
        "body":      _FONT_DIR + "Trebuchet MS.ttf",
        "body_bold": _FONT_DIR + "Trebuchet MS Bold.ttf",
        "italic":    _FONT_DIR + "Trebuchet MS Italic.ttf",
        "label":     "Trebuchet (friendly pro)",
    },
    "food": {
        "display":   _FONT_DIR + "Brush Script.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Brush Script + Georgia (recette warm)",
    },
    "fitness": {
        "display":   _FONT_DIR + "Impact.ttf",
        "body":      _FONT_DIR + "Arial.ttf",
        "body_bold": _FONT_DIR + "Arial Bold.ttf",
        "italic":    _FONT_DIR + "Arial Italic.ttf",
        "label":     "Impact + Arial (action puissant)",
    },
    "default": {
        "display":   _FONT_DIR + "Georgia Bold.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Georgia (lisible polyvalent)",
    },
    "religion": {
        "display":   _FONT_DIR + "Baskerville.ttc",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Baskerville + Georgia (solennel classique)",
    },
    "education": {
        "display":   _FONT_DIR + "Arial Bold.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Arial Bold + Georgia (clair pédagogique)",
    },
    "stories": {
        "display":   _FONT_DIR + "Bodoni 72 Smallcaps Book.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Bodoni SC + Georgia (éditorial narratif)",
    },
    "planner": {
        "display":   _FONT_DIR + "Tahoma Bold.ttf",
        "body":      _FONT_DIR + "Tahoma.ttf",
        "body_bold": _FONT_DIR + "Tahoma Bold.ttf",
        "italic":    _FONT_DIR + "Arial Italic.ttf",
        "label":     "Tahoma (productivité claire)",
    },
    "health": {
        "display":   _FONT_DIR + "Georgia Bold.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Georgia (soin doux)",
    },
    "education": {
        "display":   _FONT_DIR + "BigCaslon.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Big Caslon + Georgia (académique)",
    },
    "finance": {
        "display":   _FONT_DIR + "Tahoma Bold.ttf",
        "body":      _FONT_DIR + "Arial.ttf",
        "body_bold": _FONT_DIR + "Arial Bold.ttf",
        "italic":    _FONT_DIR + "Arial Italic.ttf",
        "label":     "Tahoma + Arial (sérieux pro)",
    },
    "craft": {
        "display":   _FONT_DIR + "Brush Script.ttf",
        "body":      _FONT_DIR + "Georgia.ttf",
        "body_bold": _FONT_DIR + "Georgia Bold.ttf",
        "italic":    _FONT_DIR + "Georgia Italic.ttf",
        "label":     "Brush Script + Georgia (artisanal)",
    },
    "gaming": {
        "display":   _FONT_DIR + "Impact.ttf",
        "body":      _FONT_DIR + "Trebuchet MS.ttf",
        "body_bold": _FONT_DIR + "Trebuchet MS Bold.ttf",
        "italic":    _FONT_DIR + "Trebuchet MS Italic.ttf",
        "label":     "Impact + Trebuchet (gaming bold)",
    },
    "kids": {
        "display":   _FONT_DIR + "Comic Sans MS Bold.ttf",
        "body":      _FONT_DIR + "Comic Sans MS.ttf",
        "body_bold": _FONT_DIR + "Comic Sans MS Bold.ttf",
        "italic":    _FONT_DIR + "Comic Sans MS.ttf",
        "label":     "Comic Sans (kids friendly)",
    },
    "travel": {
        "display":   _FONT_DIR + "Trebuchet MS Bold.ttf",
        "body":      _FONT_DIR + "Trebuchet MS.ttf",
        "body_bold": _FONT_DIR + "Trebuchet MS Bold.ttf",
        "italic":    _FONT_DIR + "Trebuchet MS Italic.ttf",
        "label":     "Trebuchet (voyage clair)",
    },
}


def get_theme_fonts(theme_name: str) -> Dict:
    """Returns the font recipe for a theme (with default fallback)."""
    return THEME_FONTS.get(theme_name, THEME_FONTS["default"])


# ── Niche-expert features library ─────────────────────────────────────────────
# Hardcoded "what a quality book in this niche should always have" lists.
# Used as fallback gap source when Claude returns nothing.
NICHE_EXPERT_FEATURES: Dict[str, List[str]] = {
    "music": [
        "no song lyric annotation pages",
        "no chord/scale reference section",
        "no setlist planner",
        "no practice log with goals",
        "no recording session tracker",
        "no gear/equipment log",
        "no songwriting prompt collection",
        "no album/influence inspiration log",
    ],
    "nature": [
        "no species identification field",
        "no GPS/location coordinates",
        "no weather conditions log",
        "no companion species note field",
        "no sketch/photo slot per entry",
        "no seasonal frequency tracker",
        "no foraging-safety reminder section",
        "no edible/non-edible classification",
    ],
    "stars": [
        "no moon phase tracker",
        "no astrological transit log",
        "no manifestation journal section",
        "no synchronicity tracker",
        "no dream interpretation pages",
        "no intention-setting ritual guide",
        "no zodiac sign reference",
    ],
    "geometry": [
        "no grid-based template variety",
        "no symmetry guide",
        "no pattern complexity progression",
        "no color theory reference",
        "no proportion / golden-ratio guide",
    ],
    "vintage": [
        "no era timeline reference",
        "no period-specific vocabulary",
        "no decorative ornament library",
        "no curated quote/wisdom pages",
        "no historical context section",
    ],
    "horror": [
        "no fear/anxiety severity scale",
        "no nightmare log with patterns",
        "no paranormal event documentation",
        "no trigger identification section",
        "no scary movie/book recommendation log",
    ],
    "wellness": [
        "no morning ritual checklist",
        "no evening reflection section",
        "no gratitude streak tracker",
        "no affirmation library",
        "no breathing exercise reference",
        "no mood-energy correlation",
        "no boundary setting prompts",
    ],
    "ocean": [
        "no tide / moon-phase tracker",
        "no water temperature log",
        "no marine species ID field",
        "no dive depth / time log",
        "no underwater visibility log",
        "no coral/reef location notes",
    ],
    "animals": [
        "no vet appointment log",
        "no vaccination/medication schedule",
        "no behavior observation pages",
        "no training milestone tracker",
        "no diet/feeding log",
        "no companion species reference",
        "no weight/growth chart",
    ],
    "food": [
        "no ingredient cost tracker",
        "no batch yield / scaling formula",
        "no allergy/dietary restrictions reference",
        "no prep-time and cost log",
        "no flavor pairing reference",
        "no source/supplier log",
        "no nutritional info field",
    ],
    "fitness": [
        "no rep/set progression log",
        "no body measurements tracker",
        "no PR (personal record) page",
        "no recovery / sleep correlation",
        "no nutrition macro tracker",
        "no rest-day plan",
        "no injury/pain log",
    ],
    "planner": [
        "no quarterly goal review",
        "no habit-streak visualization",
        "no time-block template variety",
        "no weekly retrospective page",
        "no energy-level tracker",
        "no waiting-for / followups list",
    ],
    "health": [
        "no symptom severity scale (1-10 with descriptors)",
        "no trigger correlation tracker (food/stress/weather)",
        "no medication side-effect log",
        "no sleep quality correlation",
        "no diet / food sensitivity correlation",
        "no weather / barometric pressure log",
        "no stress level tracker",
        "no menstrual cycle correlation",
        "no doctor appointment prep section",
        "no lab results history with notes",
        "no flare-frequency analytics / monthly summary",
        "no supplement / treatment effectiveness log",
        "no symptom-body-map illustration page",
    ],
    "education": [
        "no spaced repetition schedule",
        "no Cornell-note layout",
        "no exam countdown / prep checklist",
        "no concept-map template",
        "no vocabulary deck section",
        "no question bank by chapter",
    ],
    "finance": [
        "no monthly budget vs actual report",
        "no debt payoff progression chart",
        "no net-worth tracker",
        "no recurring subscription audit",
        "no investment allocation pie",
        "no emergency fund progress bar",
    ],
    "craft": [
        "no ingredient/materials cost tracker per batch",
        "no batch yield / scaling formula",
        "no cure-time / drying-time log",
        "no shelf-life tracking",
        "no pH / safety testing record",
        "no fragrance/color ratio calculator",
        "no supplier / sourcing log with prices",
        "no business pricing / margin calculator",
        "no labeling / FDA / regulation reference",
        "no finished-product photo slot per entry",
        "no skill progression checklist",
        "no inspiration / mood-board section",
        "no troubleshooting / failed-batch log",
    ],
    "gaming": [
        "no character progression sheet",
        "no campaign timeline / world log",
        "no NPC/encounter database",
        "no loot/inventory tracker",
        "no session debrief template",
        "no quest objective hierarchy",
    ],
    "kids": [
        "no age-appropriate difficulty progression",
        "no reward/sticker system",
        "no parent guidance notes",
        "no learning milestone checklist",
    ],
    "travel": [
        "no packing checklist by trip type",
        "no expense tracker per destination",
        "no border/visa reference",
        "no language phrase reference",
        "no photo memory slot per location",
        "no rating system per stop",
    ],
    "default": [
        "no premium typography choices",
        "no color-coded section system",
        "no monthly retrospective pages",
        "no goal-tracking visualization",
        "no quote / inspiration library",
    ],
}


def get_expert_features(theme_name: str) -> List[str]:
    """Returns the expert features list for a theme (with default fallback)."""
    return NICHE_EXPERT_FEATURES.get(theme_name, NICHE_EXPERT_FEATURES["default"])


def _draw_calendar_grid(c, cx, cy, r):
    """3×3 grid representing a calendar/planner."""
    cell = r * 0.42
    gap  = r * 0.06
    for row in range(3):
        for col in range(3):
            x = cx - cell * 1.5 + col * (cell + gap)
            y = cy + cell * 1.5 - (row + 1) * (cell + gap)
            c.rect(x, y, cell, cell, fill=1, stroke=0)


def _draw_heart_pulse(c, cx, cy, r):
    """Heart with pulse line — for health/wellness niches."""
    import math
    # Heart shape via two circles + triangle
    rad = r * 0.45
    c.circle(cx - rad * 0.55, cy + rad * 0.20, rad, fill=1, stroke=0)
    c.circle(cx + rad * 0.55, cy + rad * 0.20, rad, fill=1, stroke=0)
    p = c.beginPath()
    p.moveTo(cx - rad * 1.30, cy + rad * 0.20)
    p.lineTo(cx,              cy - rad * 1.20)
    p.lineTo(cx + rad * 1.30, cy + rad * 0.20)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _draw_book_open(c, cx, cy, r):
    """Open book — for education niches."""
    # Two rounded rectangles meeting at center (book pages)
    page_w = r * 0.95
    page_h = r * 1.10
    gap    = r * 0.04
    c.rect(cx - page_w - gap/2, cy - page_h/2, page_w, page_h, fill=1, stroke=0)
    c.rect(cx + gap/2,           cy - page_h/2, page_w, page_h, fill=1, stroke=0)
    # Lines on each page (subtle, in container background)
    c.setStrokeColor((1, 1, 1, 0.4))
    c.setLineWidth(r * 0.04)
    for i in range(3):
        y = cy + page_h * 0.35 - i * page_h * 0.30
        c.line(cx - page_w * 0.95, y, cx - page_w * 0.10, y)
        c.line(cx + page_w * 0.10, y, cx + page_w * 0.95, y)


def _draw_dollar_coin(c, cx, cy, r):
    """Dollar-coin emblem — finance niches."""
    c.circle(cx, cy, r * 0.95, fill=1, stroke=0)
    # Inner ring
    c.setStrokeColor((1, 1, 1, 0.9))
    c.setLineWidth(r * 0.08)
    c.circle(cx, cy, r * 0.70, fill=0, stroke=1)


def _draw_palette_swatch(c, cx, cy, r):
    """4 paint dots — craft niches."""
    s = r * 0.55
    c.circle(cx - s, cy + s/2, r * 0.42, fill=1, stroke=0)
    c.circle(cx + s, cy + s/2, r * 0.42, fill=1, stroke=0)
    c.circle(cx - s, cy - s/2, r * 0.42, fill=1, stroke=0)
    c.circle(cx + s, cy - s/2, r * 0.42, fill=1, stroke=0)


def _draw_controller_dpad(c, cx, cy, r):
    """Plus-shaped d-pad — gaming."""
    bar = r * 0.30
    arm = r * 0.95
    c.rect(cx - arm/2, cy - bar/2, arm, bar, fill=1, stroke=0)
    c.rect(cx - bar/2, cy - arm/2, bar, arm, fill=1, stroke=0)


def _draw_balloon(c, cx, cy, r):
    """Balloon with star — kids."""
    c.circle(cx, cy + r * 0.25, r * 0.75, fill=1, stroke=0)
    # String
    c.setStrokeColor(c._fillColorObj)
    c.setLineWidth(r * 0.08)
    c.line(cx, cy - r * 0.50, cx, cy - r * 1.10)


def _draw_compass(c, cx, cy, r):
    """Compass arrow — travel."""
    p = c.beginPath()
    p.moveTo(cx,            cy + r * 0.95)
    p.lineTo(cx + r * 0.25, cy)
    p.lineTo(cx,            cy - r * 0.95)
    p.lineTo(cx - r * 0.25, cy)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


_THEME_DRAWERS = {
    "music":     _draw_music_note,
    "nature":    _draw_leaf,
    "stars":     _draw_circle_sun,
    "geometry":  _draw_diamond,
    "ocean":     _draw_wave,
    "animals":   _draw_paw,
    "food":      _draw_leaf,
    "fitness":   _draw_dumbbell,
    "vintage":   _draw_ornament_flourish,
    "wellness":  _draw_leaf,
    "horror":    _draw_star,
    "planner":   _draw_calendar_grid,
    "health":    _draw_heart_pulse,
    "education": _draw_book_open,
    "finance":   _draw_dollar_coin,
    "craft":     _draw_palette_swatch,
    "gaming":    _draw_controller_dpad,
    "kids":      _draw_balloon,
    "travel":    _draw_compass,
    "default":   _draw_star,
}
