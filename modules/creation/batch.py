"""
KDP Creation Batch Runner
Orchestrates: content generation → interior PDF → cover PDF
for a list of niches. Supports 1-N products per session.
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


def _safe_folder_name(text: str) -> str:
    """Converts a niche string to a safe folder name."""
    import re
    return re.sub(r"[^\w\s-]", "", text.lower()).strip().replace(" ", "-")[:60]


def _prepend_bw_cover_page(interior_path, cover_jpg_path, grayscale: bool = True,
                           margin_in: float = 0.375) -> bool:
    """Prepend a cover as page 1 of the interior PDF. Grayscale by default
    (B&W-interior books); pass grayscale=False for COLOR-interior books so the
    cover page isn't a dull gray inside a full-colour book.
    The image is inset by `margin_in` inches and keeps its aspect ratio, so it
    stays INSIDE the KDP safe area (a full-bleed image trips the previewer's
    "content outside margins" warning).
    Returns True if a page was added (so the caller sizes the spine for +1)."""
    try:
        import fitz, io, os as _os
        from PIL import Image as _PImg
        if not Path(cover_jpg_path).exists():
            return False
        im = _PImg.open(cover_jpg_path).convert("RGB")
        if grayscale:
            im = im.convert("L").convert("RGB")
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=90)
        doc = fitz.open(str(interior_path))
        pw, ph = doc[0].rect.width, doc[0].rect.height
        page = doc.new_page(0, width=pw, height=ph)
        m = max(0.0, float(margin_in)) * 72.0        # inches → points
        rect = fitz.Rect(m, m, pw - m, ph - m)
        page.insert_image(rect, stream=buf.getvalue(), keep_proportion=True)
        tmp = str(interior_path) + ".tmp"
        doc.save(tmp); doc.close()
        _os.replace(tmp, str(interior_path))
        return True
    except Exception as e:
        logger.warning(f"B&W cover prepend skipped: {e}")
        return False


def _estimate_cost(listing: dict, product_type: str,
                   use_interior_images: bool = True) -> dict:
    """Rough per-book API cost estimate (USD), from real content/image counts.
    Dominant cost = gpt-image generations (~$0.04 each); Claude text is smaller.
    Labelled as an estimate in the UI — not a billed figure."""
    hc = product_type in ("recipe_book", "how_to")
    is_facts = bool(listing.get("_facts"))
    is_anec = bool(listing.get("_anecdotes"))
    # Claude text cost by type (from observed averages)
    if is_facts:
        claude = 1.5
    elif product_type == "recipe_book":
        claude = 3.0
    elif is_anec:
        claude = 2.0
    elif product_type == "how_to":
        claude = 2.0
    else:
        claude = 0.3
    # number of per-item interior images actually driven by the content
    n_items = 0
    if listing.get("_recipes"):
        n_items = len(listing["_recipes"])
    elif listing.get("_guide"):
        n_items = len(listing["_guide"].get("chapters", []))
    elif listing.get("_facts"):
        n_items = len(listing["_facts"].get("sections", []))
    n_cover = 5 if hc else 1          # 4 cover illustrations + hero, or 1 low-content
    n_diag = 6 if hc else 0           # explanatory diagram illustrations
    n_item = n_items if (use_interior_images and hc) else 0
    n_images = n_cover + n_diag + n_item
    img_cost = round(n_images * 0.04, 2)
    briefs = 0.40 if hc else 0.20     # cover-brief + keyword web (≈0 if cached)
    total = round(claude + img_cost + briefs, 2)
    return {
        "claude_usd": round(claude, 2),
        "images_usd": img_cost,
        "n_images": n_images,
        "briefs_usd": briefs,
        "total_usd": total,
        "note": "Estimation (le coût réel dépend des tokens + du cache).",
    }


def _ai_disclosure(product_type: str, use_interior_images: bool = True) -> dict:
    """What to declare on KDP's 'Did you use AI tools?' step. These books are
    BUILT by AI (Claude text + gpt-image covers/images) → 'AI-generated' (not
    merely AI-assisted). Amazon REQUIRES this disclosure at publish/edit time."""
    hc = product_type in ("recipe_book", "how_to")
    algorithmic = product_type in ("puzzle", "activity_book", "coloring")
    text = "None (algorithmic content)" if algorithmic else "AI-generated (Claude)"
    if hc or use_interior_images:
        images = "AI-generated (cover + interior images)"
    else:
        images = "AI-generated (cover)"
    return {
        "text": text,
        "images": images,
        "translation": "None (original English)",
        "reminder": (f"KDP → déclarer : Texte = {text} · "
                     f"Images = {images} · Traduction = None"),
    }


def _first_gen_image(product_dir) -> Optional[str]:
    """Return a generated interior image path (first available) for the B&W
    first-page 'image' style — read from the content sidecars (0 $)."""
    import json as _j
    specs = [("content_guide.json", "chapters"), ("content_facts.json", "sections"),
             ("content_anecdotes.json", "sections"), ("content_recipes.json", None)]
    for fn, key in specs:
        fp = Path(product_dir) / fn
        if not fp.exists():
            continue
        try:
            data = _j.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = data if isinstance(data, list) else (data.get(key) or [])
        for it in items:
            img = (it or {}).get("_image")
            if img and Path(img).exists():
                return img
    return None


def _prepend_first_page(interior_path, product_dir, listing, style: str = None) -> bool:
    """Prepend page 1 in BLACK & WHITE, varying the design per book (user pref):
      - 'cover' : the full front cover in grayscale
      - 'title' : a clean typographic title page (title + subtitle + author)
      - 'image' : one generated interior image + the title
    The style is chosen deterministically from the slug so a batch gets variety.
    Image/cover are inset 0.375" so nothing bleeds past the KDP safe area.
    Returns True if a page was added (caller sizes the spine for +1)."""
    try:
        import fitz, io, os as _os
        from PIL import Image as _PImg
        slug = Path(product_dir).name
        if style is None:
            style = ("cover", "title", "image")[sum(ord(c) for c in slug) % 3]
        title = (listing.get("title") or "").strip()
        subtitle = (listing.get("subtitle") or "").strip()
        author = (listing.get("author") or listing.get("publisher_name") or "").strip()

        doc = fitz.open(str(interior_path))
        pw, ph = doc[0].rect.width, doc[0].rect.height
        page = doc.new_page(0, width=pw, height=ph)   # white background
        m = 0.375 * 72                                 # 0.375" safe inset

        def _gray_image(path, rect, quality=90):
            im = _PImg.open(path).convert("L").convert("RGB")
            buf = io.BytesIO(); im.save(buf, "JPEG", quality=quality)
            page.insert_image(rect, stream=buf.getvalue(), keep_proportion=True)

        if style == "cover":
            cj = Path(product_dir) / "cover.jpg"
            if cj.exists():
                _gray_image(cj, fitz.Rect(m, m, pw - m, ph - m))
            else:
                style = "title"

        if style == "image":
            img = _first_gen_image(product_dir)
            if img:
                iy = ph * 0.30
                _gray_image(img, fitz.Rect(m, iy, pw - m, iy + (pw - 2 * m) * 0.78), 88)
                page.insert_textbox(fitz.Rect(m, ph * 0.08, pw - m, ph * 0.27), title,
                                    fontname="tibo", fontsize=25, align=1, color=(0, 0, 0))
                if subtitle:
                    page.insert_textbox(
                        fitz.Rect(m, iy + (pw - 2 * m) * 0.80, pw - m, ph * 0.90),
                        subtitle, fontname="tiro", fontsize=13, align=1,
                        color=(0.12, 0.12, 0.12))
                if author:
                    page.insert_textbox(fitz.Rect(m, ph * 0.92, pw - m, ph - m * 0.4),
                                        author, fontname="tiro", fontsize=12, align=1,
                                        color=(0.22, 0.22, 0.22))
            else:
                style = "title"

        if style == "title":
            page.insert_textbox(fitz.Rect(m, ph * 0.30, pw - m, ph * 0.58), title,
                                fontname="tibo", fontsize=29, align=1, color=(0, 0, 0))
            if subtitle:
                page.insert_textbox(fitz.Rect(m, ph * 0.60, pw - m, ph * 0.74), subtitle,
                                    fontname="tiro", fontsize=14, align=1,
                                    color=(0.15, 0.15, 0.15))
            if author:
                page.insert_textbox(fitz.Rect(m, ph * 0.82, pw - m, ph * 0.90), author,
                                    fontname="tiro", fontsize=13, align=1,
                                    color=(0.22, 0.22, 0.22))

        tmp = str(interior_path) + ".tmp"
        doc.save(tmp); doc.close()
        _os.replace(tmp, str(interior_path))
        return True
    except Exception as e:
        logger.warning(f"first page prepend skipped: {e}")
        return False


def create_product(
    niche: str,
    anthropic_key: str,
    openai_key: str,
    output_dir: Path,
    status_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    style_variant: Optional[Dict] = None,
    learning_dir: Optional[Path] = None,
    use_interior_images: bool = True,
    format_override: Optional[Dict] = None,
    generate_aplus: bool = True,
    highcontent_item_images: bool = False,
    make_epub: bool = False,
) -> Dict:
    """
    Creates one complete KDP product:
      1. Detect product type
      2. Generate listing (title, subtitle, description, keywords)
      3. Expand interior content (prompts / Q&A / log headers)
      4. Build interior PDF
      5. Generate cover (DALL-E 3 + composition)
      6. Save listing.json

    Returns a result dict with paths and metadata.
    """
    from modules.creation.content_generator import (
        detect_product_type, generate_listing, expand_content
    )
    from modules.creation.pdf_interior import create_interior
    from modules.creation.cover_generator import generate_cover

    def s(msg):
        if status_cb: status_cb(msg)
    def p(v):
        if progress_cb: progress_cb(v)

    s(f"🚀 Démarrage : \"{niche}\"")
    if style_variant:
        s(f"🎨 Variant stylistique : {style_variant.get('id', '?')}")
    p(5)

    result = {
        "niche":        niche,
        "status":       "running",
        "started_at":   datetime.now().isoformat(),
        "product_dir":  None,
        "interior_pdf": None,
        "cover_pdf":    None,
        "listing_json": None,
        "error":        None,
    }

    try:
        # ── 1. Product type ──────────────────────────────────────────────────
        product_type = detect_product_type(niche)
        # HIGH-CONTENT override (Phase 2): recipe/guide/facts niches route to
        # the high-content pipeline instead of a blank-template book.
        try:
            from modules.creation.highcontent import detect_highcontent_type
            _hc_type = detect_highcontent_type(niche)
            if _hc_type:
                product_type = _hc_type
        except Exception as _hce:
            logger.debug(f"highcontent detection skipped: {_hce}")
        s(f"📦 Type détecté : {product_type}")
        p(10)

        # ── 2. Listing generation ────────────────────────────────────────────
        listing = generate_listing(
            niche=niche,
            product_type=product_type,
            api_key=anthropic_key,
            status_cb=s,
            style_variant=style_variant,
            learning_dir=learning_dir,
        )
        p(30)

        # Inject format_override (trim_size + paper_type + target page count) from UI
        if format_override:
            for k in ("trim_size_w", "trim_size_h", "paper_type", "page_count",
                      "difficulty", "volume", "puzzle_type"):
                if format_override.get(k) is not None:
                    listing[k] = format_override[k]
            # Force product_type override (UI lets user pick puzzle/activity_book)
            forced = format_override.get("product_type_force")
            if forced:
                product_type = forced
                listing["product_type"] = forced
                s(f"🔁 product_type forcé via UI → {forced}")
            s(f"📏 Format choisi : {listing.get('trim_size_w','?')}×"
              f"{listing.get('trim_size_h','?')}in · papier {listing.get('paper_type','?')}"
              f" · cible {listing.get('page_count','?')} pages")

        # ── 2b. Hook A/B + welcome polish (A10 conversion + engagement) ─────
        try:
            from modules.creation.hook_ab import optimize_hook, polish_welcome_copy
            if anthropic_key:
                optimize_hook(listing, anthropic_key, status_cb=s)
                polish_welcome_copy(listing, anthropic_key, status_cb=s)
        except Exception as he:
            logger.debug(f"Hook A/B skipped: {he}")

        # ── 2c. Niche design brief (Claude adapts layout pool + tracker
        #        fields + reflection prompts to THIS niche) ───────────────
        try:
            from modules.creation.design_brief import generate_design_brief
            if anthropic_key and product_type in ("journal", "planner", "log"):
                brief = generate_design_brief(niche, product_type, anthropic_key,
                                              status_cb=s)
                if brief:
                    listing["_design_brief"] = brief
        except Exception as db:
            logger.debug(f"Design brief skipped: {db}")

        # ── 3. Content expansion ─────────────────────────────────────────────
        # High-content books get their content from the dedicated engine (4d),
        # not from the generic section expansion.
        if product_type not in ("recipe_book", "how_to"):
            listing = expand_content(listing, api_key=anthropic_key, status_cb=s, learning_dir=learning_dir)
        p(50)

        # ── 3a. Pick per-niche template preset ───────────────────────────
        try:
            from modules.creation.template_presets import pick_preset, preset_summary
            preset = pick_preset(niche)
            listing["_preset"] = preset
            s(f"🎨 Preset interior : {preset_summary(preset)}")
        except Exception as pe:
            logger.debug(f"Preset pick skipped: {pe}")

        # ── 3b. Anti-duplication fingerprint check ─────────────────────────
        # Amazon 2025-2026 suppresses books with interiors too close to
        # existing titles. If this niche already has a same-structure book,
        # we just log a warning — the variant/theme combo already differs
        # enough in 90% of cases (cover + fonts) to clear suppression.
        try:
            from modules.creation.fingerprint import compute_fingerprint, is_collision
            theme_name = (listing.get("niche_theme") or
                          style_variant.get("theme") if style_variant else "") or ""
            variant_id = (style_variant or {}).get("id", "")
            fp = compute_fingerprint(listing, variant_id, theme_name)
            listing["_fingerprint"] = fp
            if learning_dir:
                hit = is_collision(learning_dir, niche, fp)
                if hit:
                    s(f"⚠️ Fingerprint collision avec '{hit.get('slug','?')}' "
                      f"— variante/thème conseillés différents")
        except Exception as fe:
            logger.debug(f"Fingerprint step skipped: {fe}")

        # ── 4. Product folder ────────────────────────────────────────────────
        folder_name  = _safe_folder_name(niche)
        product_dir  = output_dir / folder_name
        product_dir.mkdir(parents=True, exist_ok=True)

        # ── 4b. Interior AI images (cached per niche, ~$0.16 once then $0) ──
        # Universal: Claude suggests niche-specific subjects, then gpt-image-2
        # renders 4 illustrations. Works for any niche without code changes.
        image_assets = None
        if use_interior_images and openai_key and learning_dir:
            try:
                from modules.creation.interior_images import build_niche_image_assets
                image_assets = build_niche_image_assets(
                    niche         = niche,
                    openai_key    = openai_key,
                    learning_dir  = learning_dir,
                    status_cb     = s,
                    enabled       = True,
                    anthropic_key = anthropic_key,   # universal subject suggestion
                    listing       = listing,         # enables coloring-book line art
                )
            except Exception as img_err:
                logger.warning(f"Interior images skipped for '{niche}': {img_err}")
                s(f"⚠️ Images intérieures ignorées : {img_err}")

        # ── Sync listing text with reality (coloring books) ──────────────
        # If we generated 30 drawings but Claude's subtitle says "50
        # illustrations", rewrite the number to match. Same for description.
        if image_assets and image_assets.get("actual_drawing_count"):
            n_real = image_assets["actual_drawing_count"]
            import re as _re
            patt = _re.compile(
                r"(\b)(\d{2,3})(\s+(?:illustration|design|drawing|page|"
                r"coloring page|hand[\s-]drawn))",
                _re.IGNORECASE,
            )
            for field in ("subtitle", "description"):
                v = listing.get(field) or ""
                if v and patt.search(v):
                    new_v = patt.sub(lambda m: f"{m.group(1)}{n_real}{m.group(3)}", v)
                    if new_v != v:
                        listing[field] = new_v
                        s(f"📝 {field} recalibré : nombre → {n_real}")
        p(60)

        # ── 4c. Puzzle / activity-book algorithmic content generation ───────
        # For puzzle product types, the interior content is generated by
        # deterministic algorithms (not Claude). We populate listing._puzzles
        # or listing._puzzle_sets here so pdf_interior can render them.
        if product_type in ("puzzle", "activity_book"):
            try:
                from modules.creation.puzzles import PUZZLE_REGISTRY
                from modules.creation.content_generator import detect_puzzle_type
                from modules.creation.puzzles import activity_book as ab_mod

                target_pages = int(listing.get("page_count", 100))
                difficulty   = (listing.get("difficulty") or "medium").lower()
                volume       = int(listing.get("volume", 1))

                if product_type == "puzzle":
                    # Pick puzzle_type from listing or detect from niche
                    ptype = listing.get("puzzle_type") or detect_puzzle_type(niche) or "mazes"
                    listing["puzzle_type"] = ptype
                    per_page = PUZZLE_REGISTRY.get(ptype, {}).get("puzzles_per_page", 1)
                    # Reserve ~10 pages for front matter + closing + solutions
                    front_back = 14
                    n_puzzles  = max(10, (target_pages - front_back) * per_page)
                    s(f"🧩 Génération {n_puzzles} puzzle(s) {ptype} en {difficulty}...")
                    mod = PUZZLE_REGISTRY[ptype]["module"]
                    if ptype in ("wordsearch", "cryptogram"):
                        pzs = mod.generate(n_puzzles, difficulty, niche,
                                           volume=volume, anthropic_key=anthropic_key)
                    else:
                        pzs = mod.generate(n_puzzles, difficulty, niche, volume=volume)
                    listing["_puzzles"] = pzs
                    s(f"✅ {len(pzs)} puzzle(s) générés (seeds déterministes par niche/volume)")
                else:
                    # activity_book — combo
                    mix_total = max(30, target_pages - 16)
                    s(f"🧩 Génération combo ({mix_total} puzzles répartis sur 5 types)...")
                    sets = ab_mod.generate_combo(
                        mix_total, difficulty, niche, mix=None,
                        volume=volume, anthropic_key=anthropic_key,
                    )
                    listing["_puzzle_sets"] = sets
                    breakdown = ", ".join(f"{t}:{len(p)}" for t, p in sets)
                    s(f"✅ Combo prêt : {breakdown}")
            except Exception as pe:
                logger.warning(f"Puzzle generation failed for '{niche}': {pe}")
                s(f"⚠️ Génération puzzles échouée : {pe}")

        # ── 4d. HIGH-CONTENT generation (recipe_book / how_to) — Phase 2 ────
        # Real written content, web-grounded via the Claude web_search tool.
        if product_type in ("recipe_book", "how_to"):
            _populate_highcontent(
                listing, niche, anthropic_key, status_cb=s,
                openai_key=openai_key, learning_dir=learning_dir,
                gen_item_images=highcontent_item_images,
            )
        p(65)

        # ── 5. Interior PDF ──────────────────────────────────────────────────
        # Force a fresh reload to pick up any signature changes (Streamlit
        # auto-reload sometimes misses cross-module updates).
        try:
            import importlib
            import modules.creation.pdf_interior as _pdf_int_mod
            importlib.reload(_pdf_int_mod)
            create_interior_fn = _pdf_int_mod.create_interior
        except Exception:
            create_interior_fn = create_interior

        interior_path = str(product_dir / "interior.pdf")
        # Defensive call: try with image_assets, fall back without if the
        # loaded function signature is stale.
        try:
            create_interior_fn(
                listing       = listing,
                output_path   = interior_path,
                status_cb     = s,
                style_variant = style_variant,
                image_assets  = image_assets,
            )
        except TypeError as te:
            if "image_assets" in str(te):
                logger.warning("Stale create_interior signature — calling without image_assets")
                s("⚠️ Module pdf_interior obsolète, images intérieures ignorées (redémarre Streamlit pour les activer)")
                create_interior_fn(
                    listing       = listing,
                    output_path   = interior_path,
                    status_cb     = s,
                    style_variant = style_variant,
                )
            else:
                raise
        p(70)

        # ── 6. Cover PDF (non-fatal — DALL-E errors won't kill the product) ──
        # CRITICAL: re-count the ACTUAL pages of the interior PDF we just
        # generated. The listing's claimed page_count is often off by ±20%
        # because Claude estimates it from section counts. KDP measures the
        # real PDF and rejects covers whose spine doesn't match.
        actual_page_count = listing.get("page_count", 120)
        try:
            from modules.quality.validator import _pdf_page_count
            real_pc = _pdf_page_count(Path(interior_path))
            if real_pc and real_pc > 0:
                actual_page_count = int(real_pc)
                listing["page_count"] = actual_page_count  # propagate to listing.json
                if real_pc != listing.get("page_count_claimed", real_pc):
                    s(f"📏 Page count recalibré : listing={listing.get('page_count','?')} "
                      f"→ PDF réel={actual_page_count} (spine ajustée)")
        except Exception as _e:
            logger.warning(f"Could not read actual page count: {_e}")

        # ── 6b. KDP TRANSPARENCY : sync description with ACTUAL numbers ─────
        # KDP rejects books whose description over-promises ("100 puzzles" but
        # only 87 inside). Rewrite the description's numeric claims to match
        # reality BEFORE saving listing.json.
        try:
            import re as _re

            actual_puzzles = 0
            if listing.get("_puzzles"):
                actual_puzzles = len(listing["_puzzles"])
            elif listing.get("_puzzle_sets"):
                actual_puzzles = sum(len(p) for _, p in listing["_puzzle_sets"])

            actual_qa = 0
            for sec in listing.get("content_sections", []):
                if sec.get("type") in ("qa", "content"):
                    items = sec.get("items", []) or []
                    actual_qa += sum(1 for i in items
                                      if isinstance(i, str) and i.startswith("Q:"))

            # Build a replacement map of (regex, replacement_func)
            # Each tuple : (label, regex_pattern, actual_value_or_None)
            replacements = []
            # Page count : "120 pages" / "120-page"
            if actual_page_count:
                replacements.append((
                    "pages",
                    _re.compile(r"\b\d{2,3}(?=[\s-]?(?:page|pp)\b)", _re.IGNORECASE),
                    str(actual_page_count),
                ))
            # Puzzle count : "100 puzzles" / "100 mazes" / "100 sudoku"
            if actual_puzzles:
                replacements.append((
                    "puzzles",
                    _re.compile(r"\b\d{2,3}(?=\s+(?:puzzle|maze|sudoku|cryptogram|"
                                r"nonogram|kakuro|kenken|logic|word\s+search|"
                                r"dot[\s-]to[\s-]dot)s?\b)", _re.IGNORECASE),
                    str(actual_puzzles),
                ))
            # Q&A count : "300 questions" / "200 trivia"
            if actual_qa:
                replacements.append((
                    "qa",
                    _re.compile(r"\b\d{2,4}(?=\s+(?:question|q&a|trivia|quiz)s?\b)",
                                _re.IGNORECASE),
                    str(actual_qa),
                ))

            for field in ("subtitle", "description"):
                v = listing.get(field) or ""
                if not v:
                    continue
                new_v = v
                for label, patt, val in replacements:
                    new_v = patt.sub(val, new_v)
                if new_v != v:
                    listing[field] = new_v
                    s(f"📝 {field} synchronisé avec réalité "
                      f"(pages={actual_page_count}, puzzles={actual_puzzles}, qa={actual_qa})")
        except Exception as e:
            logger.debug(f"Description sync skipped: {e}")

        cover_path = None
        if openai_key:
            try:
                _cover_path = str(product_dir / "cover.pdf")
                # +1 page: a grayscale COVER PAGE is prepended to the interior below,
                # so size the spine for one extra page.
                generate_cover(
                    listing=listing,
                    page_count=actual_page_count + 1,
                    openai_key=openai_key,
                    output_path=_cover_path,
                    status_cb=s,
                    style_variant=style_variant,
                    learning_dir=learning_dir,
                    anthropic_key=anthropic_key,
                )
                cover_path = _cover_path
                # Page 1 of the interior = a B&W front-matter page, design varies
                # per book (full cover / title only / one generated image).
                if _prepend_first_page(interior_path, product_dir, listing):
                    s("📄 Page 1 = page de garde N&B ajoutée")
                # HARDCOVER: an extra case-laminate cover for high-content books
                # (complete publication = paperback + hardcover + ebook). Reuses
                # the paperback front art (0 $) — no second AI image.
                if product_type in ("recipe_book", "how_to"):
                    try:
                        from modules.quality.validator import _pdf_page_count as _ppc
                        _hc_pc = _ppc(Path(interior_path)) or (actual_page_count + 1)
                        generate_cover(
                            listing=listing, page_count=int(_hc_pc),
                            openai_key=openai_key,
                            output_path=str(product_dir / "cover_hardcover.pdf"),
                            status_cb=s, style_variant=style_variant,
                            learning_dir=learning_dir, anthropic_key=anthropic_key,
                            binding="hardcover",
                            reuse_front_png=str(product_dir / ".cover_front.png"),
                        )
                    except Exception as _hce:
                        logger.warning(f"hardcover cover skipped for '{niche}': {_hce}")
                        s(f"⚠️ Hardcover ignoré : {str(_hce)[:80]}")
            except Exception as cover_err:
                logger.warning(f"Cover generation skipped for '{niche}': {cover_err}")
                s(f"⚠️ Couverture ignorée : {cover_err}")
        else:
            s("ℹ️ Pas de clé OpenAI — couverture ignorée")
        p(90)

        # ── 7. A+ Content (5 modules, ~+12% conversion) ──────────────────────
        if generate_aplus:
            try:
                from modules.creation.aplus import generate_aplus_content
                aplus_modules = generate_aplus_content(listing, anthropic_key, status_cb=s)
                if aplus_modules:
                    listing["aplus_content"] = aplus_modules
                    s(f"✅ A+ Content prêt : {len(aplus_modules)} modules")
            except Exception as ae:
                logger.warning(f"A+ Content step skipped: {ae}")
        else:
            s("⏭️ A+ Content désactivé (toggle UI)")

        # ── 7b. Persist fingerprint into the store for future collision checks
        try:
            from modules.creation.fingerprint import save_fingerprint
            if learning_dir and listing.get("_fingerprint"):
                save_fingerprint(
                    learning_dir, niche, folder_name,
                    listing["_fingerprint"],
                    variant=(style_variant or {}).get("id", ""),
                    theme=listing.get("niche_theme", ""),
                )
        except Exception as fe:
            logger.debug(f"Fingerprint save skipped: {fe}")

        # AI-content disclosure (KDP requirement) — persisted + shown in the UI
        listing["ai_disclosure"] = _ai_disclosure(product_type, use_interior_images)
        # Per-book API cost estimate (before _recipes/_guide/_facts get stripped)
        listing["est_cost"] = _estimate_cost(listing, product_type, use_interior_images)

        # ── 8. Save listing.json ─────────────────────────────────────────────
        listing_path = str(product_dir / "listing.json")
        with open(listing_path, "w", encoding="utf-8") as f:
            # Strip heavy fields:
            #   - content_sections.items (huge for quiz/journal)
            #   - _puzzles / _puzzle_sets (algorithmic, reproducible from seed)
            #   - _preset (kept summary only)
            skip_keys = {"content_sections", "_puzzles", "_puzzle_sets",
                         "_recipes", "_guide", "_bonus", "_facts"}
            save_listing = {k: v for k, v in listing.items() if k not in skip_keys}
            save_listing["content_sections"] = [
                {k2: v2 for k2, v2 in sec.items() if k2 != "items"}
                for sec in listing.get("content_sections", [])
            ]
            # Record puzzle counts (for UI / reproducibility) without the grids
            if listing.get("_puzzles"):
                save_listing["puzzle_count"] = len(listing["_puzzles"])
            if listing.get("_puzzle_sets"):
                save_listing["puzzle_set_breakdown"] = [
                    {"type": t, "count": len(pz)}
                    for t, pz in listing["_puzzle_sets"]
                ]
            # High-content counts (recipes are NOT regenerable from a seed —
            # keep the full content in a sidecar file for exact regeneration)
            if listing.get("_recipes"):
                save_listing["recipe_count"] = len(listing["_recipes"])
                try:
                    (product_dir / "content_recipes.json").write_text(
                        json.dumps(listing["_recipes"], ensure_ascii=False, indent=1),
                        encoding="utf-8")
                except Exception:
                    pass
            if listing.get("_guide"):
                save_listing["chapter_count"] = len(
                    listing["_guide"].get("chapters", []))
                try:
                    (product_dir / "content_guide.json").write_text(
                        json.dumps(listing["_guide"], ensure_ascii=False, indent=1),
                        encoding="utf-8")
                except Exception:
                    pass
            # Bonus front-matter sidecar (recipe books) — not seed-reproducible
            if listing.get("_bonus"):
                try:
                    (product_dir / "content_bonus.json").write_text(
                        json.dumps(listing["_bonus"], ensure_ascii=False, indent=1),
                        encoding="utf-8")
                except Exception:
                    pass
            # Cookbook technique diagrams sidecar (guide diagrams live in the
            # guide sidecar; cookbook diagrams need their own file)
            if listing.get("_diagrams"):
                try:
                    (product_dir / "content_diagrams.json").write_text(
                        json.dumps(listing["_diagrams"], ensure_ascii=False, indent=1),
                        encoding="utf-8")
                except Exception:
                    pass
            # Facts sidecar (facts books)
            if listing.get("_facts"):
                save_listing["facts_section_count"] = len(
                    listing["_facts"].get("sections", []))
                try:
                    (product_dir / "content_facts.json").write_text(
                        json.dumps(listing["_facts"], ensure_ascii=False, indent=1),
                        encoding="utf-8")
                except Exception:
                    pass
            # Anecdotes sidecar (adult short-story collections)
            if listing.get("_anecdotes"):
                try:
                    (product_dir / "content_anecdotes.json").write_text(
                        json.dumps(listing["_anecdotes"], ensure_ascii=False, indent=1),
                        encoding="utf-8")
                except Exception:
                    pass
            json.dump(save_listing, f, ensure_ascii=False, indent=2)

        # ── 8. EPUB / Kindle (high-content only, color images) ───────────────
        epub_path = None
        if make_epub and product_type in ("recipe_book", "how_to"):
            try:
                from modules.creation.epub_builder import build_epub
                epub_path = build_epub(listing, product_dir, status_cb=s)
            except Exception as ee:
                logger.warning(f"EPUB step skipped: {ee}")
                s(f"⚠️ EPUB ignoré : {str(ee)[:80]}")

        result.update({
            "status":        "success",
            "product_type":  product_type,
            "product_dir":   str(product_dir),
            "interior_pdf":  interior_path,
            "cover_pdf":     cover_path,
            "epub":          epub_path,
            "listing_json":  listing_path,
            "title":         listing["title"],
            "subtitle":      listing.get("subtitle", ""),
            "publisher":     listing.get("publisher_name", ""),
            "keywords":      listing.get("keywords", []),
            "description":   listing.get("description", ""),
            "categories":    listing.get("categories", []),
            "page_count":    listing.get("page_count", 120),
            "ai_disclosure": listing.get("ai_disclosure"),
            "est_cost":      listing.get("est_cost"),
            "style_variant": style_variant.get("id") if style_variant else None,
            "completed_at":  datetime.now().isoformat(),
        })

        s(f"🎉 Produit terminé : \"{listing['title'][:60]}\"")
        p(100)

    except Exception as e:
        logger.error(f"create_product error for '{niche}': {e}", exc_info=True)
        result["status"] = "error"
        result["error"]  = str(e)
        s(f"❌ Erreur \"{niche}\" : {e}")

    return result


# ── Single-asset regenerators ─────────────────────────────────────────────────

def _load_listing(product_dir: Path) -> Dict:
    """Load the listing.json saved for a product. Raises if missing."""
    p = product_dir / "listing.json"
    if not p.exists():
        raise FileNotFoundError(f"listing.json not found in {product_dir}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def recompose_cover_with_overrides(
    product_dir: Path,
    overrides: Optional[Dict] = None,
    status_cb: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Re-renders cover.pdf from the CACHED AI front image (no DALL-E call) with
    optional fine-tuning overrides.

    Overrides dict (all optional, sliders in UI map directly to these) :
      - title_size_mult       : float 0.4-1.5  (1.0 = default)
      - title_y_offset_pct    : float -0.15 to +0.15  (0 = default, fraction of full_h)
      - spine_padding_in      : float 0.375-0.8  (0.4 = default)
      - publisher_size_mult   : float 0.5-2.0  (1.0 = default)

    Reads listing.json fresh on each call → catches title/subtitle edits
    + trim/paper backfills automatically.

    Raises FileNotFoundError if .cover_front.png cache is missing
    (i.e. the cover was generated before the cache was introduced — user
    must run a full 'Auto-improve cover' or 'Régénérer cover' once first).
    """
    from modules.creation.cover_generator import (
        compose_cover, save_cover_pdf, cover_dims, _clamp_for_print_gamut,
    )
    from PIL import Image

    def s(msg):
        if status_cb: status_cb(msg)

    cache_path = product_dir / ".cover_front.png"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"No .cover_front.png cached in {product_dir.name}. "
            "Run a normal 'Auto-improve cover' or 'Régénérer cover' once to "
            "create the cache, then come back to fine-tune."
        )

    listing = _load_listing(product_dir)
    niche   = listing.get("niche", "?")
    s(f"🔧 Recomposition cover : \"{niche}\"")

    # Get the real page count from interior (spine source of truth)
    actual_pc = listing.get("page_count", 120)
    interior  = product_dir / "interior.pdf"
    if interior.exists():
        try:
            from modules.quality.validator import _pdf_page_count
            real = _pdf_page_count(interior)
            if real and real > 0:
                actual_pc = int(real)
                listing["page_count"] = actual_pc
        except Exception:
            pass

    s(f"📂 Image AI cache : {cache_path.name} ({cache_path.stat().st_size//1024} KB)")
    front_img = Image.open(cache_path).convert("RGB")

    if overrides:
        active_kvs = ", ".join(f"{k}={v}" for k, v in overrides.items())
        s(f"🎛️ Overrides actifs : {active_kvs}")

    s("🖼️ Composition (front + spine + back) avec image cachée...")
    cover = compose_cover(front_img, listing, actual_pc,
                          style_variant=None, overrides=overrides)

    # Save PDF
    trim_w     = float(listing.get("trim_size_w", 6.0))
    trim_h     = float(listing.get("trim_size_h", 9.0))
    paper_type = str(listing.get("paper_type", "white")).lower()
    cover_path = str(product_dir / "cover.pdf")
    save_cover_pdf(cover, cover_path, actual_pc,
                    trim_w=trim_w, trim_h=trim_h, paper_type=paper_type)

    dims = cover_dims(actual_pc, trim_w=trim_w, trim_h=trim_h, paper_type=paper_type)
    s(f"✅ Cover recomposée → {Path(cover_path).name} "
      f"({dims['full_w_in']:.3f}×{dims['full_h_in']:.3f}\" · spine {dims['spine_in']:.3f}\")")
    return cover_path


def fix_cover_dimensions(
    product_dir: Path,
    openai_key: str,
    status_cb: Optional[Callable[[str], None]] = None,
    learning_dir: Optional[Path] = None,
    new_trim_w: Optional[float] = None,
    new_trim_h: Optional[float] = None,
    new_paper_type: Optional[str] = None,
) -> str:
    """
    Fix a cover that KDP rejected for dimension mismatch.

    Steps :
      1. Optionally override trim/paper in listing.json (persist)
      2. Re-read the ACTUAL interior PDF page count (spine source of truth)
      3. Compute expected dims via kdp_specs
      4. Re-render cover.pdf with these dims (DALL-E NOT re-called — reuses
         the front image generated last time if it lives in cover_dims cache,
         else falls back to a fresh DALL-E call via generate_cover).

    Returns the new cover.pdf path.
    """
    from modules.creation.cover_generator import generate_cover

    def s(msg):
        if status_cb: status_cb(msg)

    listing = _load_listing(product_dir)
    niche   = listing.get("niche", "?")
    s(f"🔧 Fix dimensions cover : \"{niche}\"")

    # 1. Override trim/paper if requested
    if new_trim_w is not None and new_trim_w > 0:
        listing["trim_size_w"] = float(new_trim_w)
    if new_trim_h is not None and new_trim_h > 0:
        listing["trim_size_h"] = float(new_trim_h)
    if new_paper_type:
        listing["paper_type"] = str(new_paper_type).lower()

    # 2. Real page count from interior
    actual_pc = listing.get("page_count", 120)
    interior  = product_dir / "interior.pdf"
    if interior.exists():
        try:
            from modules.quality.validator import _pdf_page_count
            real = _pdf_page_count(interior)
            if real and real > 0:
                actual_pc = int(real)
                listing["page_count"] = actual_pc
        except Exception:
            pass

    # 3. Persist updates back to listing.json
    try:
        import json as _json
        listing_path = product_dir / "listing.json"
        saved = _json.loads(listing_path.read_text(encoding="utf-8"))
        for k in ("trim_size_w", "trim_size_h", "paper_type", "page_count"):
            if listing.get(k) is not None:
                saved[k] = listing[k]
        listing_path.write_text(
            _json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not persist listing updates: {e}")

    # 4. Show user what we're going for so they can verify
    try:
        from modules.creation.kdp_specs import compute_cover_dims
        dims = compute_cover_dims(
            actual_pc,
            float(listing["trim_size_w"]),
            float(listing["trim_size_h"]),
            str(listing["paper_type"]),
        )
        s(f"📏 Cible KDP : {dims['full_w_in']:.3f}×{dims['full_h_in']:.3f}\" "
          f"(trim {listing['trim_size_w']}×{listing['trim_size_h']} · "
          f"{listing['paper_type']} · {actual_pc}p · spine {dims['spine_in']:.3f}\")")
    except Exception:
        pass

    # 5. Re-render cover
    cover_path = str(product_dir / "cover.pdf")
    generate_cover(
        listing       = listing,
        page_count    = actual_pc,
        openai_key    = openai_key,
        output_path   = cover_path,
        status_cb     = s,
        style_variant = None,
        learning_dir  = learning_dir,
        free_style    = True,
    )
    s(f"✅ Cover ré-rendue aux bonnes dimensions → {Path(cover_path).name}")
    return cover_path


def regenerate_cover_only(
    product_dir: Path,
    anthropic_key: str,
    openai_key: str,
    status_cb: Optional[Callable[[str], None]] = None,
    learning_dir: Optional[Path] = None,
    free_style: bool = True,
    cover_overrides: Optional[dict] = None,
    reuse_art: bool = False,
) -> str:
    # Record the regen as a learning event (signals dissatisfaction)
    try:
        if learning_dir:
            from modules.learning.events import record_cover_regen
            record_cover_regen(
                learning_dir   = learning_dir,
                slug           = Path(product_dir).name,
                force          = free_style,
            )
    except Exception:
        pass
    """
    Regenerates ONLY the cover for an existing product. Overwrites cover.pdf.
    `free_style=True` ignores the saved variant palette → each call produces a
    visually different cover (different style hint + dominant color taken from
    the freshly generated AI image, not forced from a fixed palette).
    Returns the cover.pdf path.
    """
    from modules.creation.cover_generator import generate_cover

    def s(msg):
        if status_cb: status_cb(msg)

    listing = _load_listing(product_dir)
    cover_path = str(product_dir / "cover.pdf")
    s(f"🎨 Régénération couverture pour : \"{listing.get('niche','?')}\"")

    # CRITICAL: use the ACTUAL interior PDF page count for the spine, not the
    # listing's claimed value (often off by ±20%, causes KDP cover rejection).
    actual_pc = listing.get("page_count", 120)
    interior = product_dir / "interior.pdf"
    if interior.exists():
        try:
            from modules.quality.validator import _pdf_page_count
            real = _pdf_page_count(interior)
            if real and real > 0:
                actual_pc = int(real)
                if real != listing.get("page_count"):
                    s(f"📏 Page count recalibré : {listing.get('page_count','?')} → {actual_pc}")
                    listing["page_count"] = actual_pc
        except Exception:
            pass

    # Optionally REUSE the existing AI art (0 $) — e.g. when only tweaking the
    # back cover, so we don't pay for / change the front illustration.
    _reuse_png = str(product_dir / ".cover_front.png") if reuse_art else ""

    # free_style → no forced palette, no forced font set → AI free to vary
    generate_cover(
        listing        = listing,
        page_count     = actual_pc,
        openai_key     = openai_key,
        output_path    = cover_path,
        status_cb      = s,
        style_variant  = None if free_style else None,   # always None for now
        learning_dir   = learning_dir,
        free_style     = free_style,
        anthropic_key  = anthropic_key,
        extra_overrides= cover_overrides,
        reuse_front_png= _reuse_png,
    )
    s(f"✅ Couverture régénérée → {Path(cover_path).name}")
    return cover_path


def _populate_highcontent(listing: dict, niche: str, anthropic_key: str,
                          status_cb: Optional[Callable[[str], None]] = None,
                          openai_key: Optional[str] = None,
                          learning_dir: Optional[Path] = None,
                          gen_item_images: bool = False) -> None:
    """
    Populate listing["_recipes"] / ["_guide"] / ["_facts"] via the high-content
    engine (web-grounded Claude generation). Used by BOTH create_product and
    regenerate_interior_only — saved listings strip the heavy content, so a
    standalone interior regen must rebuild it (same pattern as puzzles).
    Recipe count / chapter count derive from the target page count.

    When gen_item_images=True (and openai_key given), also generates ONE color
    image per item (recipe photo / kid illustration / guide illustration),
    adapted to the niche, and attaches its path to each item under "_image".
    """
    def s(msg):
        if status_cb: status_cb(msg)

    product_type = listing.get("product_type", "")
    if product_type not in ("recipe_book", "how_to"):
        return
    if not anthropic_key:
        s("⚠️ High-content : clé Anthropic manquante — contenu non généré")
        return
    try:
        from modules.creation.highcontent import (
            generate_recipes, generate_guide, generate_bonus,
            generate_facts, is_facts_niche,
            generate_anecdotes, is_anecdotes_niche,
        )
        target_pages = int(listing.get("page_count") or 100)
        if target_pages < 30:
            target_pages = 100
        if product_type == "recipe_book":
            # ~1 page per recipe; bonus front-matter (~10 pages) added on top
            saved = int(listing.get("recipe_count", 0) or 0)
            n = saved if saved >= 10 else max(30, target_pages - 20)
            recipes = generate_recipes(niche, n, anthropic_key, status_cb=s)
            listing["_recipes"] = recipes
            s(f"✅ {len(recipes)} recettes générées (nutrition + vérif web, 100% originales)")
            # Bonus: intro + 7-day meal plan + shopping list (big value lift)
            bonus = generate_bonus(niche, recipes, anthropic_key, status_cb=s)
            if bonus:
                listing["_bonus"] = bonus
        elif is_facts_niche(niche):
            # A facts book reads wrong as how-to chapters → dedicated facts mode.
            # Kids layout ≈ 3 pages/section (illustrated opener + fun-fact cards),
            # so size sections to the target page count.
            n_sec = max(10, min(24, target_pages // 3))
            facts = generate_facts(niche, anthropic_key, n_sections=n_sec, status_cb=s)
            listing["_facts"] = facts
            s(f"✅ Livre de faits : {len(facts.get('sections', []))} sections (vérifiées web)")
        elif is_anecdotes_niche(niche):
            # Adult short-true-stories collection → dedicated anecdotes mode.
            n_sec = max(8, min(16, target_pages // 8))
            anec = generate_anecdotes(niche, anthropic_key, n_sections=n_sec, status_cb=s)
            listing["_anecdotes"] = anec
            s(f"✅ Recueil d'anecdotes : {len(anec.get('sections', []))} sections (vérifiées web)")
        else:
            # Chapters run ~4 pages each in practice → size for a fuller book
            # (guides were coming out too short at //6). Cap raised to 26.
            saved = int(listing.get("chapter_count", 0) or 0)
            n_ch = saved if saved >= 6 else max(24, min(28, target_pages // 4))
            guide = generate_guide(niche, anthropic_key, n_chapters=n_ch, status_cb=s)
            listing["_guide"] = guide
            s(f"✅ Guide : {len(guide.get('chapters', []))} chapitres générés (vérifiés web)")

        # ── Per-item COLOR images (opt-in) — niche-adapted, cached ──────────
        if gen_item_images and openai_key and learning_dir:
            try:
                from modules.creation.interior_images import build_item_images
                if product_type == "recipe_book":
                    items = listing.get("_recipes", [])
                    imgs = build_item_images(niche, items, "recipe", openai_key,
                                             learning_dir, status_cb=s)
                    for it, p in zip(items, imgs):
                        if p:
                            it["_image"] = str(p)
                elif listing.get("_facts"):
                    secs = listing["_facts"].get("sections", [])
                    imgs = build_item_images(niche, secs, "facts", openai_key,
                                             learning_dir, status_cb=s)
                    for sec, p in zip(secs, imgs):
                        if p:
                            sec["_image"] = str(p)
                elif listing.get("_guide"):
                    chaps = listing["_guide"].get("chapters", [])
                    imgs = build_item_images(niche, chaps, "guide", openai_key,
                                             learning_dir, status_cb=s)
                    for ch, p in zip(chaps, imgs):
                        if p:
                            ch["_image"] = str(p)
            except Exception as ie:
                logger.warning(f"item images skipped: {ie}")
                s(f"⚠️ Images par item ignorées : {str(ie)[:80]}")

        # ── Explanatory diagrams (code infographics + 1 optional AI illustration)
        # Guides: inserted inside their chapters (specs persist in the guide
        # sidecar). Cookbooks: a "Techniques & How-To" section (specs persist in
        # content_diagrams.json → listing["_diagrams"]).
        try:
            from modules.creation.highcontent import generate_diagrams
            if listing.get("_guide"):
                titles = [c.get("title", "") for c in listing["_guide"].get("chapters", [])]
                specs = generate_diagrams(niche, titles, anthropic_key,
                                          kind="guide", status_cb=s)
                if openai_key:
                    _gen_diagram_illustrations(specs, niche, openai_key,
                                               learning_dir, status_cb=s)
                if specs:
                    listing["_guide"]["diagrams"] = specs
            elif product_type == "recipe_book" and listing.get("_recipes"):
                titles = [r.get("title", "") for r in listing["_recipes"]]
                specs = generate_diagrams(niche, titles, anthropic_key,
                                          kind="cookbook", status_cb=s)
                if openai_key:
                    _gen_diagram_illustrations(specs, niche, openai_key,
                                               learning_dir, status_cb=s)
                if specs:
                    listing["_diagrams"] = specs   # → Techniques section
        except Exception as de:
            logger.warning(f"diagram generation skipped: {de}")
            s(f"⚠️ Schémas ignorés : {str(de)[:80]}")
    except Exception as e:
        logger.warning(f"High-content generation failed for '{niche}': {e}")
        s(f"⚠️ Génération high-content échouée : {e}")


def _gen_diagram_illustrations(specs, niche, openai_key, learning_dir,
                               status_cb=None):
    """Generate the AI image for any 'illustration' diagram spec (no-text visual),
    caching it under learning_dir. Sets spec['_image']. Best-effort."""
    def s(m):
        if status_cb: status_cb(m)
    ills = [sp for sp in (specs or [])
            if str(sp.get("type", "")).lower() == "illustration" and sp.get("image_prompt")]
    if not ills:
        return
    try:
        import openai
        from modules.creation.interior_images import _fetch_image_b64, _niche_slug
        client = openai.OpenAI(api_key=openai_key)
        base = Path(learning_dir or ".") / "interior_images" / _niche_slug(niche) / "diagrams"
        base.mkdir(parents=True, exist_ok=True)
        for idx, sp in enumerate(ills, 1):
            prompt = ("Clean, simple instructional illustration, flat editorial style, "
                      "soft professional palette, NO text, NO words, NO labels. "
                      + str(sp["image_prompt"]))
            s(f"🎨 Illustration schéma : {sp.get('title')}")
            data = _fetch_image_b64(client, prompt, size="1024x1024", quality="high")
            if data:
                p = base / f"ill_{idx}.png"
                p.write_bytes(data)
                sp["_image"] = str(p)
    except Exception as e:
        logger.warning(f"diagram illustration gen skipped: {e}")


def _populate_puzzle_content(listing: dict, niche: str, anthropic_key: str,
                             status_cb: Optional[Callable[[str], None]] = None) -> None:
    """
    Populate listing["_puzzles"] / ["_puzzle_sets"] from the deterministic seed
    (niche + volume + difficulty). Used by BOTH create_product (fresh) and
    regenerate_interior_only (the saved listing strips _puzzles to save space,
    so a standalone interior regen must rebuild them or the puzzle pages are
    empty — the "regen gave 5 blank pages" bug).
    """
    def s(msg):
        if status_cb: status_cb(msg)

    product_type = listing.get("product_type", "")
    if product_type not in ("puzzle", "activity_book"):
        return
    try:
        from modules.creation.puzzles import PUZZLE_REGISTRY
        from modules.creation.content_generator import detect_puzzle_type
        from modules.creation.puzzles import activity_book as ab_mod

        target_pages = int(listing.get("page_count", 100))
        # page_count can be corrupted to a tiny value (e.g. 4) by a previous
        # broken/empty generation. A real puzzle book is never < 24 pages, so
        # treat anything implausible as the default 100-page target.
        if target_pages < 30:
            target_pages = 100
        difficulty   = (listing.get("difficulty") or "medium").lower()
        volume       = int(listing.get("volume", 1))

        if product_type == "puzzle":
            ptype = listing.get("puzzle_type") or detect_puzzle_type(niche) or "mazes"
            listing["puzzle_type"] = ptype
            per_page = PUZZLE_REGISTRY.get(ptype, {}).get("puzzles_per_page", 1)
            front_back = 14
            # Prefer the ORIGINAL intended count (puzzle_count) — page_count can
            # get corrupted to a small value by a previous broken regen, which
            # would shrink n_puzzles and reinforce the empty-book bug.
            saved_count = int(listing.get("puzzle_count", 0) or 0)
            if saved_count >= 10:
                n_puzzles = saved_count
            else:
                n_puzzles = max(60, (target_pages - front_back) * per_page)
            s(f"🧩 Régénération {n_puzzles} puzzle(s) {ptype} en {difficulty}...")
            mod = PUZZLE_REGISTRY[ptype]["module"]
            if ptype in ("wordsearch", "cryptogram"):
                pzs = mod.generate(n_puzzles, difficulty, niche,
                                   volume=volume, anthropic_key=anthropic_key)
            else:
                pzs = mod.generate(n_puzzles, difficulty, niche, volume=volume)
            listing["_puzzles"] = pzs
            s(f"✅ {len(pzs)} puzzle(s) reconstruits (seeds déterministes)")
        else:
            saved_count = int(listing.get("puzzle_count", 0) or 0)
            mix_total = saved_count if saved_count >= 30 else max(30, target_pages - 16)
            s(f"🧩 Régénération combo ({mix_total} puzzles sur 5 types)...")
            sets = ab_mod.generate_combo(
                mix_total, difficulty, niche, mix=None,
                volume=volume, anthropic_key=anthropic_key,
            )
            listing["_puzzle_sets"] = sets
            breakdown = ", ".join(f"{t}:{len(p)}" for t, p in sets)
            s(f"✅ Combo reconstruit : {breakdown}")
    except Exception as pe:
        logger.warning(f"Puzzle regen failed for '{niche}': {pe}")
        s(f"⚠️ Régénération puzzles échouée : {pe}")


def regenerate_interior_only(
    product_dir: Path,
    anthropic_key: str,
    openai_key: str,
    status_cb: Optional[Callable[[str], None]] = None,
    learning_dir: Optional[Path] = None,
    use_interior_images: bool = True,
    gen_item_images: bool = False,
    rebuild_epub: bool = False,
) -> str:
    """
    Regenerates ONLY the interior PDF for an existing product. Overwrites
    interior.pdf. Re-expands content if any section is empty, then rebuilds
    the PDF. Reuses cached AI illustrations (no extra image cost) unless
    `force_regenerate_images` is added in future.
    """
    from modules.creation.content_generator import expand_content
    from modules.creation.pdf_interior import create_interior
    from modules.creation.interior_images import build_niche_image_assets

    def s(msg):
        if status_cb: status_cb(msg)

    listing = _load_listing(product_dir)
    niche   = listing.get("niche", "?")
    ptype   = listing.get("product_type", "")
    s(f"📄 Régénération intérieur pour : \"{niche}\"")

    # Old books generated before design_brief shipped → generate one now so
    # this regen benefits from niche-aware layouts + checkbox-heavy fields +
    # niche illustrations.
    if not listing.get("_design_brief") and anthropic_key and ptype in (
        "journal", "planner", "log"
    ):
        try:
            from modules.creation.design_brief import generate_design_brief
            brief = generate_design_brief(niche, ptype, anthropic_key, status_cb=s)
            if brief:
                listing["_design_brief"] = brief
                # Persist for future regens (cheap to keep)
                try:
                    import json as _json
                    listing_path = product_dir / "listing.json"
                    saved = _json.loads(listing_path.read_text(encoding="utf-8"))
                    saved["_design_brief"] = brief
                    listing_path.write_text(
                        _json.dumps(saved, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"design_brief regen skipped: {e}")

    # Puzzle types: the saved listing strips _puzzles/_puzzle_sets (regenerable
    # from seed) → rebuild them here or the interior has ZERO puzzle pages.
    if ptype in ("puzzle", "activity_book"):
        _populate_puzzle_content(listing, niche, anthropic_key, status_cb=s)
    elif ptype in ("recipe_book", "how_to"):
        # High-content: reload the EXACT content from the sidecar file (free);
        # only regenerate via Claude if the sidecar is missing.
        import json as _json

        def _load_sidecar(fname):
            fp = product_dir / fname
            if fp.exists():
                try:
                    return _json.loads(fp.read_text(encoding="utf-8"))
                except Exception as _se:
                    logger.warning(f"sidecar {fname} load failed: {_se}")
            return None

        loaded = False
        if ptype == "recipe_book":
            data = _load_sidecar("content_recipes.json")
            if data is not None:
                listing["_recipes"] = data
                bonus = _load_sidecar("content_bonus.json")
                if bonus:
                    listing["_bonus"] = bonus
                diagrams = _load_sidecar("content_diagrams.json")
                if diagrams:
                    listing["_diagrams"] = diagrams
                loaded = True
                s("📦 Recettes + bonus rechargés depuis les sidecars (0 $)")
        else:
            # how_to may be a facts book, an anecdotes collection, or a guide
            facts = _load_sidecar("content_facts.json")
            anec = _load_sidecar("content_anecdotes.json")
            if facts is not None:
                listing["_facts"] = facts
                loaded = True
                s("📦 Livre de faits rechargé depuis le sidecar (0 $)")
            elif anec is not None:
                listing["_anecdotes"] = anec
                loaded = True
                s("📦 Recueil d'anecdotes rechargé depuis le sidecar (0 $)")
            else:
                data = _load_sidecar("content_guide.json")
                if data is not None:
                    listing["_guide"] = data
                    loaded = True
                    s("📦 Guide rechargé depuis le sidecar (0 $)")
        if not loaded:
            s("♻️ Sidecar absent — régénération du contenu via Claude...")
            _populate_highcontent(listing, niche, anthropic_key, status_cb=s)

        # Per-item COLOR images — generate only for items missing an image, then
        # persist back into the sidecar so the EPUB and future regens reuse them.
        if gen_item_images and openai_key and learning_dir:
            try:
                from modules.creation.interior_images import build_item_images
                kind_map = {"recipe_book": ("_recipes", "recipe", "content_recipes.json")}
                if listing.get("_facts"):
                    target = ("_facts", "facts", "content_facts.json")
                    items = listing["_facts"].get("sections", [])
                elif listing.get("_guide"):
                    target = ("_guide", "guide", "content_guide.json")
                    items = listing["_guide"].get("chapters", [])
                else:
                    target = kind_map.get(ptype)
                    items = listing.get("_recipes", []) if target else []
                if target and items and any(not it.get("_image") for it in items):
                    kind = target[1]
                    imgs = build_item_images(niche, items, kind, openai_key,
                                             learning_dir, status_cb=s)
                    for it, p in zip(items, imgs):
                        if p:
                            it["_image"] = str(p)
                    # persist images back into the sidecar
                    payload = (listing.get("_facts") or listing.get("_guide")
                               if target[0] in ("_facts", "_guide")
                               else listing.get("_recipes"))
                    try:
                        (product_dir / target[2]).write_text(
                            _json.dumps(payload, ensure_ascii=False, indent=1),
                            encoding="utf-8")
                    except Exception:
                        pass
            except Exception as ie:
                logger.warning(f"item images (regen) skipped: {ie}")
                s(f"⚠️ Images par item ignorées : {str(ie)[:80]}")
    else:
        # The saved listing.json strips items to save space → regenerate them
        sections = listing.get("content_sections", [])
        if not any(sec.get("items") for sec in sections):
            s("📝 Listing sauvegardé sans items — régénération du contenu...")
            listing = expand_content(listing, api_key=anthropic_key, status_cb=s,
                                     learning_dir=learning_dir)

    # Cached images (free) + coloring pages if needed
    image_assets = None
    if use_interior_images and openai_key and learning_dir:
        try:
            image_assets = build_niche_image_assets(
                niche         = niche,
                openai_key    = openai_key,
                learning_dir  = learning_dir,
                status_cb     = s,
                enabled       = True,
                anthropic_key = anthropic_key,
                listing       = listing,
            )
        except Exception as img_err:
            logger.warning(f"Interior images skipped: {img_err}")

    interior_path = str(product_dir / "interior.pdf")
    create_interior(
        listing       = listing,
        output_path   = interior_path,
        status_cb     = s,
        style_variant = None,
        image_assets  = image_assets,
    )
    s(f"✅ Intérieur régénéré → {Path(interior_path).name}")

    # Optionally rebuild the EPUB with the (now image-enriched) content.
    if rebuild_epub and ptype in ("recipe_book", "how_to"):
        try:
            from modules.creation.epub_builder import build_epub
            build_epub(listing, product_dir, status_cb=s)
        except Exception as ee:
            logger.warning(f"EPUB rebuild skipped: {ee}")
            s(f"⚠️ EPUB non reconstruit : {str(ee)[:80]}")

    return interior_path


def run_batch(
    niches: List[str],
    anthropic_key: str,
    openai_key: str,
    output_dir: Path,
    status_cb:   Optional[Callable[[str],  None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    result_cb:   Optional[Callable[[Dict],  None]] = None,
    variant_start: int = 0,
    learning_dir: Optional[Path] = None,
    excluded_variants: Optional[List[str]] = None,
    use_interior_images: bool = True,
    format_override: Optional[Dict] = None,
    generate_aplus: bool = True,
    highcontent_item_images: bool = False,
    make_epub: bool = False,
) -> List[Dict]:
    """
    Creates multiple KDP products sequentially with rotating style variants
    (anti-duplicate). Each product gets a different palette / fonts / symbol /
    cover-art-style / listing tone — making the batch resistant to KDP's
    duplicate-content detection.

    `variant_start` lets you offset the rotation so two separate batches
    on similar niches don't pick the same variant order.
    """
    from modules.creation.variants  import get_variant, variant_count, variant_for_niche, STYLE_VARIANTS
    from modules.creation.content_generator import detect_product_type
    from modules.creation.niche_themes      import detect_theme
    from modules.learning.strategy         import choose_variant_for_niche

    def s(msg):
        if status_cb: status_cb(msg)
    def p(v):
        if progress_cb: progress_cb(v)

    total   = len(niches)
    results = []

    s(f"🏭 Démarrage batch : {total} produit(s) à créer...")
    p(0)

    # Track variants already used IN THIS BATCH (to maintain anti-duplicate
    # variety even when learning prefers the same variant repeatedly)
    used_in_this_batch: List[str] = []

    for i, niche in enumerate(niches):
        # ── Active variant choice (learning-driven) ──────────────────────
        ptype  = detect_product_type(niche)
        theme  = detect_theme(niche)
        tname  = theme.get("name", "default")

        if learning_dir:
            # Caller-specified exclusions (e.g., on "regenerate with another style")
            # + variants already used in THIS batch (force visual variety)
            base_exclude = list(excluded_variants or [])
            exclude = base_exclude + (used_in_this_batch if total > 1 else [])
            variant, confidence, reason = choose_variant_for_niche(
                learning_dir       = learning_dir,
                niche              = niche,
                product_type       = ptype,
                theme_name         = tname,
                available_variants = STYLE_VARIANTS,
                excluded_variant_ids = exclude,
            )
            conf_pct = int(confidence * 100)
            s(f"━━━ Produit {i+1}/{total} : \"{niche}\" ━━━")

            # ── Make learning visible: explain what & why the bot chose ──
            try:
                from modules.learning.profile import build_profile
                from modules.learning.feedback import feedback_counts
                _prof = build_profile(learning_dir)
                _counts = feedback_counts(learning_dir)
                n_obs = _counts.get("total", 0)
                if n_obs == 0:
                    s(f"🧠 Apprentissage : aucune observation encore — hash de la niche utilisé")
                else:
                    s(f"🧠 Profil actif : {n_obs} produit(s) noté(s) "
                      f"({_counts.get('up',0)} 👍 / {_counts.get('published',0)} ✅ / {_counts.get('down',0)} 👎)")
                    if _prof.get("top_variant"):
                        s(f"   ↳ Top variant historique : {_prof['top_variant']}")
                    if _prof.get("top_theme"):
                        s(f"   ↳ Top thème historique : {_prof['top_theme']}")
            except Exception:
                pass

            s(f"🎨 Variant choisi : **{variant['id']}**  ·  confiance {conf_pct}%  ·  raison : {reason}")
            s(f"🎯 Thème détecté : {tname}  ·  type produit : {ptype}")
        else:
            # No learning context → fall back to hash / rotation
            if total == 1:
                variant = variant_for_niche(niche)
            else:
                variant = get_variant(variant_start + i)
            s(f"━━━ Produit {i+1}/{total} : \"{niche}\"  ·  style: {variant['id']} ━━━")

        used_in_this_batch.append(variant["id"])

        def product_progress(v, _i=i):
            global_v = (_i * 100 + v) / total
            p(global_v)

        res = create_product(
            niche               = niche,
            anthropic_key       = anthropic_key,
            openai_key          = openai_key,
            output_dir          = output_dir,
            status_cb           = s,
            progress_cb         = product_progress,
            style_variant       = variant,
            learning_dir        = learning_dir,
            use_interior_images = use_interior_images,
            format_override     = format_override,
            generate_aplus      = generate_aplus,
            highcontent_item_images = highcontent_item_images,
            make_epub           = make_epub,
        )
        results.append(res)

        if result_cb:
            result_cb(res)

        # Pause between products to avoid API rate limits
        if i < total - 1:
            s("⏳ Pause 3s entre les produits...")
            time.sleep(3)

    success = sum(1 for r in results if r["status"] == "success")
    fail    = sum(1 for r in results if r["status"] == "error")
    s(f"✅ Batch terminé : {success} réussi(s), {fail} échec(s)")
    p(100)

    return results
