"""
EPUB / Kindle builder for HIGH-CONTENT books (recipe_book / how_to / facts).

Why EPUB for high-content specifically:
  - Color images are FREE on Kindle (paperback color printing is ~3x cost), so
    the realistic per-recipe photos / kid illustrations shine here.
  - Reflowable text = better reading on phones/tablets; Amazon rewards it.

Content is reused verbatim from the listing the PDF pipeline already produced
(_recipes / _guide / _facts / _bonus + per-item "_image" paths), so the ebook
and paperback stay perfectly in sync at $0 extra generation.
"""
from __future__ import annotations

import html
import logging
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_CSS = """
body { font-family: Georgia, serif; line-height: 1.5; }
h1 { color:#1A252F; font-size:1.5em; margin:0.6em 0 0.2em; }
h2 { color:#2b6b5a; font-size:1.15em; margin:0.8em 0 0.2em; }
.meta { color:#555; font-size:0.9em; margin:0.2em 0 0.6em; }
.nut { width:100%; border-collapse:collapse; margin:0.6em 0; }
.nut td { border:1px solid #cfd8d2; padding:5px 6px; text-align:center; font-size:0.85em; }
.nut .lab { color:#666; font-size:0.7em; }
.nut .key { background:#2b6b5a; color:#fff; }
.ings { background:#f3f6f4; border:1px solid #d5d5cd; padding:8px 12px; border-radius:6px; }
.tip { background:#f4f1e8; border:1px solid #d8d2c0; padding:8px 12px; border-radius:6px; }
img.hero { width:100%; max-height:60vh; object-fit:cover; border-radius:6px; margin:0.4em 0; }
ol, ul { margin:0.3em 0 0.6em 1.2em; }
table.plan { width:100%; border-collapse:collapse; font-size:0.8em; }
table.plan th { background:#2b6b5a; color:#fff; padding:4px; }
table.plan td { border:1px solid #d5d5cd; padding:4px; }
/* Kids fun-facts styling */
.kideyebrow { color:#F2792E; font-weight:bold; letter-spacing:2px; text-align:center;
              font-size:0.85em; margin:0.4em 0 0; font-family:Arial,Helvetica,sans-serif; }
h1.kidtitle { color:#fff; border-radius:14px; padding:0.4em 0.5em; text-align:center;
              font-family:Arial,Helvetica,sans-serif; font-size:1.4em; margin:0.2em 0 0.5em; }
.kidintro { text-align:center; font-style:italic; color:#243447; margin:0.5em 0 0.9em; }
.factcard { border-radius:16px; padding:0.8em 1em; margin:0.6em 0;
            font-family:Arial,Helvetica,sans-serif; font-size:1.05em; color:#243447; }
.factcard .factnum { display:inline-block; min-width:1.7em; height:1.7em; line-height:1.7em;
            border-radius:50%; color:#fff; text-align:center; font-weight:bold; margin-right:0.55em; }
/* Guide 'bold modern' chapter opener (matches the print PDF) */
.chopen { position:relative; color:#fff; border-radius:6px; overflow:hidden;
          padding:0.75em 0.85em 0.95em; margin:0 0 0.8em;
          font-family:Arial,Helvetica,sans-serif; }
.chopen .cheye { font-size:0.72em; font-weight:bold; letter-spacing:2px;
                 text-transform:uppercase; }
.chopen h1.chttl { color:#fff; font-size:1.55em; line-height:1.15; margin:0.18em 0 0;
                   border:0; font-family:Arial,Helvetica,sans-serif; }
.chopen .chnum { position:absolute; right:0.12em; bottom:-0.18em; font-weight:bold;
                 font-size:4.2em; line-height:1; color:rgba(255,255,255,0.18); }
/* Explanatory diagrams (match the print infographics) */
.dia { border-radius:8px; border-top:5px solid #333; padding:0.7em 0.9em 0.8em;
       margin:0.9em 0; font-family:Arial,Helvetica,sans-serif; }
.dia .diaeye { font-size:0.68em; font-weight:bold; letter-spacing:1.5px; text-transform:uppercase; }
.dia h3.diatitle { margin:0.1em 0 0.6em; font-size:1.12em; border:0; }
.diacap { font-style:italic; text-align:center; font-size:0.85em; color:#5b5b5b; margin-top:0.5em; }
.diastep { display:flex; align-items:flex-start; margin:0.45em 0; font-size:0.95em; }
.diastep .n { flex:0 0 auto; width:1.6em; height:1.6em; line-height:1.6em; border-radius:50%;
              color:#fff; text-align:center; font-weight:bold; margin-right:0.6em; }
.dialoop { font-style:italic; font-weight:bold; font-size:0.85em; margin:0.3em 0 0 2.2em; }
.diacmp { display:flex; gap:8px; flex-wrap:wrap; }
.diacmp .card { flex:1 1 40%; background:#fff; border:1px solid #dcdcdc; border-radius:6px; overflow:hidden; }
.diacmp .card .h { color:#fff; font-weight:bold; text-align:center; padding:0.4em; font-size:0.92em; }
.diacmp .card ul { margin:0.4em 0.5em 0.5em 1.2em; font-size:0.86em; }
.diapyr { text-align:center; }
.diapyr .tier { color:#fff; font-weight:bold; margin:3px auto; padding:0.4em; border-radius:4px; font-size:0.92em; }
.diatl { border-left:3px solid #333; margin-left:0.4em; padding-left:0.9em; }
.diatl .m { margin:0.4em 0; font-size:0.95em; }
.diafig { margin:0.8em 0; text-align:center; }
"""


def _esc(x) -> str:
    return html.escape(str(x or ""))


def _compress_jpeg(path: str, max_px: int = 1100, quality: int = 82):
    """Downscale + JPEG-compress an image to bytes. Keeps the EPUB small —
    Amazon charges a per-MB delivery fee on 70%-royalty ebooks, so raw 1.8 MB
    PNGs × 75 recipes (130 MB) would wipe out royalties. q82 @ ~1100px ≈ 10× smaller."""
    try:
        from PIL import Image as PILImage
        import io
        im = PILImage.open(path).convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.debug(f"jpeg compress failed: {e}")
        try:
            return Path(path).read_bytes()
        except Exception:
            return None


class _ImgPool:
    """Registers images with the book once, returns their in-epub href."""
    def __init__(self, book, epub):
        self.book, self.epub, self.seen, self.n = book, epub, {}, 0

    def add(self, path: str) -> Optional[str]:
        if not path or not os.path.exists(path):
            return None
        if path in self.seen:
            return self.seen[path]
        data = _compress_jpeg(path)
        if data is None:
            return None
        self.n += 1
        href = f"images/img_{self.n}.jpg"
        item = self.epub.EpubImage(uid=f"img_{self.n}", file_name=href,
                                   media_type="image/jpeg", content=data)
        self.book.add_item(item)
        self.seen[path] = href
        return href


def _nutrition_html(nut: Dict) -> str:
    if not nut:
        return ""
    cells = [("Calories", nut.get("calories")), ("Protein", nut.get("protein_g")),
             ("Carbs", nut.get("carbs_g")), ("Fat", nut.get("fat_g"))]
    tds = "".join(
        f"<td><b>{_esc(v)}</b><div class='lab'>{_esc(lab)}</div></td>"
        for lab, v in cells if v not in (None, "", "—"))
    key_lab = nut.get("key_nutrient_label")
    key_val = nut.get("key_nutrient_value")
    if key_lab and key_val:
        tds += (f"<td class='key'><b>{_esc(key_val)}</b>"
                f"<div class='lab'>{_esc(key_lab)}</div></td>")
    return f"<table class='nut'><tr>{tds}</tr></table>" if tds else ""


def _epub_niche_design(listing: Dict) -> Dict:
    """Reuse the interior renderer's niche palette so the EPUB matches the PDF."""
    try:
        from modules.creation.highcontent.render import _niche_design
        d = _niche_design(listing)
        return {"palette": ["#" + c.hexval()[2:] for c in d["palette"]],
                "motif": d["motif"]}
    except Exception:
        return {"palette": ["#1A3A5C", "#1F4E79", "#2C3E50", "#3E5C76",
                            "#2A5D8E", "#34495E"], "motif": "✦"}


def _lighten(hexcol: str, amt: float = 0.88) -> str:
    h = hexcol.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    r = int(r + (255 - r) * amt); g = int(g + (255 - g) * amt); b = int(b + (255 - b) * amt)
    return f"#{r:02x}{g:02x}{b:02x}"


def _diagram_html(spec: Dict, col: str, motif: str, pool) -> str:
    """Render one diagram spec as reflowable EPUB HTML (matches the PDF look)."""
    t = str(spec.get("type", "")).lower().strip()
    title = _esc(spec.get("title") or "")
    cap = spec.get("caption")
    cap_html = f"<div class='diacap'>{_esc(cap)}</div>" if cap else ""

    # illustration = AI image + caption (no panel)
    if t == "illustration" and spec.get("_image"):
        href = pool.add(spec["_image"])
        if href:
            c = f"<div class='diacap'><b>{title}.</b> {_esc(cap) if cap else ''}</div>"
            _alt = title or "Explanatory illustration"
            return f"<div class='diafig'><img class='hero' src='{href}' alt='{_alt}'/>{c}</div>"
        return ""

    head = (f"<div class='dia' style='background:{_lighten(col)};border-top-color:{col}'>"
            f"<div class='diaeye' style='color:{col}'>{motif} &#160; HOW IT WORKS</div>"
            f"<h3 class='diatitle' style='color:{col}'>{title}</h3>")

    nodes = [str(n) for n in (spec.get("nodes") or []) if str(n).strip()]
    if t in ("cycle", "process", "steps") and nodes:
        rows = "".join(
            f"<div class='diastep'><span class='n' style='background:{col}'>{i}</span>"
            f"<span>{_esc(n)}</span></div>" for i, n in enumerate(nodes, 1))
        loop = (f"<div class='dialoop' style='color:{col}'>&#8635; then repeat the cycle</div>"
                if t == "cycle" else "")
        return head + rows + loop + cap_html + "</div>"

    if t in ("comparison", "vs") and spec.get("items"):
        cards = ""
        for it in spec["items"][:3]:
            pts = "".join(f"<li>{_esc(p)}</li>" for p in (it.get("points") or [])[:6])
            cards += (f"<div class='card'><div class='h' style='background:{col}'>"
                      f"{_esc(it.get('label',''))}</div><ul>{pts}</ul></div>")
        return head + f"<div class='diacmp'>{cards}</div>" + cap_html + "</div>"

    if t == "pyramid" and nodes:
        n = len(nodes)
        tiers = ""
        for i, label in enumerate(reversed(nodes)):  # apex(narrow) → base(wide)
            w = 40 + int(55 * (i + 1) / n)
            tiers += (f"<div class='tier' style='background:{col};width:{w}%'>"
                      f"{_esc(label)}</div>")
        return head + f"<div class='diapyr'>{tiers}</div>" + cap_html + "</div>"

    if t == "timeline" and nodes:
        rows = "".join(f"<div class='m'>{_esc(n)}</div>" for n in nodes)
        return head + f"<div class='diatl' style='border-left-color:{col}'>{rows}</div>" + cap_html + "</div>"

    return ""


def build_epub(listing: Dict, product_dir: Path,
               status_cb: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """Build an EPUB from a high-content listing. Returns the file path or None."""
    def s(m):
        if status_cb:
            status_cb(m)

    try:
        from ebooklib import epub
    except Exception:
        s("⚠️ EPUB : ebooklib non installé — étape ignorée")
        return None

    product_type = listing.get("product_type", "")
    if product_type not in ("recipe_book", "how_to"):
        return None

    title = listing.get("title") or listing.get("niche") or "Untitled"
    subtitle = listing.get("subtitle") or ""
    author = listing.get("author") or listing.get("publisher") or "KDP Author"

    book = epub.EpubBook()
    book.set_identifier(f"kdp-{abs(hash(title)) % (10**10)}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    css = epub.EpubItem(uid="style", file_name="style/main.css",
                        media_type="text/css", content=_CSS)
    book.add_item(css)
    pool = _ImgPool(book, epub)

    chapters = []

    def _mk(uid: str, ch_title: str, body_html: str):
        c = epub.EpubHtml(title=ch_title, file_name=f"{uid}.xhtml", lang="en")
        c.content = (f"<html><head></head><body>{body_html}</body></html>")
        c.add_item(css)
        book.add_item(c)
        chapters.append(c)
        return c

    # Title page
    _mk("title", title,
        f"<h1>{_esc(title)}</h1>"
        f"<p class='meta'>{_esc(subtitle)}</p>"
        f"<p class='meta'>by {_esc(author)}</p>")

    # Copyright page — same legal notice as the paperback (recommended for ebooks
    # too: professional + legal protection; not required by KDP but standard).
    import datetime as _dt
    _cp_author = (listing.get("author") or listing.get("publisher_name")
                  or listing.get("publisher") or "Independent Publisher").strip()
    _year = str(_dt.date.today().year)
    _mk("copyright", "Copyright",
        f"<h1>Copyright</h1>"
        f"<p class='meta'>{_esc(_cp_author)}</p>"
        f"<h2>Copyright Disclaimer</h2>"
        f"<p>&#169; {_year} {_esc(_cp_author)}. All rights reserved. No part of this "
        f"publication may be reproduced, distributed, or transmitted in any form or by any "
        f"means &#8212; including photocopying, recording, or other electronic or mechanical "
        f"methods &#8212; without the prior written permission of the publisher, except in "
        f"the case of brief quotations embodied in reviews and certain other noncommercial "
        f"uses permitted by copyright law.</p>"
        f"<h2>Limitation of Liability</h2>"
        f"<p>The information in this publication is provided for educational and informational "
        f"purposes only. The author and publisher make no representations or warranties with "
        f"respect to the accuracy or completeness of the contents and specifically disclaim any "
        f"implied warranties of merchantability or fitness for a particular purpose. The reader "
        f"is responsible for their own safety and use of any tools, materials, and techniques "
        f"described herein. The author and publisher shall not be liable for any damages or "
        f"injuries arising from the use of this book or the information contained within.</p>")

    if product_type == "recipe_book":
        bonus = listing.get("_bonus") or {}
        # Bonus intro
        if bonus.get("intro_paragraphs"):
            body = f"<h1>{_esc(bonus.get('intro_title') or 'Quick Start')}</h1>"
            body += "".join(f"<p>{_esc(p)}</p>" for p in bonus["intro_paragraphs"])
            if bonus.get("eat_more"):
                body += "<h2>Enjoy freely</h2><ul>" + \
                    "".join(f"<li>{_esc(x)}</li>" for x in bonus["eat_more"]) + "</ul>"
            if bonus.get("eat_less"):
                body += "<h2>Limit / avoid</h2><ul>" + \
                    "".join(f"<li>{_esc(x)}</li>" for x in bonus["eat_less"]) + "</ul>"
            _mk("bonus_intro", "Quick Start", body)
        # Meal plan
        if bonus.get("meal_plan"):
            rows = "<tr><th>Day</th><th>Breakfast</th><th>Lunch</th><th>Dinner</th><th>Snack</th></tr>"
            for d in bonus["meal_plan"]:
                rows += (f"<tr><td><b>{_esc(d.get('day'))}</b></td>"
                         f"<td>{_esc(d.get('breakfast'))}</td><td>{_esc(d.get('lunch'))}</td>"
                         f"<td>{_esc(d.get('dinner'))}</td><td>{_esc(d.get('snack'))}</td></tr>")
            _mk("mealplan", "7-Day Meal Plan",
                f"<h1>Your 7-Day Meal Plan</h1><table class='plan'>{rows}</table>")
        # Shopping list
        if bonus.get("shopping_list"):
            body = "<h1>Shopping List</h1>"
            for grp in bonus["shopping_list"]:
                body += f"<h2>{_esc(grp.get('category'))}</h2><ul>" + \
                    "".join(f"<li>{_esc(it)}</li>" for it in (grp.get("items") or [])) + "</ul>"
            _mk("shopping", "Shopping List", body)
        # Recipes
        recipes = listing.get("_recipes", [])
        for i, r in enumerate(recipes, 1):
            body = f"<h1>{_esc(r.get('title'))}</h1>"
            cat = r.get("category")
            if cat:
                body += f"<p class='meta'>{_esc(cat)}</p>"
            href = pool.add(r.get("_image", ""))
            if href:
                body += (f"<img class='hero' src='{href}' "
                         f"alt='Photo of {_esc(r.get('title') or 'the finished dish')}'/>")
            if r.get("intro"):
                body += f"<p>{_esc(r['intro'])}</p>"
            body += (f"<p class='meta'>Servings: {_esc(r.get('servings'))} · "
                     f"Prep: {_esc(r.get('prep_time'))} · Cook: {_esc(r.get('cook_time'))} · "
                     f"{_esc(r.get('difficulty'))}</p>")
            body += _nutrition_html(r.get("nutrition") or {})
            body += "<h2>Ingredients</h2><div class='ings'><ul>" + \
                "".join(f"<li>{_esc(x)}</li>" for x in (r.get("ingredients") or [])) + "</ul></div>"
            body += "<h2>Instructions</h2><ol>" + \
                "".join(f"<li>{_esc(x)}</li>" for x in (r.get("steps") or [])) + "</ol>"
            if r.get("tip"):
                body += f"<p class='tip'><b>Pro tip:</b> {_esc(r['tip'])}</p>"
            _mk(f"recipe_{i}", r.get("title") or f"Recipe {i}", body)

    elif listing.get("_facts"):
        # Kid-styled: colorful fun-fact cards with numbered badges (matches the PDF).
        _kc = [("#FFF6C9", "#F2B705"), ("#D8EEFF", "#2E86DE"), ("#FFE1EA", "#EB5286"),
               ("#DCF5D6", "#3FA34D"), ("#ECE0FF", "#8E5AE0"), ("#FFE6CC", "#F2792E")]
        _band = ["#F2B705", "#2E86DE", "#EB5286", "#3FA34D", "#8E5AE0", "#F2792E"]
        for i, sec in enumerate(listing["_facts"].get("sections", []), 1):
            bc = _band[(i - 1) % len(_band)]
            body = (f"<p class='kideyebrow'>CHAPTER {i}</p>"
                    f"<h1 class='kidtitle' style='background:{bc}'>{_esc(sec.get('title'))}</h1>")
            href = pool.add(sec.get("_image", ""))
            if href:
                body += (f"<img class='hero' src='{href}' "
                         f"alt='Illustration for {_esc(sec.get('title') or 'this chapter')}'/>")
            body += "<p class='kidintro'>Get ready for some amazing facts!</p>"
            for k, fact in enumerate(sec.get("facts") or [], 1):
                bg, badge = _kc[(k - 1) % len(_kc)]
                body += (f"<div class='factcard' style='background:{bg}'>"
                         f"<span class='factnum' style='background:{badge}'>{k}</span>"
                         f"<span class='facttext'>{_esc(fact)}</span></div>")
            _mk(f"facts_{i}", sec.get("title") or f"Section {i}", body)

    elif listing.get("_anecdotes"):
        # Adult true-stories collection: part openers + elegant story cards.
        design = _epub_niche_design(listing)
        palette, motif = design["palette"], design["motif"]
        for i, sec in enumerate(listing["_anecdotes"].get("sections", []), 1):
            col = palette[(i - 1) % len(palette)]
            body = (f"<div class='chopen' style='background:{col}'>"
                    f"<div class='cheye'>{motif} &#160; PART {i}</div>"
                    f"<span class='chnum'>{i:02d}</span>"
                    f"<h1 class='chttl'>{_esc(sec.get('title'))}</h1></div>")
            for an in (sec.get("anecdotes") or []):
                if not an.get("story"):
                    continue
                if an.get("title"):
                    body += f"<h2 style='color:{col}'>{_esc(an.get('title'))}</h2>"
                body += f"<p>{_esc(an.get('story'))}</p>"
            _mk(f"part_{i}", sec.get("title") or f"Part {i}", body)

    else:
        guide = listing.get("_guide") or {}
        design = _epub_niche_design(listing)
        palette, motif = design["palette"], design["motif"]
        _dia_by_ch: Dict[int, List] = {}
        for _sp in (listing.get("_diagrams") or guide.get("diagrams") or []):
            try:
                _dia_by_ch.setdefault(int(_sp.get("chapter", 0)), []).append(_sp)
            except Exception:
                continue
        for i, c in enumerate(guide.get("chapters", []), 1):
            col = palette[(i - 1) % len(palette)]
            # PRO 'bold modern' coloured chapter opener (matches the PDF)
            body = (f"<div class='chopen' style='background:{col}'>"
                    f"<div class='cheye'>{motif} &#160; CHAPTER {i}</div>"
                    f"<span class='chnum'>{i:02d}</span>"
                    f"<h1 class='chttl'>{_esc(c.get('title'))}</h1></div>")
            href = pool.add(c.get("_image", ""))
            if href:
                body += (f"<img class='hero' src='{href}' "
                         f"alt='Illustration for {_esc(c.get('title') or 'this chapter')}'/>")
            if c.get("intro"):
                body += f"<p>{_esc(c['intro'])}</p>"
            for sec in (c.get("sections") or []):
                if sec.get("heading"):
                    body += f"<h2 style='color:{col}'>{_esc(sec['heading'])}</h2>"
                if sec.get("body"):
                    body += f"<p>{_esc(sec['body'])}</p>"
                if sec.get("steps"):
                    body += "<ol>" + "".join(f"<li>{_esc(x)}</li>" for x in sec["steps"]) + "</ol>"
            if c.get("tip"):
                _tiptxt = re.sub(r"^\s*pro\s*tip\s*:?\s*", "", str(c["tip"]), flags=re.IGNORECASE)
                body += (f"<p class='tip' style='border-left:4px solid {col}'>"
                         f"<b>Pro tip:</b> {_esc(_tiptxt)}</p>")
            for _sp in _dia_by_ch.get(i, []):
                body += _diagram_html(_sp, col, motif, pool)
            _mk(f"chapter_{i}", c.get("title") or f"Chapter {i}", body)

    if len(chapters) <= 1:
        s("⚠️ EPUB : aucun contenu high-content à embarquer")
        return None

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters

    out = Path(product_dir) / "book.epub"
    try:
        epub.write_epub(str(out), book)
        s(f"✅ EPUB créé → {out.name} ({len(chapters)} chapitres, images couleur)")
        return str(out)
    except Exception as e:
        logger.warning(f"EPUB write failed: {e}")
        s(f"⚠️ EPUB échoué : {str(e)[:100]}")
        return None
