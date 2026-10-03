"""
Amazon book search scraper using Playwright.
Uses direct DOM queries — more reliable than HTML string parsing.
"""
import re
import time
import random
import logging
from typing import List, Dict, Optional, Callable
from playwright.sync_api import sync_playwright, Page, Browser

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _delay(min_s=2.0, max_s=4.5):
    time.sleep(random.uniform(min_s, max_s))


def _is_blocked(page: Page) -> bool:
    title = page.title().lower()
    url = page.url.lower()
    return any(x in title for x in ["captcha", "robot check", "sorry"]) or "captcha" in url


def _extract_number(text: str) -> int:
    """Extract first integer from a string. e.g. '1,234 ratings' → 1234"""
    if not text:
        return 0
    clean = text.replace(",", "").replace(".", "")
    m = re.search(r"\d+", clean)
    return int(m.group()) if m else 0


def _extract_price(text: str) -> float:
    """Extract price float from a string. e.g. '$12.99' → 12.99"""
    if not text:
        return 0.0
    m = re.search(r"[\d]+\.[\d]{2}", text.replace(",", ""))
    if m:
        return float(m.group())
    m = re.search(r"[\d]+", text.replace(",", ""))
    return float(m.group()) if m else 0.0


def _extract_product(card) -> Optional[Dict]:
    """
    Extract all product fields directly from a Playwright element.
    Uses aria-labels and stable selectors — resilient to Amazon HTML changes.
    """
    try:
        # ASIN (always in the data-asin attribute — very stable)
        asin = card.get_attribute("data-asin")
        if not asin or len(asin) < 5:
            return None

        # Skip sponsored results
        if card.query_selector("[aria-label='Sponsored'], .puis-sponsored-label-text"):
            return None

        # ── Title ──────────────────────────────────────────────────────────
        title = ""
        for sel in ["h2 a span", "h2 span", "[data-cy='title-recipe'] span"]:
            el = card.query_selector(sel)
            if el:
                title = el.text_content().strip()
                if title:
                    break
        if not title:
            return None

        # ── Author ─────────────────────────────────────────────────────────
        author = "Unknown"
        for sel in [
            ".a-row .a-size-base a.a-link-normal",
            "[data-cy='author-recipe'] a",
            ".s-line-clamp-1 a",
        ]:
            el = card.query_selector(sel)
            if el:
                t = el.text_content().strip()
                if t and t.lower() not in title.lower():
                    author = t
                    break

        # ── Rating  (aria-label = "4.5 out of 5 stars") ────────────────────
        rating = 0.0
        for sel in [
            "i[class*='a-star'] span.a-icon-alt",
            "[aria-label*='out of 5 stars']",
            "span.a-icon-alt",
        ]:
            el = card.query_selector(sel)
            if el:
                label = (el.get_attribute("aria-label") or el.text_content() or "").strip()
                m = re.search(r"([\d.]+)\s+out of 5", label)
                if m:
                    rating = float(m.group(1))
                    break

        # ── Reviews  (aria-label = "1,234 ratings") ─────────────────────────
        reviews = 0
        for sel in [
            "a[aria-label*='ratings']",
            "a[aria-label*='rating']",
            "span[aria-label*='ratings']",
            ".s-underline-text",
        ]:
            el = card.query_selector(sel)
            if el:
                label = (el.get_attribute("aria-label") or el.text_content() or "").strip()
                n = _extract_number(label)
                if n > 0:
                    reviews = n
                    break

        # ── Price ───────────────────────────────────────────────────────────
        # Amazon search cards typically show MULTIPLE format prices :
        #   "Kindle Edition $0.99 | Paperback $12.99 | Hardcover $18.99"
        # We want the PAPERBACK price (KDP target). Strategy:
        #   1. Find rows mentioning "Paperback / Notebook / Spiral-bound", grab their price
        #   2. Fallback: get all valid prices, exclude Kindle-cheap (<$5), pick median
        #   3. Last resort: first valid price in card
        price = 0.0
        debug_prices: List[float] = []

        PAPERBACK_FORMATS = ("paperback", "notebook", "spiral", "hardcover")

        # ── Strategy 1: Format-aware (look for "Paperback" + nearby price) ──
        # Amazon usually wraps a format-price pair in <a> or <div class="a-row">
        for fmt_container in card.query_selector_all("a.a-link-normal, div.a-row, div.a-section"):
            try:
                txt = (fmt_container.text_content() or "").lower()
            except Exception:
                continue
            # Skip "Other formats" links and "From $X" patterns that aren't real prices
            if "see all" in txt or "more buying choices" in txt:
                continue
            if not any(fmt in txt for fmt in PAPERBACK_FORMATS):
                continue
            # Find price inside this container
            for psel in [".a-price[data-a-color='base'] .a-offscreen",
                         ".a-color-base .a-offscreen",
                         ".a-price .a-offscreen"]:
                p_el = fmt_container.query_selector(psel)
                if p_el:
                    p_val = _extract_price(p_el.text_content().strip())
                    if 4.99 <= p_val <= 49.99:
                        price = p_val
                        break
            if price > 0:
                break

        # ── Strategy 2: All valid prices in card, exclude Kindle range ──────
        if price == 0.0:
            for el in card.query_selector_all(".a-price .a-offscreen"):
                # Skip prices inside a strikethrough or "List Price" parent
                try:
                    parent_class = (el.evaluate(
                        "n => n.closest('.a-text-price, .a-text-strike, [data-a-color=\"secondary\"]') ? 'BAD' : 'OK'"
                    ))
                except Exception:
                    parent_class = "OK"
                if parent_class == "BAD":
                    continue
                p = _extract_price(el.text_content().strip())
                if 0.99 <= p <= 49.99:
                    debug_prices.append(p)

            if debug_prices:
                # Sort and pick the realistic paperback price
                # If multiple prices: skip the very low (kindle) and pick next
                debug_prices.sort()
                paperback_range = [p for p in debug_prices if 4.99 <= p <= 35.0]
                if paperback_range:
                    price = paperback_range[0]
                elif len(debug_prices) >= 2:
                    # No paperback range — pick second smallest (skip Kindle)
                    price = debug_prices[1]
                else:
                    price = debug_prices[0]

        # ── Strategy 3: last resort — the [data-a-color='base'] price ───────
        if price == 0.0:
            el = card.query_selector("[data-a-color='base'] .a-offscreen")
            if el:
                p = _extract_price(el.text_content().strip())
                if 0.99 <= p <= 49.99:
                    price = p

        # ── Cover image URL (for competitor color analysis) ────────────────
        image_url = ""
        for sel in ["img.s-image", "img[data-image-latency='s-product-image']", "img"]:
            el = card.query_selector(sel)
            if el:
                src = el.get_attribute("src") or el.get_attribute("data-src") or ""
                if src and src.startswith("http") and any(
                    e in src.lower() for e in [".jpg", ".jpeg", ".png", ".webp"]
                ):
                    image_url = src
                    break

        # ── Format ──────────────────────────────────────────────────────────
        fmt = "Unknown"
        fmt_keywords = ["Kindle", "Paperback", "Hardcover", "Spiral-bound", "Notebook"]
        for sel in [".a-size-base.a-color-secondary", ".a-badge-text", ".a-size-base"]:
            for el in card.query_selector_all(sel):
                t = el.text_content().strip()
                for kw in fmt_keywords:
                    if kw.lower() in t.lower():
                        fmt = kw
                        break
                if fmt != "Unknown":
                    break
            if fmt != "Unknown":
                break

        return {
            "asin":      asin,
            "title":     title,
            "author":    author,
            "rating":    rating,
            "reviews":   reviews,
            "price":     price,
            "format":    fmt,
            "image_url": image_url,
            "sponsored": False,
        }

    except Exception as e:
        logger.debug(f"Extract error: {e}")
        return None


class AmazonScraper:
    """Amazon KDP research scraper. Use as context manager."""

    # Restart Chromium every N searches — even with contexts closed, the
    # browser process itself slowly accumulates memory during huge scans.
    _RECYCLE_EVERY = 25

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._ctx = None
        self._search_count = 0

    def _launch_browser(self):
        return self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
            ],
        )

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._launch_browser()
        return self

    def __exit__(self, *args):
        if self._ctx:
            try:
                self._ctx.close()
            except Exception:
                pass
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _new_page(self) -> Page:
        # MEMORY-LEAK FIX: close the previous context before opening a new one.
        # Each Chromium context holds real memory; hundreds of unclosed contexts
        # during a big scan exhausted the machine's RAM (system crash/reboot).
        if self._ctx:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None

        # BROWSER RECYCLING: periodically restart Chromium to release memory
        # accumulated inside the browser process itself.
        self._search_count += 1
        if self._search_count % self._RECYCLE_EVERY == 0:
            try:
                logger.info("Recycling Chromium browser (memory hygiene)")
                self._browser.close()
            except Exception:
                pass
            self._browser = self._launch_browser()

        self._ctx = ctx = self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        page = ctx.new_page()
        # Hide automation fingerprint
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
        """)
        return page

    def search_books(
        self,
        keyword: str,
        max_results: int = 20,
        progress_callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        Search Amazon books section for keyword.
        Returns list of product dicts with real price/reviews data.
        """
        products = []
        page = self._new_page()
        page_num = 1

        def cb(msg):
            if progress_callback:
                progress_callback(msg)

        try:
            while len(products) < max_results:
                url = (
                    f"https://www.amazon.com/s"
                    f"?k={keyword.replace(' ', '+')}"
                    f"&i=stripbooks"
                    f"&page={page_num}"
                )
                cb(f"Page {page_num} — \"{keyword}\"...")

                page.goto(url, wait_until="load", timeout=35000)
                _delay(2.5, 4.0)

                if _is_blocked(page):
                    cb("Temporisation Amazon détectée, pause...")
                    _delay(10.0, 18.0)
                    page.goto(url, wait_until="load", timeout=35000)
                    _delay(3.0, 5.0)
                    if _is_blocked(page):
                        break

                cards = page.query_selector_all('[data-component-type="s-search-result"]')
                if not cards:
                    cb(f"Aucun produit trouvé page {page_num}")
                    break

                page_found = 0
                for card in cards:
                    if len(products) >= max_results:
                        break
                    product = _extract_product(card)
                    if product:
                        product["keyword"]  = keyword
                        product["position"] = len(products) + 1
                        product["url"]      = f"https://www.amazon.com/dp/{product['asin']}"
                        products.append(product)
                        page_found += 1

                cb(f"Page {page_num} — {page_found} produits extraits (total: {len(products)})")

                # Validate data quality
                non_zero_reviews = sum(1 for p in products if p["reviews"] > 0)
                if len(products) >= 5 and non_zero_reviews == 0:
                    logger.warning(f"All reviews=0 for '{keyword}' — possible scrape block")

                # Next page
                nxt = page.query_selector(".s-pagination-next:not(.s-pagination-disabled)")
                if not nxt or len(products) >= max_results:
                    break
                page_num += 1
                _delay(2.0, 3.5)

        except Exception as e:
            logger.error(f"search_books error: {e}")
        finally:
            page.close()

        return products

    def get_product_bsr(self, asin: str) -> Dict:
        """Fetch BSR and details from a product detail page."""
        page = self._new_page()
        result = {"asin": asin, "bsr": [], "pages": None, "pub_date": None}

        try:
            page.goto(f"https://www.amazon.com/dp/{asin}", wait_until="load", timeout=30000)
            _delay(2.0, 3.5)

            if _is_blocked(page):
                return result

            # BSR — look in product details table
            bsr_els = page.query_selector_all("#detailBulletsWrapper_feature_div li, #productDetails_detailBullets_sections1 tr")
            for el in bsr_els:
                text = el.text_content()
                if "Best Sellers Rank" in text or "Amazon Best Sellers Rank" in text:
                    # Extract rank numbers
                    ranks = re.findall(r"#([\d,]+)\s+in\s+([^(#\n]+)", text)
                    for rank_str, cat in ranks:
                        try:
                            result["bsr"].append({
                                "rank": int(rank_str.replace(",", "")),
                                "category": cat.strip(),
                            })
                        except ValueError:
                            pass
                    break

            # Page count
            for label in ["Print length", "Pages", "pages"]:
                el = page.query_selector(f"[class*='detail'] tr:has-text('{label}')")
                if el:
                    t = el.text_content()
                    m = re.search(r"([\d,]+)\s*pages?", t, re.I)
                    if m:
                        result["pages"] = int(m.group(1).replace(",", ""))
                    break

        except Exception as e:
            logger.error(f"get_product_bsr error ({asin}): {e}")
        finally:
            page.close()

        return result

    def enrich_with_bsr(
        self,
        products: List[Dict],
        sample_size: int = 5,
        progress_callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """Add BSR data to a sample of products."""
        sample = products[:sample_size]
        for i, p in enumerate(sample):
            if progress_callback:
                progress_callback(f"BSR {i+1}/{len(sample)}...")
            details = self.get_product_bsr(p["asin"])
            if details["bsr"]:
                p["bsr_main"]     = details["bsr"][0]["rank"]
                p["bsr_category"] = details["bsr"][0]["category"]
            if details["pages"]:
                p["pages"] = details["pages"]
            _delay(2.0, 3.0)
        return products
