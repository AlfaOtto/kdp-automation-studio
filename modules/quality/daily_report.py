"""
Daily report generator — produces a recap of yesterday's activity:
  - books generated today
  - books published today
  - average quality score across drafts
  - top insights from the learning system
  - quality trend over time

Output: Markdown file saved to output/reports/daily_YYYYMMDD.md
        + can be displayed in the Streamlit UI directly.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _list_products_modified_since(kdp_root: Path, since: datetime) -> List[Path]:
    """Returns product folders whose listing.json was modified after `since`."""
    out = []
    for child in Path(kdp_root).iterdir():
        if not child.is_dir() or child.name in ("published", ".DS_Store"):
            continue
        listing = child / "listing.json"
        if listing.exists() and datetime.fromtimestamp(listing.stat().st_mtime) >= since:
            out.append(child)
    # Also include published-today
    pub_root = Path(kdp_root) / "published"
    if pub_root.exists():
        for child in pub_root.iterdir():
            if not child.is_dir():
                continue
            marker = child / "published.json"
            if marker.exists() and datetime.fromtimestamp(marker.stat().st_mtime) >= since:
                out.append(child)
    return out


def generate_daily_report(
    kdp_root: Path,
    learning_dir: Path,
    window_hours: int = 24,
) -> Dict:
    """
    Builds the report data and returns it as a dict, AND writes a Markdown file.
    """
    from modules.quality.validator import validate_product
    from modules.learning.insights import generate_insights
    from modules.publishing.scanner import scan_products

    since = datetime.now() - timedelta(hours=window_hours)

    # ── Activity stats ──────────────────────────────────────────────────
    recent = _list_products_modified_since(kdp_root, since)
    all_products = scan_products(kdp_root)
    drafts = [p for p in all_products if p.status == "draft"]
    published = [p for p in all_products if p.status == "published"]

    # ── Quality scores ──────────────────────────────────────────────────
    scores = []
    blocked = []
    for d in drafts:
        try:
            r = validate_product(d.folder)
            scores.append((d.slug, r.score, r.critical_count, r.warning_count))
            if r.critical_count > 0:
                blocked.append(d.slug)
        except Exception:
            continue

    avg_score = round(sum(s[1] for s in scores) / max(len(scores), 1), 1) if scores else 0

    # ── Insights ────────────────────────────────────────────────────────
    insights = generate_insights(learning_dir)

    report = {
        "generated_at":   datetime.now().isoformat(timespec="seconds"),
        "window_hours":   window_hours,
        "n_recent":       len(recent),
        "n_drafts":       len(drafts),
        "n_published":    len(published),
        "n_blocked":      len(blocked),
        "avg_quality":    avg_score,
        "scores":         scores,
        "blocked_slugs":  blocked,
        "insights":       [
            {"code": i.code, "icon": i.icon, "severity": i.severity,
             "message": i.message, "confidence": i.confidence}
            for i in insights
        ],
    }

    # ── Write Markdown ──────────────────────────────────────────────────
    reports_dir = Path("output/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    md_path = reports_dir / f"daily_{date_str}.md"

    lines = [
        f"# 📊 KDP Daily Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"_Window: last {window_hours} hour(s)_",
        "",
        "## Activity",
        f"- **{len(recent)}** product(s) modified in the last {window_hours}h",
        f"- **{len(drafts)}** draft(s) in inventory",
        f"- **{len(published)}** book(s) already published",
        f"- **{len(blocked)}** draft(s) with publication blockers",
        "",
        "## Quality",
        f"- **Average score across drafts** : {avg_score}/100",
    ]
    if scores:
        sorted_scores = sorted(scores, key=lambda x: -x[1])
        lines.append("- Top 3 best drafts :")
        for slug, sc, cr, wr in sorted_scores[:3]:
            lines.append(f"  - 🟢 **{sc}/100** — `{slug}`")
        lines.append("- Bottom 3 :")
        for slug, sc, cr, wr in sorted_scores[-3:][::-1]:
            icon = "🔴" if cr else "🟡"
            lines.append(f"  - {icon} **{sc}/100** — `{slug}` ({cr} blockers, {wr} warnings)")
    if blocked:
        lines.extend([
            "",
            "## ❌ Blockers requiring action",
            *[f"- `{s}` — needs auto-fix or manual review" for s in blocked],
        ])

    if insights:
        lines.extend([
            "",
            "## 🧠 Learning insights",
            *[f"- {i.icon} **{i.code}** ({i.severity}): {i.message}" for i in insights],
        ])

    md_path.write_text("\n".join(lines), encoding="utf-8")
    report["markdown_path"] = str(md_path)
    return report
