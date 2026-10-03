"""
A+ Content generator — Amazon KDP enhanced product description (PRO).
====================================================================
Generates a 5-module A+ Content layout mapped to REAL KDP standard module
types, with EXACT image dimensions and per-module character limits, plus
ultra-marketing copy that is KDP-compliant (no banned words).

KDP A+ Content (free for paperback authors) lifts conversion ~10-12%. It can't
be auto-published (no public API), so we prepare copy-paste-ready modules AND
exact-dimension image specs (optionally we render the images too).

── KDP A+ standard module specs (researched June 2026) ──────────────────────
Sources: KDP Help (A+ Content Examples), flairox.com, kdpforge.com.
  • Max 5 modules per A+ layout (free tier).
  • Images: JPG/PNG, RGB only (NOT CMYK), ≤ 2 MB, ≥ 72 DPI (design at 2×).
  • 70% visual / 30% text rule. Mobile font ≥ 24px → design text ≥ 30pt.
  • BANNED (gets A+ rejected): "best seller", "#1", "free", "guarantee",
    "sale", "discount", price, shipping/warranty, competitor names, contact
    info / URLs / emails, review quotes, time-sensitive claims.
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── KDP standard module catalogue with exact dimensions + char limits ────────
# Each entry: the 5-module layout we build for a book. `images` = list of
# (label, width_px, height_px). `heading_max` / `body_max` / `bullet_max` are
# the KDP-safe character caps for that module type.
APLUS_MODULE_SPECS = {
    "hero_header": {
        "kdp_module":  "Standard Image Header with Text",
        "purpose":     "Big lifestyle hero + one-line value promise (above the fold).",
        "images":      [("Hero lifestyle image", 970, 600)],
        "heading_max": 160,
        "body_max":    1000,
        "bullet_max":  0,
    },
    "three_features": {
        "kdp_module":  "Standard Three Images & Text",
        "purpose":     "Three key features/benefits, each with a square image.",
        "images":      [("Feature 1 image", 300, 300),
                        ("Feature 2 image", 300, 300),
                        ("Feature 3 image", 300, 300)],
        "heading_max": 160,
        "body_max":    0,
        "bullet_max":  200,   # per-feature caption
    },
    "perfect_for": {
        "kdp_module":  "Standard Text",
        "purpose":     "Audience targeting — who this book is perfect for (no image).",
        "images":      [],
        "heading_max": 160,
        "body_max":    1000,
        "bullet_max":  0,
    },
    "why_stands_out": {
        "kdp_module":  "Standard Four Images & Text (Quadrant)",
        "purpose":     "Four differentiators that set this book apart.",
        "images":      [("Differentiator 1", 220, 220),
                        ("Differentiator 2", 220, 220),
                        ("Differentiator 3", 220, 220),
                        ("Differentiator 4", 220, 220)],
        "heading_max": 160,
        "body_max":    0,
        "bullet_max":  150,
    },
    "cta_closer": {
        "kdp_module":  "Standard Image Header with Text",
        "purpose":     "Closing banner — reinforce the promise, gentle call to action.",
        "images":      [("Closing banner image", 970, 300)],
        "heading_max": 160,
        "body_max":    1000,
        "bullet_max":  0,
    },
}

# Also commonly useful (not in the default 5, but exported for the UI):
APLUS_EXTRA_SPECS = {
    "company_logo":     {"kdp_module": "Standard Company Logo", "images": [("Brand logo", 600, 180)]},
    "comparison_chart": {"kdp_module": "Standard Comparison Chart", "images": [("Each product", 150, 300)]},
}

# Words/patterns that get A+ Content REJECTED by KDP moderation.
_BANNED_PATTERNS = [
    # "free" only when standalone (a free OFFER) — NOT compounds like
    # "screen-free", "hassle-free", "ad-free" which are allowed selling points.
    r"\bbest[\s-]?seller\b", r"\b#\s*1\b", r"\bnumber one\b",
    r"(?<![\w-])free(?![\w-])",
    r"\bguarantee[d]?\b", r"\bon sale\b", r"\bdiscount\b",
    r"\bspecial offer\b", r"\blimited offer\b",
    r"\bcheap\b", r"\blimited time\b", r"\btoday only\b", r"\bshipping\b",
    r"\bwarranty\b", r"\brefund\b", r"\$\d", r"\b\d+%\s*off\b",
    r"\bamazon\b", r"\bkindle\b", r"\bclick here\b", r"\bwww\.", r"http",
    r"\b5[\s-]?star[s]?\b", r"\breview[s]?\b", r"\bbonus\b",
]


def _clip(text: str, max_chars: int) -> str:
    """Truncate at a word boundary (never mid-word) within max_chars."""
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    sp = cut.rfind(" ")
    if sp > max_chars * 0.6:
        cut = cut[:sp]
    return cut.rstrip(" ,.-")


def _sanitize(text: str) -> str:
    """Remove/replace KDP-banned words so the module passes A+ moderation."""
    if not text:
        return text
    out = text
    replacements = {
        r"\bbest[\s-]?seller\b":      "reader favourite",
        r"(?<![\w-])free(?![\w-])":   "included",
        r"\bguarantee[d]?\b":         "designed",
        r"\bbonus\b":                 "extra",
        r"\b5[\s-]?star[s]?\b":       "highly rated",
    }
    for pat, rep in replacements.items():
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    # Hard-strip the rest (price, urls, amazon/kindle, reviews, %off…)
    for pat in _BANNED_PATTERNS:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", out).strip(" ,.-")


def _compliance_flags(modules: List[Dict]) -> List[str]:
    """Return human-readable warnings if any banned pattern slipped through."""
    flags = []
    blob = json.dumps(modules).lower()
    for pat in _BANNED_PATTERNS:
        if re.search(pat, blob):
            flags.append(pat)
    return flags


def _extract_audience(text: str) -> str:
    m = re.search(r"\bfor\s+([a-z][a-z\s&]{2,40})", text.lower())
    return m.group(1).strip() if m else ""


def generate_aplus_content(
    listing: Dict,
    anthropic_key: str,
    status_cb=None,
) -> List[Dict]:
    """
    Generate a KDP-compliant, ultra-marketing 5-module A+ layout.
    Each module carries: kind, kdp_module, heading, body/bullets, image specs
    (label + exact px), and an AI image prompt for each image slot.
    """
    if not anthropic_key:
        return []
    try:
        import anthropic
    except ImportError:
        return []

    title    = listing.get("title", "")
    subtitle = listing.get("subtitle", "")
    desc     = listing.get("description", "")
    niche    = listing.get("niche", "")
    p_type   = listing.get("product_type", "book")
    pages    = listing.get("page_count", "")
    audience = _extract_audience(f"{title} {subtitle}") or "general readers"

    # Build a compact spec brief so Claude knows each module's exact limits.
    spec_brief = "\n".join(
        f"  - {k} → KDP «{v['kdp_module']}» · heading ≤{v['heading_max']}c"
        + (f" · body ≤{v['body_max']}c" if v['body_max'] else "")
        + (f" · {len(v['images'])} image(s)" if v['images'] else " · no image")
        + (f" · {sum(1 for _ in v['images'])} caption(s) ≤{v['bullet_max']}c" if v['bullet_max'] else "")
        for k, v in APLUS_MODULE_SPECS.items()
    )

    prompt = f"""You are an elite Amazon KDP A+ Content copywriter. Write the copy
for a 5-module A+ layout that maximises conversion for this paperback.

BOOK
  title: "{title}"
  subtitle: "{subtitle}"
  niche: "{niche}"  ·  type: {p_type}  ·  pages: {pages}
  audience: {audience}
  description (context only — DO NOT copy verbatim):
{desc[:1000]}

THE 5 MODULES (respect every character limit EXACTLY):
{spec_brief}

Return STRICT JSON — array of 5 objects in THIS order, with these keys:
[
 {{"kind":"hero_header","heading":"...","body":"...",
   "images":[{{"prompt":"vivid lifestyle scene that sells the feeling of using this book"}}]}},
 {{"kind":"three_features","heading":"...",
   "features":[{{"caption":"...","prompt":"..."}},{{"caption":"...","prompt":"..."}},{{"caption":"...","prompt":"..."}}]}},
 {{"kind":"perfect_for","heading":"...","body":"..."}},
 {{"kind":"why_stands_out","heading":"...",
   "features":[{{"caption":"...","prompt":"..."}},{{"caption":"...","prompt":"..."}},{{"caption":"...","prompt":"..."}},{{"caption":"...","prompt":"..."}}]}},
 {{"kind":"cta_closer","heading":"...","body":"...",
   "images":[{{"prompt":"warm closing banner scene"}}]}}
]

COPY RULES (CRITICAL — A+ gets REJECTED otherwise):
- ULTRA-MARKETING: lead with emotion + benefit, sensory, specific to "{niche}".
- Each "prompt" = a concrete image description (subject, mood, colours, setting)
  the user can use to generate/buy the exact image. 8-20 words.
- BANNED WORDS — never use: best seller, #1, free, guarantee, sale, discount,
  price, $, % off, shipping, warranty, refund, amazon, kindle, bonus, reviews,
  5-star, click here, URLs, time-limited claims.
- ENGLISH only. No emoji. No HTML. No markdown fences. Respect char limits.
- Return ONLY the JSON array."""

    client = anthropic.Anthropic(api_key=anthropic_key)
    if status_cb:
        status_cb("✨ Génération A+ Content ultra-marketing (5 modules KDP)...")
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return _assemble_modules(data, status_cb)
    except Exception as e:
        logger.warning(f"A+ Content generation failed: {e}")
        if status_cb:
            status_cb(f"⚠️ A+ Content skipped: {e}")
        return []


def _assemble_modules(data: List[Dict], status_cb=None) -> List[Dict]:
    """Merge Claude copy with the fixed KDP specs (dimensions + caps) + sanitize."""
    out: List[Dict] = []
    for item in data:
        kind = item.get("kind", "")
        spec = APLUS_MODULE_SPECS.get(kind)
        if not spec:
            continue
        mod: Dict = {
            "kind":       kind,
            "kdp_module": spec["kdp_module"],
            "purpose":    spec["purpose"],
            "heading":    _clip(_sanitize(item.get("heading", "")), spec["heading_max"]),
        }
        if spec["body_max"]:
            mod["body"] = _clip(_sanitize(item.get("body", "")), spec["body_max"])
        # Image slots with exact dimensions + per-slot prompt
        img_specs = spec["images"]
        feats = item.get("features") or []
        imgs  = item.get("images") or []
        image_slots = []
        for idx, (label, w, h) in enumerate(img_specs):
            # caption from features (three/four modules) ; prompt from features or images
            caption = ""
            prompt  = ""
            if feats and idx < len(feats):
                caption = _clip(_sanitize(feats[idx].get("caption", "")), spec["bullet_max"] or 150)
                prompt  = str(feats[idx].get("prompt", ""))[:200]
            elif imgs and idx < len(imgs):
                prompt = str(imgs[idx].get("prompt", ""))[:200]
            image_slots.append({
                "label":   label,
                "width":   w,
                "height":  h,
                "dimensions": f"{w}×{h}px",
                "caption": caption,
                "prompt":  prompt,
            })
        mod["images"] = image_slots
        out.append(mod)
    if status_cb:
        flags = _compliance_flags(out)
        if flags:
            status_cb(f"⚠️ A+ compliance: {len(flags)} terme(s) à vérifier")
        else:
            status_cb("✅ A+ Content conforme KDP (aucun terme interdit)")
    return out


def attach_aplus(listing_path: Path, modules: List[Dict]) -> None:
    """Persist A+ modules into listing.json under 'aplus_content'."""
    try:
        data = json.loads(Path(listing_path).read_text(encoding="utf-8"))
        data["aplus_content"] = modules
        Path(listing_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"attach_aplus failed: {e}")


def render_module_text(module: Dict) -> str:
    """Plain-text version of a module ready to paste into KDP's A+ editor."""
    parts = []
    if module.get("kdp_module"):
        parts.append(f"[KDP module: {module['kdp_module']}]")
    if module.get("heading"):
        parts.append(module["heading"].upper())
        parts.append("")
    if module.get("body"):
        parts.append(module["body"])
        parts.append("")
    for slot in module.get("images", []):
        if slot.get("caption"):
            parts.append(f"• {slot['caption']}")
    if any(s.get("caption") for s in module.get("images", [])):
        parts.append("")
    # Image specs
    for slot in module.get("images", []):
        line = f"[Image «{slot['label']}» — {slot['dimensions']}]"
        if slot.get("prompt"):
            line += f"  →  {slot['prompt']}"
        parts.append(line)
    return "\n".join(parts).strip()


def generate_aplus_images(
    modules: List[Dict],
    listing: Dict,
    output_dir: Path,
    openai_key: str = "",
    status_cb=None,
    max_images: int = 12,
) -> List[Dict]:
    """
    Render every A+ image at its EXACT KDP dimensions, ready to upload.
      - With an OpenAI key: DALL-E lifestyle image per slot, then ImageOps.fit
        crops to the precise (w,h) — no distortion.
      - Without a key: a clean branded gradient (cover palette) at exact size.
    Saves JPG (RGB, ≤2 MB) into {output_dir}/aplus_images/. Returns manifest
    with the saved file path per image.
    """
    from PIL import Image, ImageOps, ImageDraw, ImageFont
    out_dir = Path(output_dir) / "aplus_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    def s(m):
        if status_cb: status_cb(m)

    # Palette for fallback gradient (derive from cover if present)
    base_rgb = (28, 42, 74)
    accent_rgb = (210, 180, 120)

    # A+ images use gpt-image-1 DIRECTLY (≈30-40s, good quality) instead of the
    # cover fallback chain — gpt-image-2 high can take 140s+ and we render up to
    # 9 images, so speed matters more than the marginal quality gain here.
    client = None
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key, timeout=90.0, max_retries=0)
        except Exception:
            client = None

    def _fast_dalle(prompt_text: str):
        if not client:
            return None
        import base64
        from io import BytesIO
        for model, size in [("gpt-image-1", "1024x1024")]:
            try:
                resp = client.images.generate(model=model, prompt=prompt_text[:1000],
                                               n=1, size=size, quality="high")
                b64 = resp.data[0].b64_json
                if b64:
                    return Image.open(BytesIO(base64.b64decode(b64)))
                url = getattr(resp.data[0], "url", None)
                if url:
                    import requests
                    return Image.open(BytesIO(requests.get(url, timeout=30).content))
            except Exception as e:
                logger.warning(f"A+ dalle ({model}) failed: {e}")
        return None

    manifest = aplus_image_manifest(modules)
    saved = []
    for i, img in enumerate(manifest):
        if i >= max_images:
            break
        w, h = img["width"], img["height"]
        fname = f"{img['module'].lower().replace(' ', '_')[:24]}_{i}_{w}x{h}.jpg"
        fpath = out_dir / fname
        try:
            pil = None
            if client and img.get("prompt"):
                s(f"🎨 A+ image {i+1}/{min(len(manifest), max_images)} ({w}×{h}) via DALL-E...")
                full = (f"Marketing lifestyle image for a book A+ page. {img['prompt']}. "
                        "Clean, bright, professional, NO text, NO words, NO logos, "
                        "high-quality photography style, RGB.")
                pil = _fast_dalle(full)
            if pil is None:
                # Branded gradient fallback at exact size
                pil = Image.new("RGB", (w, h), base_rgb)
                d = ImageDraw.Draw(pil)
                for y in range(h):
                    t = y / max(h, 1)
                    r = int(base_rgb[0] + (accent_rgb[0]-base_rgb[0]) * t * 0.5)
                    g = int(base_rgb[1] + (accent_rgb[1]-base_rgb[1]) * t * 0.5)
                    b = int(base_rgb[2] + (accent_rgb[2]-base_rgb[2]) * t * 0.5)
                    d.line([(0, y), (w, y)], fill=(r, g, b))
            # Crop-to-fill at EXACT dimensions (no distortion)
            pil = ImageOps.fit(pil.convert("RGB"), (w, h), method=Image.LANCZOS)
            # Save JPG, RGB, compress to stay well under 2 MB
            q = 88
            pil.save(fpath, "JPEG", quality=q, optimize=True)
            while fpath.stat().st_size > 2_000_000 and q > 50:
                q -= 8
                pil.save(fpath, "JPEG", quality=q, optimize=True)
            rec = dict(img); rec["file"] = str(fpath); rec["bytes"] = fpath.stat().st_size
            saved.append(rec)
        except Exception as e:
            logger.warning(f"A+ image {i} failed: {e}")
    s(f"✅ {len(saved)} image(s) A+ générée(s) aux dimensions exactes → {out_dir.name}/")
    return saved


def aplus_image_manifest(modules: List[Dict]) -> List[Dict]:
    """Flat list of every image the user must create, with exact dimensions +
    prompt. Drives the optional image auto-generator and the UI checklist."""
    out = []
    for m in modules:
        for slot in m.get("images", []):
            out.append({
                "module":     m.get("kdp_module", m.get("kind")),
                "label":      slot["label"],
                "width":      slot["width"],
                "height":     slot["height"],
                "dimensions": slot["dimensions"],
                "prompt":     slot.get("prompt", ""),
                "caption":    slot.get("caption", ""),
            })
    return out
