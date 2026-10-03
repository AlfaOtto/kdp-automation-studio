"""
Auto-fixer — runs each fix_strategy from validator issues.
Fixes call existing infrastructure (categories_helper, batch.regenerate_*, etc.)
so we don't duplicate logic.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FixResult:
    strategy:   str
    success:    bool
    message:    str


@dataclass
class FixReport:
    product_slug: str
    fixes:        List[FixResult] = field(default_factory=list)

    @property
    def n_successes(self) -> int:
        return sum(1 for f in self.fixes if f.success)

    @property
    def n_failures(self) -> int:
        return sum(1 for f in self.fixes if not f.success)


def auto_fix_product(
    product_folder: Path,
    anthropic_key: str,
    openai_key:    str,
    learning_dir:  Optional[Path] = None,
    strategies:    Optional[List[str]] = None,
    status_cb:     Optional[Callable[[str], None]] = None,
) -> FixReport:
    """
    Applies each strategy in `strategies` (or all auto-fixable from a fresh
    validation if None). Returns a FixReport.

    Available strategies:
      - gen_categories         → call categories_helper
      - fix_primary_category   → mark first category as primary in listing.json
      - fix_keywords           → trim, dedupe, pad to 7 via Claude
      - regen_cover            → rebuild cover.pdf
      - regen_interior         → rebuild interior.pdf
      - regen_listing          → regenerate listing entirely (preserves niche)
      - infer_page_count       → use actual PDF page count as listing.page_count
    """
    def s(msg):
        if status_cb: status_cb(msg)

    product_folder = Path(product_folder)
    report = FixReport(product_slug=product_folder.name)

    if strategies is None:
        from modules.quality.validator import validate_product
        v = validate_product(product_folder)
        strategies = sorted({i.fix_strategy for i in v.auto_fixable if i.fix_strategy})

    if not strategies:
        s("ℹ️ Nothing to auto-fix")
        return report

    listing_path = product_folder / "listing.json"

    # Order matters: fix listing.json BEFORE rebuilding PDFs that depend on it
    order = [
        "gen_categories", "fix_primary_category", "fix_keywords",
        "infer_page_count", "regen_listing",
        "regen_interior", "regen_cover",
    ]
    sorted_strategies = sorted(strategies, key=lambda x: order.index(x) if x in order else 99)

    for strat in sorted_strategies:
        s(f"🔧 Applying: {strat}…")
        try:
            if strat == "gen_categories":
                from modules.publishing.categories_helper import generate_categories_for_listing
                cats = generate_categories_for_listing(
                    listing_path, anthropic_key=anthropic_key, status_cb=lambda m: None,
                )
                report.fixes.append(FixResult(strat, True,
                    f"{len(cats)} categories added"))

            elif strat == "fix_primary_category":
                listing = json.loads(listing_path.read_text(encoding="utf-8"))
                cats = listing.get("categories", []) or []
                if cats:
                    # Clear any existing primary, set first as primary
                    for c in cats:
                        if isinstance(c, dict):
                            c["primary"] = False
                    if isinstance(cats[0], dict):
                        cats[0]["primary"] = True
                    else:
                        cats[0] = {"path": str(cats[0]), "primary": True}
                    listing["categories"] = cats
                    listing_path.write_text(json.dumps(listing, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
                    report.fixes.append(FixResult(strat, True, "Primary category set to first"))
                else:
                    report.fixes.append(FixResult(strat, False, "No categories to mark"))

            elif strat == "fix_keywords":
                listing = json.loads(listing_path.read_text(encoding="utf-8"))
                kws = listing.get("keywords", []) or []
                # Dedupe (case-insensitive), trim each to 50 chars
                seen = set()
                cleaned = []
                for kw in kws:
                    k = (kw or "").strip()[:50]
                    if k and k.lower() not in seen:
                        seen.add(k.lower())
                        cleaned.append(k)
                # If less than 7, ask Claude to fill the rest
                if len(cleaned) < 7:
                    import anthropic
                    client = anthropic.Anthropic(api_key=anthropic_key)
                    needed = 7 - len(cleaned)
                    prompt = (
                        f"Generate {needed} additional Amazon KDP search keywords for the book:\n"
                        f"Niche: {listing.get('niche', '?')}\n"
                        f"Title: {listing.get('title', '?')}\n"
                        f"Existing keywords: {cleaned}\n\n"
                        f"Rules:\n- Each ≤50 chars\n- No duplicates of existing\n"
                        f"- Buyer search terms, not author terms\n"
                        f"Return ONLY the {needed} new keywords, one per line."
                    )
                    msg = client.messages.create(
                        model="claude-haiku-4-5", max_tokens=300,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    new_kws = [l.strip()[:50] for l in msg.content[0].text.strip().splitlines()
                               if l.strip() and len(l.strip()) > 2]
                    for kw in new_kws:
                        if kw.lower() not in seen and len(cleaned) < 7:
                            seen.add(kw.lower())
                            cleaned.append(kw)
                listing["keywords"] = cleaned[:7]
                listing_path.write_text(json.dumps(listing, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
                report.fixes.append(FixResult(strat, True,
                    f"Keywords cleaned: {len(cleaned)} unique"))

            elif strat == "infer_page_count":
                from modules.quality.validator import _pdf_page_count
                interior = product_folder / "interior.pdf"
                if interior.exists():
                    pc = _pdf_page_count(interior)
                    if pc:
                        listing = json.loads(listing_path.read_text(encoding="utf-8"))
                        listing["page_count"] = int(pc)
                        listing_path.write_text(json.dumps(listing, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
                        report.fixes.append(FixResult(strat, True,
                            f"page_count set to {pc} (from actual PDF)"))
                    else:
                        report.fixes.append(FixResult(strat, False, "Could not read PDF page count"))
                else:
                    report.fixes.append(FixResult(strat, False, "interior.pdf missing"))

            elif strat == "regen_cover":
                from modules.creation.batch import regenerate_cover_only
                regenerate_cover_only(
                    product_dir=product_folder,
                    anthropic_key=anthropic_key,
                    openai_key=openai_key,
                    status_cb=lambda m: None,
                    learning_dir=learning_dir,
                    free_style=True,
                )
                report.fixes.append(FixResult(strat, True, "cover.pdf regenerated"))

            elif strat == "regen_interior":
                from modules.creation.batch import regenerate_interior_only
                regenerate_interior_only(
                    product_dir=product_folder,
                    anthropic_key=anthropic_key,
                    openai_key=openai_key,
                    status_cb=lambda m: None,
                    learning_dir=learning_dir,
                )
                report.fixes.append(FixResult(strat, True, "interior.pdf regenerated"))

            elif strat == "regen_listing":
                # Most expensive — regenerate the whole listing via Claude
                from modules.creation.content_generator import generate_listing, detect_product_type
                listing = json.loads(listing_path.read_text(encoding="utf-8"))
                niche = listing.get("niche", "")
                if not niche:
                    report.fixes.append(FixResult(strat, False, "No niche in listing"))
                    continue
                ptype = listing.get("product_type") or detect_product_type(niche)
                new_listing = generate_listing(
                    niche=niche, product_type=ptype, api_key=anthropic_key,
                    status_cb=lambda m: None,
                )
                # Preserve original niche/product_type
                new_listing["niche"] = niche
                new_listing["product_type"] = ptype
                listing_path.write_text(json.dumps(new_listing, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
                report.fixes.append(FixResult(strat, True, "Listing regenerated"))

            else:
                report.fixes.append(FixResult(strat, False, f"Unknown strategy: {strat}"))
        except Exception as e:
            logger.warning(f"Fix '{strat}' failed: {e}", exc_info=True)
            report.fixes.append(FixResult(strat, False, f"Error: {e}"))

    return report
