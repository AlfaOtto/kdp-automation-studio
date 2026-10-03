"""
Cover genre-signaling check using Claude Vision
================================================
Sends the rendered cover PNG to Claude Sonnet and asks :
  "Does this cover communicate it's a {product_type} for {niche}
   in under 3 seconds at thumbnail size?"

Returns a 0-100 score and a one-line critique. Used by the quality validator
to flag covers that may look good but fail to signal the genre to a scrolling
Amazon shopper.
"""
import base64
import io
import logging
from pathlib import Path
from typing import Dict, Optional

from PIL import Image

logger = logging.getLogger(__name__)


def _render_cover_png(cover_pdf: Path, max_w: int = 600) -> Optional[bytes]:
    """Render front face of cover PDF as PNG bytes (downsampled for the API)."""
    try:
        import fitz
        doc = fitz.open(str(cover_pdf))
        if doc.page_count == 0:
            doc.close()
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
        png_bytes = pix.tobytes("png")
        doc.close()
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        # Crop front face (right ~45%)
        w, h = img.size
        front = img.crop((int(w * 0.55), 0, w, h))
        # Downscale for the vision API
        if front.size[0] > max_w:
            ratio = max_w / front.size[0]
            front = front.resize((max_w, int(front.size[1] * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        front.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"genre_signal: render failed: {e}")
        return None


def check_genre_signal(
    cover_pdf: Path,
    product_type: str,
    niche: str,
    anthropic_key: str,
) -> Dict:
    """
    Returns {score: 0-100, verdict: str, critique: str, ok: bool}.
    On failure (no key, API error), returns {ok: False} silently.
    """
    if not anthropic_key:
        return {"ok": False, "reason": "no_api_key"}
    try:
        import anthropic
    except ImportError:
        return {"ok": False, "reason": "anthropic_pkg_missing"}

    png = _render_cover_png(Path(cover_pdf))
    if not png:
        return {"ok": False, "reason": "render_failed"}

    b64 = base64.standard_b64encode(png).decode("ascii")
    prompt = f"""You are an Amazon shopper scrolling Amazon book search results.
You see this book cover thumbnail (it's the FRONT of a paperback called
"{niche}", category: {product_type}).

In under 3 seconds, answer:
1) GENRE_SCORE (0-100): how clearly does this cover communicate it's a
   {product_type} about "{niche}"? 100 = instantly obvious, 0 = could be anything.
2) READABILITY (0-100): is the title readable at thumbnail size?
3) CRITIQUE (one sentence, max 25 words): the SINGLE biggest improvement.

Return STRICT JSON only, no markdown fences:
{{"genre_score": 0-100, "readability": 0-100, "critique": "..."}}"""

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        import json, re
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        gs   = int(data.get("genre_score", 0))
        rb   = int(data.get("readability", 0))
        crit = str(data.get("critique", ""))[:140]
        combined = (gs * 0.6 + rb * 0.4)

        if   combined >= 80: verdict = "🟢 Excellent signaling"
        elif combined >= 65: verdict = "🟡 Acceptable"
        elif combined >= 45: verdict = "🟠 Faible — regen conseillée"
        else:                verdict = "🔴 Échoue — regen requise"

        return {
            "ok":           True,
            "score":        round(combined, 1),
            "genre_score":  gs,
            "readability":  rb,
            "critique":     crit,
            "verdict":      verdict,
        }
    except Exception as e:
        logger.warning(f"genre_signal: Claude call failed: {e}")
        return {"ok": False, "reason": str(e)[:80]}
