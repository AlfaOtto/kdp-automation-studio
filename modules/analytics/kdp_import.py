"""
KDP royalty-report importer — Module 4 Analytics.

KDP has no public API, so the robust path is: the user downloads their official
royalty report (Reports → Prior months' royalties → Download / or the
Dashboard export) as .xlsx or .csv, and we parse it here.

KDP changes column names occasionally, so we match headers FUZZILY via a
synonym map rather than hard-coding exact strings.

Normalized row schema (one per title × month × marketplace × transaction):
    {
      "date":          "YYYY-MM",     # royalty month
      "title":         str,
      "asin":          str,
      "marketplace":   str,           # "Amazon.com", "Amazon.co.uk", ...
      "format":        str,           # "Paperback" / "Kindle eBook" / "Hardcover"
      "units_sold":    int,
      "units_refunded":int,
      "net_units":     int,
      "royalty":       float,
      "currency":      str,           # "USD", "GBP", ...
      "matched_slug":  str | None,    # local book this row maps to
    }

Imports are appended to output/analytics/sales.jsonl (deduplicated by a stable
row hash so re-importing the same file is idempotent).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Column synonym map (lowercased, stripped) ────────────────────────────────
_COLUMN_SYNONYMS = {
    "date": [
        "royalty date", "royalty month", "date", "month", "order date",
        "transaction date",
    ],
    "title": ["title", "title name", "book title", "asin/title"],
    "asin": ["asin", "asin/isbn", "isbn", "asin / isbn"],
    "marketplace": ["marketplace", "market place", "store", "amazon store"],
    "format": ["royalty type", "format", "product type", "binding", "book type"],
    "units_sold": ["units sold", "units ordered", "quantity", "sold"],
    "units_refunded": ["units refunded", "refunds", "refunded"],
    "net_units": ["net units sold", "net units", "net qty", "net quantity"],
    "royalty": ["royalty", "royalties", "net royalty", "earnings", "estimated royalty"],
    "currency": ["currency", "currency code"],
}


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _build_header_map(headers: List[str]) -> Dict[str, int]:
    """Map normalized synonym → column index. First match wins per field."""
    norm_headers = [_norm(h) for h in headers]
    out: Dict[str, int] = {}
    for field, synonyms in _COLUMN_SYNONYMS.items():
        for syn in synonyms:
            if syn in norm_headers:
                out[field] = norm_headers.index(syn)
                break
        else:
            # Substring fallback (e.g. "royalty date (utc)")
            for i, h in enumerate(norm_headers):
                if any(syn in h for syn in synonyms):
                    out[field] = i
                    break
    return out


def _to_float(v) -> float:
    if v is None:
        return 0.0
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _to_int(v) -> int:
    return int(round(_to_float(v)))


def _norm_date(v) -> str:
    """Return 'YYYY-MM' from many possible date formats."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m")
    s = str(v).strip()
    # Try common patterns
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m", "%b %Y", "%B %Y",
                "%Y/%m/%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    # Last resort: pull a YYYY-MM or YYYY out of the string
    m = re.search(r"(20\d{2})[-/ ](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(20\d{2})", s)
    return m.group(1) if m else s[:7]


def _row_hash(row: Dict) -> str:
    key = f"{row['date']}|{row['asin']}|{row['title']}|{row['marketplace']}|{row['format']}|{row['net_units']}|{row['royalty']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ── Parsing ──────────────────────────────────────────────────────────────────
def _iter_sheets(path: Path):
    """Yield (sheet_name, list_of_rows) for xlsx, or one pseudo-sheet for csv."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = [[c for c in r] for r in ws.iter_rows(values_only=True)]
            yield ws.title, rows
        wb.close()
    elif suffix == ".csv":
        import csv
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            rows = [r for r in csv.reader(f)]
        yield "csv", rows
    else:
        raise ValueError(f"Format non supporté : {suffix} (utilise .xlsx ou .csv)")


def _find_header_row(rows: List[List]) -> Tuple[int, Dict[str, int]]:
    """Scan the first ~15 rows for the one that yields the most field matches."""
    best_idx, best_map, best_score = -1, {}, 0
    for i, row in enumerate(rows[:15]):
        if not row:
            continue
        hmap = _build_header_map([("" if c is None else c) for c in row])
        # Need at least title + (units or royalty) to be a real header
        score = len(hmap)
        if ("title" in hmap and ("net_units" in hmap or "units_sold" in hmap
                                  or "royalty" in hmap) and score > best_score):
            best_idx, best_map, best_score = i, hmap, score
    return best_idx, best_map


def parse_kdp_report(path) -> Dict:
    """
    Parse a KDP royalty .xlsx/.csv → normalized rows + per-sheet diagnostics.
    Returns {"rows": [...], "sheets_used": [...], "warnings": [...]}.
    """
    path = Path(path)
    out_rows: List[Dict] = []
    sheets_used: List[str] = []
    warnings: List[str] = []

    for sheet_name, rows in _iter_sheets(path):
        if not rows:
            continue
        hdr_idx, hmap = _find_header_row(rows)
        if hdr_idx < 0 or "title" not in hmap:
            continue  # not a sales sheet (e.g. summary tab)
        sheets_used.append(sheet_name)

        for raw in rows[hdr_idx + 1:]:
            if not raw or all(c is None or str(c).strip() == "" for c in raw):
                continue

            def cell(field, default=None):
                idx = hmap.get(field)
                if idx is None or idx >= len(raw):
                    return default
                return raw[idx]

            title = str(cell("title", "") or "").strip()
            if not title or _norm(title) in ("total", "totals", "grand total"):
                continue

            units_sold = _to_int(cell("units_sold", 0))
            refunded   = _to_int(cell("units_refunded", 0))
            net        = cell("net_units", None)
            net_units  = _to_int(net) if net is not None else (units_sold - refunded)

            row = {
                "date":          _norm_date(cell("date", "")),
                "title":         title,
                "asin":          str(cell("asin", "") or "").strip(),
                "marketplace":   str(cell("marketplace", "") or "").strip() or "Unknown",
                "format":        str(cell("format", "") or "").strip() or "Unknown",
                "units_sold":    units_sold,
                "units_refunded":refunded,
                "net_units":     net_units,
                "royalty":       round(_to_float(cell("royalty", 0)), 2),
                "currency":      (str(cell("currency", "") or "").strip().upper() or "USD"),
                "matched_slug":  None,
            }
            row["row_hash"] = _row_hash(row)
            out_rows.append(row)

    if not sheets_used:
        warnings.append("Aucune feuille de ventes reconnue. Vérifie que c'est bien "
                        "un rapport de royalties KDP (.xlsx) avec une colonne Title.")
    return {"rows": out_rows, "sheets_used": sheets_used, "warnings": warnings}


# ── Matching to local books ──────────────────────────────────────────────────
def _local_books() -> List[Dict]:
    """Read all local listings (drafts + published) → [{slug, title, asin}]."""
    root = Path.home() / "Desktop" / "KDP"
    books = []
    if not root.exists():
        return books
    candidates = list(root.iterdir())
    pub = root / "published"
    if pub.exists():
        candidates += list(pub.iterdir())
    for d in candidates:
        if not d.is_dir() or d.name in ("published", "Tuto"):
            continue
        lp = d / "listing.json"
        if not lp.exists():
            continue
        try:
            L = json.loads(lp.read_text(encoding="utf-8"))
            books.append({
                "slug":  d.name,
                "title": str(L.get("title", "")).strip(),
                "asin":  str(L.get("asin", "")).strip(),
            })
        except Exception:
            continue
    return books


def _match_slug(row: Dict, books: List[Dict]) -> Optional[str]:
    asin = row.get("asin", "").strip().upper()
    rtitle = _norm(row.get("title", ""))
    # 1. ASIN exact
    if asin:
        for b in books:
            if b["asin"] and b["asin"].strip().upper() == asin:
                return b["slug"]
    # 2. Title exact
    for b in books:
        if _norm(b["title"]) == rtitle and rtitle:
            return b["slug"]
    # 3. Title prefix overlap (KDP truncates long titles)
    for b in books:
        bt = _norm(b["title"])
        if bt and rtitle and (bt.startswith(rtitle[:25]) or rtitle.startswith(bt[:25])):
            return b["slug"]
    return None


def match_rows_to_books(rows: List[Dict]) -> Tuple[List[Dict], int]:
    """Annotate each row with matched_slug. Returns (rows, n_matched)."""
    books = _local_books()
    n = 0
    for r in rows:
        slug = _match_slug(r, books)
        r["matched_slug"] = slug
        if slug:
            n += 1
    return rows, n


# ── Persistence (idempotent) ─────────────────────────────────────────────────
def _store_path(analytics_dir: Path) -> Path:
    p = Path(analytics_dir) / "sales.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_sales(analytics_dir: Path) -> List[Dict]:
    p = _store_path(analytics_dir)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def save_sales(analytics_dir: Path, rows: List[Dict]) -> Dict:
    """
    Append new rows, deduplicated by row_hash. Returns {"added", "skipped",
    "total"}.
    """
    p = _store_path(analytics_dir)
    existing = load_sales(analytics_dir)
    seen = {r.get("row_hash") for r in existing if r.get("row_hash")}
    added = 0
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            h = r.get("row_hash") or _row_hash(r)
            r["row_hash"] = h
            if h in seen:
                continue
            seen.add(h)
            r["_imported_at"] = datetime.now().isoformat(timespec="seconds")
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            added += 1
    return {"added": added, "skipped": len(rows) - added, "total": len(existing) + added}


def import_kdp_file(file_path, analytics_dir: Path) -> Dict:
    """Full pipeline: parse → match → save. Returns a summary dict."""
    parsed = parse_kdp_report(file_path)
    rows, n_matched = match_rows_to_books(parsed["rows"])
    saved = save_sales(analytics_dir, rows)
    return {
        "parsed_rows":  len(rows),
        "matched":      n_matched,
        "sheets_used":  parsed["sheets_used"],
        "warnings":     parsed["warnings"],
        **saved,
    }
