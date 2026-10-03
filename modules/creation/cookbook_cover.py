"""
Commercial FRONT-cover renderer for HIGH-CONTENT books (cookbooks / guides).

Low-content books (journals, coloring) keep the elegant `compose_cover` look.
High-content books need a *purely commercial* cover that mirrors the best-selling
Amazon cookbooks: a full-bleed food photo, a GIANT bold title, a round "N Recipes"
badge, a benefit ribbon, an audience eyebrow ("For Beginners"), and a "Full Color"
tag. This module builds that front image; the existing pipeline still handles the
print wrap (spine + back) by receiving this as a pre-rendered front.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

_SUP = "/System/Library/Fonts/Supplemental/"
# Heavy display fonts for the commercial look (with graceful fallbacks).
_HEAVY = [_SUP + "Arial Black.ttf", _SUP + "Impact.ttf",
          "/System/Library/Fonts/Helvetica.ttc",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_COND = [_SUP + "DIN Condensed Bold.ttf", _SUP + "Impact.ttf"] + _HEAVY
_BOLD = [_SUP + "Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_REG = [_SUP + "Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

# Warm, appetizing accent palette (cookbook-standard).
_RED = (193, 39, 45)
_GOLD = (240, 190, 70)
_CREAM = (252, 248, 240)
_INK = (28, 28, 30)


def _font(paths: List[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


_ROUND = ["/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"] + _HEAVY


def _tw(draw, text, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _th(draw, text, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return b[3] - b[1]


def _wrap_lines(draw, text, font, max_w) -> List[str]:
    """Greedy word-wrap into lines that each fit max_w."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _tw(draw, trial, font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_wrapped(draw, text, paths, max_w, max_lines, start, min_size=24):
    """Shrink the font until the title wraps into <= max_lines lines that all fit."""
    size = start
    while size > min_size:
        f = _font(paths, size)
        lines = _wrap_lines(draw, text, f, max_w)
        if len(lines) <= max_lines and all(_tw(draw, ln, f) <= max_w for ln in lines):
            return f, lines
        size -= 3
    f = _font(paths, min_size)
    return f, _wrap_lines(draw, text, f, max_w)


def _fit_font(draw, text, paths, max_w, start, min_size=24) -> ImageFont.FreeTypeFont:
    size = start
    while size > min_size:
        f = _font(paths, size)
        if _tw(draw, text, f) <= max_w:
            return f
        size -= 4
    return _font(paths, min_size)


def _center(draw, text, font, cx, y, fill, shadow=(0, 0, 0, 170), letter=0):
    """Draw centered text with a soft shadow for legibility over photos."""
    if letter:
        # crude letter-spacing
        total = sum(_tw(draw, ch, font) + letter for ch in text) - letter
        x = cx - total // 2
        for ch in text:
            if shadow:
                draw.text((x + 3, y + 3), ch, font=font, fill=shadow)
            draw.text((x, y), ch, font=font, fill=fill)
            x += _tw(draw, ch, font) + letter
        return
    w = _tw(draw, text, font)
    x = cx - w // 2
    if shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _gradient(w, h, top_alpha, bottom_alpha) -> Image.Image:
    """Vertical black gradient (RGBA) — top_alpha at y=0 → bottom_alpha at y=h."""
    grad = Image.new("L", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        grad.putpixel((0, y), int(top_alpha + (bottom_alpha - top_alpha) * t))
    alpha = grad.resize((w, h))
    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    black.putalpha(alpha)
    return black


def _starburst(size: int, fill, points: int = 20) -> Image.Image:
    """A round seal/starburst badge (RGBA) for the recipe count."""
    import math
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = cy = size / 2
    r_out, r_in = size / 2 - 2, size / 2 * 0.86
    pts = []
    for i in range(points * 2):
        ang = math.pi * i / points
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d.polygon(pts, fill=fill)
    d.ellipse([size * 0.11, size * 0.11, size * 0.89, size * 0.89],
              fill=fill, outline=(255, 255, 255, 255), width=max(3, size // 60))
    return im


# ── Title parsing ─────────────────────────────────────────────────────────────
_ANCHORS = [("cookbook", "COOKBOOK"), ("recipe book", "COOKBOOK"),
            ("recipes", "RECIPES"), ("cooking", "COOKBOOK"),
            ("handbook", "HANDBOOK"), ("guide", "GUIDE")]
_AUDIENCE_RE = re.compile(r"\bfor (beginners|seniors|two|one|men|women|kids|"
                          r"teens|busy .+?|the .+?)$", re.I)


def _title_parts(listing: Dict) -> Dict:
    """Split the listing title into commercial cover pieces."""
    title = (listing.get("title") or listing.get("niche") or "").strip()
    low = title.lower()

    eyebrow = ""
    m = _AUDIENCE_RE.search(title)
    if m:
        eyebrow = "FOR " + m.group(1).upper()
        title = title[:m.start()].strip(" -–—")
        low = title.lower()

    anchor_disp = ""
    pre = title
    for key, disp in _ANCHORS:
        idx = low.find(key)
        if idx != -1:
            pre = title[:idx].strip(" -–—")
            anchor_disp = disp
            break

    pre = pre or title
    words = pre.split()
    # split the pre-anchor words into 1-2 CHARACTER-balanced big lines
    if len(words) <= 1:
        big_lines = [pre.upper()] if pre else []
    else:
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            score = abs(len(a) - len(b))
            if best is None or score < best[0]:
                best = (score, [a.upper(), b.upper()])
        big_lines = best[1]
    if anchor_disp:
        big_lines.append(anchor_disp)
    return {"eyebrow": eyebrow, "big_lines": [l for l in big_lines if l]}


def _derive_badges(listing: Dict) -> Dict:
    """Coherent, truthful badges from the listing."""
    n = int(listing.get("recipe_count") or 0)
    is_cook = listing.get("product_type") == "recipe_book"
    count_txt = ""
    if is_cook and n >= 10:
        count_txt = f"{n}\nRECIPES"
    elif is_cook:
        count_txt = "EASY\nRECIPES"
    # benefit ribbon from niche keywords
    niche = (listing.get("niche") or "").lower()
    bits = []
    for kw, label in (("high protein", "High-Protein"), ("air fryer", "Air Fryer"),
                      ("low carb", "Low-Carb"), ("keto", "Keto"),
                      ("diabetic", "Diabetic-Friendly"), ("beginner", "Beginner-Friendly"),
                      ("low sodium", "Low-Sodium"), ("osteoporosis", "Bone-Healthy")):
        if kw in niche:
            bits.append(label)
    if not bits:
        bits = ["Quick", "Easy", "Delicious"]
    ribbon = "  ·  ".join(bits[:3]) if is_cook else ""
    return {"count": count_txt, "corner": "FULL COLOR EDITION", "ribbon": ribbon}


_KID_NAVY = (33, 52, 74)
_KID_BLUE = (46, 134, 222)
_KID_ORANGE = (240, 140, 30)


def _kids_badge_count(listing: Dict) -> str:
    f = listing.get("_facts") or {}
    n = sum(len(s.get("facts", [])) for s in f.get("sections", [])) if f else 0
    if not n:
        n = int(listing.get("facts_section_count", 0) or 0) * 12
    return f"{(n // 10) * 10}+\nFUN FACTS" if n >= 20 else "FUN\nFACTS"


def render_kids_front(art: Image.Image, listing: Dict,
                      front_w: int, front_h: int) -> Image.Image:
    """A PLAYFUL children's-book FRONT cover: full illustration + a rounded title
    panel (title always WRAPS to fit, never cut) + a fun 'N Fun Facts' star badge."""
    W, H = int(front_w), int(front_h)
    base = ImageOps.fit(art.convert("RGB"), (W, H), method=Image.LANCZOS,
                        centering=(0.5, 0.5)).convert("RGBA")
    d = ImageDraw.Draw(base)
    cx = W // 2
    margin = int(W * 0.055)
    pad = int(W * 0.05)
    inner_w = W - 2 * margin - 2 * pad

    title = (listing.get("title") or listing.get("niche") or "").strip().upper()
    subtitle = re.sub(r"\s+", " ", (listing.get("subtitle") or "").strip())[:72]

    tf, tlines = _fit_wrapped(d, title, _ROUND, inner_w, 3, int(H * 0.060), int(H * 0.030))
    lh = _th(d, "AgGjy", tf) + int(H * 0.008)
    ef = _font(_ROUND, int(H * 0.024))
    eb_h = int(H * 0.045)
    sub_f = None
    sub_lines: List[str] = []
    if subtitle:
        sub_f, sub_lines = _fit_wrapped(d, subtitle, _HEAVY, inner_w, 2,
                                        int(H * 0.026), int(H * 0.017))
    slh = (_th(d, "AgGjy", sub_f) + int(H * 0.005)) if sub_f else 0
    inner_h = eb_h + len(tlines) * lh + (int(H * 0.010) + len(sub_lines) * slh) + 2 * pad

    # Rounded cream panel at the top (guarantees legibility + a place for the title)
    panel_top = int(H * 0.04)
    panel = Image.new("RGBA", (W - 2 * margin, inner_h), (0, 0, 0, 0))
    pdrw = ImageDraw.Draw(panel)
    pdrw.rounded_rectangle([0, 0, W - 2 * margin - 1, inner_h - 1],
                           radius=int(H * 0.03), fill=(255, 252, 245, 236),
                           outline=(*_KID_BLUE, 255), width=max(4, W // 260))
    base.alpha_composite(panel, (margin, panel_top))
    d = ImageDraw.Draw(base)

    y = panel_top + pad
    _center(d, "FOR CURIOUS KIDS", ef, cx, y, _KID_ORANGE, shadow=None, letter=int(W * 0.008))
    y += eb_h
    for ln in tlines:
        _center(d, ln, tf, cx, y, _KID_NAVY, shadow=None)
        y += lh
    if sub_lines:
        y += int(H * 0.010)
        for ln in sub_lines:
            _center(d, ln, sub_f, cx, y, _KID_BLUE, shadow=None)
            y += slh

    # Fun star badge (bottom-right, kid blue) with the fact count
    badge = _kids_badge_count(listing)
    bs = int(W * 0.30)
    seal = _starburst(bs, (*_KID_BLUE, 255), points=16)
    sx, sy = W - bs - int(W * 0.04), int(H * 0.63)
    base.alpha_composite(seal, (sx, sy))
    d = ImageDraw.Draw(base)
    bl = badge.split("\n")
    bf_big = _font(_ROUND, int(bs * 0.30))
    bf_sm = _font(_ROUND, int(bs * 0.15))
    cxb = sx + bs // 2
    _center(d, bl[0], bf_big, cxb, sy + int(bs * 0.22), _CREAM, shadow=None)
    if len(bl) > 1:
        _center(d, bl[1], bf_sm, cxb, sy + int(bs * 0.58), _CREAM, shadow=None)

    # Bottom tags + publisher on a soft strip
    strip_h = int(H * 0.11)
    base.alpha_composite(_gradient(W, strip_h, 0, 180), (0, H - strip_h))
    d = ImageDraw.Draw(base)
    cf = _font(_ROUND, int(H * 0.020))
    _center(d, "FULL COLOR EDITION", cf, cx, int(H * 0.90), (255, 240, 180), letter=int(W * 0.004))
    author = (listing.get("author") or listing.get("publisher_name") or "").strip()
    if author:
        af = _font(_ROUND, int(H * 0.024))
        _center(d, author.upper(), af, cx, int(H * 0.945), (255, 255, 255), letter=int(W * 0.005))
    return base.convert("RGB")


def render_cookbook_front(art: Image.Image, listing: Dict,
                          front_w: int, front_h: int) -> Image.Image:
    """Compose a commercial cookbook/guide FRONT cover image."""
    W, H = int(front_w), int(front_h)
    base = ImageOps.fit(art.convert("RGB"), (W, H), method=Image.LANCZOS,
                        centering=(0.5, 0.42)).convert("RGBA")

    # Legibility gradients: strong at top (title) + bottom (subtitle/author).
    top_h = int(H * 0.52)
    base.alpha_composite(_gradient(W, top_h, 210, 0), (0, 0))
    bot_h = int(H * 0.30)
    base.alpha_composite(_gradient(W, bot_h, 0, 205), (0, H - bot_h))

    d = ImageDraw.Draw(base)
    cx = W // 2
    margin = int(W * 0.08)
    max_tw = W - 2 * margin

    parts = _title_parts(listing)
    badges = _derive_badges(listing)

    y = int(H * 0.045)
    # Eyebrow (audience) — gold, letter-spaced
    if parts["eyebrow"]:
        ef = _font(_BOLD, int(H * 0.024))
        _center(d, parts["eyebrow"], ef, cx, y, _GOLD, letter=int(W * 0.010))
        y += int(H * 0.045)
    else:
        y += int(H * 0.015)

    # GIANT title lines — compact block in the top zone (no collisions).
    big = parts["big_lines"]
    reg_size = int(H * 0.066)
    anc_size = int(H * 0.082)
    for i, line in enumerate(big):
        is_anchor = (i == len(big) - 1 and line in ("COOKBOOK", "GUIDE", "HANDBOOK", "RECIPES"))
        start_size = anc_size if is_anchor else reg_size
        f = _fit_font(d, line, _HEAVY, max_tw, start_size, min_size=int(H * 0.040))
        lh = _th(d, line, f)
        if is_anchor:
            y += int(H * 0.020)   # clearance so the band never clips the line above
            bw = _tw(d, line, f) + int(W * 0.05)
            bx0, bx1 = cx - bw // 2, cx + bw // 2
            d.rectangle([bx0, y - int(lh * 0.22), bx1, y + lh + int(lh * 0.40)], fill=_RED)
            _center(d, line, f, cx, y, _CREAM, shadow=None)
            y += lh + int(H * 0.030)
        else:
            _center(d, line, f, cx, y, (255, 255, 255))
            y += lh + int(H * 0.012)

    # Subtitle (from listing.subtitle) — wraps to <=2 lines, never clipped.
    sub = (listing.get("subtitle") or "").strip()
    sub = re.sub(r"\s+", " ", sub)
    if sub:
        y += int(H * 0.012)
        sf, slines = _fit_wrapped(d, sub, _BOLD, max_tw, 2,
                                  int(H * 0.028), int(H * 0.016))
        slh = _th(d, "AgGjy", sf) + int(H * 0.006)
        for ln in slines:
            _center(d, ln, sf, cx, y, _GOLD)
            y += slh

    # Recipe-count starburst badge — mid-RIGHT over the food, below the title.
    if badges["count"]:
        bs = int(W * 0.27)
        seal = _starburst(bs, (_RED[0], _RED[1], _RED[2], 255))
        sx, sy = W - bs - int(W * 0.05), int(H * 0.52)
        base.alpha_composite(seal, (sx, sy))
        d = ImageDraw.Draw(base)
        lines = badges["count"].split("\n")
        bf_big = _font(_HEAVY, int(bs * 0.42))
        bf_sm = _font(_BOLD, int(bs * 0.17))
        cxb = sx + bs // 2
        if len(lines) == 2:
            _center(d, lines[0], bf_big, cxb, sy + int(bs * 0.20), _CREAM, shadow=None)
            _center(d, lines[1], bf_sm, cxb, sy + int(bs * 0.60), _CREAM, shadow=None)
        else:
            _center(d, lines[0], bf_sm, cxb, sy + int(bs * 0.42), _CREAM, shadow=None)

    # Benefit ribbon (gold pill) near the bottom
    if badges["ribbon"]:
        rf = _font(_BOLD, int(H * 0.023))
        ph = int(H * 0.048)
        rw = _tw(d, badges["ribbon"], rf) + int(W * 0.07)
        ry = int(H * 0.815)
        pill = Image.new("RGBA", (rw, ph), (0, 0, 0, 0))
        pd = ImageDraw.Draw(pill)
        pd.rounded_rectangle([0, 0, rw - 1, ph - 1], radius=ph // 2, fill=_GOLD)
        base.alpha_composite(pill, (cx - rw // 2, ry))
        d = ImageDraw.Draw(base)
        _center(d, badges["ribbon"], rf, cx, ry + int(ph * 0.22), _INK, shadow=None)

    # "Full color" tag + author near the very bottom
    if badges["corner"]:
        cf = _font(_BOLD, int(H * 0.019))
        _center(d, badges["corner"], cf, cx, int(H * 0.878), _CREAM, letter=int(W * 0.004))

    author = (listing.get("author") or listing.get("publisher_name") or "").strip()
    if author:
        af = _font(_BOLD, int(H * 0.024))
        _center(d, author.upper(), af, cx, int(H * 0.93), (255, 255, 255), letter=int(W * 0.006))
    return base.convert("RGB")


# ── GUIDE (how-to) commercial front — niche-coloured, premium/minimal ─────────
# Category research (resin, gardening, DIY…): winners use the SUBJECT colour
# (teal/gold for resin, green for garden, red for fitness) — never a cookbook
# red — a huge high-contrast title, a "FOR BEGINNERS" eyebrow, and a slim
# benefit ribbon (Full Color · Step-by-Step · Troubleshooting).
_THEME_COVER = {
    "craft":    ((14, 110, 110), (214, 162, 56)),
    "ocean":    ((20, 108, 142), (214, 162, 56)),
    "nature":   ((45, 106, 79),  (214, 162, 56)),
    "food":     ((178, 58, 46),  (214, 162, 56)),
    "fitness":  ((192, 57, 43),  (44, 62, 80)),
    "wellness": ((78, 128, 105), (214, 162, 56)),
    "vintage":  ((123, 94, 59),  (201, 166, 107)),
    "stars":    ((59, 58, 107),  (180, 150, 220)),
    "business": ((31, 78, 121),  (214, 162, 56)),
    "geometry": ((44, 62, 80),   (93, 138, 168)),
    "religion":  ((123, 63, 46),  (214, 162, 56)),
    "education": ((31, 92, 139),  (214, 162, 56)),
    "stories":   ((74, 59, 46),   (201, 166, 107)),
    "default":  ((26, 58, 92),   (214, 162, 56)),
}


def _guide_palette(niche: str):
    try:
        from modules.creation.niche_themes import detect_theme
        t = detect_theme(niche or "").get("name", "default")
    except Exception:
        t = "default"
    return _THEME_COVER.get(t, _THEME_COVER["default"])


def render_guide_front(art: Image.Image, listing: Dict,
                       front_w: int, front_h: int,
                       accent_override: Optional[Tuple] = None,
                       band_override: Optional[Tuple] = None) -> Image.Image:
    """Premium/minimal commercial FRONT for how-to GUIDES (niche-coloured).
    accent_override lets a competitor cover-brief drive the accent (anchor pill);
    band_override sets the deep title-banner colour (brief palette[0], e.g. walnut).
    The whole title + subtitle sit on ONE high-contrast dark banner so the cover
    stays razor-legible at thumbnail size — the brief's #1 rule."""
    W, H = int(front_w), int(front_h)
    base = ImageOps.fit(art.convert("RGB"), (W, H), method=Image.LANCZOS,
                        centering=(0.5, 0.42)).convert("RGBA")
    accent, gold = _guide_palette(listing.get("niche", ""))
    if accent_override:
        accent = tuple(accent_override)
    # deep story colour behind the title (warm near-black fallback if no brief)
    dark = tuple(band_override) if band_override else (32, 25, 18)

    base.alpha_composite(_gradient(W, int(H * 0.50), 200, 0), (0, 0))
    base.alpha_composite(_gradient(W, int(H * 0.34), 0, 200), (0, H - int(H * 0.34)))
    d = ImageDraw.Draw(base)
    cx = W // 2
    margin = int(W * 0.08)
    max_tw = W - 2 * margin
    parts = _title_parts(listing)

    y = int(H * 0.05)
    # eyebrow (audience) — gold, letter-spaced (stays above the banner)
    eyebrow = parts["eyebrow"] or "FOR BEGINNERS"
    ef = _font(_BOLD, int(H * 0.024))
    _center(d, eyebrow, ef, cx, y, gold, letter=int(W * 0.010))
    y += int(H * 0.052)

    # ── Pre-measure the title lines + subtitle so the dark banner fits them ──
    reg_size = int(H * 0.070)
    anc_size = int(H * 0.080)
    tlines = []   # (line, font, is_anchor, line_height)
    for i, line in enumerate(parts["big_lines"]):
        is_anchor = (i == len(parts["big_lines"]) - 1 and
                     line in ("GUIDE", "HANDBOOK", "MANUAL", "BIBLE", "COOKBOOK"))
        if is_anchor:
            f = _fit_font(d, line, _HEAVY, int(max_tw * 0.92), anc_size,
                          min_size=int(H * 0.045))
        else:
            f = _fit_font(d, line, _HEAVY, max_tw, reg_size, min_size=int(H * 0.042))
        tlines.append((line, f, is_anchor, _th(d, line, f)))
    sub = re.sub(r"\s+", " ", (listing.get("subtitle") or "").strip())
    sf, slines = (None, [])
    if sub:
        sf, slines = _fit_wrapped(d, sub, _BOLD, max_tw, 2,
                                  int(H * 0.026), int(H * 0.016))
    slh = (_th(d, "AgGjy", sf) + int(H * 0.006)) if sf else 0

    # dry-run the vertical extent the title block will occupy
    y0 = y
    yy = y0
    for (line, f, is_anchor, lh) in tlines:
        yy += lh + int(H * 0.012)
    sub_gap = int(H * 0.034)   # breathing room between title block and subtitle
    if slines:
        yy += sub_gap + slh * len(slines)
    banner_top = y0 - int(H * 0.024)
    banner_bot = yy + int(H * 0.012)
    bx = int(margin * 0.45)
    band = Image.new("RGBA", (W - 2 * bx, banner_bot - banner_top), (0, 0, 0, 0))
    ImageDraw.Draw(band).rounded_rectangle(
        [0, 0, W - 2 * bx - 1, banner_bot - banner_top - 1],
        radius=int(H * 0.024), fill=(*dark, 180))
    base.alpha_composite(band, (bx, banner_top))
    d = ImageDraw.Draw(base)

    # ── Draw the GIANT title on the banner (cream), anchor word in ACCENT pill ──
    y = y0
    for (line, f, is_anchor, lh) in tlines:
        if is_anchor:
            # anchor word in the accent colour (text only — no box), so it still
            # carries the warm accent without a hard coloured rectangle.
            _center(d, line, f, cx, y, accent, shadow=None)
            y += lh + int(H * 0.012)
        else:
            _center(d, line, f, cx, y, _CREAM, shadow=None)
            y += lh + int(H * 0.012)

    # subtitle — cream on the dark banner (fully legible, no busy art behind it)
    if slines:
        y += sub_gap
        for ln in slines:
            _center(d, ln, sf, cx, y, _CREAM, shadow=None)
            y += slh

    # benefit ribbon near the bottom — sober walnut bar, cream text (premium)
    ribbon = "Full Color   ·   Step-by-Step   ·   Troubleshooting"
    rf = _font(_BOLD, int(H * 0.020))
    ph = int(H * 0.046)
    rw = _tw(d, ribbon, rf) + int(W * 0.06)
    ry = int(H * 0.855)
    pill = Image.new("RGBA", (rw, ph), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle([0, 0, rw - 1, ph - 1],
                                           radius=ph // 2, fill=(*dark, 236))
    base.alpha_composite(pill, (cx - rw // 2, ry))
    d = ImageDraw.Draw(base)
    _center(d, ribbon, rf, cx, ry + int(ph * 0.24), _CREAM, shadow=None)

    author = (listing.get("author") or listing.get("publisher_name") or "").strip()
    if author:
        af = _font(_BOLD, int(H * 0.024))
        _center(d, author.upper(), af, cx, int(H * 0.93), (255, 255, 255),
                letter=int(W * 0.006))
    return base.convert("RGB")


# ── BOTANICAL / EDITORIAL front (gardening & nature guides) ───────────────────
# Beats the category's best-sellers (Wylie / Hallowell / Nones): a calm CREAM
# canvas, one clean framed subject photo, an elegant green SERIF title, an inset
# editorial border and a small botanical divider — premium, airy, minimal.
_SERIF      = [_SUP + "Baskerville.ttc", _SUP + "Georgia.ttf",
               "/System/Library/Fonts/Times.ttc"]
_SERIF_BOLD = [_SUP + "Georgia Bold.ttf", _SUP + "Baskerville.ttc"] + _REG
_PARCHMENT  = (244, 238, 222)
_GARDEN     = (43, 92, 58)
_EARTH      = (110, 92, 66)


def render_botanical_front(art: Image.Image, listing: Dict,
                           front_w: int, front_h: int) -> Image.Image:
    W, H = int(front_w), int(front_h)
    base = Image.new("RGB", (W, H), _PARCHMENT)
    d = ImageDraw.Draw(base)
    cx = W // 2
    margin = int(W * 0.085)
    max_tw = W - 2 * margin

    # inset editorial border (thin double rule)
    b = int(W * 0.045)
    d.rectangle([b, b, W - b, H - b], outline=_GARDEN, width=max(2, int(W * 0.004)))
    d.rectangle([b + int(W*0.012), b + int(W*0.012), W - b - int(W*0.012),
                 H - b - int(W*0.012)], outline=_GARDEN, width=max(1, int(W * 0.0015)))

    parts = _title_parts(listing)
    y = int(H * 0.085)
    # eyebrow (audience) — tracked green
    eye = (parts["eyebrow"] or "FOR BEGINNERS")
    ef = _font(_SERIF, int(H * 0.021))
    _center(d, eye.upper(), ef, cx, y, _GARDEN, shadow=None, letter=int(W * 0.014))
    y += int(H * 0.045)

    # elegant serif title (green), wrapped, generously spaced
    words_title = re.sub(r"\s+", " ", (listing.get("title") or "").strip())
    tf, tlines = _fit_wrapped(d, words_title, _SERIF_BOLD, max_tw, 3,
                              int(H * 0.058), int(H * 0.036))
    tlh = _th(d, "AgjY", tf) + int(H * 0.010)
    for ln in tlines:
        _center(d, ln, tf, cx, y, _GARDEN, shadow=None)
        y += tlh

    # small botanical divider — drawn (a thin rule with a centered diamond) so
    # it always renders crisply (glyphs like ❦ tofu-box in book serifs)
    y += int(H * 0.028)
    rule_w = int(W * 0.16)
    lw = max(1, int(W * 0.0016))
    d.line([cx - rule_w, y, cx - int(W * 0.014), y], fill=_EARTH, width=lw)
    d.line([cx + int(W * 0.014), y, cx + rule_w, y], fill=_EARTH, width=lw)
    _ds = int(W * 0.008)
    d.polygon([(cx, y - _ds), (cx + _ds, y), (cx, y + _ds), (cx - _ds, y)], fill=_GARDEN)
    y += int(H * 0.030)

    # subtitle — refined, earthy, italic-ish serif
    sub = re.sub(r"\s+", " ", (listing.get("subtitle") or "").strip())
    if sub:
        sf, slines = _fit_wrapped(d, sub, _SERIF, max_tw, 2,
                                  int(H * 0.026), int(H * 0.018))
        slh = _th(d, "AgjY", sf) + int(H * 0.006)
        for ln in slines:
            _center(d, ln, sf, cx, y, _EARTH, shadow=None)
            y += slh

    # clean framed subject photo in the lower half
    img_top = int(H * 0.50)
    img_bot = int(H * 0.905)
    iw = W - 2 * margin
    ih = img_bot - img_top
    photo = ImageOps.fit(art.convert("RGB"), (iw, ih), method=Image.LANCZOS,
                         centering=(0.5, 0.5))
    base.paste(photo, (margin, img_top))
    d = ImageDraw.Draw(base)
    d.rectangle([margin, img_top, margin + iw, img_top + ih],
                outline=_GARDEN, width=max(2, int(W * 0.004)))

    # author / publisher on the cream strip at the very bottom
    author = (listing.get("author") or listing.get("publisher_name") or "").strip()
    if author:
        af = _font(_SERIF, int(H * 0.022))
        _center(d, author.upper(), af, cx, int(H * 0.945), _GARDEN,
                shadow=None, letter=int(W * 0.008))
    return base.convert("RGB")


# ── BRIEF-DRIVEN front (low-content, competitor-informed, niche-aware) ─────────
# Consumes a cover_research brief (winning palette / background / art style /
# title treatment for the niche) and renders a pro cover: the generated art as
# the hero, the niche's winning colours, and a title font matching the brief.
def _hex(c, default=(20, 20, 20)):
    try:
        h = str(c).lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _lum(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _title_font_for(style: str, size: int):
    st = (style or "").lower()
    if "serif" in st or "classic" in st or "elegant" in st:
        return _font([_SUP + "Baskerville.ttc", _SUP + "Georgia Bold.ttf"], size)
    if "script" in st:
        return _font([_SUP + "SnellRoundhand.ttc", _SUP + "Baskerville.ttc"], size)
    return _font(_HEAVY, size)          # bold-sans / stencil / default


def render_brief_front(art: Image.Image, listing: Dict, front_w: int, front_h: int,
                       brief: Dict) -> Image.Image:
    """Competitor-informed front for ANY (low-content) book, driven by the brief."""
    W, H = int(front_w), int(front_h)
    brief = brief or {}
    pal = [_hex(c) for c in (brief.get("palette") or [])] or [(26, 30, 46), (40, 26, 78)]
    accent = _hex(brief.get("accent"), pal[-1] if pal else (201, 168, 76))
    bg_mode = (brief.get("background") or "photo").lower()
    tstyle = brief.get("title_style") or "bold-sans"
    cx = W // 2
    margin = int(W * 0.08)
    max_tw = W - 2 * margin
    parts = _title_parts(listing)

    if bg_mode in ("light", "cream"):
        # light editorial: pale ground + framed art + dark title
        ground = pal[-1] if _lum(pal[-1]) > 180 else (244, 238, 222)
        base = Image.new("RGB", (W, H), ground)
        d = ImageDraw.Draw(base)
        title_col = accent if _lum(accent) < 150 else (30, 30, 30)
        # framed hero art, lower 55%
        iw, ih = W - 2 * margin, int(H * 0.44)
        itop = int(H * 0.44)
        photo = ImageOps.fit(art.convert("RGB"), (iw, ih), method=Image.LANCZOS)
        base.paste(photo, (margin, itop))
        d.rectangle([margin, itop, margin + iw, itop + ih], outline=accent,
                    width=max(2, int(W * 0.004)))
        y = int(H * 0.09)
    else:
        # dark / photo: full-bleed art + gradient overlays, light title
        base = ImageOps.fit(art.convert("RGB"), (W, H), method=Image.LANCZOS,
                            centering=(0.5, 0.42)).convert("RGBA")
        if bg_mode == "dark":
            veil = Image.new("RGBA", (W, H), (*pal[0], 150))
            base.alpha_composite(veil)
        base.alpha_composite(_gradient(W, int(H * 0.42), 210, 0), (0, 0))
        base.alpha_composite(_gradient(W, int(H * 0.30), 0, 210), (0, H - int(H * 0.30)))
        base = base.convert("RGB")
        d = ImageDraw.Draw(base)
        title_col = accent if _lum(accent) > 150 else (255, 255, 255)
        y = int(H * 0.08)

    # eyebrow (audience) if any
    if parts.get("eyebrow"):
        ef = _font(_BOLD, int(H * 0.022))
        _center(d, parts["eyebrow"].upper(), ef, cx, y, title_col,
                shadow=None, letter=int(W * 0.012))
        y += int(H * 0.045)

    # title — niche's winning font style + colour
    ttext = re.sub(r"\s+", " ", (listing.get("title") or "").strip())
    # wrap with the brief's chosen title font
    def _wrap(txt, size):
        f = _title_font_for(tstyle, size)
        words, lines, cur = txt.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if _tw(d, t, f) <= max_tw or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        return f, lines
    tsize = int(H * 0.066)
    while tsize > int(H * 0.036):
        tfont, tlines = _wrap(ttext, tsize)
        if len(tlines) <= 3:
            break
        tsize -= int(H * 0.004)
    tlh = _th(d, "AgjY", tfont) + int(H * 0.008)
    for ln in tlines:
        _center(d, ln, tfont, cx, y, title_col,
                shadow=None if bg_mode in ("light", "cream") else (0, 0, 0, 150))
        y += tlh

    # subtitle
    sub = re.sub(r"\s+", " ", (listing.get("subtitle") or "").strip())
    if sub:
        y += int(H * 0.006)
        sf, slines = _fit_wrapped(d, sub, _BOLD, max_tw, 2, int(H * 0.024), int(H * 0.016))
        slh = _th(d, "AgjY", sf) + int(H * 0.005)
        for ln in slines:
            _center(d, ln, sf, cx, y, title_col,
                    shadow=None if bg_mode in ("light", "cream") else (0, 0, 0, 150))
            y += slh

    # author / publisher
    author = (listing.get("author") or listing.get("publisher_name") or "").strip()
    if author:
        af = _font(_SERIF if "serif" in (tstyle or "") else _BOLD, int(H * 0.022))
        _center(d, author.upper(), af, cx, int(H * 0.94), title_col,
                shadow=None if bg_mode in ("light", "cream") else (0, 0, 0, 150),
                letter=int(W * 0.006))
    return base.convert("RGB")


# ── ANECDOTES / TRUE-STORIES front (adult "encyclopedia of fascinating facts") ─
# Category codes (The Book of Incredible Information / Weird & Unusual Trivia):
# rich jewel-tone ground, ORNATE GOLD BORDER, elegant white serif title, a small
# teaser fact, gold ornaments — a premium leather-bound-reference look.
_JEWELS = {
    "stories":   (30, 42, 74),    # deep navy
    "religion":  (58, 30, 34),    # deep burgundy
    "education": (22, 54, 82),     # deep teal-blue
    "default":   (28, 46, 40),     # deep forest green
}


def render_anecdotes_front(art: Image.Image, listing: Dict,
                           front_w: int, front_h: int,
                           theme: str = "stories") -> Image.Image:
    W, H = int(front_w), int(front_h)
    ground = _JEWELS.get(theme, _JEWELS["default"])
    gold = (206, 170, 92)
    # jewel gradient background (slightly lighter centre → richer look)
    base = Image.new("RGB", (W, H), ground)
    d = ImageDraw.Draw(base)
    for y in range(H):
        t = abs(y - H * 0.42) / H
        f = 1.0 - min(t, 0.5) * 0.5
        d.line([(0, y), (W, y)], fill=tuple(int(c * (0.75 + 0.25 * f)) for c in ground))
    d = ImageDraw.Draw(base)
    # ornate double gold border + corner diamonds
    m = int(W * 0.05)
    d.rectangle([m, m, W - m, H - m], outline=gold, width=max(3, int(W * 0.006)))
    mi = m + int(W * 0.018)
    d.rectangle([mi, mi, W - mi, H - mi], outline=gold, width=max(1, int(W * 0.002)))
    ds = int(W * 0.012)
    for cxp, cyp in [(m, m), (W - m, m), (m, H - m), (W - m, H - m)]:
        d.polygon([(cxp, cyp - ds), (cxp + ds, cyp), (cxp, cyp + ds), (cxp - ds, cyp)], fill=gold)
    cx = W // 2
    max_tw = W - 2 * mi - int(W * 0.06)

    # "eyebrow" — a small gold lead-in, shrunk to fit inside the frame
    y = int(H * 0.14)
    eyebrow_txt = "A COLLECTION OF FASCINATING TRUE STORIES"
    esp = int(W * 0.003)
    es = int(H * 0.024)
    while es > int(H * 0.013):
        eyef = _font(_SERIF, es)
        ew = sum(_tw(d, ch, eyef) + esp for ch in eyebrow_txt) - esp
        if ew <= max_tw:
            break
        es -= 2
    _center(d, eyebrow_txt, eyef, cx, y, gold, shadow=None, letter=esp)
    y += int(H * 0.055)
    # gold rule
    d.line([cx - int(W * 0.22), y, cx + int(W * 0.22), y], fill=gold, width=max(1, int(W * 0.002)))
    y += int(H * 0.03)

    # TITLE — elegant white serif, large, centred
    ttext = re.sub(r"\s+", " ", (listing.get("title") or "").strip())
    tf, tlines = _fit_wrapped(d, ttext, _SERIF_BOLD, max_tw, 3, int(H * 0.060), int(H * 0.038))
    tlh = _th(d, "AgjY", tf) + int(H * 0.012)
    for ln in tlines:
        _center(d, ln, tf, cx, y, (250, 248, 242), shadow=None)
        y += tlh
    y += int(H * 0.01)
    d.line([cx - int(W * 0.22), y, cx + int(W * 0.22), y], fill=gold, width=max(1, int(W * 0.002)))
    y += int(H * 0.03)

    # subtitle (gold italic-ish serif)
    sub = re.sub(r"\s+", " ", (listing.get("subtitle") or "").strip())
    if sub:
        sf, slines = _fit_wrapped(d, sub, _SERIF, max_tw, 3, int(H * 0.026), int(H * 0.018))
        slh = _th(d, "AgjY", sf) + int(H * 0.006)
        for ln in slines:
            _center(d, ln, sf, cx, y, gold, shadow=None)
            y += slh

    # a small framed teaser image from the AI art (like the category's teaser box)
    try:
        iw = int(W * 0.42)
        ih = int(iw * 0.62)
        itop = int(H * 0.60)
        photo = ImageOps.fit(art.convert("RGB"), (iw, ih), method=Image.LANCZOS)
        base.paste(photo, (cx - iw // 2, itop))
        d = ImageDraw.Draw(base)
        d.rectangle([cx - iw // 2, itop, cx + iw // 2, itop + ih], outline=gold,
                    width=max(2, int(W * 0.003)))
    except Exception:
        pass

    # author / publisher
    author = (listing.get("author") or listing.get("publisher_name") or "").strip()
    if author:
        af = _font(_SERIF, int(H * 0.024))
        _center(d, author.upper(), af, cx, int(H * 0.90), (245, 240, 230),
                shadow=None, letter=int(W * 0.006))
    return base.convert("RGB")
