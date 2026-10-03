"""
Scans the user's KDP products folder and classifies books as:
  - "draft"     : interior.pdf + cover.pdf + listing.json present, NOT in published/
  - "published" : the folder lives inside ~/Desktop/KDP/published/
  - "incomplete": missing at least one of the 3 required files

The "Marquer comme publié" action moves a folder into published/.
"""
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


@dataclass
class ProductFile:
    slug:         str                       # folder name
    folder:       Path
    interior_pdf: Optional[Path]   = None
    cover_pdf:    Optional[Path]   = None
    listing_json: Optional[Path]   = None
    listing_data: Optional[Dict]   = None
    status:       str              = "incomplete"   # draft | published | incomplete
    published_at: Optional[str]    = None           # ISO timestamp
    published_url: Optional[str]   = None           # KDP product URL or ASIN

    @property
    def is_complete(self) -> bool:
        return all([
            self.interior_pdf and self.interior_pdf.exists(),
            self.cover_pdf    and self.cover_pdf.exists(),
            self.listing_json and self.listing_json.exists(),
        ])

    @property
    def title(self) -> str:
        return (self.listing_data or {}).get("title", self.slug)

    @property
    def niche(self) -> str:
        return (self.listing_data or {}).get("niche", self.slug)

    @property
    def product_type(self) -> str:
        return (self.listing_data or {}).get("product_type", "?")


def _build_product(folder: Path, status_hint: str = "draft") -> Optional[ProductFile]:
    """Inspect a folder and produce a ProductFile, or None if it's not a product."""
    if not folder.is_dir():
        return None
    interior = folder / "interior.pdf"
    cover    = folder / "cover.pdf"
    listing  = folder / "listing.json"
    pub_marker = folder / "published.json"

    data = None
    if listing.exists():
        try:
            data = json.loads(listing.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Bad listing.json in {folder}: {e}")

    pf = ProductFile(
        slug         = folder.name,
        folder       = folder,
        interior_pdf = interior if interior.exists() else None,
        cover_pdf    = cover if cover.exists() else None,
        listing_json = listing if listing.exists() else None,
        listing_data = data,
    )

    if pub_marker.exists():
        try:
            marker = json.loads(pub_marker.read_text(encoding="utf-8"))
            pf.published_at  = marker.get("published_at")
            pf.published_url = marker.get("kdp_url") or marker.get("asin")
        except Exception:
            pass

    if status_hint == "published":
        pf.status = "published"
    elif pf.is_complete:
        pf.status = "draft"
    else:
        pf.status = "incomplete"
    return pf


def scan_products(kdp_root: Path) -> List[ProductFile]:
    """
    Scan ~/Desktop/KDP/ and return all products (drafts + published).
    Drafts = direct subfolders. Published = subfolders of KDP/published/.
    """
    kdp_root = Path(kdp_root)
    if not kdp_root.exists():
        return []

    products: List[ProductFile] = []
    published_root = kdp_root / "published"

    # 1. Drafts: subfolders of KDP/ that are NOT 'published' itself
    for child in sorted(kdp_root.iterdir()):
        if not child.is_dir() or child.name in ("published", ".DS_Store"):
            continue
        pf = _build_product(child, status_hint="draft")
        if pf:
            products.append(pf)

    # 2. Published: subfolders of KDP/published/
    if published_root.exists():
        for child in sorted(published_root.iterdir()):
            if not child.is_dir() or child.name == ".DS_Store":
                continue
            pf = _build_product(child, status_hint="published")
            if pf:
                products.append(pf)

    return products


def mark_as_published(
    product: ProductFile,
    kdp_root: Path,
    kdp_url: str = "",
    asin: str = "",
) -> Path:
    """
    Move the product folder into ~/Desktop/KDP/published/{slug}/ and write a
    published.json marker with the date + KDP URL/ASIN.
    Returns the new folder path.
    Raises if the source doesn't exist or the destination already has a
    folder with the same name.
    """
    kdp_root = Path(kdp_root)
    published_root = kdp_root / "published"
    published_root.mkdir(parents=True, exist_ok=True)
    dest = published_root / product.slug

    if not product.folder.exists():
        raise FileNotFoundError(f"Source folder missing: {product.folder}")
    if dest.exists():
        # Avoid clobbering — suffix with timestamp
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = published_root / f"{product.slug}_{stamp}"

    # Write the marker BEFORE moving so it's part of the moved folder
    marker = product.folder / "published.json"
    marker.write_text(
        json.dumps({
            "published_at": datetime.now().isoformat(),
            "kdp_url":      kdp_url,
            "asin":         asin,
            "original_slug": product.slug,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    shutil.move(str(product.folder), str(dest))
    logger.info(f"Marked as published: {product.slug} → {dest}")
    return dest


def revert_published(product: ProductFile, kdp_root: Path) -> Path:
    """
    Move a published product back to drafts (in case of mistake).
    Removes the published.json marker.
    """
    kdp_root = Path(kdp_root)
    dest = kdp_root / product.slug
    if dest.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = kdp_root / f"{product.slug}_{stamp}"

    marker = product.folder / "published.json"
    if marker.exists():
        marker.unlink()

    shutil.move(str(product.folder), str(dest))
    return dest


def summary(products: List[ProductFile]) -> Dict[str, int]:
    """Counts by status — useful for the UI banner."""
    return {
        "total":      len(products),
        "draft":      sum(1 for p in products if p.status == "draft"),
        "published":  sum(1 for p in products if p.status == "published"),
        "incomplete": sum(1 for p in products if p.status == "incomplete"),
    }
