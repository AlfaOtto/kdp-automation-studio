"""
Book mockup generator — turns the REAL cover + interior into professional 3D
mockups for A+ Content credibility.

Why: generic DALL-E lifestyle shots look fake. A 3D render of the ACTUAL book
(exact cover, exact interior pages) is what makes a listing credible.

Pipeline:
  1. extract_front_cover()  — crop the exact front panel (with title) from the
     full-wrap cover.pdf using the official KDP layout dims (no distortion).
  2. extract_interior_pages() — render real interior pages at high DPI.
  3. make_mockups() — compose:
       • standing_3d   : angled paperback (front + page-thickness + spine + shadow)
       • flat_shadow   : front flat with page block + soft shadow (clean)
       • open_book     : two real interior pages as an open spread
       • stack         : a few copies stacked
     All on transparent PNG so they drop onto any Canva template / A+ background.

Everything is local (Pillow + PyMuPDF) — no external API, no quality loss.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)


# ── Extraction (exact, no defects) ───────────────────────────────────────────
def extract_front_cover(cover_pdf: Path, listing: Dict, dpi: int = 300) -> Image.Image:
    """
    Render cover.pdf and crop the EXACT front panel (with title), using the
    official KDP layout so there is zero distortion or wrong-panel cropping.
    """
    import fitz
    from modules.creation.cover_generator import cover_dims

    page_count = int(listing.get("page_count") or 100)
    trim_w = float(listing.get("trim_size_w", 6.0))
    trim_h = float(listing.get("trim_size_h", 9.0))
    paper  = str(listing.get("paper_type", "white")).lower()
    dims = cover_dims(page_count, trim_w, trim_h, paper)

    doc = fitz.open(str(cover_pdf))
    page = doc[0]
    # Render whole wrap at dpi
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    mode = "RGBA" if pix.alpha else "RGB"
    full = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")
    doc.close()

    # Crop front panel in pixels (front_x_in → +trim_w, bleed_in → +trim_h)
    x0 = int(dims["front_x_in"] * dpi)
    y0 = int(dims["bleed_in"] * dpi)
    x1 = int((dims["front_x_in"] + trim_w) * dpi)
    y1 = int((dims["bleed_in"] + trim_h) * dpi)
    # Clamp to image bounds
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(full.width, x1), min(full.height, y1)
    front = full.crop((x0, y0, x1, y1))
    return front


def export_cover_for_canva(cover_pdf: Path, listing: Dict, output_dir: Path,
                           dpi: int = 300) -> Path:
    """Save the EXACT front cover (with title, no defects) as a high-res PNG
    ready to upload into Canva's Smartmockups app. Returns the file path."""
    front = extract_front_cover(Path(cover_pdf), listing, dpi=dpi)
    out = Path(output_dir) / "cover_for_canva.png"
    front.save(out, "PNG", optimize=True)
    return out


def export_interior_for_canva(interior_pdf: Path, output_dir: Path,
                              page: int = 8, dpi: int = 300) -> Optional[Path]:
    """Save one real interior page as a high-res PNG for an open-book mockup."""
    pages = extract_interior_pages(Path(interior_pdf), [page], dpi=dpi)
    if not pages:
        return None
    out = Path(output_dir) / "interior_for_canva.png"
    pages[0].save(out, "PNG", optimize=True)
    return out


def extract_interior_pages(interior_pdf: Path, pages: List[int], dpi: int = 200) -> List[Image.Image]:
    """Render specific interior pages (0-indexed) to clean RGB images."""
    import fitz
    doc = fitz.open(str(interior_pdf))
    zoom = dpi / 72.0
    out = []
    for p in pages:
        if 0 <= p < len(doc):
            pix = doc[p].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out.append(img)
    doc.close()
    return out


# ── Geometry helpers ─────────────────────────────────────────────────────────
def _quad_transform(img: Image.Image, dst_w: int, dst_h: int,
                    corners: List[Tuple[float, float]]) -> Image.Image:
    """
    Map img into a destination quad on a transparent canvas of (dst_w,dst_h).
    corners = [top-left, top-right, bottom-right, bottom-left] in dest pixels.
    Uses a perspective transform (PIL QUAD maps dest→source).
    """
    img = img.convert("RGBA")
    w, h = img.size
    tl, tr, br, bl = corners
    # PIL QUAD: for the bounding box of the dest quad, we provide the 8 source
    # coords. Simpler: use a full-canvas QUAD where the source is the whole img
    # and the quad is the 4 dest corners (as one quad covering the canvas bbox).
    canvas = Image.new("RGBA", (dst_w, dst_h), (0, 0, 0, 0))
    # Compute perspective coefficients (dest→source) and warp
    coeffs = _perspective_coeffs(
        [tl, tr, br, bl],
        [(0, 0), (w, 0), (w, h), (0, h)],
    )
    warped = img.transform((dst_w, dst_h), Image.PERSPECTIVE, coeffs,
                           Image.BICUBIC)
    canvas.alpha_composite(warped)
    return canvas


def _perspective_coeffs(dst, src):
    """Solve the 8 perspective coefficients mapping dst→src (for Image.transform)."""
    import numpy as np
    A = []
    B = []
    for (xd, yd), (xs, ys) in zip(dst, src):
        A.append([xd, yd, 1, 0, 0, 0, -xs * xd, -xs * yd])
        A.append([0, 0, 0, xd, yd, 1, -ys * xd, -ys * yd])
        B += [xs, ys]
    A = np.array(A, dtype=float)
    B = np.array(B, dtype=float)
    res = np.linalg.solve(A, B)
    return res.tolist()


def _soft_shadow(size: Tuple[int, int], quad: List[Tuple[float, float]],
                 blur: int = 22, alpha: int = 110) -> Image.Image:
    """A blurred drop shadow polygon on a transparent canvas."""
    sh = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.polygon(quad, fill=(0, 0, 0, alpha))
    return sh.filter(ImageFilter.GaussianBlur(blur))


# ── Lighting / material helpers (for realistic 3D) ──────────────────────────
def _directional_light(size: Tuple[int, int], quad: List[Tuple[float, float]],
                       strength: float = 0.45) -> Image.Image:
    """A diagonal light→shadow gradient clipped to a quad (gives the cover a
    realistic sheen: brighter top-left, darker bottom-right)."""
    w, h = size
    grad = Image.new("L", (w, h), 0)
    gd = ImageDraw.Draw(grad)
    xs = [p[0] for p in quad]; ys = [p[1] for p in quad]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span = max((x1 - x0) + (y1 - y0), 1)
    for yy in range(int(y0), int(y1)):
        # one horizontal band per row, value depends on diagonal position
        v0 = ((x0 - x0) + (yy - y0)) / span
        # draw a gradient line by sampling a few segments
        for seg in range(0, w, 8):
            t = ((seg - x0) + (yy - y0)) / span
            t = max(0.0, min(1.0, t))
            val = int(255 * (1 - t))
            gd.line([(seg, yy), (seg + 8, yy)], fill=val)
    # Clip to quad
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(quad, fill=255)
    light = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    # white highlight where grad high, dark where low
    hi = Image.new("RGBA", (w, h), (255, 255, 255, int(90 * strength)))
    lo = Image.new("RGBA", (w, h), (0, 0, 0, int(120 * strength)))
    light = Image.composite(hi, lo, grad)
    light.putalpha(Image.composite(Image.new("L", (w, h), int(110*strength)),
                                   Image.new("L", (w, h), 0), mask))
    return light.filter(ImageFilter.GaussianBlur(3))


def _contact_shadow(size, cx, cy, rw, rh, blur=40, alpha=140):
    """Soft elliptical ground-contact shadow (anchors the book to the floor)."""
    sh = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(0, 0, 0, alpha))
    return sh.filter(ImageFilter.GaussianBlur(blur))


# ── Mockups ──────────────────────────────────────────────────────────────────
def make_standing_3d(front: Image.Image, scale: int = 1300,
                     bg: Optional[Tuple[int, int, int]] = None) -> Image.Image:
    """
    Professional standing paperback: subtle perspective, a real 3D page-edge
    block on the right with many page lines + gradient, directional cover
    lighting, a soft elliptical contact shadow, and a faint floor reflection.
    """
    fw, fh = front.size
    ar = fh / fw
    bw = scale
    bh = int(bw * ar)
    pad_x = int(bw * 0.55)
    pad_y = int(bh * 0.30)
    W = bw + pad_x
    H = bh + pad_y
    canvas = Image.new("RGBA", (W, H), (*bg, 255) if bg else (0, 0, 0, 0))

    ox = int(bw * 0.10)
    oy = int(bh * 0.06)
    # Subtle right-turn perspective: right edge slightly shorter (recedes)
    persp = int(bh * 0.045)
    tl = (ox, oy)
    tr = (ox + bw, oy + persp)
    br = (ox + bw, oy + bh - persp)
    bl = (ox, oy + bh)
    front_quad = [tl, tr, br, bl]

    # 1. Contact shadow on the ground
    cx = ox + bw // 2 + int(bw * 0.04)
    cy = oy + bh + int(bh * 0.015)
    canvas.alpha_composite(_contact_shadow((W, H), cx, cy,
                                           int(bw * 0.52), int(bh * 0.045),
                                           blur=34, alpha=120))

    # 2. 3D page-edge block on the right (thick, with gradient + many lines)
    thick = int(bw * 0.085)
    pd = ImageDraw.Draw(canvas)
    pblock = [tr, (tr[0] + thick, tr[1] + int(thick*0.35)),
              (br[0] + thick, br[1] - int(thick*0.35)), br]
    pd.polygon(pblock, fill=(243, 240, 232, 255))
    # gradient + page lines (darker toward the back for depth)
    for k in range(1, 26):
        t = k / 26
        xx = tr[0] + thick * t
        shade = int(232 - 40 * t)
        y_top = tr[1] + int((tr[0]+thick - xx) * 0.0) + int(thick * 0.35 * t)
        y_bot = br[1] - int(thick * 0.35 * t)
        pd.line([(xx, tr[1] + int(thick*0.35*t)), (xx, br[1] - int(thick*0.35*t))],
                fill=(shade, shade-6, shade-16, 255), width=2)

    # 3. Front face (perspective)
    face = _quad_transform(front, W, H, front_quad)
    canvas.alpha_composite(face)

    # 4. Directional lighting sheen on the cover
    canvas.alpha_composite(_directional_light((W, H), front_quad, strength=0.4))

    # 5. Spine-edge darkening (left edge in shadow)
    spine = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spine)
    sd.polygon([tl, (tl[0] + int(bw*0.04), tl[1] + 4),
                (bl[0] + int(bw*0.04), bl[1] - 4), bl], fill=(0, 0, 0, 70))
    canvas.alpha_composite(spine.filter(ImageFilter.GaussianBlur(6)))

    # 6. Faint floor reflection
    refl = face.transpose(Image.FLIP_TOP_BOTTOM)
    refl_mask = Image.new("L", (W, H), 0)
    rm = ImageDraw.Draw(refl_mask)
    rm.rectangle([0, oy + bh, W, oy + bh + int(bh*0.22)], fill=70)
    refl.putalpha(Image.composite(refl.getchannel("A"),
                                  Image.new("L", (W, H), 0), refl_mask))
    refl = ImageOps_offset(refl, 0, 2 * (oy + bh) - oy)  # mirror below baseline
    canvas.alpha_composite(refl)
    return canvas


def make_flat_shadow(front: Image.Image, scale: int = 1300) -> Image.Image:
    """Clean front-facing paperback with realistic page block, cover sheen and
    soft contact shadow (no perspective — straight product shot)."""
    fw, fh = front.size
    ar = fh / fw
    bw = scale
    bh = int(bw * ar)
    pad = int(bw * 0.22)
    W, H = bw + pad, bh + pad
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ox, oy = pad // 2, pad // 3
    # Contact shadow
    canvas.alpha_composite(_contact_shadow((W, H), ox + bw//2, oy + bh + 8,
                                           int(bw*0.50), int(bh*0.035),
                                           blur=30, alpha=110))
    # Page block (right) with lines + gradient
    th = int(bw * 0.045)
    pd = ImageDraw.Draw(canvas)
    pd.rectangle([ox + bw, oy + 6, ox + bw + th, oy + bh - 6], fill=(243, 240, 232, 255))
    for k in range(1, 16):
        t = k / 16
        xx = ox + bw + th * t
        shade = int(232 - 36 * t)
        pd.line([(xx, oy + 8), (xx, oy + bh - 8)], fill=(shade, shade-6, shade-16, 255), width=2)
    # Front + sheen
    f = front.convert("RGBA").resize((bw, bh), Image.LANCZOS)
    canvas.alpha_composite(f, (ox, oy))
    fq = [(ox, oy), (ox+bw, oy), (ox+bw, oy+bh), (ox, oy+bh)]
    canvas.alpha_composite(_directional_light((W, H), fq, strength=0.32))
    return canvas


def ImageOps_offset(img: Image.Image, dx: int, dy: int) -> Image.Image:
    """Shift an RGBA image on a same-size transparent canvas."""
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(img, (dx, dy))
    return out


def make_open_book(pages: List[Image.Image], scale: int = 1500) -> Optional[Image.Image]:
    """Two real interior pages as an open-book spread with a center gutter."""
    if len(pages) < 2:
        return None
    left, right = pages[0], pages[1]
    ph = scale
    pw = int(ph * (left.width / left.height))
    left  = left.convert("RGBA").resize((pw, ph), Image.LANCZOS)
    right = right.convert("RGBA").resize((pw, ph), Image.LANCZOS)
    pad = int(pw * 0.18)
    canvas = Image.new("RGBA", (pw * 2 + pad, ph + pad), (0, 0, 0, 0))
    ox, oy = pad // 2, pad // 2
    # Shadow under the open book
    sh = [(ox - 6, oy + ph - 8), (ox + 2*pw + 6, oy + ph - 8),
          (ox + 2*pw - 30, oy + ph + 40), (ox + 30, oy + ph + 40)]
    canvas.alpha_composite(_soft_shadow(canvas.size, sh, blur=24, alpha=85))
    # Slight inward perspective for a real open-book feel
    persp = int(ph * 0.04)
    lq = [(ox, oy + persp), (ox + pw, oy), (ox + pw, oy + ph), (ox, oy + ph - persp)]
    rq = [(ox + pw, oy), (ox + 2*pw, oy + persp), (ox + 2*pw, oy + ph - persp), (ox + pw, oy + ph)]
    canvas.alpha_composite(_quad_transform(left,  canvas.width, canvas.height, lq))
    canvas.alpha_composite(_quad_transform(right, canvas.width, canvas.height, rq))
    # Center gutter shadow
    g = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    gd.rectangle([ox + pw - int(pw*0.04), oy, ox + pw + int(pw*0.04), oy + ph],
                 fill=(0, 0, 0, 60))
    canvas.alpha_composite(g.filter(ImageFilter.GaussianBlur(12)))
    return canvas


def make_stack(front: Image.Image, n: int = 3, scale: int = 1000) -> Image.Image:
    """A small stack of the same book (depth/credibility)."""
    fw, fh = front.size
    ar = fh / fw
    bw = scale
    bh = int(bw * ar)
    off = int(bh * 0.05)
    canvas = Image.new("RGBA", (bw + off * (n+2), bh + off * (n+3)), (0, 0, 0, 0))
    for i in range(n):
        dx = (n - 1 - i) * off
        dy = i * off
        sh = [(dx + 10, dy + bh + 6), (dx + bw + 10, dy + bh + 6),
              (dx + bw, dy + bh + off), (dx, dy + bh + off)]
        canvas.alpha_composite(_soft_shadow(canvas.size, sh, blur=14, alpha=60))
        f = front.convert("RGBA").resize((bw, bh), Image.LANCZOS)
        canvas.alpha_composite(f, (dx, dy))
    return canvas


def compose_on_background(mockup_png: Path, width: int, height: int,
                          palette: Optional[Tuple[Tuple[int,int,int], Tuple[int,int,int]]] = None,
                          out_path: Optional[Path] = None) -> Image.Image:
    """
    Place a transparent mockup centered on a clean branded gradient background,
    sized to EXACT A+ dimensions (width×height). Returns/saves a flat RGB image
    ready to upload OR to drop into a Canva template.
    """
    top = (245, 243, 238) if not palette else palette[0]
    bot = (228, 222, 210) if not palette else palette[1]
    bg = Image.new("RGB", (width, height), top)
    d = ImageDraw.Draw(bg)
    for y in range(height):
        t = y / max(height, 1)
        r = int(top[0] + (bot[0]-top[0]) * t)
        g = int(top[1] + (bot[1]-top[1]) * t)
        b = int(top[2] + (bot[2]-top[2]) * t)
        d.line([(0, y), (width, y)], fill=(r, g, b))
    mk = Image.open(mockup_png).convert("RGBA")
    # Fit the mockup to ~82% of the smaller dimension, preserve aspect
    target_h = int(height * 0.82)
    target_w = int(mk.width * target_h / mk.height)
    if target_w > width * 0.9:
        target_w = int(width * 0.9)
        target_h = int(mk.height * target_w / mk.width)
    mk = mk.resize((target_w, target_h), Image.LANCZOS)
    bg_rgba = bg.convert("RGBA")
    bg_rgba.alpha_composite(mk, ((width - target_w)//2, (height - target_h)//2))
    out = bg_rgba.convert("RGB")
    if out_path:
        q = 90
        out.save(out_path, "JPEG", quality=q, optimize=True)
        while Path(out_path).stat().st_size > 2_000_000 and q > 50:
            q -= 8
            out.save(out_path, "JPEG", quality=q, optimize=True)
    return out


# Premium light backgrounds for A+ images
_PAL_LIGHT = ((250, 249, 246), (235, 231, 223))   # cream → warm grey
_PAL_SAGE  = ((246, 248, 244), (228, 235, 226))    # soft neutral tint


def make_aplus_images_from_book(image_manifest: List[Dict], cover_pdf: Path,
                                interior_pdf: Optional[Path], listing: Dict,
                                output_dir: Path, status_cb=None) -> List[Dict]:
    """
    Build the A+ image set from the REAL book — 3D mockups + interior — on clean
    premium backgrounds, each at the EXACT dimensions required by its A+ module.
    This replaces generic DALL-E lifestyle shots with credible product imagery.

    `image_manifest` = output of aplus.aplus_image_manifest(modules): a flat list
    of {module, label, width, height, ...} slots to fill.
    """
    def s(m):
        if status_cb: status_cb(m)

    out_dir = Path(output_dir) / "aplus_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Ensure mockups exist (generate if missing)
    mk_dir = Path(output_dir) / "mockups"
    if not (mk_dir.exists() and list(mk_dir.glob("*.png"))):
        s("📕 Génération des mockups 3D (vraie couverture + intérieur)...")
        make_mockups(cover_pdf, interior_pdf, listing, output_dir, status_cb=status_cb)

    def mk(name):
        p = mk_dir / f"mockup_{name}.png"
        return p if p.exists() else None

    # Interior page thumbnails for small quadrant slots
    interior_thumbs = []
    if interior_pdf and Path(interior_pdf).exists():
        import fitz
        doc = fitz.open(str(interior_pdf)); n = len(doc); doc.close()
        idxs = [i for i in (8, 9, 20, 40) if i < n][:4]
        interior_thumbs = extract_interior_pages(Path(interior_pdf), idxs, dpi=150)

    # Rotation of book assets for variety
    big_assets   = [mk("standing_3d"), mk("open_book"), mk("flat_shadow"), mk("stack")]
    big_assets   = [a for a in big_assets if a]
    small_assets = [mk("flat_shadow"), mk("open_book"), mk("stack"), mk("standing_3d")]
    small_assets = [a for a in small_assets if a]

    saved = []
    bi = si = ti = 0
    for i, slot in enumerate(image_manifest):
        w, h = slot["width"], slot["height"]
        pal = _PAL_SAGE if w >= 900 else _PAL_LIGHT
        fname = f"aplus_{slot['module'].lower().replace(' ', '_')[:20]}_{i}_{w}x{h}.jpg"
        fpath = out_dir / fname
        try:
            is_wide = w >= 900
            is_small = max(w, h) <= 260
            # Choose the most fitting real-book asset for this slot
            if is_small and interior_thumbs:
                # tiny quadrant slot → interior page thumbnail on light bg
                thumb = interior_thumbs[ti % len(interior_thumbs)]; ti += 1
                tmp = out_dir / f"_thumb_{i}.png"
                thumb.save(tmp, "PNG")
                compose_on_background(tmp, w, h, palette=_PAL_LIGHT, out_path=fpath)
                tmp.unlink(missing_ok=True)
            elif is_wide:
                asset = (mk("open_book") if (i % 2 and mk("open_book")) else mk("standing_3d")) \
                        or (big_assets[bi % len(big_assets)] if big_assets else None)
                if asset:
                    compose_on_background(asset, w, h, palette=pal, out_path=fpath); bi += 1
            else:
                asset = small_assets[si % len(small_assets)] if small_assets else None
                if asset:
                    compose_on_background(asset, w, h, palette=_PAL_LIGHT, out_path=fpath); si += 1
            if fpath.exists():
                rec = dict(slot); rec["file"] = str(fpath); rec["bytes"] = fpath.stat().st_size
                saved.append(rec)
                s(f"🖼️ A+ image {i+1}/{len(image_manifest)} ({w}×{h}) ← vrai livre")
        except Exception as e:
            logger.warning(f"A+ mockup image {i} failed: {e}")
    s(f"✅ {len(saved)} image(s) A+ générées depuis le vrai livre → {out_dir.name}/")
    return saved


def make_mockups(cover_pdf: Path, interior_pdf: Optional[Path], listing: Dict,
                 output_dir: Path, status_cb=None) -> List[Dict]:
    """
    Generate the full mockup set from the REAL cover + interior.
    Saves transparent PNGs into {output_dir}/mockups/. Returns manifest.
    """
    def s(m):
        if status_cb: status_cb(m)

    out_dir = Path(output_dir) / "mockups"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    s("📕 Extraction de la couverture exacte (avec titre)...")
    front = extract_front_cover(Path(cover_pdf), listing, dpi=300)

    jobs = [
        ("standing_3d", lambda: make_standing_3d(front)),
        ("flat_shadow", lambda: make_flat_shadow(front)),
        ("stack",       lambda: make_stack(front)),
    ]
    if interior_pdf and Path(interior_pdf).exists():
        # Pick two facing content pages (skip front matter)
        import fitz
        doc = fitz.open(str(interior_pdf)); npages = len(doc); doc.close()
        p1 = min(8, max(0, npages - 2))
        pages = extract_interior_pages(Path(interior_pdf), [p1, p1 + 1], dpi=200)
        if len(pages) >= 2:
            jobs.append(("open_book", lambda: make_open_book(pages)))

    for name, fn in jobs:
        try:
            s(f"🎨 Mockup « {name} »...")
            img = fn()
            if img is None:
                continue
            # Trim fully-transparent margins for a tight asset
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
            fpath = out_dir / f"mockup_{name}.png"
            img.save(fpath, "PNG", optimize=True)
            saved.append({"name": name, "file": str(fpath),
                          "size": img.size, "bytes": fpath.stat().st_size})
        except Exception as e:
            logger.warning(f"mockup {name} failed: {e}")
            s(f"⚠️ Mockup {name} échoué : {e}")

    s(f"✅ {len(saved)} mockup(s) générés → {out_dir.name}/")
    return saved
