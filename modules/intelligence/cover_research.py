"""
Web-grounded COVER-DESIGN research for KDP books.

Studies the current best-selling covers in a niche and returns a compact "cover
design brief" — the winning visual codes (palette, background, art style, title
treatment, layout) to EMULATE (never copy verbatim: copyright + duplicates hurt).

Cost-conscious: ONE web-grounded Claude call (~$0.15-0.30), and the brief is
CACHED PER NICHE (learning_dir/cover_briefs/<slug>.json) → one research serves
every book in that niche. Works for BOTH high-content and low-content, and is
niche-aware. The renderer consumes the brief to colour/style the cover.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

_SCHEMA = """{
  "palette": ["#RRGGBB", "#RRGGBB", "#RRGGBB"],   // 3-5 dominant colours that WIN in this category
  "accent": "#RRGGBB",                             // the single strongest accent colour
  "background": "light | cream | dark | photo",    // dominant background treatment of top covers
  "art_style": "photo | illustration | pattern | minimal | bold-graphic",
  "title_style": "elegant-serif | bold-sans | script | classic | stencil",
  "layout": "one short phrase (e.g. 'single centred subject, title top, author bottom')",
  "do": ["3-5 winning visual codes to emulate"],
  "avoid": ["3-5 things that look amateur/cluttered in this category"],
  "summary": "1-2 sentences on how to beat these covers"
}"""


def _slug(niche: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (niche or "").lower()).strip("-")[:80] or "niche"


def _extract_json(text: str):
    raw = (text or "").strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    a, b = raw.find("{"), raw.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(raw[a:b + 1])
        except Exception:
            pass
    raise ValueError("No JSON found")


def _call_grounded(client, prompt: str, max_tokens: int = 2500,
                   retries: int = 4) -> str:
    """Web-grounded call with retry/backoff on transient overload/rate errors."""
    import time as _t
    last_err = None
    for attempt in range(retries):
        try:
            messages = [{"role": "user", "content": prompt}]
            for _hop in range(4):
                with client.messages.stream(model=MODEL, max_tokens=max_tokens,
                                            tools=[_WEB_SEARCH_TOOL],
                                            messages=messages) as stream:
                    final = stream.get_final_message()
                if getattr(final, "stop_reason", None) == "pause_turn":
                    messages = [{"role": "user", "content": prompt},
                                {"role": "assistant", "content": final.content}]
                    continue
                return "\n".join(b.text for b in final.content
                                 if getattr(b, "type", "") == "text")
            return ""
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            transient = any(w in msg for w in ("overload", "rate", "429", "529",
                                               "timeout", "connection"))
            if transient and attempt < retries - 1:
                _t.sleep(6 * (attempt + 1))     # 6s, 12s, 18s backoff
                continue
            raise
    if last_err:
        raise last_err
    return ""


def _validate_brief(d: Dict) -> Optional[Dict]:
    if not isinstance(d, dict):
        return None
    pal = [c for c in (d.get("palette") or []) if isinstance(c, str)
           and re.fullmatch(r"#?[0-9A-Fa-f]{6}", c.strip())]
    pal = ["#" + c.lstrip("#").upper() for c in pal][:5]
    if not pal:
        return None
    acc = d.get("accent", "")
    if not (isinstance(acc, str) and re.fullmatch(r"#?[0-9A-Fa-f]{6}", acc.strip())):
        acc = pal[0]
    return {
        "palette": pal,
        "accent": "#" + acc.lstrip("#").upper(),
        "background": str(d.get("background", "light")).lower().split()[0][:12],
        "art_style": str(d.get("art_style", "photo")).lower().split()[0][:16],
        "title_style": str(d.get("title_style", "bold-sans")).lower().split()[0][:20],
        "layout": str(d.get("layout", ""))[:200],
        "do": [str(x)[:120] for x in (d.get("do") or [])][:5],
        "avoid": [str(x)[:120] for x in (d.get("avoid") or [])][:5],
        "summary": str(d.get("summary", ""))[:400],
    }


def research_cover_design(niche: str, product_type: str, anthropic_key: str,
                          content_level: str = "",
                          cache_dir: Optional[Path] = None,
                          force: bool = False,
                          status_cb: Optional[Callable[[str], None]] = None) -> Dict:
    """Return a cached-or-fresh cover-design brief for the niche. {} on failure."""
    def s(m):
        if status_cb:
            status_cb(m)

    # 1) cache (per niche)
    cache_file = None
    if cache_dir:
        cache_file = Path(cache_dir) / "cover_briefs" / f"{_slug(niche)}.json"
        if cache_file.exists() and not force:
            try:
                brief = json.loads(cache_file.read_text(encoding="utf-8"))
                s("🎨 Brief couverture réutilisé depuis le cache (0 $)")
                return brief
            except Exception:
                pass

    if not anthropic_key:
        return {}
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=600.0)

    lvl = content_level or ("high-content" if product_type in ("recipe_book", "how_to")
                            else "low-content")
    s("🌐 Recherche web : couvertures gagnantes des concurrents...")
    prompt = f"""You are a top Amazon KDP COVER designer. Research the niche: "{niche}"
(a {lvl} {product_type} book).

Use web_search to study the CURRENT BEST-SELLING book covers in this exact niche
(search "best {niche} books", Amazon best-seller lists, the top results' cover
thumbnails). Identify the VISUAL CODES that make the top covers work — and what
makes the weaker ones look amateur.

Then return a COVER DESIGN BRIEF so we can EMULATE the winning look and beat it —
NEVER copy any single cover verbatim (that is copyright infringement and a
duplicate). Real hex colours, honest observations.

Return ONLY strict JSON (no markdown fences), schema:
{_SCHEMA}"""
    try:
        text = _call_grounded(client, prompt, max_tokens=2500)
        brief = _validate_brief(_extract_json(text))
        if not brief:
            s("⚠️ Brief couverture invalide — design par défaut par niche utilisé")
            return {}
        brief["niche"] = niche
        if cache_file:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(brief, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
            except Exception:
                pass
        s(f"✅ Brief couverture prêt (palette {', '.join(brief['palette'][:3])} · "
          f"{brief['art_style']} · fond {brief['background']})")
        return brief
    except Exception as e:
        logger.warning(f"cover research failed: {e}")
        s(f"⚠️ Recherche couverture échouée : {str(e)[:90]}")
        return {}
