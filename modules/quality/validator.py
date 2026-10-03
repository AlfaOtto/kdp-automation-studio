"""
Quality validator — scans a generated product and computes a 0-100 score
+ a structured list of issues with severity, code, and auto-fix availability.

Checks (each contributes points):
  ── listing.json structural ──
   - has title, subtitle, description, keywords, publisher, page_count, niche
   - title length 30-200 chars
   - subtitle length 0-200 chars
   - description length 200-4000 chars (and has HTML tags for KDP rich text)
   - exactly 7 keywords, each ≤50 chars, no duplicates
   - categories: 3 entries with valid path format, exactly 1 primary
   - product_type ∈ {journal, log, quiz, planner, coloring}
  ── PDFs ──
   - interior.pdf exists, opens, page_count matches listing.page_count (±10%)
   - cover.pdf exists, opens
   - cover dimensions match KDP spec for the page_count (full-wrap)
  ── content quality ──
   - quiz books: at least N Q&A pairs in the listing's content_sections.items
   - coloring books: at least M illustrations referenced
  ── publishing readiness ──
   - listing has the categories field needed by Module 3
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    severity:       str             # 'critical' | 'warning' | 'info'
    code:           str             # short stable id e.g. 'missing_categories'
    message:        str             # human-readable
    fix_available:  bool = False
    fix_strategy:   str  = ""       # short id used by auto_fix.py


@dataclass
class ValidationReport:
    product_slug:   str
    score:          int             # 0-100
    issues:         List[Issue] = field(default_factory=list)
    summary:        str         = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def is_publishable(self) -> bool:
        return self.critical_count == 0

    @property
    def auto_fixable(self) -> List[Issue]:
        return [i for i in self.issues if i.fix_available]

    def add(self, severity: str, code: str, message: str,
            fix_available: bool = False, fix_strategy: str = "") -> None:
        self.issues.append(Issue(severity, code, message, fix_available, fix_strategy))


# ── KDP cover dimension specs (B&W cream) ─────────────────────────────────────

_PAPER_SPINE_PER_PAGE = {
    "white":            0.002252,
    "cream":            0.0025,
    "groundwood":       0.002252,
    "color":            0.002347,
    "color standard":   0.002347,
    "premium_color":    0.002347,
    "premium color":    0.002347,
}


def _expected_cover_dims_in(page_count: int,
                            trim_w: float = 6.0,
                            trim_h: float = 9.0,
                            paper_type: str = "white") -> Tuple[float, float]:
    """Returns expected (width_in, height_in) for a full-wrap KDP cover,
    honoring the listing's trim and paper type (NOT hardcoded 6x9 white)."""
    BLEED = 0.125
    mult  = _PAPER_SPINE_PER_PAGE.get(str(paper_type).lower(), 0.002252)
    spine = round(page_count * mult, 4)
    full_w = BLEED + trim_w + spine + trim_w + BLEED
    full_h = trim_h + BLEED * 2
    return round(full_w, 4), round(full_h, 4)


# Known KDP trims for snap-to-spec when reverse-engineering from cover dims
_KNOWN_TRIMS = [
    (5.0, 8.0), (5.06, 7.81), (5.25, 8.0), (5.5, 8.5),
    (6.0, 9.0), (6.14, 9.21), (6.69, 9.61),
    (7.0, 10.0), (7.44, 9.69), (7.5, 9.25),
    (8.0, 10.0), (8.25, 6.0), (8.25, 11.0),
    (8.5, 8.5), (8.5, 11.0),
]


def derive_trim_from_cover(cover_pdf: Path, page_count: int,
                            paper_type: str = "white") -> Optional[Tuple[float, float, str]]:
    """
    Reverse-engineer (trim_w, trim_h, paper_type) from an existing cover.pdf
    given its page_count. Used to BACKFILL listings that are missing trim
    fields. Returns None if cover dims don't match any known KDP trim.
    """
    actual = _pdf_dims_in(cover_pdf)
    if not actual or not page_count:
        return None
    full_w, full_h = actual
    BLEED = 0.125
    # Try each paper type for the spine multiplier
    for ptype in (paper_type, "white", "cream", "color", "premium_color"):
        mult = _PAPER_SPINE_PER_PAGE.get(str(ptype).lower(), 0.002252)
        spine = page_count * mult
        # trim_h = full_h - 2*bleed
        trim_h_derived = round(full_h - 2 * BLEED, 3)
        # trim_w = (full_w - 2*bleed - spine) / 2
        trim_w_derived = round((full_w - 2 * BLEED - spine) / 2, 3)
        # Snap to the closest known trim within 0.06" tolerance
        for (kw, kh) in _KNOWN_TRIMS:
            if (abs(trim_w_derived - kw) < 0.06
                    and abs(trim_h_derived - kh) < 0.08):
                return (kw, kh, ptype)
    return None


def backfill_listing_page_count(product_folder: Path) -> bool:
    """Sync listing.page_count with the actual interior.pdf page count.
    Returns True if a write happened."""
    listing_p  = product_folder / "listing.json"
    interior_p = product_folder / "interior.pdf"
    if not listing_p.exists() or not interior_p.exists():
        return False
    real = _pdf_page_count(interior_p)
    if not real or real <= 0:
        return False
    try:
        import json as _json
        d = _json.loads(listing_p.read_text(encoding="utf-8"))
    except Exception:
        return False
    claimed = d.get("page_count") or 0
    if abs(int(claimed) - int(real)) <= 2:
        return False   # close enough, no need to touch
    d["page_count"] = int(real)
    try:
        import json as _json
        listing_p.write_text(_json.dumps(d, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        return True
    except Exception:
        return False


def backfill_listing_trim(product_folder: Path) -> bool:
    """
    If listing.json has page_count + cover.pdf but missing trim_size_w/h:
    derive them from cover.pdf dims and persist. Returns True if backfilled.
    """
    listing_p = product_folder / "listing.json"
    cover_p   = product_folder / "cover.pdf"
    if not listing_p.exists() or not cover_p.exists():
        return False
    try:
        import json as _json
        d = _json.loads(listing_p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if d.get("trim_size_w") and d.get("trim_size_h"):
        return False   # already set
    # ALWAYS prefer the actual interior PDF page count over the listing's
    # claim — the cover.pdf was generated using the REAL count (post-batch
    # recalibration), so deriving from listing's stale value gives wrong trim.
    interior_p = product_folder / "interior.pdf"
    page_count = 0
    if interior_p.exists():
        page_count = _pdf_page_count(interior_p) or 0
    if not page_count:
        page_count = d.get("page_count") or 0
    if not page_count:
        return False
    derived = derive_trim_from_cover(cover_p, page_count,
                                      d.get("paper_type", "white"))
    if not derived:
        return False
    tw, th, pt = derived
    d["trim_size_w"] = tw
    d["trim_size_h"] = th
    d["paper_type"]  = pt
    d["_trim_backfilled_from_cover"] = True
    try:
        import json as _json
        listing_p.write_text(_json.dumps(d, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        return True
    except Exception:
        return False


def _pdf_page_count(pdf_path: Path) -> Optional[int]:
    """Returns the number of pages in a PDF or None if it can't be opened."""
    try:
        from reportlab.pdfgen.canvas import Canvas   # noqa
        # Use a lightweight pdf parser — try pypdf, then fallback to byte counting
        try:
            from pypdf import PdfReader
            return len(PdfReader(str(pdf_path)).pages)
        except ImportError:
            pass
        # Fallback: count /Type /Page markers (rough)
        content = pdf_path.read_bytes()
        return content.count(b"/Type /Page\n") + content.count(b"/Type/Page\n") + content.count(b"/Type /Page ")
    except Exception as e:
        logger.debug(f"PDF page count failed for {pdf_path}: {e}")
        return None


def qa_interior(product_folder: Path) -> List[dict]:
    """Lightweight interior QA for a finished book. Returns a list of
    {sev: 'error'|'warning'|'ok', msg: str}. Catches the issues that lead to KDP
    'poor customer experience' flags: page-count mismatch, unexpected blank
    pages, missing images (high-content), and duplicated content blocks."""
    import json as _json
    out: List[dict] = []
    interior = Path(product_folder) / "interior.pdf"
    if not interior.exists():
        return [{"sev": "error", "msg": "interior.pdf manquant"}]
    try:
        listing = _json.loads((Path(product_folder) / "listing.json").read_text(encoding="utf-8"))
    except Exception:
        listing = {}
    pt = listing.get("product_type", "")
    hc = pt in ("recipe_book", "how_to")
    try:
        import fitz
    except Exception:
        return [{"sev": "warning", "msg": "PyMuPDF indisponible — QA intérieur ignorée"}]
    try:
        doc = fitz.open(str(interior))
    except Exception as e:
        return [{"sev": "error", "msg": f"interior.pdf illisible : {str(e)[:60]}"}]

    real = doc.page_count
    # 1) page count vs listing
    claimed = listing.get("page_count")
    if claimed and abs(real - int(claimed)) > 2:
        out.append({"sev": "warning",
                    "msg": f"Nb de pages : listing dit {claimed}, PDF réel {real}"})

    # 2) unexpected blank pages (high-content only — journals have blanks on purpose)
    if hc:
        blanks = []
        for i in range(min(4, real), real):        # skip front matter
            pg = doc[i]
            if len(pg.get_text().strip()) < 3 and not pg.get_images():
                blanks.append(i + 1)
        if blanks:
            out.append({"sev": "warning",
                        "msg": f"{len(blanks)} page(s) vide(s) inattendue(s) : "
                               f"{blanks[:8]}{'…' if len(blanks) > 8 else ''}"})

    # 3) images present? (high-content books should have interior images)
    total_imgs = sum(len(doc[i].get_images()) for i in range(real))
    if hc and total_imgs == 0:
        out.append({"sev": "warning", "msg": "Aucune image intérieure détectée"})

    # 4) duplicated content blocks (generation glitch) — high-content only
    if hc:
        from collections import Counter
        blocks = []
        for i in range(real):
            for line in doc[i].get_text().split("\n"):
                t = line.strip()
                # long blocks only → avoids flagging legit recipe/step boilerplate
                # ("Preheat the air fryer to 400°F", section headers, etc.)
                if len(t) > 70 and not t[:2].strip().isdigit():
                    blocks.append(t)
        dup = [t for t, n in Counter(blocks).items() if n >= 5]
        if dup:
            out.append({"sev": "warning",
                        "msg": f"{len(dup)} bloc(s) de texte répété(s) ≥4× "
                               f"(ex. « {dup[0][:40]}… »)"})
    doc.close()
    if not out:
        out.append({"sev": "ok", "msg": f"Intérieur OK ({real} pages, {total_imgs} image(s))"})
    return out


def _pdf_dims_in(pdf_path: Path) -> Optional[Tuple[float, float]]:
    """Returns the (width, height) of the first page in inches, or None."""
    try:
        try:
            from pypdf import PdfReader
            page = PdfReader(str(pdf_path)).pages[0]
            box  = page.mediabox
            # mediabox dimensions are in points (1 in = 72 pt)
            return (float(box.width) / 72.0, float(box.height) / 72.0)
        except ImportError:
            return None
    except Exception:
        return None


# ── Main validator ────────────────────────────────────────────────────────────

def validate_product(product_folder: Path,
                     anthropic_key: str = "",
                     deep_check: bool = False) -> ValidationReport:
    """Run all quality checks on a product folder. Returns a ValidationReport."""
    product_folder = Path(product_folder)
    report = ValidationReport(product_slug=product_folder.name, score=100)

    # ── File presence ────────────────────────────────────────────────────
    listing_path = product_folder / "listing.json"
    interior_path = product_folder / "interior.pdf"
    cover_path = product_folder / "cover.pdf"

    if not listing_path.exists():
        report.add("critical", "missing_listing", "listing.json is missing",
                   fix_available=False)
        report.score -= 40
        report.summary = "Product is missing core files."
        return report
    if not interior_path.exists():
        report.add("critical", "missing_interior", "interior.pdf is missing",
                   fix_available=True, fix_strategy="regen_interior")
        report.score -= 30
    if not cover_path.exists():
        report.add("critical", "missing_cover", "cover.pdf is missing",
                   fix_available=True, fix_strategy="regen_cover")
        report.score -= 30

    # ── Auto-backfill silent — fixes stale listings (pre-persistence) ───
    # 1) Sync page_count with real PDF (Claude often estimates wrong)
    # 2) Derive trim/paper from cover.pdf if missing (avoids fake blocker)
    try:
        if interior_path.exists():
            backfill_listing_page_count(product_folder)
        if cover_path.exists() and interior_path.exists():
            backfill_listing_trim(product_folder)
    except Exception as e:
        logger.debug(f"backfill skipped: {e}")

    # ── Parse listing.json ───────────────────────────────────────────────
    try:
        listing = json.loads(listing_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.add("critical", "malformed_listing",
                   f"listing.json is not valid JSON: {e}",
                   fix_available=False)
        report.score = max(0, report.score - 50)
        return report

    # ── Required fields ──────────────────────────────────────────────────
    for field_name in ["title", "publisher_name", "page_count", "niche", "product_type"]:
        if not listing.get(field_name):
            report.add("critical", f"missing_{field_name}",
                       f"listing.json missing required field: {field_name}",
                       fix_available=field_name in {"page_count"},
                       fix_strategy="regen_listing" if field_name != "page_count" else "infer_page_count")
            report.score -= 10

    # ── Title length + mobile truncation check ─────────────────────────
    title = listing.get("title", "")
    if title and not (10 <= len(title) <= 200):
        report.add("warning", "bad_title_length",
                   f"Title length is {len(title)} chars (KDP: 10-200 ideal)",
                   fix_available=False)
        report.score -= 5
    elif title and len(title) > 60:
        # 70% des achats Amazon sur mobile → seuls les 60 premiers chars sont visibles
        report.add("warning", "title_truncated_mobile",
                   f"Title is {len(title)} chars — only first 60 visible on mobile "
                   f"(seen: '{title[:60]}…'). Consider shortening or moving secondary "
                   "info to subtitle.",
                   fix_available=True, fix_strategy="regen_listing")
        report.score -= 4

    # ── Subtitle ─────────────────────────────────────────────────────────
    subtitle = listing.get("subtitle", "")

    # ── KDP content-block stuffing detection (HARD rejection risk) ──────
    def _stuffed(t):
        if not t: return False
        return (t.count(":") >= 2 or t.count(",") >= 2 or
                len(t) > 80)
    if _stuffed(title):
        report.add("critical", "title_stuffed",
                   f"Title has KDP content-block stuffing pattern "
                   f"(multi-colon / comma list / >80 chars). KDP will block.",
                   fix_available=True, fix_strategy="regen_listing")
        report.score -= 15
    if _stuffed(subtitle):
        report.add("warning", "subtitle_stuffed",
                   f"Subtitle has stuffing pattern (multi-colon or 3+ commas). "
                   f"Risk of content block.",
                   fix_available=True, fix_strategy="regen_listing")
        report.score -= 8

    if subtitle and len(subtitle) > 200:
        report.add("warning", "subtitle_too_long",
                   f"Subtitle is {len(subtitle)} chars (KDP max: 200)",
                   fix_available=False)
        report.score -= 3

    # ── Description ──────────────────────────────────────────────────────
    desc = (listing.get("description") or "").strip()
    if not desc:
        report.add("critical", "missing_description",
                   "Description is empty",
                   fix_available=True, fix_strategy="regen_listing")
        report.score -= 15
    elif len(desc) < 200:
        report.add("warning", "description_too_short",
                   f"Description is only {len(desc)} chars (recommended ≥200)",
                   fix_available=True, fix_strategy="regen_listing")
        report.score -= 8
    elif len(desc) > 4000:
        report.add("warning", "description_too_long",
                   f"Description is {len(desc)} chars (KDP max: 4000) — will be truncated",
                   fix_available=False)
        report.score -= 3
    elif "<" not in desc:
        report.add("info", "description_no_html",
                   "Description has no HTML tags — plain text is OK but bold/italic improves sales",
                   fix_available=False)

    # ── HTML tag safety (Amazon strips many tags silently) ──────────────
    if desc:
        import re as _re
        stripped_tags = []
        for tag in ("ul", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                    "div", "span", "style", "img", "a"):
            if _re.search(rf"<\s*{tag}\b", desc, _re.IGNORECASE):
                stripped_tags.append(tag)
        if stripped_tags:
            report.add(
                "warning", "description_invalid_html",
                f"Description uses HTML tags Amazon STRIPS silently: "
                f"{', '.join(f'<{t}>' for t in stripped_tags)}. "
                "Description will render as a wall of text on KDP. "
                "Use only <b>, <i>, <br>, <p>. Bullets: <br>• item<br>.",
                fix_available=True, fix_strategy="regen_listing",
            )
            report.score -= 6

        # Visible text length (strip tags) check — A10 conversion sweet spot 150-300 words
        visible = _re.sub(r"<[^>]+>", " ", desc)
        word_count = len(visible.split())
        if word_count > 400:
            report.add("info", "description_too_long_for_mobile",
                       f"Description visible text is {word_count} words. "
                       "Mobile readers lose interest past ~300 words. Trim for higher conversion.",
                       fix_available=False)

    # ── Subtitle vs title overlap ───────────────────────────────────────
    if subtitle and title:
        t_low = title.lower()
        sub_low = subtitle.lower()
        # Check overlapping 2-word phrases
        t_words = t_low.split()
        bigrams = [" ".join(t_words[i:i+2]) for i in range(len(t_words) - 1)]
        overlapping = [b for b in bigrams if len(b) > 6 and b in sub_low]
        if overlapping:
            report.add("info", "subtitle_repeats_title",
                       f"Subtitle repeats title phrase(s) {overlapping[:2]}. "
                       "Pros use subtitle for ADJACENT relevance (audience / "
                       "transformation / numeric promise / trope), not paraphrasing.",
                       fix_available=False)

    # ── Keywords ─────────────────────────────────────────────────────────
    keywords = listing.get("keywords", []) or []
    if len(keywords) != 7:
        report.add("warning", "wrong_keyword_count",
                   f"{len(keywords)} keywords (KDP wants exactly 7)",
                   fix_available=True, fix_strategy="fix_keywords")
        report.score -= 5
    too_long = [kw for kw in keywords if len(kw) > 50]
    if too_long:
        report.add("warning", "keyword_too_long",
                   f"{len(too_long)} keyword(s) >50 chars: {too_long[0][:40]!r}…",
                   fix_available=True, fix_strategy="fix_keywords")
        report.score -= 3
    if len(keywords) != len(set(kw.lower() for kw in keywords)):
        report.add("warning", "duplicate_keywords",
                   "Some keywords are duplicates (case-insensitive)",
                   fix_available=True, fix_strategy="fix_keywords")
        report.score -= 3

    # ── Categories (KDP requires 3) ──────────────────────────────────────
    categories = listing.get("categories", []) or []
    if not categories:
        report.add("critical", "missing_categories",
                   "No categories — required by KDP and Module 3 publisher",
                   fix_available=True, fix_strategy="gen_categories")
        report.score -= 15
    elif len(categories) < 3:
        report.add("warning", "few_categories",
                   f"Only {len(categories)} categories (KDP allows 3)",
                   fix_available=True, fix_strategy="gen_categories")
        report.score -= 8
    else:
        n_primary = sum(1 for c in categories if isinstance(c, dict) and c.get("primary"))
        if n_primary == 0:
            report.add("warning", "no_primary_category",
                       "No category marked as primary",
                       fix_available=True, fix_strategy="fix_primary_category")
            report.score -= 3
        elif n_primary > 1:
            report.add("warning", "multiple_primary",
                       f"{n_primary} categories marked primary (should be 1)",
                       fix_available=True, fix_strategy="fix_primary_category")
            report.score -= 3
        # Validate path format
        for c in categories[:3]:
            if isinstance(c, dict):
                path = c.get("path", "")
            else:
                path = str(c)
            if " > " not in path:
                report.add("warning", "bad_category_path",
                           f"Category path missing ' > ' separator: {path[:60]!r}",
                           fix_available=True, fix_strategy="gen_categories")
                report.score -= 2

    # ── Product type ─────────────────────────────────────────────────────
    valid_types = {"journal", "log", "quiz", "planner", "coloring",
                   "puzzle", "activity_book"}
    ptype = listing.get("product_type", "")
    if ptype and ptype not in valid_types:
        report.add("warning", "unknown_product_type",
                   f"product_type={ptype!r} not in {valid_types}",
                   fix_available=False)
        report.score -= 3

    # ── Interior PDF checks ──────────────────────────────────────────────
    if interior_path.exists():
        size_kb = interior_path.stat().st_size // 1024
        if size_kb < 10:
            report.add("critical", "interior_tiny",
                       f"interior.pdf is suspiciously small ({size_kb} KB)",
                       fix_available=True, fix_strategy="regen_interior")
            report.score -= 20
        actual_pages = _pdf_page_count(interior_path)
        claimed_pages = listing.get("page_count")
        if actual_pages and claimed_pages:
            delta_pct = abs(actual_pages - claimed_pages) / claimed_pages * 100
            if delta_pct > 25:
                report.add("warning", "page_count_mismatch",
                           f"Interior has {actual_pages} pages but listing claims {claimed_pages} "
                           f"({delta_pct:.0f}% mismatch — risk of disappointed buyers)",
                           fix_available=False)
                report.score -= 8

    # ── Cover PDF checks ─────────────────────────────────────────────────
    if cover_path.exists():
        size_kb = cover_path.stat().st_size // 1024
        if size_kb < 50:
            report.add("critical", "cover_tiny",
                       f"cover.pdf is suspiciously small ({size_kb} KB)",
                       fix_available=True, fix_strategy="regen_cover")
            report.score -= 15
        # Dimension check — uses ACTUAL interior PDF page count + listing
        # trim/paper. SKIP entirely if listing doesn't define trim
        # (would generate a false-positive blocker vs the 6×9 fallback).
        has_trim = bool(listing.get("trim_size_w") and listing.get("trim_size_h"))
        if not has_trim:
            report.add(
                "info", "trim_unknown",
                "Trim non défini dans listing.json — dim check sauté. "
                "Ouvre 🔧 Fix dimensions cover pour le définir + persister.",
                fix_available=True, fix_strategy="regen_cover",
            )
        trim_w     = float(listing.get("trim_size_w") or 6.0)
        trim_h     = float(listing.get("trim_size_h") or 9.0)
        paper_type = str(listing.get("paper_type") or "white")
        # Prefer the actual interior PDF page count (claimed value can be stale)
        if interior_path.exists():
            real_pc = _pdf_page_count(interior_path)
            page_count = real_pc if (real_pc and real_pc > 0) else listing.get("page_count")
        else:
            page_count = listing.get("page_count")
        if page_count and has_trim:
            expected = _expected_cover_dims_in(page_count, trim_w, trim_h, paper_type)
            actual   = _pdf_dims_in(cover_path)
            if expected and actual:
                w_off = abs(actual[0] - expected[0])
                h_off = abs(actual[1] - expected[1])
                if w_off > 0.05 or h_off > 0.05:
                    report.add(
                        "critical" if (w_off > 0.1 or h_off > 0.1) else "warning",
                        "cover_dims_off",
                        f"Cover is {actual[0]:.3f}×{actual[1]:.3f}\" "
                        f"but KDP expects {expected[0]:.3f}×{expected[1]:.3f}\" "
                        f"for {page_count}p · trim {trim_w}×{trim_h} · {paper_type} — "
                        f"KDP will reject (delta W {w_off:+.3f}\", H {h_off:+.3f}\")",
                        fix_available=True, fix_strategy="regen_cover")
                    report.score -= 12 if (w_off > 0.1 or h_off > 0.1) else 8

    # ── Cover visual quality (PyMuPDF rendering + analysis) ─────────────
    if cover_path.exists():
        try:
            from modules.quality.visual import analyze_cover
            visual = analyze_cover(cover_path)
            for sev, code, msg in visual.issues:
                fix_avail = code in {"cover_unreadable", "cover_too_dark",
                                     "cover_washed_out", "cover_low_contrast",
                                     "cover_monochrome_grey",
                                     "cover_unreadable_thumbnail"}
                report.add(sev, code, msg,
                           fix_available=fix_avail,
                           fix_strategy="regen_cover" if fix_avail else "")
                if sev == "critical":
                    report.score -= 15
                elif sev == "warning":
                    report.score -= 5
                else:
                    report.score -= 1
        except Exception as e:
            logger.debug(f"Cover visual analysis failed: {e}")

    # ── Deep cover check: Claude Vision genre signaling (opt-in) ────────
    if deep_check and cover_path.exists() and anthropic_key:
        try:
            from modules.quality.genre_signal import check_genre_signal
            gs = check_genre_signal(
                cover_path,
                product_type=ptype or "book",
                niche=listing.get("niche", ""),
                anthropic_key=anthropic_key,
            )
            if gs.get("ok"):
                listing["_genre_signal"] = gs   # surfaced in UI if needed
                score = gs.get("score", 100)
                if score < 45:
                    report.add(
                        "warning", "cover_genre_signal_weak",
                        f"Claude Vision: {gs.get('critique','')} (signal {score:.0f}/100)",
                        fix_available=True, fix_strategy="regen_cover",
                    )
                    report.score -= 8
                elif score < 65:
                    report.add(
                        "info", "cover_genre_signal_meh",
                        f"Cover signaling moyen ({score:.0f}/100) — {gs.get('critique','')}",
                        fix_available=False,
                    )
        except Exception as e:
            logger.debug(f"genre_signal deep check failed: {e}")

    # ── Content section quality (quiz / coloring) ────────────────────────
    sections = listing.get("content_sections", []) or []
    if ptype == "quiz":
        total_qa = 0
        for sec in sections:
            if sec.get("type") in ("qa", "content"):
                items = sec.get("items", []) or []
                total_qa += sum(1 for i in items if isinstance(i, str) and i.startswith("Q:"))
        target_qa = max(20, listing.get("page_count", 100) // 2)
        if total_qa < target_qa * 0.5:
            report.add("warning", "quiz_thin",
                       f"Quiz has only {total_qa} Q&A pairs (target ≥{target_qa}) — book will feel empty",
                       fix_available=True, fix_strategy="regen_interior")
            report.score -= 8

    # ── Clamp + summary ──────────────────────────────────────────────────
    report.score = max(0, min(100, report.score))
    if report.critical_count > 0:
        report.summary = f"❌ {report.critical_count} blocker(s) — NOT publishable as-is"
    elif report.warning_count > 0:
        report.summary = f"⚠️ {report.warning_count} warning(s) — publishable but could be improved"
    else:
        report.summary = "✅ All checks passed — ready to publish"

    return report
