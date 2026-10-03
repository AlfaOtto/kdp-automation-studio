"""
Analytics aggregations on imported KDP sales — Module 4.

All functions take the list of normalized rows (from kdp_import.load_sales) and
return plain dicts/lists ready for the Streamlit dashboards. Royalties are
grouped BY CURRENCY (KDP reports mix USD/GBP/EUR…); we never fake a conversion.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List


def _sum_by_currency(rows: List[Dict], field: str = "royalty") -> Dict[str, float]:
    out: Dict[str, float] = defaultdict(float)
    for r in rows:
        out[r.get("currency", "USD")] += float(r.get(field, 0) or 0)
    return {k: round(v, 2) for k, v in out.items()}


def overview(rows: List[Dict]) -> Dict:
    """Headline KPIs across the whole imported dataset."""
    if not rows:
        return {"empty": True}
    total_units = sum(int(r.get("net_units", 0) or 0) for r in rows)
    total_refunds = sum(int(r.get("units_refunded", 0) or 0) for r in rows)
    royalty_by_cur = _sum_by_currency(rows)
    months = sorted({r["date"] for r in rows if r.get("date")})
    books = {r.get("matched_slug") or r.get("title") for r in rows}
    return {
        "empty":          False,
        "total_net_units": total_units,
        "total_refunds":  total_refunds,
        "royalty_by_currency": royalty_by_cur,
        "n_months":       len(months),
        "first_month":    months[0] if months else "—",
        "last_month":     months[-1] if months else "—",
        "n_titles":       len(books),
        "n_rows":         len(rows),
    }


def by_book(rows: List[Dict]) -> List[Dict]:
    """One aggregated entry per book (matched_slug or title), sorted by units."""
    agg: Dict[str, Dict] = {}
    for r in rows:
        key = r.get("matched_slug") or r.get("title") or "?"
        e = agg.setdefault(key, {
            "key": key,
            "title": r.get("title", key),
            "slug": r.get("matched_slug"),
            "net_units": 0,
            "refunds": 0,
            "royalty_by_currency": defaultdict(float),
            "marketplaces": set(),
            "formats": set(),
        })
        e["net_units"] += int(r.get("net_units", 0) or 0)
        e["refunds"]   += int(r.get("units_refunded", 0) or 0)
        e["royalty_by_currency"][r.get("currency", "USD")] += float(r.get("royalty", 0) or 0)
        if r.get("marketplace"): e["marketplaces"].add(r["marketplace"])
        if r.get("format"):      e["formats"].add(r["format"])
    out = []
    for e in agg.values():
        e["royalty_by_currency"] = {k: round(v, 2) for k, v in e["royalty_by_currency"].items()}
        e["marketplaces"] = sorted(e["marketplaces"])
        e["formats"] = sorted(e["formats"])
        e["royalty_str"] = " · ".join(f"{v:.2f} {k}" for k, v in e["royalty_by_currency"].items())
        out.append(e)
    out.sort(key=lambda x: -x["net_units"])
    return out


def by_month(rows: List[Dict]) -> List[Dict]:
    """Monthly time-series: units + royalty (primary currency) per month."""
    agg: Dict[str, Dict] = {}
    for r in rows:
        m = r.get("date", "")
        if not m:
            continue
        e = agg.setdefault(m, {"month": m, "net_units": 0,
                               "royalty_by_currency": defaultdict(float)})
        e["net_units"] += int(r.get("net_units", 0) or 0)
        e["royalty_by_currency"][r.get("currency", "USD")] += float(r.get("royalty", 0) or 0)
    out = []
    for e in agg.values():
        e["royalty_by_currency"] = {k: round(v, 2) for k, v in e["royalty_by_currency"].items()}
        # Primary currency = the one with the most royalty this month
        if e["royalty_by_currency"]:
            prim = max(e["royalty_by_currency"].items(), key=lambda kv: kv[1])
            e["royalty_primary"] = prim[1]
            e["currency_primary"] = prim[0]
        else:
            e["royalty_primary"] = 0.0
            e["currency_primary"] = "USD"
        out.append(e)
    out.sort(key=lambda x: x["month"])
    return out


def by_marketplace(rows: List[Dict]) -> List[Dict]:
    agg: Dict[str, Dict] = {}
    for r in rows:
        mk = r.get("marketplace", "Unknown")
        e = agg.setdefault(mk, {"marketplace": mk, "net_units": 0,
                                "royalty_by_currency": defaultdict(float)})
        e["net_units"] += int(r.get("net_units", 0) or 0)
        e["royalty_by_currency"][r.get("currency", "USD")] += float(r.get("royalty", 0) or 0)
    out = []
    for e in agg.values():
        e["royalty_by_currency"] = {k: round(v, 2) for k, v in e["royalty_by_currency"].items()}
        e["royalty_str"] = " · ".join(f"{v:.2f} {k}" for k, v in e["royalty_by_currency"].items())
        out.append(e)
    out.sort(key=lambda x: -x["net_units"])
    return out


def movers(rows: List[Dict], min_months: int = 2) -> Dict:
    """
    Detect books that are accelerating vs declining month-over-month.
    Returns {"rising": [...], "falling": [...]} — feeds the Wave-4 PPC
    'launch only if it sells organically' gate (see SESSION_HANDOFF §26.1).
    """
    per_book_month: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        key = r.get("matched_slug") or r.get("title") or "?"
        if r.get("date"):
            per_book_month[key][r["date"]] += int(r.get("net_units", 0) or 0)
    rising, falling = [], []
    for key, months in per_book_month.items():
        if len(months) < min_months:
            continue
        ordered = sorted(months.items())
        last = ordered[-1][1]
        prev = ordered[-2][1]
        delta = last - prev
        entry = {"key": key, "last_month": ordered[-1][0], "last": last,
                 "prev": prev, "delta": delta}
        if delta > 0:
            rising.append(entry)
        elif delta < 0:
            falling.append(entry)
    rising.sort(key=lambda x: -x["delta"])
    falling.sort(key=lambda x: x["delta"])
    return {"rising": rising, "falling": falling}
