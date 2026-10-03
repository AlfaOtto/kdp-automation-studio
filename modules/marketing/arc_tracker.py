"""
ARC Tracker — Module A
========================
ARC = Advance Review Copy. You give your book to 15-30 readers BEFORE Amazon
publication, in exchange for honest reviews on launch day. This is the #1
unpaid lever to crack the Amazon ranking in 2026.

This module provides :

  1. Generate "ARC Copy" watermarked PDF (interior with diagonal watermark
     on every page, plus a cover page reminder, plus a final "review CTA" page)
  2. Email templates (recruitment / sending / launch-day reminder / thank you)
     personalised by Claude per book
  3. Per-book reviewer log : email, status, dates
  4. Stats : sent / opened / posted / pending

Storage : output/learning/arc_teams.json
{
  "<slug>": {
    "team_size_target": 15,
    "reviewers": [
      {"email": "x@y.com", "name": "...", "status": "invited",
       "sent_at": "...", "review_at": null, "notes": "..."},
      ...
    ],
    "amazon_url": "https://www.amazon.com/dp/...",
    "launch_date": "...",
    "templates_personalized": {...}
  }
}
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


ARC_FILE = "arc_teams.json"
VALID_STATUSES = ("invited", "sent_pdf", "reminded", "posted_review", "declined", "no_reply")


# ──────────────────────────────────────────────────────────────────────────────
#  Storage
# ──────────────────────────────────────────────────────────────────────────────

def _load(learning_dir: Path) -> Dict:
    p = Path(learning_dir) / ARC_FILE
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"arc_teams load failed: {e}")
        return {}


def _save(learning_dir: Path, data: Dict) -> bool:
    p = Path(learning_dir) / ARC_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning(f"arc_teams save failed: {e}")
        return False


def get_team(learning_dir: Path, slug: str) -> Dict:
    data = _load(learning_dir)
    return data.get(slug, {
        "team_size_target":     15,
        "reviewers":            [],
        "amazon_url":           "",
        "launch_date":          "",
        "templates_personalized": None,
    })


def upsert_team(learning_dir: Path, slug: str, team: Dict) -> bool:
    data = _load(learning_dir)
    data[slug] = team
    return _save(learning_dir, data)


def add_reviewer(learning_dir: Path, slug: str, email: str,
                 name: str = "", notes: str = "") -> bool:
    team = get_team(learning_dir, slug)
    email = email.strip().lower()
    if not email or "@" not in email:
        return False
    # Dedup
    for r in team["reviewers"]:
        if r["email"].lower() == email:
            return False
    team["reviewers"].append({
        "email":     email,
        "name":      name.strip()[:60],
        "status":    "invited",
        "sent_at":   None,
        "review_at": None,
        "notes":     notes.strip()[:200],
    })
    return upsert_team(learning_dir, slug, team)


def update_reviewer_status(learning_dir: Path, slug: str, email: str,
                            new_status: str, notes: str = "") -> bool:
    if new_status not in VALID_STATUSES:
        return False
    team = get_team(learning_dir, slug)
    now = datetime.now().isoformat(timespec="seconds")
    found = False
    for r in team["reviewers"]:
        if r["email"].lower() == email.lower():
            r["status"] = new_status
            if new_status == "sent_pdf":
                r["sent_at"] = now
            if new_status == "posted_review":
                r["review_at"] = now
            if notes:
                r["notes"] = (r.get("notes", "") + " · " + notes)[:300]
            found = True
            break
    if not found:
        return False
    return upsert_team(learning_dir, slug, team)


def remove_reviewer(learning_dir: Path, slug: str, email: str) -> bool:
    team = get_team(learning_dir, slug)
    before = len(team["reviewers"])
    team["reviewers"] = [r for r in team["reviewers"]
                          if r["email"].lower() != email.lower()]
    if len(team["reviewers"]) == before:
        return False
    return upsert_team(learning_dir, slug, team)


# ──────────────────────────────────────────────────────────────────────────────
#  Stats
# ──────────────────────────────────────────────────────────────────────────────

def team_stats(team: Dict) -> Dict:
    """Returns counts per status + funnel ratio."""
    counts = {s: 0 for s in VALID_STATUSES}
    for r in team.get("reviewers", []):
        s = r.get("status", "invited")
        if s in counts:
            counts[s] += 1
    total = len(team.get("reviewers", []))
    sent  = counts["sent_pdf"] + counts["reminded"] + counts["posted_review"]
    posted = counts["posted_review"]
    target = team.get("team_size_target", 15)
    return {
        "total":        total,
        "target":       target,
        **counts,
        "sent_pct":     int(sent / max(total, 1) * 100),
        "review_pct":   int(posted / max(total, 1) * 100),
        "target_pct":   int(posted / max(target, 1) * 100),
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Watermarked ARC PDF
# ──────────────────────────────────────────────────────────────────────────────

def make_arc_pdf(interior_pdf: Path, output_pdf: Path,
                  book_title: str, author: str = "Author",
                  watermark_text: str = "ADVANCE REVIEW COPY · NOT FOR RESALE",
                  amazon_url: str = "") -> bool:
    """
    Stamps every page of `interior_pdf` with a diagonal watermark and prepends
    a "ARC reader brief" page + appends a "How to leave your review" page.

    Uses pypdf (pure Python, already installed).
    """
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import RectangleObject
        from reportlab.pdfgen import canvas as _canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        import io
    except ImportError as e:
        logger.error(f"make_arc_pdf deps missing: {e}")
        return False

    interior_pdf = Path(interior_pdf)
    output_pdf   = Path(output_pdf)
    if not interior_pdf.exists():
        return False

    reader = PdfReader(str(interior_pdf))
    if not reader.pages:
        return False

    # Get page size from first page
    page0 = reader.pages[0]
    w_pt = float(page0.mediabox.width)
    h_pt = float(page0.mediabox.height)
    page_size = (w_pt, h_pt)

    # ── Build the watermark overlay PDF in memory ────────────────────────
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=page_size)
    c.saveState()
    # Diagonal stamp
    c.setFillColorRGB(0.85, 0.10, 0.10, alpha=0.18)
    c.setStrokeColorRGB(0.85, 0.10, 0.10, alpha=0.30)
    c.translate(w_pt / 2, h_pt / 2)
    c.rotate(35)
    c.setFont("Helvetica-Bold", min(36, int(w_pt / 16)))
    c.drawCentredString(0, 0, watermark_text)
    c.restoreState()
    # Footer text small
    c.setFillColorRGB(0.4, 0.4, 0.4, alpha=0.6)
    c.setFont("Helvetica", 7)
    c.drawCentredString(w_pt / 2, 12, "ARC Copy — Please do not share or redistribute.")
    c.showPage()
    c.save()
    wm_reader = PdfReader(io.BytesIO(buf.getvalue()))
    wm_page   = wm_reader.pages[0]

    # ── Prepend ARC brief page ───────────────────────────────────────────
    brief_buf = io.BytesIO()
    bc = _canvas.Canvas(brief_buf, pagesize=page_size)
    bc.setFillColorRGB(0.10, 0.15, 0.25)
    bc.rect(0, h_pt - 60, w_pt, 60, fill=1, stroke=0)
    bc.setFillColorRGB(1, 1, 1)
    bc.setFont("Helvetica-Bold", 18)
    bc.drawCentredString(w_pt / 2, h_pt - 38, "ADVANCE REVIEW COPY")
    bc.setFillColorRGB(0.10, 0.15, 0.25)
    # Auto-shrink the title so it NEVER overflows the page width (long titles
    # like "DROP THE MIC! ..." were clipped on both sides at a fixed 16pt).
    _title = book_title[:90]
    _avail = w_pt - 80
    _ts = 16
    while _ts > 9 and bc.stringWidth(_title, "Helvetica-Bold", _ts) > _avail:
        _ts -= 1
    bc.setFont("Helvetica-Bold", _ts)
    bc.drawCentredString(w_pt / 2, h_pt - 120, _title)
    bc.setFont("Helvetica", 11)
    bc.drawCentredString(w_pt / 2, h_pt - 145, f"by {author}")
    # Brief body
    bc.setFillColorRGB(0.2, 0.2, 0.2)
    bc.setFont("Helvetica-Bold", 12)
    bc.drawString(60, h_pt - 200, "Hi reviewer,")
    bc.setFont("Helvetica", 11)
    lines = [
        "Thank you for joining the ARC team — your honest review is everything.",
        "",
        "How this works :",
        "  1. Read / use this advance copy at your own pace",
        "  2. On launch day, post your HONEST review on Amazon",
        "  3. Forward your review link back to me so I know to thank you.",
        "",
        "Important :",
        "  · This PDF is for YOUR PERSONAL review only — please don't share.",
        "  · Your review must be honest. Loved it? Say so. Hated it? Say so.",
        "  · A 3-5 star review is far better than no review at all.",
        "",
        "Disclosure : You may add 'I received an advance copy in exchange for an",
        "honest review.' (FTC compliant — fully optional but transparent.)",
        "",
        "Amazon launch link will be sent the day the book goes live.",
    ]
    y = h_pt - 230
    for ln in lines:
        bc.drawString(60, y, ln)
        y -= 16
    bc.showPage()
    bc.save()
    brief_reader = PdfReader(io.BytesIO(brief_buf.getvalue()))

    # ── Append "How to leave review" page at end ─────────────────────────
    cta_buf = io.BytesIO()
    cc = _canvas.Canvas(cta_buf, pagesize=page_size)
    cc.setFillColorRGB(0.10, 0.45, 0.20)
    cc.rect(0, h_pt - 60, w_pt, 60, fill=1, stroke=0)
    cc.setFillColorRGB(1, 1, 1)
    cc.setFont("Helvetica-Bold", 18)
    cc.drawCentredString(w_pt / 2, h_pt - 38, "Ready to leave your review?")
    cc.setFillColorRGB(0.2, 0.2, 0.2)
    cc.setFont("Helvetica", 12)
    y = h_pt - 110
    cta_lines = [
        "Thank you for reading the ARC of:",
        f"   {book_title[:80]}",
        "",
        "When the book goes live on Amazon :",
        "",
        "  1. Open the Amazon product page (link will be emailed)",
        "  2. Scroll down to 'Customer reviews'",
        "  3. Click 'Write a customer review'",
        "  4. Be HONEST — 3 stars is fine, 5 stars is great, just be real",
        "",
        "Suggested review ideas :",
        "  · What worked best for you?",
        "  · Who would you recommend this to?",
        "  · One detail you wish was different?",
        "",
        "Optional (FTC-compliant disclosure) :",
        "  'I received an advance copy in exchange for an honest review.'",
        "",
    ]
    if amazon_url:
        cta_lines.append("Amazon link :")
        cta_lines.append(f"   {amazon_url[:100]}")
    for ln in cta_lines:
        cc.drawString(60, y, ln)
        y -= 16
    cc.setFillColorRGB(0.10, 0.45, 0.20)
    cc.setFont("Helvetica-Bold", 14)
    cc.drawCentredString(w_pt / 2, 80, "Your review = my livelihood. Thank you!")
    cc.showPage()
    cc.save()
    cta_reader = PdfReader(io.BytesIO(cta_buf.getvalue()))

    # ── Write final PDF ──────────────────────────────────────────────────
    writer = PdfWriter()
    writer.add_page(brief_reader.pages[0])
    for page in reader.pages:
        page.merge_page(wm_page)
        writer.add_page(page)
    writer.add_page(cta_reader.pages[0])

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(output_pdf, "wb") as f:
        writer.write(f)
    return True


# ──────────────────────────────────────────────────────────────────────────────
#  Email templates (Claude-personalised per book)
# ──────────────────────────────────────────────────────────────────────────────

def generate_email_templates(listing: Dict, anthropic_key: str,
                              status_cb=None) -> Dict[str, str]:
    """
    Generates 4 email templates personalised for this book :
      - recruitment : invite ARC readers
      - send_pdf    : send the watermarked PDF after they accept
      - reminder    : launch-day reminder
      - thank_you   : after they post the review

    Returns dict of plain-text templates ready to copy-paste.
    Falls back to generic templates if Claude unavailable.
    """
    title    = listing.get("title", "the book")
    niche    = listing.get("niche", "")
    p_type   = listing.get("product_type", "book")
    author   = listing.get("publisher_name", "Author")

    fallback = _fallback_templates(title, niche, author)

    if not anthropic_key:
        return fallback
    try:
        import anthropic
    except ImportError:
        return fallback

    prompt = f"""Generate 4 SHORT email templates for an ARC reader campaign.

BOOK
  title    : "{title}"
  niche    : {niche}
  type     : {p_type}
  author   : {author}

Tone : warm, casual, genuine — like a friend asking a favour.
Style : 70-120 words per email. Use plain text only, no HTML, no emoji-overload.
Each must include the placeholders [NAME] (recipient first name), [AMAZON_LINK]
when relevant, and a clear single CTA per email.

Return STRICT JSON only :
{{
  "recruitment":  "...",  // subject + body, sep by \\n\\n
  "send_pdf":     "...",
  "reminder":     "...",
  "thank_you":    "..."
}}

Each value MUST start with "Subject: ..." on the first line."""

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        if status_cb:
            status_cb("✍️ Claude personnalise les 4 emails ARC…")
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        out = {}
        for k in ("recruitment", "send_pdf", "reminder", "thank_you"):
            v = str(data.get(k, "")).strip()
            if len(v) > 50:
                out[k] = v
        # Fill missing with fallback
        for k in fallback:
            out.setdefault(k, fallback[k])
        return out
    except Exception as e:
        logger.warning(f"generate_email_templates failed: {e}")
        if status_cb:
            status_cb(f"⚠️ Claude email échec, fallback générique : {e}")
        return fallback


def _fallback_templates(title: str, niche: str, author: str) -> Dict[str, str]:
    return {
        "recruitment": f"""Subject: Free advance copy in exchange for an honest review?

Hi [NAME],

I'm wrapping up my new book "{title}" — a {niche} book I've been pouring my heart into.

I'm building a small launch team and would love to send you a free advance copy if you'd be willing to leave an honest review on Amazon when it goes live.

No fluff needed — your real opinion, good or bad, is exactly what helps other readers decide.

Interested? Just reply with your email and I'll send the PDF over.

Thanks for considering it,
{author}""",
        "send_pdf": f"""Subject: Your advance copy of "{title}" 📖

Hi [NAME],

Here's your advance copy of "{title}" — thanks again for joining the launch team.

The PDF is attached. A few notes :
  · It's for your personal review only — please don't share.
  · Take your time. There's no deadline yet.
  · When the book goes live on Amazon, I'll send you the link to post your review.

Honest reviews — including the bits you wish were different — help me grow.

Looking forward to hearing your thoughts!
{author}""",
        "reminder": f"""Subject: "{title}" is live on Amazon — ready for your review?

Hi [NAME],

Quick update — "{title}" just went live on Amazon!

If you've had a chance to look through the ARC copy, would you be willing to post your honest review in the next few days?

Here's the link :
  [AMAZON_LINK]

A 3-5 star honest review is exactly what I need — please don't sugarcoat it.

Thanks so much for your support,
{author}""",
        "thank_you": f"""Subject: Thank you for your review 🙏

Hi [NAME],

Just wanted to say thank you for your review of "{title}" — it really means a lot.

If you'd like, I'll add you to my private ARC list for future releases — first dibs on advance copies before anyone else.

Either way, thanks for taking the time to read and review. It moves the needle more than you know.

Warmly,
{author}""",
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Bulk import reviewers from a textarea paste
# ──────────────────────────────────────────────────────────────────────────────

def bulk_import_reviewers(learning_dir: Path, slug: str, raw_text: str) -> int:
    """
    Accepts text like :
      Alice <alice@example.com>
      bob@example.com
      Charlie Doe, charlie@x.com
      ...
    Returns the number of NEW reviewers added (dedupes existing).
    """
    added = 0
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Try to extract email + name
        m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", line)
        if not m:
            continue
        email = m.group(0).lower()
        # Name = anything before/after the email
        rest = re.sub(re.escape(m.group(0)), "", line)
        rest = re.sub(r"[<>,]+", " ", rest).strip()
        name = rest[:60]
        if add_reviewer(learning_dir, slug, email, name=name):
            added += 1
    return added


# ──────────────────────────────────────────────────────────────────────────────
#  Render reviewer table as markdown (for copy-paste reporting)
# ──────────────────────────────────────────────────────────────────────────────

def reviewers_to_markdown(team: Dict) -> str:
    rows = ["| Email | Name | Status | Sent | Reviewed |",
            "|---|---|---|---|---|"]
    for r in team.get("reviewers", []):
        rows.append(
            f"| {r['email']} | {r.get('name','')} | {r['status']} | "
            f"{(r.get('sent_at') or '')[:10]} | {(r.get('review_at') or '')[:10]} |"
        )
    return "\n".join(rows)
