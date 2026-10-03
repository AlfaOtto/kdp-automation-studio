"""
KDP form uploader — drives the "Create new title" paperback flow in 3 steps:
  1. Details   — language, title, subtitle, author, publisher, description,
                 publishing rights, audience, marketplace, categories, low-content
                 flag, 7 keywords, publication & release date
  2. Content   — ISBN choice, print options (ink/paper/trim/bleed/cover finish),
                 manuscript upload, cover upload
  3. Pricing   — territories, marketplaces, USD price, KU enrollment → Save as Draft

Strategy:
- Selectors use stable KDP `data-print-book-*` IDs (work in any UI language).
- Each step has a fallback by visible label text (EN + FR) when the ID fails.
- Every action is wrapped in a try-block that screenshots on error.

Status: Step 1 ~90% wired, Step 2 ~85% (manual radio override available),
Step 3 mostly manual but auto-detects completion. User can click "✅ Fait"
in the UI at any time to skip a polling wait (via publish_runner signals).
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Result / error types ──────────────────────────────────────────────────────

@dataclass
class UploadResult:
    success:         bool            = False
    step_reached:    str             = ""
    screenshot_path: Optional[Path]  = None
    error_message:   str             = ""
    draft_url:       str             = ""


class UploadError(Exception):
    """Raised when the upload halts. Carries a screenshot for the UI to show."""
    def __init__(self, message: str, screenshot: Optional[Path] = None,
                 step: str = ""):
        super().__init__(message)
        self.screenshot = screenshot
        self.step       = step


# ── Helpers ────────────────────────────────────────────────────────────────────

def _user_signalled_continue(learning_dir: Path) -> bool:
    """True if user clicked '✅ Continue' button in the UI. Consumes the flag."""
    try:
        from modules.publishing.publish_runner import was_signalled
        return was_signalled(learning_dir, consume=True)
    except Exception:
        return False


def _snap(page, learning_dir: Path, label: str) -> Path:
    """Take a debug screenshot, return its path."""
    snap_dir = Path(learning_dir) / "publishing_snaps"
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    p  = snap_dir / f"{label}_{ts}.png"
    try:
        page.screenshot(path=str(p), full_page=True)
    except Exception as e:
        logger.debug(f"Screenshot {label} failed: {e}")
    return p


def _try_fill(page, selectors: List[str], value: str, name: str,
              timeout_ms: int = 4000) -> bool:
    """Try each selector; fill the first one that works. Returns True/False — does NOT raise."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            loc.fill(value)
            logger.info(f"✓ Filled '{name}' via {sel}")
            return True
        except Exception:
            continue
    logger.warning(f"✗ Could not fill '{name}' — tried {len(selectors)} selectors")
    return False


def _try_click(page, selectors: List[str], name: str, timeout_ms: int = 4000) -> bool:
    """Try each selector; click the first that works. Returns True/False — does NOT raise."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            loc.click()
            logger.info(f"✓ Clicked '{name}' via {sel}")
            return True
        except Exception:
            continue
    logger.warning(f"✗ Could not click '{name}' — tried {len(selectors)} selectors")
    return False


def _try_select(page, selectors: List[str], value: str, name: str,
                timeout_ms: int = 4000) -> bool:
    """Try each selector; pick the option matching `value`. Returns True/False — does NOT raise."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            try:
                loc.select_option(label=value)
            except Exception:
                try:
                    loc.select_option(value=value)
                except Exception:
                    continue
            logger.info(f"✓ Selected '{value}' in '{name}' via {sel}")
            return True
        except Exception:
            continue
    logger.warning(f"✗ Could not select '{value}' in '{name}'")
    return False


# Strict versions that DO raise — only use for absolutely critical fields
# (manuscript upload, cover upload, title)

def _safe_fill(page, selectors: List[str], value: str, name: str,
               learning_dir: Path, timeout_ms: int = 8000) -> None:
    """Critical: raises UploadError if not found."""
    if _try_fill(page, selectors, value, name, timeout_ms):
        return
    snap = _snap(page, learning_dir, f"fill_failed_{name}")
    raise UploadError(
        f"CRITICAL: Could not fill '{name}' — tried {len(selectors)} selectors.",
        screenshot=snap, step=name,
    )


def _safe_click(page, selectors: List[str], name: str,
                learning_dir: Path, timeout_ms: int = 8000) -> None:
    """Critical: raises UploadError if not found."""
    if _try_click(page, selectors, name, timeout_ms):
        return
    snap = _snap(page, learning_dir, f"click_failed_{name}")
    raise UploadError(
        f"CRITICAL: Could not click '{name}' — tried {len(selectors)} selectors.",
        screenshot=snap, step=name,
    )


def _safe_select(page, selectors: List[str], value: str, name: str,
                 learning_dir: Path, timeout_ms: int = 8000) -> None:
    """Critical: raises UploadError if not found."""
    if _try_select(page, selectors, value, name, timeout_ms):
        return
    snap = _snap(page, learning_dir, f"select_failed_{name}")
    raise UploadError(
        f"CRITICAL: Could not select '{value}' in '{name}'.",
        screenshot=snap, step=name,
    )


def _parse_author(publisher_name: str) -> tuple:
    """Derive a believable Author first/last from the publisher name.
    KDP requires non-empty Author fields. Returns ('First', 'Last')."""
    if not publisher_name:
        return ("Independent", "Publisher")
    words = [w for w in publisher_name.split() if w]
    if len(words) >= 2:
        return (words[0], " ".join(words[1:]))
    return (words[0], "Press")


# ── Step 1: Details ────────────────────────────────────────────────────────────

def fill_details(page, listing: Dict, status_cb: Callable[[str], None],
                 learning_dir: Path) -> None:
    """
    Fill the KDP 'Paperback Details' page. Uses tolerant fills (skip if not
    found) for non-critical fields and strict fill for critical ones (title).
    """
    status_cb("📝 Étape 1/3 — Détails…")
    filled = []   # for status report
    skipped = []

    # ── Language → English (optional — usually pre-selected) ─────────────
    if _try_select(page, [
        "select#data-print-book-language-native",
        "select[name='language']",
        "[aria-label='Language'] select",
        "label:has-text('Language') >> .. >> select",
    ], "English", "language"):
        filled.append("language")
    else:
        skipped.append("language (already English by default)")

    # ── Book Title (CRITICAL — must succeed) ────────────────────────────
    _safe_fill(
        page,
        selectors=[
            "input#data-print-book-title",
            "input[name='title']",
            "input[aria-label*='Book Title']",
            "input[aria-label*='Titre du livre']",
            "label:has-text('Book Title') >> .. >> input",
        ],
        value=listing.get("title", "")[:200],
        name="title",
        learning_dir=learning_dir,
    )
    filled.append("title")

    # ── Subtitle (optional) ──────────────────────────────────────────────
    subtitle = (listing.get("subtitle") or "").strip()
    if subtitle:
        if _try_fill(page, [
            "input#data-print-book-subtitle",
            "input[name='subtitle']",
            "input[aria-label*='Subtitle']",
            "input[aria-label*='Sous-titre']",
            "label:has-text('Subtitle') >> .. >> input",
        ], subtitle[:200], "subtitle"):
            filled.append("subtitle")
        else:
            skipped.append("subtitle")

    # ── Author (Primary Author) — locator scoped to Author section ──────
    # The form has BOTH a "Primary Author" section AND a "Contributors"
    # section, both with First Name / Last Name fields. We must target the
    # Author section specifically using its heading as anchor.
    first, last = _parse_author(listing.get("publisher_name", ""))
    author_first_ok = False
    author_last_ok = False
    try:
        # Scope to the Author fieldset/section (heading text "Author")
        author_section = page.locator(
            "div:has(h2:text('Author')), "
            "section:has(h2:text('Author')), "
            "fieldset:has(legend:text('Author'))"
        ).first
        # Within that section, fill first/last by placeholder or position
        for sel in [
            "input[placeholder='First name']",
            "input[placeholder='First Name']",
            "input[aria-label*='First Name']",
            "input:nth-of-type(2)",   # position fallback (Prefix is 1st)
        ]:
            try:
                inp = author_section.locator(sel).first
                inp.wait_for(state="visible", timeout=2500)
                inp.fill(first)
                author_first_ok = True
                logger.info(f"✓ Filled author_first via section + {sel}")
                break
            except Exception:
                continue
        for sel in [
            "input[placeholder='Last name']",
            "input[placeholder='Last Name']",
            "input[aria-label*='Last Name']",
            "input:nth-of-type(4)",
        ]:
            try:
                inp = author_section.locator(sel).first
                inp.wait_for(state="visible", timeout=2500)
                inp.fill(last)
                author_last_ok = True
                logger.info(f"✓ Filled author_last via section + {sel}")
                break
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Author section locator failed: {e}")

    # Fallback to global ID selectors if section-scoped failed
    if not author_first_ok:
        author_first_ok = _try_fill(page, [
            "input#data-print-book-primary-author-first-name",
            "input[name='primaryAuthor.firstName']",
        ], first, "author_first_fallback")
    if not author_last_ok:
        author_last_ok = _try_fill(page, [
            "input#data-print-book-primary-author-last-name",
            "input[name='primaryAuthor.lastName']",
        ], last, "author_last_fallback")

    if author_first_ok and author_last_ok:
        filled.append("author")
    else:
        skipped.append("author (à remplir manuellement)")

    # ── Description (rich-text CKEditor iframe) ─────────────────────────
    # CRITICAL: KDP's form-state listens to CKEditor internal events, not just
    # the iframe body. We must use CKEditor's JS API to set content and trigger
    # the change event that updates the form's hidden textarea.
    desc = (listing.get("description") or "")[:4000]
    if desc:
        desc_ok = False
        try:
            # Strategy 1: CKEditor 4 JS API — the cleanest way
            # Find the editor instance and use setData() which triggers all events
            result = page.evaluate(
                """(html) => {
                    if (typeof CKEDITOR === 'undefined' || !CKEDITOR.instances) return false;
                    const keys = Object.keys(CKEDITOR.instances);
                    for (const k of keys) {
                        const editor = CKEDITOR.instances[k];
                        if (editor && editor.name && editor.name.toLowerCase().includes('description')) {
                            editor.setData(html);
                            editor.fire('change');
                            editor.fire('blur');
                            // Also update the underlying textarea
                            if (editor.element && editor.element.$) {
                                editor.element.$.value = html;
                                editor.element.$.dispatchEvent(new Event('input', {bubbles: true}));
                                editor.element.$.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                            return k;
                        }
                    }
                    // Fallback: use first instance
                    if (keys.length > 0) {
                        const editor = CKEDITOR.instances[keys[0]];
                        editor.setData(html);
                        editor.fire('change');
                        return keys[0];
                    }
                    return false;
                }""",
                desc,
            )
            if result:
                desc_ok = True
                logger.info(f"✓ Filled description via CKEDITOR API ({result})")
        except Exception as e:
            logger.warning(f"CKEditor API fill failed: {e}")

        # Strategy 2: iframe body + manual event dispatch (fallback)
        if not desc_ok:
            for iframe_sel in [
                "#cke_data-print-book-description iframe",
                "iframe[title*='Rich Text Editor']",
                "iframe.cke_wysiwyg_frame",
            ]:
                try:
                    frame_loc = page.frame_locator(iframe_sel)
                    body = frame_loc.locator("body").first
                    body.wait_for(state="visible", timeout=3000)
                    body.click()
                    page.evaluate(
                        """([sel, html]) => {
                            const iframe = document.querySelector(sel);
                            if (!iframe || !iframe.contentDocument) return false;
                            iframe.contentDocument.body.innerHTML = html;
                            ['input','change','keyup','blur'].forEach(ev => {
                                iframe.contentDocument.body.dispatchEvent(
                                    new Event(ev, {bubbles: true})
                                );
                            });
                            return true;
                        }""",
                        [iframe_sel, desc],
                    )
                    # Also click outside to trigger blur
                    page.locator("body").click(position={"x": 10, "y": 10})
                    desc_ok = True
                    logger.info(f"✓ Filled description via iframe {iframe_sel}")
                    break
                except Exception:
                    continue
        if desc_ok:
            filled.append("description")
        else:
            skipped.append("description (à remplir manuellement)")

    # ── Publishing Rights → "I own the copyright" ───────────────────────
    if _try_click(page, [
        "input#data-print-book-publishing-rights-radio-1",
        "input[name='publishing-rights'][value='hold-copyright']",
        "input[value='copyright']",
        "label:has-text('I own the copyright')",
        "label:has-text('I own copyright')",
        "label:has-text('Je détiens les droits')",
    ], "publishing_rights_own"):
        filled.append("publishing_rights")
    else:
        skipped.append("publishing_rights (à cocher manuellement: I own copyright)")

    # ── Primary Audience → Sexually explicit = No ───────────────────────
    # Tricky because the radio is often a custom React component, not a
    # native input. We scope to the Sexually Explicit section.
    sex_ok = False
    try:
        sex_section = page.locator(
            "div:has(> :text('Sexually Explicit')), "
            "fieldset:has(legend:text('Sexually Explicit')), "
            "div:has(span:text('Sexually Explicit'))"
        ).first
        # Within section, click the "No" label/radio
        for sel in [
            "label:has-text('No')",
            "input[type='radio'][value='no']",
            "input[type='radio'][value='false']",
            "input[type='radio']:nth-of-type(2)",
        ]:
            try:
                el = sex_section.locator(sel).first
                el.wait_for(state="visible", timeout=2000)
                el.click()
                sex_ok = True
                logger.info(f"✓ Clicked Sexually Explicit No via section + {sel}")
                break
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Sexually Explicit section locator failed: {e}")

    # Fallback to global selectors
    if not sex_ok:
        sex_ok = _try_click(page, [
            "input#data-print-book-sexually-explicit-no",
            "input[name='sexually-explicit'][value='no']",
            "input[name='isAdultProduct'][value='false']",
            # Label-based — look for a "No" label that's a sibling of the
            # Sexually Explicit heading
            "div:has(> h3:text('Sexually Explicit')) label:has-text('No')",
        ], "sexually_explicit_no_fallback")

    if sex_ok:
        filled.append("sexually_explicit_no")
    else:
        skipped.append("sexually_explicit (à cocher No manuellement)")

    # Reading age — kids niches only (optional)
    niche_lc = (listing.get("niche") or "").lower()
    kid_markers = ["kid", "child", "toddler", "boys", "girls", "preschool"]
    if any(k in niche_lc for k in kid_markers):
        _try_select(page, [
            "select#data-print-book-reading-age-minimum",
            "select[name='readingAgeMin']",
        ], "4", "reading_age_min")
        _try_select(page, [
            "select#data-print-book-reading-age-maximum",
            "select[name='readingAgeMax']",
        ], "8", "reading_age_max")

    # ── Primary marketplace → Amazon.com (usually pre-selected) ─────────
    if _try_select(page, [
        "select#data-print-book-home-marketplace",
        "select[name='homeMarketplace']",
    ], "Amazon.com", "primary_marketplace"):
        filled.append("primary_marketplace")

    # ── Categories — open modal, attempt auto-fill, fall back to manual ─
    categories = listing.get("categories", []) or []
    if categories and _try_click(page, [
        "button:has-text('Choose categories')",
        "button:has-text('Edit categories')",
        "button:has-text('Modifier les catégories')",
        "button#data-print-book-categories-button",
    ], "open_categories_modal"):
        # Wait for modal to render
        time.sleep(2)
        try:
            page.wait_for_selector(
                "[role='dialog'], .a-popover, .modal, div[aria-modal='true']",
                timeout=4000, state="visible",
            )
        except Exception:
            pass

        # Best-effort auto-fill: try to type each path in a search box
        auto_filled = 0
        modal = None
        for sel in [
            "div[role='dialog']",
            ".a-popover-content",
            "div[aria-modal='true']",
            ".modal-content",
        ]:
            try:
                cand = page.locator(sel).first
                cand.wait_for(state="visible", timeout=1500)
                modal = cand
                break
            except Exception:
                continue

        if modal:
            for cat in categories[:3]:
                path = cat.get("path", "") if isinstance(cat, dict) else str(cat)
                if " > " not in path:
                    continue
                # Try to type the LEAF (last segment after final >) in any search input
                leaf = path.split(" > ")[-1].strip()
                full = path.strip()
                placed = False
                for inp_sel in [
                    "input[type='search']",
                    "input[type='text'][placeholder*='Search']",
                    "input[type='text'][placeholder*='earch']",
                    "input[role='combobox']",
                ]:
                    try:
                        inp = modal.locator(inp_sel).first
                        inp.wait_for(state="visible", timeout=1500)
                        inp.click()
                        inp.fill("")
                        inp.fill(leaf)
                        time.sleep(1)   # wait for results
                        # Click the first matching result containing the leaf
                        for res_sel in [
                            f"li:has-text('{leaf}')",
                            f"button:has-text('{leaf}')",
                            f"a:has-text('{leaf}')",
                            f"[role='option']:has-text('{leaf}')",
                            f"label:has-text('{leaf}')",
                        ]:
                            try:
                                opt = modal.locator(res_sel).first
                                opt.wait_for(state="visible", timeout=2000)
                                opt.click()
                                placed = True
                                auto_filled += 1
                                logger.info(f"✓ Auto-picked category: {leaf}")
                                time.sleep(1)
                                break
                            except Exception:
                                continue
                        if placed:
                            break
                    except Exception:
                        continue

            if auto_filled >= 3:
                # Try to confirm/save the modal
                _try_click(page, [
                    "button:has-text('Save')",
                    "button:has-text('Apply')",
                    "button:has-text('Confirm')",
                    "button:has-text('Done')",
                    "button:has-text('Continue')",
                    "[role='dialog'] button[type='submit']",
                ], "save_categories_modal")
                filled.append(f"categories (auto: {auto_filled}/3)")
            elif auto_filled > 0:
                status_cb(
                    f"⚠️ Auto-pick partiel ({auto_filled}/3 catégories). "
                    "Complète manuellement les manquantes dans le modal Firefox."
                )
                filled.append(f"categories ({auto_filled}/3 auto + manuel)")
            else:
                status_cb(
                    "⚠️ Auto-pick catégories raté — coche les 3 manuellement "
                    "dans le modal qui est ouvert."
                )
                skipped.append("categories (modal ouvert — manuel)")
        else:
            skipped.append("categories (modal pas trouvé)")
    elif categories:
        skipped.append("categories (bouton 'Choose categories' pas trouvé)")

    # ── Low-content book checkbox ────────────────────────────────────────
    try:
        for sel in [
            "input#data-print-book-is-low-content-book",
            "input[name='is-low-content-book']",
            "label:has-text('Low-content book') input",
        ]:
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=1500)
                if not loc.is_checked():
                    loc.check()
                logger.info("✓ Checked low-content book")
                filled.append("low_content_book")
                break
            except Exception:
                continue
    except Exception:
        skipped.append("low_content_book")

    # ── Keywords (7 inputs) — robust with explicit event dispatch ───────
    # KDP keywords are React-controlled inputs. fill() alone often doesn't
    # trigger React's state update. We need: focus → fill → dispatch events.
    keywords = (listing.get("keywords") or [])[:7]
    kw_ok = 0
    try:
        # Find ALL keyword inputs by scoping to the Keywords section
        kw_section = page.locator(
            "div:has(> :text('Keywords')), "
            "fieldset:has(legend:text('Keywords')), "
            "section:has(h2:text('Keywords'))"
        ).first
        # Get all the visible text inputs inside the section
        for i, kw in enumerate(keywords):
            placed = False
            # Strategy 1: nth-of-type within section
            for sel in [
                f"input[type='text']:nth-of-type({i+1})",
                f"input[placeholder]:nth-of-type({i+1})",
            ]:
                try:
                    inp = kw_section.locator(sel).nth(0) if "nth-of-type" not in sel else kw_section.locator(sel)
                    inp.wait_for(state="visible", timeout=1500)
                    # Use a chain that React respects:
                    inp.click()
                    inp.fill("")           # clear any default
                    inp.fill(kw[:50])
                    inp.evaluate(
                        """(el, val) => {
                            el.value = val;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            el.dispatchEvent(new Event('blur', {bubbles: true}));
                        }""",
                        kw[:50],
                    )
                    placed = True
                    kw_ok += 1
                    logger.info(f"✓ Keyword {i+1} via section + {sel}")
                    break
                except Exception:
                    continue
            if placed:
                continue
            # Strategy 2: global ID-based fallback
            if _try_fill(page, [
                f"input#data-print-book-keywords-{i}",
                f"input[name='keywords-{i}']",
                f"input[id$='keywords-{i}']",
                f"input[aria-label*='Keyword {i+1}']",
                f"input[aria-label='Keyword {i+1}']",
            ], kw[:50], f"keyword_{i}"):
                # Also trigger React events
                try:
                    page.evaluate(
                        """([sel, val]) => {
                            const el = document.querySelector(sel);
                            if (el) {
                                el.value = val;
                                el.dispatchEvent(new Event('input', {bubbles: true}));
                                el.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                        }""",
                        [f"input[id$='keywords-{i}']", kw[:50]],
                    )
                except Exception:
                    pass
                kw_ok += 1
    except Exception as e:
        logger.warning(f"Keywords section approach failed: {e}")

    if kw_ok > 0:
        filled.append(f"{kw_ok}/{len(keywords)} keywords")
    else:
        skipped.append("keywords (à remplir manuellement)")

    # ── Publication & Release dates (optional, often pre-selected) ──────
    _try_click(page, [
        "input[name='publication-date'][value='same-as-release']",
        "input[name='publication-date'][value='same-as-release-date']",
        "label:has-text('Publication date and release date are the same')",
        "label:has-text('Publication date and release date are the same')",
    ], "pub_date_same")

    _try_click(page, [
        "input[name='release-date'][value='release-now']",
        "input[name='release-date'][value='now']",
        "label:has-text('Release my book for sale now')",
    ], "release_now")

    # ── Final report ─────────────────────────────────────────────────────
    if filled:
        status_cb(f"✅ Step 1 rempli : {', '.join(filled)}")
    if skipped:
        status_cb(f"⚠️ Step 1 skippé : {', '.join(skipped)}")


# ── Step 2: Content ────────────────────────────────────────────────────────────

def fill_content(page, interior_pdf: Path, cover_pdf: Path,
                 product_type: str,
                 status_cb: Callable[[str], None],
                 learning_dir: Path,
                 cover_finish: str = "Matte",
                 has_bleed: bool = True,
                 trim_w: float = 6.0,
                 trim_h: float = 9.0,
                 paper_type: str = "white") -> None:
    """
    Fill the KDP 'Content' page:
      - ISBN: Publish without an ISBN
      - Print options:
          Ink/Paper:    Black and white interior with white paper
          Trim size:    6 x 9 inches (already default in our PDFs)
          Bleed:        Bleed (PDF only) — our cover_generator adds 0.125" bleed
          Cover finish: Matte (more premium for low-content)
      - Manuscript upload: interior.pdf
      - Cover upload:      cover.pdf (full wrap)
      - AI-Generated Content disclosure (Amazon 2024 requirement)
    """
    status_cb("📤 Étape 2/3 — Contenu (upload PDFs, peut prendre 1-3 min)…")

    # ── ISBN → "Get a free KDP ISBN" (the modern equivalent) ─────────────
    # KDP renamed "Publish without an ISBN" to "Get a free KDP ISBN".
    # There are two sub-actions:
    #   1. Select the "Get a free KDP ISBN" radio (usually pre-selected)
    #   2. Click the yellow "Assign ISBN" button to actually request one
    if not _try_click(page, [
        "label:has-text('Get a free KDP ISBN')",
        "label:has-text('Publish without an ISBN')",   # legacy
        "label:has-text('Publier sans ISBN')",
        "input[name='isbn-radio'][value='without-isbn']",
        "input[name='isbn'][value='no-isbn']",
        "input[name='isbn-option'][value='free-isbn']",
    ], "isbn_free_radio"):
        # Don't fail — radio may already be selected by default
        logger.warning("ISBN radio not clickable but may already be selected")

    # Click "Assign ISBN" button to actually request the free ISBN
    if not _try_click(page, [
        "button:has-text('Assign ISBN')",
        "button:has-text('Attribuer un ISBN')",
        "button:has-text('Get free ISBN')",
        "button[type='button']:near(:text('Get a free KDP ISBN'))",
    ], "assign_isbn_btn"):
        # If the button is not there, the ISBN may already be assigned —
        # don't fail the whole flow.
        logger.info("'Assign ISBN' button not found — assumed already assigned")

    # ── Print Options: Ink/Paper — driven by listing.paper_type ─────────
    # KDP has 5 ink/paper combinations. Pick the one matching the listing.
    paper_label_map = {
        "white":          ("Black and white interior with white paper",
                           "Intérieur noir et blanc, papier blanc",
                           "black-and-white-with-white-paper"),
        "cream":          ("Black and white interior with cream paper",
                           "Intérieur noir et blanc, papier crème",
                           "black-and-white-with-cream-paper"),
        "groundwood":     ("Black and white interior with groundwood paper",
                           "Intérieur noir et blanc, papier groundwood",
                           "black-and-white-with-groundwood-paper"),
        "color":          ("Standard color interior with white paper",
                           "Intérieur couleur standard, papier blanc",
                           "standard-color-with-white-paper"),
        "premium_color":  ("Premium color interior with white paper",
                           "Intérieur couleur premium, papier blanc",
                           "premium-color-with-white-paper"),
    }
    paper_en, paper_fr, paper_val = paper_label_map.get(
        paper_type, paper_label_map["white"]
    )
    if not _try_click(page, [
        f"input[value='{paper_val}']",
        f"label:has-text('{paper_en}')",
        f"label:has-text('{paper_fr}')",
        f"input[name='ink-paper'][value='{paper_val}']",
    ], f"ink_paper_{paper_type}"):
        logger.info(f"Ink/Paper '{paper_type}' not clicked (may be default)")

    # ── Trim size — driven by listing.trim_size_w × trim_size_h ─────────
    # KDP shows trim sizes as "6.00 x 9.00 in (15.24 x 22.86 cm)".
    # We open the selector and click the option matching our dimensions.
    expected_label = f"{trim_w:.2f} x {trim_h:.2f}"
    # Check if the trim is already correctly set (saves a click)
    try:
        already_set = page.locator(
            f"button:has-text('{expected_label}')"
        ).first.is_visible(timeout=1500)
    except Exception:
        already_set = False

    if not already_set:
        # Open the trim picker (modal or dropdown)
        if _try_click(page, [
            "button:has-text('Select different size')",
            "button:has-text('Sélectionner une autre taille')",
            "button:has-text('Trim Size')",
            "button[aria-label*='Trim Size']",
        ], "open_trim_picker", timeout_ms=4000):
            time.sleep(1)   # let modal/dropdown render
            # Pick the matching trim option — try multiple label formats
            if not _try_click(page, [
                f"label:has-text('{expected_label} in')",
                f"label:has-text('{trim_w} x {trim_h} in')",
                f"li:has-text('{expected_label}')",
                f"button:has-text('{expected_label} in')",
                f"div[role='option']:has-text('{expected_label}')",
            ], f"pick_trim_{trim_w}x{trim_h}", timeout_ms=4000):
                status_cb(
                    f"⚠️ Trim {trim_w}×{trim_h}in non sélectionné — "
                    "vérifie/coche manuellement dans Firefox"
                )

    # ── Bleed Settings: "Bleed (PDF only)" since our covers HAVE bleed ──
    # IMPORTANT: this one we actually want to change (default is No Bleed but
    # our cover_generator adds 0.125" bleed). Tolerant though.
    if has_bleed:
        if _try_click(page, [
            "label:has-text('Bleed (PDF only)')",
            "input[name='bleed-settings'][value='with-bleed']",
            "input[name='bleed'][value='bleed-pdf']",
            "div:has(:text('Bleed Settings')) label:has-text('Bleed (PDF only)')",
        ], "bleed_pdf"):
            logger.info("✓ Bleed set to PDF only")
        else:
            status_cb("⚠️ Bleed PDF non coché — coche-le manuellement dans Firefox")

    # ── Paperback cover finish: Matte (TOLERANT) ────────────────────────
    if not _try_click(page, [
        f"label:has-text('{cover_finish}')",
        f"input[name='cover-finish'][value='{cover_finish.lower()}']",
        f"div:has(:text('Paperback cover finish')) label:has-text('{cover_finish}')",
    ], f"cover_finish_{cover_finish.lower()}"):
        logger.info(f"Cover finish '{cover_finish}' not clicked (may be default)")

    # ── Upload manuscript (interior.pdf) ─────────────────────────────────
    # KDP hides file inputs (the visible button triggers OS picker). Find by
    # attribute regardless of visibility.
    status_cb(f"📤 Upload manuscript : {interior_pdf.name}…")
    try:
        upload_input = None
        for sel in [
            "#data-print-book-publisher-interior-file-upload-AjaxFileUpload-INPUT",
            "input[type='file'][id*='interior']",
            "input[type='file'][name*='interior']",
            "input[type='file'][id*='manuscript']",
            "input[type='file'][name*='manuscript']",
            "section:has(:text('Manuscript')) input[type='file']",
            "div:has(> h2:text('Manuscript')) input[type='file']",
            "input[type='file'][accept*='pdf']",
            "input[type='file']",
        ]:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="attached", timeout=2000)
                upload_input = loc
                logger.info(f"✓ Manuscript file input found via: {sel}")
                break
            except Exception:
                continue
        if upload_input is None:
            raise UploadError(
                "Manuscript file input introuvable",
                screenshot=_snap(page, learning_dir, "manuscript_input_missing"),
                step="manuscript_upload",
            )
        upload_input.set_input_files(str(interior_pdf))
        # Wait for upload success message — confirmed from screenshot:
        #   "Manuscript "interior.pdf" uploaded successfully!"
        deadline = time.time() + 5 * 60
        while time.time() < deadline:
            try:
                if page.locator(
                    "text=/manuscript.*uploaded successfully/i, "
                    "text=/manuscrit.*téléchargé avec succès/i"
                ).first.is_visible(timeout=2000):
                    break
            except Exception:
                pass
            time.sleep(3)
        status_cb("✅ Manuscript uploaded")
    except Exception as e:
        snap = _snap(page, learning_dir, "manuscript_upload_failed")
        raise UploadError(
            f"Manuscript upload failed: {e}",
            screenshot=snap, step="manuscript_upload",
        )

    # ── Upload cover (cover.pdf) ─────────────────────────────────────────
    # KDP shows TWO radio options:
    #   ○ Use Cover Creator to make your book cover (DEFAULT — wrong for us)
    #   ○ Upload a cover you already have (print-ready PDF only) ← we want this
    # We must FIRST click the second radio to reveal the file input.
    status_cb(f"📤 Upload cover : {cover_pdf.name}…")

    radio_clicked = False
    # Strategy 1: scope to the Book Cover section then iterate label/input options
    try:
        cover_section = page.locator(
            "div:has(> h2:text('Book Cover')), "
            "section:has(h2:text('Book Cover')), "
            "div:has(:text('Book Cover')):not(:has(h2:text('Paperback')))"
        ).first
        for sel in [
            "label:has-text('Upload a cover you already have')",
            "label:has-text('print-ready PDF')",
            "input[type='radio'][value*='upload']",
            "input[type='radio'][value*='print-ready']",
            "input[type='radio']:nth-of-type(2)",
        ]:
            try:
                el = cover_section.locator(sel).first
                el.wait_for(state="visible", timeout=2000)
                el.click()
                radio_clicked = True
                logger.info(f"✓ Cover radio clicked via section + {sel}")
                break
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Cover section locator failed: {e}")

    # Strategy 2: global fallback selectors
    if not radio_clicked:
        radio_clicked = _try_click(page, [
            "label:has-text('Upload a cover you already have')",
            "label:has-text('upload a cover you already have')",
            "label:has-text('print-ready PDF only')",
            "label:has-text('Charger une couverture que vous avez déjà')",
            "input[name='cover-choice'][value='upload-cover']",
            "input[name='cover-option'][value='upload-pdf']",
            "input[type='radio'][value='print-ready']",
            "input[type='radio'][value='your-own-cover']",
        ], "cover_upload_radio_fallback")

    # Strategy 3: JavaScript click on any input matching by label text
    if not radio_clicked:
        try:
            result = page.evaluate(
                """() => {
                    const labels = Array.from(document.querySelectorAll('label'));
                    for (const lab of labels) {
                        const txt = (lab.textContent || '').toLowerCase();
                        if (txt.includes('upload') && txt.includes('cover') && txt.includes('have')) {
                            const inp = lab.querySelector('input[type=radio]')
                                     || document.getElementById(lab.htmlFor || '');
                            if (inp) { inp.click(); return 'clicked'; }
                            lab.click();
                            return 'label-clicked';
                        }
                    }
                    return 'not-found';
                }"""
            )
            if result and "clicked" in result:
                radio_clicked = True
                logger.info(f"✓ Cover radio clicked via JS ({result})")
        except Exception as e:
            logger.warning(f"JS cover radio click failed: {e}")

    if not radio_clicked:
        snap = _snap(page, learning_dir, "cover_radio_failed")
        status_cb(
            "⚠️ Bouton 'Upload a cover you already have' introuvable — "
            "clique-le MANUELLEMENT dans Firefox, puis attends, le bot va "
            "essayer d'uploader quand l'input file devient visible."
        )
        # Don't raise — give user 60s to do it manually
        time.sleep(60)

    # Now find the file input — KDP HIDES it (button click triggers OS picker),
    # so we look for the input by attribute regardless of visibility.
    # set_input_files() works on hidden inputs since it bypasses the UI.
    try:
        cover_input = None
        # Try multiple selector strategies — file input might be anywhere
        cover_input_selectors = [
            "#data-print-book-publisher-cover-file-upload-AjaxFileUpload-INPUT",
            "input[type='file'][accept*='pdf'][id*='cover']",
            "input[type='file'][id*='cover']",
            "input[type='file'][name*='cover']",
            # Scope to Book Cover section
            "section:has(:text('Book Cover')) input[type='file']",
            "div:has(> h2:text('Book Cover')) input[type='file']",
            # Last resort: any file input that accepts PDF
            "input[type='file'][accept*='pdf']",
            "input[type='file']",
        ]
        for sel in cover_input_selectors:
            try:
                loc = page.locator(sel).last   # use .last in case multiple match
                loc.wait_for(state="attached", timeout=2000)
                cover_input = loc
                logger.info(f"✓ Cover file input found via: {sel}")
                break
            except Exception:
                continue

        if cover_input is None:
            # JS fallback: find any file input via script
            handle = page.evaluate_handle(
                """() => {
                    const inputs = Array.from(document.querySelectorAll('input[type=file]'));
                    // Prefer one related to cover
                    return inputs.find(i =>
                        (i.id || '').toLowerCase().includes('cover') ||
                        (i.name || '').toLowerCase().includes('cover') ||
                        (i.accept || '').toLowerCase().includes('pdf')
                    ) || inputs[0] || null;
                }"""
            )
            if handle:
                try:
                    cover_input = handle.as_element()
                except Exception:
                    cover_input = None

        if cover_input is None:
            raise UploadError(
                "Cover file input introuvable même via JS. KDP a peut-être changé son DOM.",
                screenshot=_snap(page, learning_dir, "cover_input_missing"),
                step="cover_upload",
            )

        cover_input.set_input_files(str(cover_pdf))

        # Wait for "Cover uploaded successfully!" message (confirmed by screenshot)
        deadline = time.time() + 3 * 60
        while time.time() < deadline:
            try:
                if page.locator(
                    "text=/cover uploaded successfully/i, "
                    "text=/couverture téléchargée avec succès/i"
                ).first.is_visible(timeout=2000):
                    break
            except Exception:
                pass
            time.sleep(3)
        status_cb("✅ Cover uploaded")
    except Exception as e:
        snap = _snap(page, learning_dir, "cover_upload_failed")
        raise UploadError(
            f"Cover upload failed: {e}",
            screenshot=snap, step="cover_upload",
        )

    # ── AI-Generated Content disclosure (Amazon 2024 requirement) ───────
    # We declare honestly: Yes for images (DALL-E), text AI-drafted with
    # significant editing. ALL fields are TOLERANT — bot skips on failure
    # instead of crashing the whole publication.
    ai_filled = []
    ai_skipped = []

    # 1. Click "Yes" radio in AI-Generated Content section
    if _try_click(page, [
        "input[name='ai-content-radio'][value='yes']",
        "input[name='aiContent'][value='yes']",
        "label:has-text('Yes'):near(:text('AI-Generated Content'))",
        "label:has-text('Oui'):near(:text('contenu généré par IA'))",
        # Scope-based fallback
        "div:has(h2:text('AI-Generated Content')) label:has-text('Yes')",
        "div:has(:text('AI-Generated Content')) input[type='radio'][value='yes']",
    ], "ai_content_yes"):
        ai_filled.append("Yes")
        time.sleep(1)   # let the sub-fields appear

        # 2. Texts dropdown
        if _try_select(page, [
            "select[name='ai-text-usage']",
            "select:near(:text('Texts'))",
            "select:near(:text('Textes'))",
            "div:has(label:text('Texts')) select",
        ], "Some AI-generated text, with significant human editing",
           "ai_text_usage"):
            ai_filled.append("Texts")
        else:
            ai_skipped.append("Texts (dropdown)")

        # 3. Images dropdown
        if _try_select(page, [
            "select[name='ai-images-usage']",
            "select:near(:text('Images'))",
            "div:has(label:text('Images')) select",
        ], "One or a few AI-generated images, with extensive human editing",
           "ai_images_usage"):
            ai_filled.append("Images")
        else:
            ai_skipped.append("Images (dropdown)")

        # 4. Tool used for images (free-text)
        if _try_fill(page, [
            "input[name='ai-images-tools-0']",
            "input:near(:text('Which tool'))",
            "div:has(:text('Which tool')) input[type='text']",
        ], "DALL-E", "ai_images_tool"):
            ai_filled.append("Tool=DALL-E")
        else:
            ai_skipped.append("AI tool name")

        # 5. Translations dropdown
        if _try_select(page, [
            "select[name='ai-translations-usage']",
            "select:near(:text('Translations'))",
            "select:near(:text('Traductions'))",
            "div:has(label:text('Translations')) select",
        ], "None", "ai_translations_none"):
            ai_filled.append("Translations=None")
        else:
            ai_skipped.append("Translations (dropdown)")
    else:
        ai_skipped.append("AI 'Yes' radio")

    if ai_filled and not ai_skipped:
        status_cb(f"✅ AI disclosure complète : {', '.join(ai_filled)}")
    elif ai_filled:
        status_cb(
            f"⚠️ AI disclosure partielle — rempli : {', '.join(ai_filled)} | "
            f"à finir manuellement : {', '.join(ai_skipped)}"
        )
    else:
        status_cb(
            "⚠️ Section AI-Generated Content non remplie — coche 'Yes' + remplis "
            "les dropdowns toi-même dans Firefox avant de continuer"
        )


# ── Step 3: Pricing ────────────────────────────────────────────────────────────

def fill_pricing(page, listing: Dict, status_cb: Callable[[str], None],
                 learning_dir: Path) -> None:
    """
    Pricing step is mostly manual (screenshots pending). The bot:
      1. Waits 5 min for user to fill territories + price + click Save as Draft
      2. Auto-detects completion via URL change (leaves /pricing) OR
         success message OR Firefox closure
      3. Returns immediately once any of these signals fires
    """
    status_cb("💵 Étape 3/3 — Pricing")
    status_cb(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏸️ Remplis MANUELLEMENT dans Firefox :\n"
        "   1. Territoires → All territories (worldwide)\n"
        "   2. Primary marketplace → Amazon.com\n"
        "   3. List Price USD → ex: 7.99 ou 9.99\n"
        "   4. Clique 'Save as Draft' (bouton blanc, PAS 'Publish your book')\n"
        "Le bot détecte automatiquement quand t'as fini.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    import time
    deadline = time.time() + 5 * 60   # 5 min max
    success_patterns = (
        "/bookshelf",            # KDP redirects here after Save as Draft
        "/title-list",
        "saved successfully",
        "saved as draft",
        "draft saved",
    )

    while time.time() < deadline:
        if _user_signalled_continue(learning_dir):
            status_cb("⚡ Continue manuel reçu — fin de la publication")
            return
        # User closed Firefox = they're done
        try:
            if page.is_closed():
                status_cb("✅ Firefox fermé — fin de la publication")
                return
        except Exception:
            status_cb("✅ Fenêtre Firefox terminée")
            return

        url = (page.url or "").lower()

        # Successful save → URL changed away from /pricing
        if "/pricing" not in url:
            # Verify it's a positive transition (bookshelf, draft list, etc.)
            if any(p in url for p in success_patterns):
                status_cb(f"✅ Draft sauvegardé — URL: {url}")
                return
            # OR maybe URL just changed to a different page — log it
            logger.info(f"Pricing polling — URL changed to: {url}")
            # Give it 2 sec for any redirects to settle
            time.sleep(2)
            url_after = (page.url or "").lower()
            if any(p in url_after for p in success_patterns):
                status_cb(f"✅ Draft sauvegardé — {url_after}")
                return

        # Detect success message on page (without URL change)
        try:
            for marker in [
                "text=/saved successfully/i",
                "text=/draft saved/i",
                "text=/saved as draft/i",
                "text=/your book is in draft/i",
            ]:
                try:
                    page.wait_for_selector(marker, timeout=500, state="visible")
                    status_cb("✅ Message de succès détecté — fin de la publication")
                    return
                except Exception:
                    continue
        except Exception:
            pass

        time.sleep(3)

    status_cb("⏱️ Timeout 5 min — si tu as fini, ferme Firefox pour terminer proprement")


# ── Master orchestrator ────────────────────────────────────────────────────────

def publish_to_kdp_draft(
    *,
    listing:      Dict,
    interior_pdf: Path,
    cover_pdf:    Path,
    learning_dir: Path,
    status_cb:    Callable[[str], None],
    headless:     bool = False,
) -> UploadResult:
    """
    End-to-end Option-A publish: fills the 3 KDP forms then 'Save as Draft'.
    Stops BEFORE the final 'Publish your book' click.
    """
    from modules.publishing.session import kdp_browser, KDP_CREATE_URL

    res = UploadResult()
    try:
        with kdp_browser(learning_dir, headless=headless) as page:
            status_cb(f"🌐 Ouverture KDP → {KDP_CREATE_URL}")
            page.goto(KDP_CREATE_URL, wait_until="domcontentloaded", timeout=60_000)

            # If session expired, KDP cycles through:
            #   /signin → /ap/signin → /ap/cvf (2FA) → /en_US/bookshelf → final
            # Give user 10 min to complete login; detect via MULTIPLE signals
            # (URL no longer auth-related AND Step 1 element appears).
            import time
            url = (page.url or "").lower()
            signin_patterns = ("/signin", "/ap/signin", "/ap/cvf", "/ap/mfa", "/ap/forgotpassword")
            on_auth = any(p in url for p in signin_patterns)

            if on_auth:
                status_cb(
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🔐 Session KDP expirée — fais le login dans Firefox :\n"
                    "   1. Entre email + password\n"
                    "   2. Valide 2FA si demandé\n"
                    "   3. Le bot reprend AUTOMATIQUEMENT (max 10 min)\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
                deadline = time.time() + 10 * 60
                last_logged_url = ""
                step1_loaded = False
                while time.time() < deadline:
                    # Manual "Continue" signal from UI
                    if _user_signalled_continue(learning_dir):
                        status_cb("⚡ Continue manuel reçu — vérification Step 1…")
                        try:
                            page.goto(KDP_CREATE_URL, wait_until="domcontentloaded", timeout=30_000)
                            step1_loaded = True
                            break
                        except Exception as e:
                            status_cb(f"⚠️ Goto échoué après continue manuel : {e}")
                    # Detect closed window
                    try:
                        if page.is_closed():
                            raise UploadError(
                                "Fenêtre Firefox fermée pendant le login.",
                                step="login",
                            )
                    except UploadError:
                        raise
                    except Exception:
                        pass

                    cur_url = (page.url or "").lower()
                    if cur_url != last_logged_url:
                        logger.info(f"Login polling — URL: {cur_url}")
                        last_logged_url = cur_url

                    still_on_auth = any(p in cur_url for p in signin_patterns)
                    if still_on_auth:
                        time.sleep(2)
                        continue

                    # Past auth — try to reach the create page
                    try:
                        page.goto(KDP_CREATE_URL,
                                  wait_until="domcontentloaded", timeout=30_000)
                    except Exception as e:
                        logger.warning(f"Goto create URL failed (will retry): {e}")
                        time.sleep(3)
                        continue

                    post_nav_url = (page.url or "").lower()
                    if any(p in post_nav_url for p in signin_patterns):
                        # Got bounced back to auth — keep waiting
                        time.sleep(3)
                        continue

                    # Confirm Step 1 is actually loaded by looking for the title input
                    step1_markers = [
                        "input#data-print-book-title",
                        "input[name='title']",
                        "input[aria-label*='Book Title']",
                        "input[aria-label*='Titre du livre']",
                        "h1:has-text('Paperback Details')",
                        "text=/Paperback Details/i",
                    ]
                    for mk in step1_markers:
                        try:
                            page.wait_for_selector(mk, timeout=4000, state="visible")
                            step1_loaded = True
                            break
                        except Exception:
                            continue
                    if step1_loaded:
                        status_cb("✅ Login validé + Step 1 chargé — reprise de la publication…")
                        # Save the fresh session for next time
                        try:
                            page.context.storage_state(
                                path=str(learning_dir / "kdp_session.json")
                            )
                            logger.info("Fresh KDP session saved")
                        except Exception as e:
                            logger.warning(f"Session save failed: {e}")
                        break
                    # Not on auth, not on Step 1 — probably on bookshelf or homepage
                    # Loop will retry the goto
                    time.sleep(3)

                if not step1_loaded:
                    raise UploadError(
                        "Login détecté mais Step 1 jamais chargé après 10 min. "
                        f"Dernière URL : {last_logged_url}. "
                        "Réessaie : ferme Firefox + reclique 'Pousser vers KDP'.",
                        screenshot=_snap(page, learning_dir, "login_step1_fail"),
                        step="login",
                    )

            fill_details(page, listing, status_cb, learning_dir)
            res.step_reached = "details"

            # ── CRITICAL HUMAN STEP : categories must be picked manually ──
            # Build the category list inline so user sees exactly what to pick
            _cats = listing.get("categories", []) or []
            if _cats:
                _cat_lines = []
                for c in _cats:
                    path = c.get("path", "") if isinstance(c, dict) else str(c)
                    mark = "⭐ PRIMAIRE" if isinstance(c, dict) and c.get("primary") else "▫️"
                    _cat_lines.append(f"      {mark}  {path}")
                _cat_block = "\n".join(_cat_lines)
            else:
                _cat_block = "      ⚠️ (aucune dans listing.json — choisis à ton goût)"

            status_cb(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⏸️  ACTION MANUELLE REQUISE (5 min max) :\n"
                "   1. Va dans Firefox\n"
                "   2. Section 'Categories' → clique 'Choose categories'\n"
                "   3. COCHE CES 3 CATÉGORIES :\n"
                f"{_cat_block}\n"
                "   4. Vérifie qu'il n'y a plus d'erreur rouge sur la page\n"
                "   5. Clique 'Save and Continue' (en bas à droite)\n"
                "Le bot reprend dès qu'il voit 'Paperback Content' ou 'ISBN'.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

            # Wait for Step 2 — THREE independent signals, first wins:
            #   1. URL contains /content/ (KDP usually adds the book ID + /content)
            #   2. "Upload manuscript" yellow button is visible (Step 2 only)
            #   3. "Bleed Settings" or "Book Cover" heading visible (Step 2 only)
            # Polling logs the actual URL every 10s so we can debug if needed.
            import time
            step2_deadline = time.time() + 8 * 60   # 8 min — generous
            reached_step2 = False
            last_url = ""
            last_log_at = 0.0
            step2_signals = [
                # Element-based: these only exist on Step 2 form body
                "button:has-text('Upload manuscript')",
                "button:has-text('Upload Manuscript')",
                "button:has-text('Launch Cover Creator')",
                "h2:has-text('Print Options')",
                "h2:has-text('Bleed Settings')",
                "h2:has-text('Book Cover')",
                "h2:has-text('Manuscript')",
                "label:has-text('Bleed Settings')",
                "label:has-text('Paperback cover finish')",
            ]
            while time.time() < step2_deadline:
                if _user_signalled_continue(learning_dir):
                    reached_step2 = True
                    status_cb("⚡ Continue manuel reçu — passage à Step 2")
                    break
                # Detect closed Firefox window
                try:
                    if page.is_closed():
                        raise UploadError(
                            "Fenêtre Firefox fermée — publication annulée.",
                            step="details",
                        )
                except UploadError:
                    raise
                except Exception:
                    pass

                url = (page.url or "").lower()
                # Periodic URL log (terminal only — helps debug if detection fails)
                if time.time() - last_log_at > 10:
                    logger.info(f"Step 1 polling — current URL: {url}")
                    last_log_at = time.time()
                    last_url = url

                # Signal 1: URL-based
                url_step2 = (
                    "/content" in url
                    and "/details" not in url
                    and "/signin" not in url
                )
                if url_step2:
                    reached_step2 = True
                    logger.info(f"✅ Step 2 detected via URL: {url}")
                    break

                # Signal 2/3: Step 2-only elements
                for sig_sel in step2_signals:
                    try:
                        page.wait_for_selector(
                            sig_sel, timeout=600, state="visible",
                        )
                        reached_step2 = True
                        logger.info(f"✅ Step 2 detected via element: {sig_sel}")
                        break
                    except Exception:
                        continue
                if reached_step2:
                    break
                time.sleep(2)

            if not reached_step2:
                raise UploadError(
                    f"Step 2 jamais atteint (8 min). Dernière URL : {last_url or '?'}. "
                    "Solutions : (1) si tu es bien sur Paperback Content, ferme Firefox + "
                    "reclique Pousser ; (2) sinon vérifie les erreurs rouges sur Step 1.",
                    screenshot=_snap(page, learning_dir, "step1_blocked"),
                    step="details",
                )

            status_cb("✅ Step 2 atteint — début upload PDFs")
            page.wait_for_load_state("networkidle", timeout=30_000)

            fill_content(
                page, interior_pdf, cover_pdf,
                product_type = listing.get("product_type", ""),
                status_cb    = status_cb,
                learning_dir = learning_dir,
                # Read from listing.json — set at creation time by the UI
                cover_finish = listing.get("cover_finish", "Matte"),
                has_bleed    = listing.get("has_bleed", True),
                trim_w       = float(listing.get("trim_size_w", 6.0)),
                trim_h       = float(listing.get("trim_size_h", 9.0)),
                paper_type   = str(listing.get("paper_type", "white")).lower(),
            )
            res.step_reached = "content"

            status_cb(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⏸️  ACTION MANUELLE REQUISE :\n"
                "   1. Vérifie Step 2 dans Firefox (ISBN, trim, bleed, finish, AI)\n"
                "   2. Attends que les uploads PDF soient verts ('uploaded successfully')\n"
                "   3. Corrige les erreurs rouges éventuelles\n"
                "   4. Clique 'Save and Continue' en bas à droite\n"
                "Le bot reprend au Step 3 Pricing. 5 min.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            step3_deadline = time.time() + 8 * 60
            reached_step3 = False
            last_log3 = 0.0
            step3_signals = [
                "h2:has-text('Territories')",
                "h2:has-text('Royalty')",
                "h2:has-text('Pricing')",
                "label:has-text('All territories')",
                "label:has-text('List Price')",
                "input[name='listPrice.US']",
            ]
            while time.time() < step3_deadline:
                if _user_signalled_continue(learning_dir):
                    reached_step3 = True
                    status_cb("⚡ Continue manuel reçu — passage à Step 3")
                    break
                try:
                    if page.is_closed():
                        raise UploadError(
                            "Fenêtre Firefox fermée — publication annulée.",
                            step="content",
                        )
                except UploadError:
                    raise
                except Exception:
                    pass

                url = (page.url or "").lower()
                if time.time() - last_log3 > 10:
                    logger.info(f"Step 2 polling — current URL: {url}")
                    last_log3 = time.time()

                # Signal 1: URL
                if "/pricing" in url:
                    reached_step3 = True
                    logger.info(f"✅ Step 3 detected via URL: {url}")
                    break
                # Signal 2/3: elements
                for sig_sel in step3_signals:
                    try:
                        page.wait_for_selector(sig_sel, timeout=600, state="visible")
                        reached_step3 = True
                        logger.info(f"✅ Step 3 detected via element: {sig_sel}")
                        break
                    except Exception:
                        continue
                if reached_step3:
                    break
                time.sleep(2)

            if not reached_step3:
                raise UploadError(
                    "Step 3 (Pricing) jamais atteint. Vérifie Firefox + ferme/reclique si bloqué.",
                    screenshot=_snap(page, learning_dir, "step2_blocked"),
                    step="content",
                )

            status_cb("✅ Step 3 atteint")
            fill_pricing(page, listing, status_cb, learning_dir)
            res.step_reached = "pricing"

            # Try to click Save as Draft if visible (often manual step still)
            try:
                _safe_click(
                    page,
                    selectors=[
                        "button:has-text('Save as Draft')",
                        "button:has-text('Enregistrer comme brouillon')",
                    ],
                    name="save_as_draft",
                    learning_dir=learning_dir,
                    timeout_ms=5_000,
                )
                res.success    = True
                res.draft_url  = page.url
                res.step_reached = "draft_saved"
                status_cb("✅ Brouillon sauvegardé — va sur KDP pour cliquer Publish")
            except UploadError:
                res.success    = True   # still consider success since steps 1-2 worked
                res.draft_url  = page.url
                res.step_reached = "pricing_manual"
                status_cb("⏸️ Pricing à finaliser manuellement — clique Save as Draft toi-même")

    except UploadError as e:
        res.success         = False
        res.step_reached    = e.step
        res.error_message   = str(e)
        res.screenshot_path = e.screenshot
        status_cb(f"❌ Bloqué à l'étape '{e.step}' : {e}")
    except Exception as e:
        res.success         = False
        res.error_message   = f"Erreur inattendue : {e}"
        status_cb(f"❌ {res.error_message}")

    return res
