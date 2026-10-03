"""
Interior image generator for KDP paperback books.

Produces:
  - A set of 6 niche-themed B&W icons (1 API call → cropped into 6 PNGs)
  - 1 hero / decorative image for the welcome page

KEY CONSTRAINT: KDP paperback interiors are PRINTED in black & white by default.
Color interiors cost ~3x more to print. So all generated images target
high-contrast monochrome / grayscale aesthetics that look great in B&W.

Heavy caching: results are saved per niche in `output/interior_images/{slug}/`.
Subsequent books on the same niche reuse the cached set (cost = $0).
"""
import base64
import concurrent.futures
import hashlib
import io
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _niche_slug(niche: str) -> str:
    """URL-safe folder name for a niche."""
    import re
    s = re.sub(r"[^\w\s-]", "", (niche or "").lower()).strip()
    s = re.sub(r"\s+", "-", s)
    return s[:60] or "unknown"


def _cache_dir(base: Path, niche: str) -> Path:
    d = base / "interior_images" / _niche_slug(niche)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _icons_complete(cache: Path, n: int = 4) -> bool:
    """Returns True if all N cached illustration files exist."""
    return all((cache / f"illustration_{i}.png").exists() for i in range(n))


def _hero_complete(cache: Path) -> bool:
    return (cache / "hero.png").exists()


# ── OpenAI image generation ───────────────────────────────────────────────────

def _fetch_image_b64(client, prompt: str, size: str, quality: str = "high",
                     max_retries: int = 2) -> Optional[bytes]:
    """Calls gpt-image-2 → returns PNG bytes, or None on failure.
    Retries each model up to `max_retries` times before falling to next model.
    Universal across niches — works for any prompt content."""
    attempts = [
        ("gpt-image-2-2026-04-21", {"size": size, "quality": quality}),
        ("gpt-image-2",            {"size": size, "quality": quality}),
        ("gpt-image-1",            {"size": size, "quality": quality}),
        ("gpt-image-1-mini",       {"size": size, "quality": "medium"}),
    ]
    for model, kwargs in attempts:
        for attempt in range(max_retries):
            try:
                resp = client.images.generate(model=model, prompt=prompt[:4000], n=1, **kwargs)
                item = resp.data[0]
                if getattr(item, "b64_json", None):
                    data = base64.b64decode(item.b64_json)
                    # Validate: must be > 1KB to be a real image
                    if len(data) > 1000:
                        return data
                elif getattr(item, "url", None):
                    import requests
                    r = requests.get(item.url, timeout=30)
                    if r.status_code == 200 and len(r.content) > 1000:
                        return r.content
            except Exception as e:
                logger.debug(f"Image gen {model} attempt {attempt+1} failed: {e}")
                continue
    return None


# ── Niche icon set ────────────────────────────────────────────────────────────

# Distinct subject hints per theme — ensures 4 visually different illustrations
_ILLUSTRATION_SUBJECTS = {
    "horror":   ["a ghost or specter",  "an antique lantern",  "an ouija board",            "a haunted clock"],
    "nature":   ["a leafy branch",       "a single bloom",       "a mushroom or fern",       "a feather"],
    "music":    ["a vinyl record",       "a microphone",         "headphones",                "a sound wave"],
    "wellness": ["a sun and moon",       "a lotus flower",       "a candle",                  "a leafy branch"],
    "craft":    ["scissors and thread",  "a sewing notion",      "yarn balls",                "a paintbrush"],
    "fitness":  ["a dumbbell",           "a running shoe",       "a stopwatch",               "a water bottle"],
    "food":     ["a steaming cup",       "a wooden spoon",       "a bowl of ingredients",     "an herb sprig"],
    "stars":    ["a crescent moon",      "a constellation",      "a sun with rays",           "a comet"],
    "animals":  ["a single bird",        "a small mammal",       "a paw print",               "a feather"],
    "ocean":    ["a sea shell",          "a wave crest",         "a small fish",              "a coral"],
    "planner":  ["a calendar grid",      "a checkmark badge",    "an hourglass",              "a quill and ink"],
    "health":   ["a heart with leaves",  "a medicine bottle",    "a stethoscope",             "a wellness charm"],
    "education":["an open book",         "a graduation cap",     "a pencil and ruler",        "a globe"],
    "finance":  ["a coin stack",         "a piggy bank",         "a wallet",                  "a growth chart"],
    "gaming":   ["a game controller",    "a die",                "a wizard hat",              "a sword and shield"],
    "kids":     ["a balloon",            "a teddy bear",         "a paper airplane",          "a star sticker"],
    "travel":   ["a compass",            "a passport",           "a vintage suitcase",        "a paper map"],
    "vintage":  ["an antique key",       "a pocket watch",       "an ornate frame",           "a quill and inkwell"],
    "geometry": ["a hexagonal pattern",  "concentric circles",   "a diamond shape",           "a triangular motif"],
    "default":  ["a decorative emblem",  "a botanical sprig",    "an ornamental flourish",    "a star burst"],
}


def _suggest_subjects_via_claude(niche: str, anthropic_key: str) -> List[str]:
    """
    Asks Claude Haiku to suggest 4 niche-specific visual subjects.
    This makes the system universal — works for any niche, present or future.
    Returns [] if Claude fails (caller will fall back to theme defaults).
    """
    if not anthropic_key:
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
    except ImportError:
        return []

    prompt = f"""You are designing illustrations for a low-content KDP book in the niche: "{niche}".

Suggest 4 distinct visual subjects that perfectly represent this niche — things that, when illustrated in a clean black-and-white botanical-engraving style, would look beautiful in this specific book.

Rules:
- Each subject is a CONCRETE OBJECT or simple compound subject (e.g., "a vintage pocket watch" or "a hand holding a feather")
- 4 DIFFERENT subjects — diverse but all clearly tied to the niche
- Phrase each as a short noun phrase ("a X", "an X", "a X and Y") — exactly what an illustrator would draw
- No abstract concepts, no people's faces, no text or logos
- Specific enough to be drawable as a single illustration

For example:
  niche: "vintage soap making recipe journal"
  → ["a vintage soap bar with botanical herbs", "a lye jar and wooden mold", "a lavender bundle and pestle", "an apothecary scale"]

  niche: "90s hip hop trivia book"
  → ["a vintage boombox", "a vinyl record with sleeve", "a microphone with cord", "a snapback cap and chain"]

Return EXACTLY 4 subjects as a JSON array of strings:
["subject 1", "subject 2", "subject 3", "subject 4"]
No preamble, no explanation, just the JSON array."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown if present
        import re as _re
        raw = _re.sub(r"^```(?:json)?\s*", "", raw)
        raw = _re.sub(r"\s*```$", "", raw)
        import json as _json
        subjects = _json.loads(raw)
        if isinstance(subjects, list) and len(subjects) >= 4:
            return [str(s).strip() for s in subjects[:4] if isinstance(s, str) and s.strip()]
    except Exception as e:
        logger.debug(f"Claude subject suggestion failed: {e}")
    return []


def _load_or_suggest_subjects(
    niche: str,
    anthropic_key: Optional[str],
    cache: Path,
) -> List[str]:
    """
    Returns 4 illustration subjects, in priority order:
      1. Cached AI suggestion (already saved on disk per niche)
      2. Fresh AI suggestion from Claude (if anthropic_key provided)
      3. Theme-hardcoded subjects (fallback)
    """
    subjects_cache = cache / "subjects.json"

    # 1. Cache hit
    if subjects_cache.exists():
        try:
            import json as _json
            data = _json.loads(subjects_cache.read_text())
            if isinstance(data, list) and len(data) >= 4:
                return data[:4]
        except Exception:
            pass

    # 2. Ask Claude (universal — works for ANY niche)
    if anthropic_key:
        suggested = _suggest_subjects_via_claude(niche, anthropic_key)
        if len(suggested) >= 4:
            # Persist cache
            try:
                import json as _json
                subjects_cache.write_text(_json.dumps(suggested, ensure_ascii=False, indent=2))
            except Exception:
                pass
            return suggested

    # 3. Fallback to theme-based hardcoded
    try:
        from modules.creation.niche_themes import detect_theme
        theme = detect_theme(niche)
        return _ILLUSTRATION_SUBJECTS.get(theme["name"], _ILLUSTRATION_SUBJECTS["default"])
    except Exception:
        return _ILLUSTRATION_SUBJECTS["default"]


def _subjects_for_niche(niche: str, anthropic_key: Optional[str] = None,
                        cache: Optional[Path] = None) -> List[str]:
    """4 distinct illustration subjects — universal across all niches.
    Tries AI suggestion first, falls back to theme hardcoded."""
    if cache is not None:
        return _load_or_suggest_subjects(niche, anthropic_key, cache)
    # No cache provided → just use theme-based
    try:
        from modules.creation.niche_themes import detect_theme
        theme = detect_theme(niche)
        return _ILLUSTRATION_SUBJECTS.get(theme["name"], _ILLUSTRATION_SUBJECTS["default"])
    except Exception:
        return _ILLUSTRATION_SUBJECTS["default"]


_SINGLE_ILLUSTRATION_PROMPT = """Single black-and-white botanical-engraving style illustration for a book about "{niche}".
Subject: {subject}.

Style requirements (critical):
- Pure BLACK linework on PURE WHITE background — no gray fills, no shading, no color
- Centered subject with generous white space (will be placed in a small circle on a colored banner)
- Fine confident linework — vintage etching / botanical field-guide aesthetic
- Single coherent composition, not a collage
- High contrast — must print crisp at small sizes on uncoated paper
- No text, no captions, no borders, no signatures

Think old natural-history engraving — elegant, detailed, with breathing room."""


def _to_rgba_with_alpha(gray_img: Image.Image) -> Image.Image:
    """Converts a grayscale image to RGBA where:
        - Black pixels → fully opaque black
        - White pixels → fully transparent
    """
    from PIL import ImageMath
    alpha = ImageMath.eval("convert(255 - g, 'L')", g=gray_img.convert("L"))
    black = Image.new("L", gray_img.size, 0)
    return Image.merge("RGBA", (black, black, black, alpha))


def _trim_transparent(img: Image.Image, padding: int = 30) -> Image.Image:
    """Crops away transparent borders around an RGBA image."""
    try:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        bbox = img.getbbox()
        if not bbox:
            return img
        left, top, right, bot = bbox
        w, h = img.size
        return img.crop((
            max(0, left - padding),
            max(0, top  - padding),
            min(w, right + padding),
            min(h, bot  + padding),
        ))
    except Exception:
        return img


def generate_niche_icons(
    niche: str,
    openai_key: str,
    learning_dir: Path,
    status_cb=None,
    force_regenerate: bool = False,
    n_illustrations: int = 4,
    anthropic_key: Optional[str] = None,
) -> List[Path]:
    """
    Generates (or loads from cache) N niche-themed RGBA illustrations.
    Each illustration is a separate API call → distinct subject → no grid-cropping risk.
    White background becomes TRANSPARENT — black linework overlays any color cleanly.

    Subjects are AI-suggested per niche (universal) with theme-based fallback.

    Cost: 4 × $0.04 (image) + 1 × $0.001 (subject suggestion) = $0.16 per niche,
    then $0 thanks to cache.
    """
    cache = _cache_dir(learning_dir, niche)
    paths = [cache / f"illustration_{i}.png" for i in range(n_illustrations)]

    if all(p.exists() for p in paths) and not force_regenerate:
        if status_cb:
            status_cb(f"🖼️ {n_illustrations} illustrations en cache pour cette niche")
        return paths

    try:
        import openai
        client = openai.OpenAI(api_key=openai_key)
    except ImportError:
        return []

    # ── Universal subject suggestion: Claude > theme fallback ──────────
    if status_cb:
        status_cb(f"🧠 Demande à Claude les 4 meilleurs sujets visuels pour cette niche...")
    subjects = _subjects_for_niche(niche, anthropic_key, cache)
    if status_cb:
        status_cb(f"   ↳ Sujets choisis : {', '.join(s[:30] for s in subjects[:4])}")

    generated: List[Path] = []

    for i in range(n_illustrations):
        if paths[i].exists() and not force_regenerate:
            generated.append(paths[i])
            continue

        subject = subjects[i % len(subjects)]
        if status_cb:
            status_cb(f"🎨 Illustration {i+1}/{n_illustrations} : {subject}...")

        prompt = _SINGLE_ILLUSTRATION_PROMPT.format(niche=niche, subject=subject)
        png_bytes = _fetch_image_b64(client, prompt, size="1024x1024", quality="high")
        if not png_bytes:
            if status_cb:
                status_cb(f"   ⚠️ illustration {i+1} échouée — skip")
            continue

        try:
            gray = Image.open(io.BytesIO(png_bytes)).convert("L")
            # Threshold to crisp B&W (anything darker than 180 = ink)
            gray = gray.point(lambda v: 0 if v < 180 else 255)
            # Convert to RGBA with transparency
            rgba = _to_rgba_with_alpha(gray)
            rgba = _trim_transparent(rgba)
            rgba.save(paths[i], "PNG")
            generated.append(paths[i])
            if status_cb:
                status_cb(f"   ✅ illustration {i+1} sauvegardée (RGBA)")
        except Exception as e:
            logger.warning(f"Could not process illustration {i}: {e}")
            continue

    if status_cb:
        status_cb(f"✅ {len(generated)} illustrations B&W RGBA cachées")
    return generated


def _trim_white(img: Image.Image, threshold: int = 240, padding: int = 20) -> Image.Image:
    """Crops away mostly-white borders around an icon, leaves small padding."""
    try:
        gray = img.convert("L")
        w, h = gray.size
        pixels = gray.load()
        # Find bounding box of non-white content
        left, top, right, bot = w, h, 0, 0
        for y in range(h):
            for x in range(w):
                if pixels[x, y] < threshold:
                    left  = min(left,  x)
                    right = max(right, x)
                    top   = min(top,   y)
                    bot   = max(bot,   y)
        if right <= left or bot <= top:
            return img   # Empty cell — return original
        # Add padding
        left  = max(0, left - padding)
        top   = max(0, top  - padding)
        right = min(w, right + padding)
        bot   = min(h, bot  + padding)
        return img.crop((left, top, right, bot))
    except Exception:
        return img


# ── Hero image (decorative welcome page graphic) ──────────────────────────────

_HERO_PROMPT_TEMPLATE = """Decorative black-and-white illustration for the welcome page of a book about "{niche}".
A single, beautifully composed monochrome line-art illustration that evokes the niche's essence.

Style requirements:
- Pure BLACK on PURE WHITE background — no color, no gray fills
- Botanical / etching / antique field-guide aesthetic — fine confident linework
- Centered composition with breathing room — leaves space at top and bottom for text overlay
- Symmetrical or balanced — not chaotic
- Print-ready at high resolution — crisp lines that hold at small print sizes
- Cohesive with vintage book engraving style

No text, no captions, no borders, no signatures. Pure illustration."""


def generate_hero_image(
    niche: str,
    openai_key: str,
    learning_dir: Path,
    status_cb=None,
    force_regenerate: bool = False,
) -> Optional[Path]:
    """
    Generates (or loads from cache) a single B&W decorative hero image.
    Returns file path or None if generation fails.
    """
    cache = _cache_dir(learning_dir, niche)
    hero_path = cache / "hero.png"

    if hero_path.exists() and not force_regenerate:
        if status_cb:
            status_cb(f"🖼️ Hero image en cache")
        return hero_path

    if status_cb:
        status_cb(f"🎨 Génération de l'image hero B&W...")

    try:
        import openai
        client = openai.OpenAI(api_key=openai_key)
    except ImportError:
        return None

    prompt = _HERO_PROMPT_TEMPLATE.format(niche=niche)
    png_bytes = _fetch_image_b64(client, prompt, size="1024x1024", quality="high")
    if not png_bytes:
        if status_cb:
            status_cb("⚠️ Hero image échouée")
        return None

    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("L")
        img = img.point(lambda v: 0 if v < 200 else 255).convert("L")
        img.save(hero_path, "PNG")
    except Exception as e:
        logger.warning(f"Could not process hero: {e}")
        return None

    if status_cb:
        status_cb(f"✅ Hero image générée")
    return hero_path


# ── Coloring-book line art (full-page drawings to color) ──────────────────────

_COLORING_PROMPT_KIDS = """Black-and-white COLORING BOOK page for CHILDREN, themed "{niche}".
Subject to draw: {subject}.

Style requirements (critical for a printable kids coloring page):
- BOLD, THICK black outlines — at least 3pt stroke equivalent (~4-5 px at 1024×1536)
- All outlines uniform thickness so the page reproduces crisply at KDP print scale
- Simple, friendly shapes with LARGE open areas that are easy to color
- Minimal interior detail — clear, uncluttered, cheerful
- NO shading, NO gray, NO color fills, NO hatching — pure B&W outlines only
- A single full-page illustration, centered, filling most of the frame
- NO text, NO captions, NO borders, NO signature, NO watermark

Think classic children's coloring book — clean, cute, and inviting."""

_COLORING_PROMPT_ADULT = """Black-and-white COLORING BOOK page for ADULTS, themed "{niche}".
Subject to draw: {subject}.

Style requirements (critical for a printable adult coloring page):
- Detailed black LINE ART with CONFIDENT MEDIUM-WEIGHT outlines
  (main shapes ≥2.5pt stroke equivalent — never sub-pixel hairlines)
- Inner detail lines can be slightly finer but must stay ≥1.5pt to print cleanly
- Decorative mandala / zentangle patterns woven into and around the subject
- Balanced contrast between bold contour lines and fine interior detail
- NO shading, NO gray fills, NO color, NO solid-black areas — pure outline art
- A single full-page composition filling the frame edge to edge
- NO text, NO captions, NO borders, NO signature, NO watermark

Think premium adult relaxation coloring book — elegant, intricate but PRINTABLE."""


def _coloring_style_for_niche(niche: str) -> str:
    """Detects whether a coloring book targets kids (bold/simple) or adults (detailed)."""
    nl = (niche or "").lower()
    kids_markers = [
        "kid", "child", "toddler", "preschool", "kindergarten", "boys", "girls",
        "baby", "for children", "little", "ages 2", "ages 3", "ages 4", "ages 5",
        "ages 6", "ages 7", "ages 8", "first coloring", "easy coloring",
    ]
    adult_markers = [
        "adult", "mandala", "zentangle", "stress", "relax", "anti-stress",
        "grown", "intricate", "meditation", "mindful",
    ]
    if any(k in nl for k in kids_markers):
        return "kids"
    if any(k in nl for k in adult_markers):
        return "adult"
    return "adult"   # detailed default — safer/broader market for generic niches


def _generate_single_coloring(
    client, prompt: str, out_path: Path, idx: int, total: int,
    subject: str, log_lock, status_cb,
) -> Optional[Path]:
    """Worker: fetch one image, threshold to B&W, save. Returns path or None."""
    png_bytes = _fetch_image_b64(client, prompt, size="1024x1536",
                                 quality="high", max_retries=1)
    if not png_bytes:
        with log_lock:
            if status_cb:
                status_cb(f"  ⚠️ page {idx+1}/{total} échouée — skip")
        return None
    try:
        # Pro coloring practice: pure grayscale L mode, threshold to crisp B&W.
        # Avoids RGB→KDP-print muddy-line artifacts. Stays in L mode (not "1")
        # so ReportLab embeds it efficiently and KDP keeps line smoothness.
        img = Image.open(io.BytesIO(png_bytes)).convert("L")
        img = img.point(lambda v: 0 if v < 190 else 255)

        # Estimate line weight (mean stroke thickness in px) for a quick QA log
        try:
            lw = _estimate_line_weight(img)
            if lw and lw < 1.6:
                with log_lock:
                    if status_cb:
                        status_cb(
                            f"  ⚠️ page {idx+1}/{total} traits fins (~{lw:.1f}px) "
                            "— pourra paraître pâle à l'impression"
                        )
        except Exception:
            pass

        img.save(out_path, "PNG", optimize=True)
        with log_lock:
            if status_cb:
                status_cb(f"  ✅ page {idx+1}/{total} : {subject[:42]}")
        return out_path
    except Exception as e:
        logger.warning(f"Coloring page {idx} processing failed: {e}")
        return None


def _estimate_line_weight(img: Image.Image) -> float:
    """
    Rough estimate of average black-stroke thickness in pixels.
    Method: for each row, count runs of dark pixels and average their lengths.
    Returns 0 if no dark pixels found.

    Sub-2px lines tend to disappear at print scale on KDP cream/white paper.
    """
    small = img.resize((400, int(400 * img.size[1] / img.size[0])))
    px = small.load()
    w, h = small.size
    runs = []
    for y in range(0, h, 4):       # sample every 4th row to stay fast
        run = 0
        for x in range(w):
            if px[x, y] < 128:
                run += 1
            else:
                if 1 <= run <= 30:   # ignore huge fills
                    runs.append(run)
                run = 0
        if 1 <= run <= 30:
            runs.append(run)
    return (sum(runs) / len(runs)) if runs else 0.0


def generate_coloring_pages(
    niche: str,
    subjects: List[str],
    openai_key: str,
    learning_dir: Path,
    status_cb=None,
    n_pages: int = 25,
    force_regenerate: bool = False,
    max_workers: int = 5,
) -> List[Path]:
    """
    Generates (or loads from cache) N full-page coloring line-art illustrations
    using `max_workers` PARALLEL OpenAI calls. 25 images ÷ 5 workers ≈ 1-2 min
    instead of 25 × 12s sequential. Cached per niche → re-runs are free.
    """
    cache = _cache_dir(learning_dir, niche)
    style = _coloring_style_for_niche(niche)
    template = _COLORING_PROMPT_KIDS if style == "kids" else _COLORING_PROMPT_ADULT
    paths = [cache / f"coloring_{i}.png" for i in range(n_pages)]

    if all(p.exists() for p in paths) and not force_regenerate:
        if status_cb:
            status_cb(f"🖼️ {n_pages} pages de coloriage en cache (style: {style})")
        return paths

    try:
        import openai
        client = openai.OpenAI(api_key=openai_key)
    except ImportError:
        return []

    subs = [s for s in (subjects or []) if isinstance(s, str) and s.strip()]
    if not subs:
        subs = _subjects_for_niche(niche, None, cache)
    if not subs:
        subs = [f"a decorative {niche} motif"]

    # Build the work queue — only indexes that aren't already cached
    todo: List[Tuple[int, str, Path]] = []
    for i in range(n_pages):
        if paths[i].exists() and not force_regenerate:
            continue
        subject = subs[i % len(subs)]
        todo.append((i, subject, paths[i]))

    if status_cb:
        status_cb(
            f"🎨 Génération de {len(todo)} pages de coloriage en parallèle "
            f"(style: {style}, {max_workers} workers)..."
        )

    log_lock = threading.Lock()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {
            exe.submit(
                _generate_single_coloring,
                client,
                template.format(niche=niche, subject=subject),
                out_path, idx, n_pages, subject, log_lock, status_cb,
            ): idx
            for idx, subject, out_path in todo
        }
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.warning(f"Coloring future failed: {e}")

    # Collect everything that's on disk (cache + fresh)
    generated = [p for p in paths if p.exists()]
    if status_cb:
        status_cb(
            f"✅ {len(generated)}/{n_pages} pages de coloriage prêtes (cache)"
        )
    return generated


# ── Per-item images (recipes / facts / guide) — COLOR, niche-adapted ──────────
def _item_image_prompt(niche: str, kind: str, title: str) -> str:
    """Niche-appropriate prompt for ONE item image."""
    if kind == "recipe":
        return (f'Professional appetizing food photography of the finished dish "{title}". '
                f"Plated beautifully on a clean neutral surface, natural soft daylight, "
                f"45-degree or top-down angle, shallow depth of field, high detail, "
                f"realistic, magazine cookbook style. No text, no words, no watermark.")
    if kind == "facts":
        return (f'Cute, colorful, kid-friendly cartoon illustration about "{title}" for a '
                f"children's fun-facts book. Bright cheerful colors, simple clean "
                f"composition, friendly and educational. No text, no words, no watermark.")
    # guide / how_to
    return (f'Professional realistic instructional photograph showing "{title}" for a '
            f"practical how-to guide about {niche}. Real materials, tools and hands where "
            f"relevant, clean well-lit workspace, natural soft daylight, sharp focus, "
            f"high detail, magazine how-to / DIY tutorial style. Photographic, not an "
            f"illustration or cartoon. No text, no words, no watermark.")


def build_item_images(
    niche: str,
    items: List,
    kind: str,
    openai_key: str,
    learning_dir: Path,
    status_cb=None,
    quality: str = "medium",
    size: str = "1024x1024",
    max_images: int = 0,
) -> List[Optional[Path]]:
    """
    Generate ONE color image per content item (recipe / fact-section / chapter),
    adapted to the niche kind. Cached per (niche, kind, item title) → the SAME
    book regenerates for $0, and re-runs never repay for an existing image.

    Returns a list of Path|None aligned index-for-index with `items`.
    `max_images=0` means "one per item"; a positive value caps the count.
    """
    def s(m):
        if status_cb:
            status_cb(m)

    out: List[Optional[Path]] = [None] * len(items)
    if not openai_key or not items:
        return out

    import hashlib
    import openai
    client = openai.OpenAI(api_key=openai_key)
    cache = _cache_dir(learning_dir, niche) / "items"
    cache.mkdir(parents=True, exist_ok=True)

    n_target = len(items) if not max_images else min(len(items), max_images)
    made = cached = 0
    for i, it in enumerate(items):
        if i >= n_target:
            break
        title = (it.get("title") if isinstance(it, dict) else str(it)) or f"item {i+1}"
        h = hashlib.md5(f"{kind}|{title}".encode("utf-8")).hexdigest()[:16]
        fp = cache / f"{h}.png"
        if fp.exists():
            out[i] = fp
            cached += 1
            continue
        s(f"🖼️ Image {made + 1}/{n_target} : {title[:42]}...")
        data = _fetch_image_b64(client, _item_image_prompt(niche, kind, title),
                                size, quality)
        if data:
            try:
                fp.write_bytes(data)
                out[i] = fp
                made += 1
            except Exception as e:
                logger.debug(f"item image write failed: {e}")
    s(f"✅ Images intérieures : {made} générée(s) + {cached} en cache "
      f"({sum(1 for p in out if p)}/{n_target}) — régénération à 0 $")
    return out


# ── Master builder ────────────────────────────────────────────────────────────

def build_niche_image_assets(
    niche: str,
    openai_key: str,
    learning_dir: Path,
    status_cb=None,
    enabled: bool = True,
    anthropic_key: Optional[str] = None,
    listing: Optional[Dict] = None,
) -> Dict:
    """
    Returns a dict of asset paths for this niche:
      {
        "icons":          [Path, ...]   # up to 4 decorative illustrations
        "hero":           Path or None, # hero image for the welcome page
        "coloring_pages": [Path, ...]   # full-page line art (coloring books only)
        "enabled":        bool,
      }
    Caches aggressively — calling this twice for the same niche is essentially free.

    For coloring books (listing.product_type == "coloring"), generates 25 full-page
    line-art drawings using the section item titles as subjects.
    """
    out = {"icons": [], "hero": None, "coloring_pages": [], "enabled": enabled}
    if not enabled or not openai_key:
        return out

    product_type = (listing or {}).get("product_type", "")

    try:
        if product_type == "coloring":
            # Gather coloring subjects (illustration titles) from the listing items
            subjects: List[str] = []
            for sec in (listing or {}).get("content_sections", []):
                if sec.get("type") in ("content", "qa", "tracker"):
                    for it in sec.get("items", []):
                        if isinstance(it, str) and it.strip():
                            subjects.append(it.strip())
            # ── Dynamic page count based on listing.page_count ──────────
            # Layout: each drawing = 2 pages (drawing + intentional blank back)
            #   front matter ≈ 6 pages (welcome+how-to+section banner)
            #   back matter  ≈ 2 pages (closing+thank you)
            #   coloring drawings = (page_count − 8) / 2
            target_pages = int(listing.get("page_count", 56))
            n_coloring = max(15, min(80, (target_pages - 8) // 2))
            if status_cb:
                status_cb(
                    f"🖍️ Coloring : cible {target_pages}p → {n_coloring} dessins "
                    f"({n_coloring*2 + 8}p total estimé)"
                )
            out["coloring_pages"] = generate_coloring_pages(
                niche, subjects, openai_key, learning_dir, status_cb,
                n_pages=n_coloring,
            )
            # Propagate the actual count so listing.subtitle / description
            # can be rewritten to match reality (no more "50 illustrations"
            # when we only made 25)
            out["actual_drawing_count"] = n_coloring
            # Still produce a hero for the welcome page
            out["hero"] = generate_hero_image(niche, openai_key, learning_dir, status_cb)
        else:
            out["icons"] = generate_niche_icons(
                niche, openai_key, learning_dir, status_cb,
                anthropic_key=anthropic_key,
            )
            out["hero"]  = generate_hero_image(niche, openai_key, learning_dir, status_cb)
    except Exception as e:
        logger.warning(f"Niche image assets failed: {e}")
        if status_cb:
            status_cb(f"⚠️ Génération images intérieures partielle : {e}")

    return out
