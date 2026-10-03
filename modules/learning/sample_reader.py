"""
Competitor "Look Inside" reader — deep learning from sample pages.

Workflow:
  1. For each top competitor (by reviews × rating) in a winning niche,
     open the Amazon product page via Playwright.
  2. Trigger the "Look Inside" / "Read Sample" view.
  3. Screenshot the visible preview pages (cap at 6-8 per book to keep
     vision-API cost low).
  4. Send the screenshots to Claude Vision (Sonnet) with a prompt that asks
     for STRUCTURAL patterns only — never verbatim text.
  5. Aggregate patterns across competitors → "what they all do well, what's
     missing, what's saturated".
  6. Save to learning_dir for injection into future generation prompts.

LEGAL & ETHICAL STANCE:
  This module extracts ONLY structural / categorical data:
    - Layout type (lined / dotted / table / Q&A)
    - Number of writing lines per page
    - Page header elements (date, mood, weather)
    - Decorative elements
    - Topic categories (NOT specific prompt wording)
    - Typography style
    - Color palette
    - Unique features
  Verbatim text from competitor previews is NEVER stored or passed back to
  generation prompts. The bot learns the MARKET PATTERNS so it can create
  ORIGINAL content that is structurally competitive — the same approach a
  human market researcher uses.
"""
import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import Counter

logger = logging.getLogger(__name__)


# ── Sample fetcher (Playwright) ───────────────────────────────────────────────

def fetch_sample_screenshots(
    asin: str,
    max_pages: int = 6,
    headless: bool = True,
) -> List[bytes]:
    """
    Tries multiple strategies to capture preview pages from an Amazon book:
      1. Kindle Cloud Reader embed (read.amazon.com/kp/embed) — most reliable
      2. Direct sample URL (read.amazon.com/sample)
      3. Product page "Look Inside" click
    Returns list of PNG bytes. Returns [] if everything fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed — sample reading disabled")
        return []

    screenshots: List[bytes] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            # Hide the navigator.webdriver flag (Amazon anti-bot)
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = ctx.new_page()

            # ── Strategy 1: Kindle Cloud Reader embed ─────────────────────
            try:
                embed_url = f"https://read.amazon.com/kp/embed?asin={asin}&preview=newtab&linkCode=kpe"
                page.goto(embed_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2500)
                # Take 3 screenshots scrolling down (the embed reader pages on scroll)
                for i in range(min(max_pages, 4)):
                    img = page.screenshot(full_page=False)
                    # Only keep if it's not mostly white/empty (rough heuristic)
                    if img and len(img) > 8000:
                        screenshots.append(img)
                    page.evaluate("window.scrollBy(0, 800)")
                    page.wait_for_timeout(700)
                if len(screenshots) >= 2:
                    browser.close()
                    logger.info(f"[{asin}] Kindle embed: {len(screenshots)} screenshots")
                    return screenshots
            except Exception as e:
                logger.debug(f"[{asin}] Kindle embed failed: {e}")
                screenshots = []

            # ── Strategy 2: Direct sample URL ─────────────────────────────
            try:
                sample_url = f"https://read.amazon.com/sample/{asin}"
                page.goto(sample_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                for i in range(max_pages):
                    img = page.screenshot(full_page=False)
                    if img and len(img) > 8000:
                        screenshots.append(img)
                    try:
                        page.keyboard.press("ArrowRight")
                    except Exception:
                        pass
                    page.wait_for_timeout(800)
                if len(screenshots) >= 2:
                    browser.close()
                    logger.info(f"[{asin}] Sample URL: {len(screenshots)} screenshots")
                    return screenshots
            except Exception as e:
                logger.debug(f"[{asin}] Sample URL failed: {e}")
                screenshots = []

            # ── Strategy 3: Product page + click Look Inside ──────────────
            try:
                page.goto(f"https://www.amazon.com/dp/{asin}",
                          wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                clicked = False
                for sel in [
                    "#sitb-pop", "a[id^='sitb-']", "img.sitb-cover",
                    "#litb-canvas", "#ebooksImgBlkFront",
                    "#litb-image-container img", "img#litb-pop-image",
                    "a:has-text('Read sample')", "a:has-text('Look inside')",
                    "[data-action='show-sample']",
                    "#imgBlkFront",        # main book image (sometimes opens preview)
                    "#main-image-container img",
                ]:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            el.scroll_into_view_if_needed(timeout=2000)
                            el.click(timeout=2000)
                            clicked = True
                            break
                    except Exception:
                        continue
                if clicked:
                    page.wait_for_timeout(3500)
                    for i in range(max_pages):
                        img = page.screenshot(full_page=False)
                        if img and len(img) > 8000:
                            screenshots.append(img)
                        try:
                            page.keyboard.press("ArrowRight")
                        except Exception:
                            pass
                        page.wait_for_timeout(900)
            except Exception as e:
                logger.debug(f"[{asin}] Product click failed: {e}")

            browser.close()
    except Exception as e:
        logger.warning(f"Sample fetch failed for {asin}: {e}")
        return []

    logger.info(f"[{asin}] final captured {len(screenshots)} screenshots")
    return screenshots


# ── Description scraper (reliable fallback when Look Inside is blocked) ───────

def fetch_product_description(asin: str, headless: bool = True) -> Dict[str, str]:
    """
    Scrapes the Amazon product detail page for the niche-relevant text fields.
    Always works (no anti-bot countermeasures) — used as fallback when Look
    Inside is blocked / unavailable.

    Returns:
      {
        "title":             str,
        "description":       str,   # main book description
        "editorial_reviews": str,   # editorial blurbs if any
        "about_author":      str,
        "product_details":   str,   # pages, language, dimensions
        "bullet_features":   str,   # the "What you'll get" bullets
      }
      Returns dict with empty strings if scrape fails.
    """
    out = {
        "title":             "",
        "description":       "",
        "editorial_reviews": "",
        "about_author":      "",
        "product_details":   "",
        "bullet_features":   "",
    }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return out

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()
            page.goto(f"https://www.amazon.com/dp/{asin}",
                      wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1200)

            def _text(sel: str) -> str:
                try:
                    el = page.query_selector(sel)
                    if el:
                        return re.sub(r"\s+", " ", (el.text_content() or "").strip())
                except Exception:
                    pass
                return ""

            out["title"] = _text("#productTitle")

            # Try multiple description containers (Amazon DOM varies)
            for sel in [
                "#bookDescription_feature_div .a-expander-content",
                "#bookDescription_feature_div",
                "[data-feature-name='bookDescription']",
                "#productDescription",
                "#feature-bullets",
            ]:
                txt = _text(sel)
                if len(txt) > len(out["description"]):
                    out["description"] = txt

            # Editorial Reviews (publisher / author / praise)
            for sel in [
                "#editorialReviews_feature_div",
                "[data-feature-name='editorialReviews']",
            ]:
                txt = _text(sel)
                if txt:
                    out["editorial_reviews"] = txt
                    break

            # About the author
            for sel in [
                "#authorPage_feature_div",
                "[data-feature-name='authorBio']",
                "#author_feature_div",
            ]:
                txt = _text(sel)
                if txt:
                    out["about_author"] = txt[:1500]
                    break

            # Product details (paperback pages, language, dimensions)
            for sel in [
                "#detailBullets_feature_div",
                "#productDetails_feature_div",
                "[data-feature-name='detailBullets']",
            ]:
                txt = _text(sel)
                if txt:
                    out["product_details"] = txt[:1200]
                    break

            # Bullet features
            txt = _text("#feature-bullets")
            if txt:
                out["bullet_features"] = txt[:1500]

            browser.close()
    except Exception as e:
        logger.warning(f"Description scrape failed for {asin}: {e}")

    # Trim everything to reasonable lengths
    for k in out:
        if len(out[k]) > 4000:
            out[k] = out[k][:4000] + " …"

    return out


# ── Vision analysis (Claude Sonnet) ───────────────────────────────────────────

_ANALYSIS_PROMPT = """You are analyzing competitor book preview pages for a low-content KDP book in the niche: "{niche}".

Your goal: extract STRUCTURAL and CATEGORICAL patterns ONLY. DO NOT copy or paraphrase any actual text from the pages. You are studying the market — not reproducing content.

For each image, identify visible patterns. Then aggregate your observations and return a JSON object with EXACTLY these keys:

{{
  "layout_type":         "lined-journal | dotted-grid | quiz-qa | log-table | coloring | planner | mixed",
  "lines_per_page":      <integer 0-30, approximate>,
  "header_elements":     ["date","mood","weather","title","page_num","section",...],
  "decorative_elements": ["icons","dividers","borders","illustrations","ornaments","color_bands",...],
  "typography_style":    "serif | sans-serif | script | display | mixed",
  "palette_description": "<short phrase: warm earth | cool blue | monochrome | vibrant pop | pastel | etc.>",
  "topic_categories":    ["<broad theme 1>","<broad theme 2>","..."],
  "density":             "sparse | medium | dense",
  "intro_style":         "long-narrative | short-blurb | bullet-list | quote | none",
  "unique_features":     ["<feature 1>","<feature 2>","..."],
  "gaps_or_weaknesses":  ["<thing missing or poorly done>",...],
  "quality_score":       <integer 1-10, your overall assessment of this competitor's interior quality>
}}

CRITICAL: do not include any verbatim prompt text, question text, or content from the pages. Only describe structural and categorical observations. Return ONLY the JSON object, no preamble."""


def analyze_screenshots_with_vision(
    screenshots: List[bytes],
    niche: str,
    anthropic_key: str,
    model: str = "claude-sonnet-4-5",
) -> Dict:
    """
    Sends screenshots to Claude Vision. Returns structured pattern dict.
    Never returns verbatim text — only structural observations.
    """
    if not screenshots:
        return {}

    try:
        import anthropic
    except ImportError:
        return {}

    client = anthropic.Anthropic(api_key=anthropic_key)

    content = [{"type": "text", "text": _ANALYSIS_PROMPT.format(niche=niche)}]
    for png in screenshots[:6]:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(png).decode("utf-8"),
            },
        })

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=1200,
            messages=[{"role": "user", "content": content}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"Vision returned non-JSON: {e}")
        return {"_error": "json_parse", "_raw_preview": raw[:300] if raw else ""}
    except Exception as e:
        logger.warning(f"Vision analysis failed: {e}")
        return {"_error": str(e)}


# ── Text-based analysis (fallback when no screenshots) ────────────────────────

_TEXT_ANALYSIS_PROMPT = """You are a senior KDP product strategist with deep niche expertise. You are studying a competitor's Amazon SALES PAGE for a low-content book in the niche: "{niche}".

NICHE: "{niche}"

COMPETITOR'S SALES PAGE:
---
{text}
---

## Your Job

You will infer the structure of this competitor's book AND identify what an EXPERT-LEVEL book in this niche would include that this competitor's description doesn't mention or promise.

## Critical Rule for `gaps_or_weaknesses`

Step 1 — Internally list 8-12 features/sections an expert-level book in "{niche}" would typically include (use your domain knowledge of the niche, NOT what's in the description).

Step 2 — For each, check: does the competitor's description CLEARLY advertise this feature?

Step 3 — If NOT clearly advertised, list it as a gap, phrased as a noun about the FEATURE itself (not about your access).

### EXAMPLES

For "autoimmune flare tracker journal" expert-level features include:
  - diet/food trigger correlation
  - weather/barometric pressure tracking
  - medication side-effect log
  - sleep quality correlation
  - stress level tracker
  - flare frequency analytics / summary pages
  - doctor-appointment prep section
  - lab results log
  - menstrual cycle correlation (for women)

→ If description doesn't mention diet correlation → gap: `"no diet/food trigger correlation"`
→ If description doesn't mention weather → gap: `"no weather/barometric pressure tracking"`

For "vintage soap making recipe journal" expert-level features include:
  - ingredient cost tracker per batch
  - batch yield / scaling formulas
  - cure time tracking
  - shelf-life log
  - pH testing record
  - fragrance ratio calculator
  - lye safety calculation reference
  - business pricing / margin calculator
  - labeling / FDA compliance reference
  - photo-of-finished-bar slot per recipe
  - sourcing / supplier log

For "ghost hunting evidence log" expert-level features include:
  - EMF reading column
  - temperature drop tracking
  - audio/EVP timestamp field
  - location coordinates / GPS
  - investigator team member field
  - witness statement section
  - equipment-used checklist
  - weather/conditions at investigation
  - photo/video reference field
  - debrief / follow-up section

### FORBIDDEN phrasings (will be auto-rejected)

Anything starting with or containing:
  - "no preview" / "preview only" / "cover page only" / "preview unavailable"
  - "can't see" / "cannot see" / "unable to view" / "unable to assess" / "cannot evaluate"
  - "no visible X" / "no observable X" / "X not visible" / "X not available"
  - "no evidence of" / "unclear if" / "ambiguous if" / "uncertain if" / "hard to tell"
  - "interior page structure" / "interior content" / "interior format"
  - "based on description" / "from description only" / "from sales page alone"
  - "not enough information" / "insufficient data"
  - any meta-reference to YOUR access to information

REQUIREMENT: You MUST produce 5-10 niche-expert features for the `gaps_or_weaknesses` field.
Every niche has expert features that low-effort competitors omit. Use your domain knowledge of "{niche}" to list them. Phrase each as "no <feature>" or "<missing aspect>".

This is your most important task — do not return `[]` unless the niche is so unusual you have zero domain knowledge of it (extremely rare).

## Return JSON (exact keys)

{{
  "layout_type":         "lined-journal | dotted-grid | quiz-qa | log-table | coloring | planner | tracker | mixed | unknown",
  "lines_per_page":      <integer 0-30 OR null>,
  "header_elements":     [<items the description mentions>],
  "decorative_elements": [<items the description mentions>],
  "typography_style":    "serif | sans-serif | script | display | mixed | unknown",
  "palette_description": "<short phrase or 'unknown'>",
  "topic_categories":    [<what the book actually covers>],
  "density":             "sparse | medium | dense | unknown",
  "intro_style":         "long-narrative | short-blurb | bullet-list | quote | none | unknown",
  "unique_features":     [<specific features advertised>],
  "gaps_or_weaknesses":  [<5-10 expert-level features this description doesn't promise>],
  "quality_score":       <integer 1-10>
}}

Return ONLY the JSON object, no preamble."""


def analyze_description_with_text(
    description_bundle: Dict[str, str],
    niche: str,
    anthropic_key: str,
    model: str = "claude-sonnet-4-5",   # Sonnet for stronger domain reasoning
) -> Dict:
    """
    Sends the scraped product description text to Claude (text model, no vision)
    to extract the same structural patterns. Returns dict or {} on failure.
    """
    try:
        import anthropic
    except ImportError:
        return {}

    # Concatenate the relevant fields into one source blob
    parts = []
    for k in ("title", "description", "editorial_reviews",
              "bullet_features", "about_author", "product_details"):
        if description_bundle.get(k):
            parts.append(f"### {k.upper()}\n{description_bundle[k]}")
    source_text = "\n\n".join(parts)
    if len(source_text) < 100:
        return {}

    # Cap to keep token usage in check
    source_text = source_text[:8000]

    prompt = _TEXT_ANALYSIS_PROMPT.format(niche=niche, text=source_text)

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        msg = client.messages.create(
            model=model,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"Text analysis returned non-JSON: {e}")
        return {"_error": "json_parse"}
    except Exception as e:
        logger.warning(f"Text analysis failed: {e}")
        return {"_error": str(e)}


# ── Per-niche orchestrator ────────────────────────────────────────────────────

def _samples_cache_file(learning_dir: Path) -> Path:
    return learning_dir / "competitor_samples.json"


def _niche_insights_file(learning_dir: Path) -> Path:
    return learning_dir / "sample_insights.json"


def _load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# Regex patterns matching "Claude self-complains about not seeing the book"
# rather than reporting a real niche-specific gap.
_HALLUCINATION_PATTERNS = [
    # Variants: "preview shows only cover", "preview limited", "preview not available"
    re.compile(r"\bpreview\b.*\b(?:cover|only|limited|missing|unavailable|insufficient|short)\b", re.I),
    re.compile(r"\b(?:sample|sample\s*pages?)\b.*\b(?:unavailable|missing|limited)\b", re.I),
    # "cannot/unable to + assess/evaluate/see/view/determine/analyze/tell"
    re.compile(r"\b(?:cannot|can\'?t|unable\s+to)\s+(?:assess|evaluate|see|view|determine|"
               r"analyze|tell|verify|judge|infer|gauge|confirm|observe|examine)\b", re.I),
    # "no [adjective] X visible/observable/accessible/apparent/available"
    re.compile(r"\b(?:no|not|nothing)\s+[\w\s/-]{0,40}?\b(?:visible|observable|accessible|"
               r"apparent|discernible|evident|shown|displayed|available|provided|present|"
               r"included|exists?)\b", re.I),
    # Direct "preview pages X" / "preview X available"
    re.compile(r"\bpreview\s+pages?\b", re.I),
    re.compile(r"\bcontent\s+available\b", re.I),
    # Self-references to the inability of the analyst (interior/inside/internal)
    re.compile(r"\b(?:interior|inside|internal)\s+(?:page|content|structure|layout|format|"
               r"template|design)\b", re.I),
    # "X visible" / "X shown" where X is page/template/format/structure
    re.compile(r"\b(?:page|template|format|structure|layout|content|element)s?\s+"
               r"(?:visible|shown|displayed|accessible)\b", re.I),
    # "from/based on description only"
    re.compile(r"\b(?:from|based\s+on)\s+(?:description|sales[-\s]*page|metadata|listing)\s+"
               r"(?:only|alone)\b", re.I),
    # "insufficient/not enough information"
    re.compile(r"\b(?:insufficient|not\s+enough|limited|lacking)\s+(?:data|information|context|"
               r"detail|content)\b", re.I),
    # Direct error / access mentions
    re.compile(r"\b(?:error\s+state|access\s+blocked|not\s+accessible|preview\s+blocked)\b", re.I),
    # "description does/n't [reveal/show/mention/say]"  — Claude reflecting on its input
    re.compile(r"\bdescription\s+(?:does(?:n\'?t|\s+not)|lacks|doesn\'?t)\s+(?:reveal|show|"
               r"mention|say|indicate|specify|provide)\b", re.I),
    # Generic "no X data/info"
    re.compile(r"\bno\s+(?:data|information|details?)\s+(?:to|on|about|regarding|concerning)\b", re.I),
    # "no evidence of X" — Claude saying it can't verify
    re.compile(r"\bno\s+evidence\s+of\b", re.I),
    # "unclear/ambiguous/uncertain if/whether/about" — Claude expressing doubt
    re.compile(r"\b(?:unclear|ambiguous|uncertain|unsure)\s+(?:if|whether|what|how|about)\b", re.I),
    # "hard/difficult to tell/determine"
    re.compile(r"\b(?:hard|difficult|impossible)\s+to\s+(?:tell|determine|judge|assess|verify|"
               r"infer|evaluate|know)\b", re.I),
    # "can't/cannot tell if/whether"
    re.compile(r"\b(?:cannot|can\'?t)\s+tell\s+(?:if|whether|what|how)\b", re.I),
    # "no way to know/verify/confirm"
    re.compile(r"\bno\s+way\s+to\s+(?:know|verify|confirm|tell|determine)\b", re.I),
    # "not clear what/how/whether"
    re.compile(r"\bnot\s+clear\s+(?:what|how|whether|if)\b", re.I),
]

# Words that should NEVER appear alone as a topic category (Claude dumping its limitations)
_BAD_TOPIC_WORDS = {
    "unavailable", "unknown", "none", "n/a", "na", "missing", "not available",
    "no data", "not specified", "unclear", "tbd",
}


def _is_real_gap(gap: str) -> bool:
    """Returns True if the gap describes a real competitor weakness (not a
    self-complaint about the analyst's inability to see screenshots)."""
    g = (gap or "").strip()
    if not g or len(g) < 4:
        return False
    for pattern in _HALLUCINATION_PATTERNS:
        if pattern.search(g):
            return False
    return True


def _is_real_topic(topic: str) -> bool:
    """Filters out junk topic categories (e.g. Claude dumping 'unavailable')."""
    t = (topic or "").strip().lower()
    if not t or len(t) < 3:
        return False
    if t in _BAD_TOPIC_WORDS:
        return False
    # Also reject anything matching the hallucination patterns
    for pattern in _HALLUCINATION_PATTERNS:
        if pattern.search(topic):
            return False
    return True


def _inject_expert_fallback_gaps(
    gaps_counter: Counter,
    niche: str,
    description_features_mentioned: set,
) -> Counter:
    """If Claude's gaps are empty after filtering, fall back to a hardcoded
    niche-expert features library. Features advertised by competitors
    (in description_features_mentioned) are excluded."""
    try:
        from modules.creation.niche_themes import detect_theme, get_expert_features
    except ImportError:
        return gaps_counter

    if len(gaps_counter) >= 4:
        return gaps_counter   # Claude gave enough — no fallback needed

    theme = detect_theme(niche)
    expert_gaps = get_expert_features(theme.get("name", "default"))

    # Inject expert gaps that aren't trivially covered by what competitors mention
    mention_text = " ".join(description_features_mentioned).lower()
    for g in expert_gaps:
        # Extract the key word from "no <X>" pattern
        key = re.sub(r"^no\s+", "", g.lower()).split("/")[0].strip()
        # Skip if competitor mentions this concept
        if key and key.split()[0] in mention_text:
            continue
        gaps_counter[g] += 1
        if len(gaps_counter) >= 8:
            break
    return gaps_counter


def _aggregate(analyses: List[Dict], niche: str = "") -> Dict:
    """Aggregates a list of per-competitor analyses into niche-level patterns."""
    if not analyses:
        return {}

    layouts    = Counter()
    headers    = Counter()
    decorative = Counter()
    topics     = Counter()
    intros     = Counter()
    features   = Counter()
    gaps       = Counter()
    typo       = Counter()
    palettes   = Counter()
    densities  = Counter()
    lines_per_page: List[int]  = []
    quality_scores: List[int]  = []

    for entry in analyses:
        a = entry.get("analysis", {})
        if not a or a.get("_error"):
            continue
        if a.get("layout_type"):         layouts[a["layout_type"]] += 1
        for h in a.get("header_elements", [])    or []: headers[h] += 1
        for d in a.get("decorative_elements", []) or []: decorative[d] += 1
        for t in a.get("topic_categories", []) or []:
            if _is_real_topic(t):
                topics[t] += 1
        if a.get("intro_style"):         intros[a["intro_style"]] += 1
        for f in a.get("unique_features", [])    or []: features[f] += 1
        for g in a.get("gaps_or_weaknesses", []) or []:
            if _is_real_gap(g):
                gaps[g] += 1
        if a.get("typography_style"):    typo[a["typography_style"]] += 1
        if a.get("palette_description"): palettes[a["palette_description"]] += 1
        if a.get("density"):             densities[a["density"]] += 1
        if isinstance(a.get("lines_per_page"), int): lines_per_page.append(a["lines_per_page"])
        if isinstance(a.get("quality_score"), int):  quality_scores.append(a["quality_score"])

    avg_lines = round(sum(lines_per_page) / len(lines_per_page)) if lines_per_page else None
    avg_quality = round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else None

    # If Claude returned <4 real gaps, inject niche-expert hardcoded fallback
    mentioned = set()
    for w, _ in features.most_common(): mentioned.add(w.lower())
    for w, _ in headers.most_common():  mentioned.add(w.lower())
    for w, _ in topics.most_common():   mentioned.add(w.lower())
    gaps = _inject_expert_fallback_gaps(gaps, niche, mentioned)

    return {
        "n_analyses":            len(analyses),
        "common_layouts":        layouts.most_common(3),
        "common_headers":        headers.most_common(6),
        "common_decorative":     decorative.most_common(6),
        "common_topics":         topics.most_common(10),
        "common_intros":         intros.most_common(3),
        "common_features":       features.most_common(6),
        "common_gaps":           gaps.most_common(8),
        "typography_distribution": typo.most_common(3),
        "palette_distribution":  palettes.most_common(3),
        "density_distribution":  densities.most_common(3),
        "avg_lines_per_page":    avg_lines,
        "avg_quality_score":     avg_quality,
    }


def analyze_competitor_samples(
    niche: str,
    products: List[Dict],
    anthropic_key: str,
    learning_dir: Path,
    max_competitors: int = 3,
    status_cb=None,
) -> Dict:
    """
    Master function:
      - Picks top N competitors by social proof
      - Fetches sample screenshots via Playwright
      - Sends to Claude Vision for structural analysis
      - Aggregates and persists insights
    Returns the aggregated patterns dict.
    """
    def say(msg):
        logger.info(msg)
        if status_cb: status_cb(msg)

    samples_cache = _load_json(_samples_cache_file(learning_dir))
    niche_cache   = _load_json(_niche_insights_file(learning_dir))

    # Top competitors by reviews × rating
    ranked = sorted(
        products,
        key=lambda p: (p.get("reviews", 0) or 0) * max(p.get("rating", 0) or 0, 0.1),
        reverse=True,
    )
    top = [p for p in ranked if p.get("asin")][:max_competitors]

    if not top:
        say(f"⚠️ Aucun concurrent avec ASIN trouvé pour '{niche}'")
        return {}

    analyses: List[Dict] = []
    for prod in top:
        asin  = prod["asin"]
        title = prod.get("title", "")[:50]

        # Cache hit?
        if asin in samples_cache and samples_cache[asin].get("analysis"):
            say(f"   • {title} ({asin}) — cached")
            analyses.append(samples_cache[asin])
            continue

        say(f"   • {title} ({asin}) — capture en cours...")
        analysis: Dict = {}
        source = "none"

        # ── Path A: Try Look Inside screenshots → Claude Vision ─────────
        screenshots = fetch_sample_screenshots(asin, max_pages=6)
        if screenshots:
            say(f"     ↳ {len(screenshots)} page(s) capturées · Claude Vision...")
            analysis = analyze_screenshots_with_vision(
                screenshots, niche, anthropic_key
            )
            if analysis and not analysis.get("_error"):
                source = "vision"

        # ── Path B: Fallback → scrape product description + Claude Text ──
        if not analysis or analysis.get("_error"):
            say(f"     ↳ Look Inside indisponible — fallback description...")
            desc_bundle = fetch_product_description(asin)
            if desc_bundle and any(desc_bundle.values()):
                bundle_len = sum(len(v or "") for v in desc_bundle.values())
                # Skip if too thin — Claude would just hallucinate from thin air
                if bundle_len < 300:
                    say(f"     ↳ ⚠️ Description trop courte ({bundle_len} chars) — skip")
                else:
                    say(f"     ↳ {bundle_len} chars de description scrapés · Claude Haiku...")
                    analysis = analyze_description_with_text(
                        desc_bundle, niche, anthropic_key
                    )
                    if analysis and not analysis.get("_error"):
                        source = "description"

        if not analysis or analysis.get("_error"):
            say(f"     ↳ ⚠️ Aucune analyse exploitable")
            continue

        entry = {
            "asin":     asin,
            "title":    prod.get("title", ""),
            "analysis": analysis,
            "source":   source,        # "vision" | "description"
            "captured_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }
        samples_cache[asin] = entry
        analyses.append(entry)

        say(f"     ↳ ✅ Analysé via {source}")

        # Small pause to be polite to Amazon
        time.sleep(1.5)

    # Persist cache
    _save_json(_samples_cache_file(learning_dir), samples_cache)

    # Aggregate
    agg = _aggregate(analyses, niche=niche)

    if not agg:
        say(f"⚠️ Aucune analyse exploitable pour '{niche}'")
        return {}

    niche_cache[niche.lower().strip()] = {
        "niche":           niche,
        "n_competitors":   len(analyses),
        "patterns":        agg,
        "analyzed_at":     __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    _save_json(_niche_insights_file(learning_dir), niche_cache)

    say(f"✅ Analyse approfondie terminée : {len(analyses)} concurrent(s) → {len(agg.get('common_topics', []))} topics identifiés")
    return agg


# ── Retrieval & prompt-injection helpers ──────────────────────────────────────

def get_sample_insights(learning_dir: Path, niche: str) -> Optional[Dict]:
    """Returns the aggregated patterns saved for a niche (or None)."""
    data = _load_json(_niche_insights_file(learning_dir))
    return data.get(niche.lower().strip())


def compute_design_directives(insights: Optional[Dict]) -> Dict:
    """
    Converts raw competitor patterns into ACTIONABLE design decisions
    that the cover generator and interior PDF builder consume directly.

    Strategy: match competitors' proven patterns, but exceed them where
    possible (more lines, more features, fill their gaps).
    """
    defaults = {
        "cover": {
            "ambition":            "premium",
            "palette_strategy":    "match",
            "palette_hint":        None,
            "composition_hint":    "balanced centered composition with clear focal point",
            "typography_emphasis": "bold confident title hierarchy",
        },
        "interior": {
            "lines_per_page_target":  14,
            "must_have_headers":      ["date", "mood"],
            "gap_fixing_features":    [],
            "density_target":         "medium",
            "add_differentiation":    False,
            "extra_header_elements":  [],
        },
    }
    if not insights:
        return defaults

    patterns = insights.get("patterns") or insights
    if not patterns:
        return defaults

    out = {
        "cover":    dict(defaults["cover"]),
        "interior": dict(defaults["interior"]),
    }

    # ── Cover side ────────────────────────────────────────────────────────
    avg_q = patterns.get("avg_quality_score")
    if avg_q is not None:
        out["cover"]["ambition"] = "premium" if avg_q < 7.5 else "world-class"

    palette = patterns.get("palette_distribution") or []
    if palette:
        out["cover"]["palette_hint"]     = palette[0][0]
        out["cover"]["palette_strategy"] = "match"

    typo = patterns.get("typography_distribution") or []
    if typo:
        top_typo = typo[0][0].lower()
        if "serif" in top_typo:
            out["cover"]["typography_emphasis"] = "modern bold sans-serif title (stands out from serif competitors)"
        elif "sans" in top_typo:
            out["cover"]["typography_emphasis"] = "elegant high-contrast serif title (stands out from sans-serif competitors)"
        elif "script" in top_typo:
            out["cover"]["typography_emphasis"] = "clean bold geometric title (stands out from script competitors)"

    # ── Interior side ─────────────────────────────────────────────────────
    avg_lines = patterns.get("avg_lines_per_page")
    if isinstance(avg_lines, int) and 8 <= avg_lines <= 25:
        out["interior"]["lines_per_page_target"] = avg_lines + 1

    density_dist = patterns.get("density_distribution") or [["medium", 0]]
    density = density_dist[0][0] if density_dist else "medium"
    out["interior"]["density_target"] = "rich" if density == "sparse" else "medium"

    headers = [h for h, _ in patterns.get("common_headers", [])][:5]
    if headers:
        out["interior"]["must_have_headers"] = headers

    gaps = [g for g, _ in patterns.get("common_gaps", [])][:6]
    feats_competitors_have = set(h.lower() for h in headers)
    feature_catalog = ["weather", "energy", "intention", "gratitude"]
    feats_we_can_add = [f for f in feature_catalog if f not in feats_competitors_have]
    out["interior"]["extra_header_elements"] = feats_we_can_add[:2]
    out["interior"]["gap_fixing_features"]   = gaps[:5]
    out["interior"]["add_differentiation"]   = bool(gaps or feats_we_can_add)

    return out


def directives_summary_for_status(d: Dict) -> str:
    """Compact human-readable summary for status_cb messages."""
    intr = d.get("interior", {})
    cov  = d.get("cover", {})
    parts = [
        f"int:{intr.get('lines_per_page_target','?')}lines/{intr.get('density_target','?')}",
    ]
    extras = intr.get("extra_header_elements") or []
    if extras:
        parts.append("+" + ",".join(extras))
    if cov.get("ambition"):
        parts.append(f"cover:{cov['ambition']}")
    return " · ".join(parts)


def sample_insights_for_prompt(insights: Dict) -> str:
    """
    Builds a single concise sentence injectable into Claude listing prompts.
    Explicitly directs Claude to BEAT competitors, not copy them.
    """
    if not insights:
        return ""
    patterns = insights.get("patterns") or insights
    bits = []

    if patterns.get("avg_lines_per_page"):
        bits.append(f"competitors use ~{patterns['avg_lines_per_page']} lines per page")

    if patterns.get("avg_quality_score") is not None:
        bits.append(f"competitor avg quality {patterns['avg_quality_score']}/10")

    layouts = patterns.get("common_layouts", [])
    if layouts:
        bits.append(f"dominant layout: {layouts[0][0]}")

    headers = patterns.get("common_headers", [])
    if headers:
        common = [h for h, _ in headers[:3]]
        bits.append(f"common page headers: {', '.join(common)}")

    topics = patterns.get("common_topics", [])
    if topics:
        common = [t for t, _ in topics[:5]]
        bits.append(f"topic categories competitors cover: {', '.join(common)}")

    features = patterns.get("common_features", [])
    if features:
        common = [f for f, _ in features[:3]]
        bits.append(f"unique features they use: {', '.join(common)}")

    gaps = patterns.get("common_gaps", [])
    if gaps:
        common = [g for g, _ in gaps[:3]]
        bits.append(f"WEAKNESSES to fix: {', '.join(common)}")

    if not bits:
        return ""

    return (
        "DEEP COMPETITOR INTEL (study to BEAT, never copy verbatim): "
        + "; ".join(bits)
        + ". Your goal: match their best patterns AND fix their weaknesses. "
        "Generate ORIGINAL content that is structurally competitive but distinctly your own voice."
    )
