"""
Web-grounded KEYWORD research for KDP listings.

Complements the Amazon-autocomplete harvester (keywords_pro.py) with a single
web-grounded Claude call that studies what ACTUALLY sells in a niche — top-selling
book titles/subtitles, real buyer search language, and current trends — then
returns optimized, buyer-intent KDP keywords with a grounded rationale.

Cost-conscious by design (lesson from the high-content engine): ONE web-grounded
call per research (~$0.15-0.30), not a loop. Facts/keywords are grounded in real
sources; wording stays 100% original (never copy competitor titles verbatim).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


def _extract_json(text: str):
    raw = (text or "").strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            # repair a truncated object
            last = raw.rfind("}", start, end)
            if last > start:
                return json.loads(raw[start:last + 1] + "}")
    raise ValueError("No JSON found")


def _call_grounded(client, prompt: str, max_tokens: int = 4000) -> str:
    """One web-grounded generation (streaming, handles pause_turn)."""
    messages = [{"role": "user", "content": prompt}]
    for _hop in range(4):
        with client.messages.stream(model=MODEL, max_tokens=max_tokens,
                                    tools=[_WEB_SEARCH_TOOL], messages=messages) as stream:
            final = stream.get_final_message()
        if getattr(final, "stop_reason", None) == "pause_turn":
            messages = [{"role": "user", "content": prompt},
                        {"role": "assistant", "content": final.content}]
            continue
        return "\n".join(b.text for b in final.content if getattr(b, "type", "") == "text")
    return ""


_SCHEMA = """{
  "optimized_keywords": [
    {"keyword": "3-6 word long-tail phrase", "intent": "audience|problem|benefit|occasion|format|trope|gift",
     "why": "one short grounded reason it sells"}
  ],
  "trending": ["rising terms buyers search NOW for this niche"],
  "avoid": ["saturated / overused terms that no longer differentiate"],
  "best_angle": "1-2 sentences: the strongest positioning angle the research reveals"
}"""


def research_keywords(
    niche: str,
    anthropic_key: str,
    book_title: str = "",
    existing_keywords: Optional[List[str]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Dict:
    """
    Web-research the best KDP keywords for a niche. Returns a dict following
    _SCHEMA (optimized_keywords / trending / avoid / best_angle), or {} on failure.
    """
    def s(m):
        if status_cb:
            status_cb(m)

    if not anthropic_key:
        s("⚠️ Clé Anthropic manquante — recherche web keywords impossible")
        return {}

    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=600.0)

    have = ", ".join(existing_keywords or []) or "none"
    title_ctx = f'\nThe book is titled roughly: "{book_title}".' if book_title else ""
    s("🌐 Recherche web : ce qui marche comme keywords pour cette niche...")
    prompt = f"""You are a top Amazon KDP SEO strategist. Research the niche: "{niche}".{title_ctx}

Use the web_search tool to study what ACTUALLY SELLS and ranks in this niche RIGHT NOW:
- Titles/subtitles of the current best-selling books (Amazon best-seller lists, "best <niche> books").
- The real language buyers use to search (audiences, problems, benefits, occasions).
- Current trends and rising interest for this topic.

Then produce OPTIMIZED Amazon KDP backend keywords. RULES:
- 7 to 10 keywords, each 2-5 words, ≤ 50 characters.
- ⚑ THE #1 RULE: each keyword MUST be a phrase REAL SHOPPERS ACTUALLY TYPE into the
  Amazon search box for this kind of book — common, high-volume searches and their
  close variants. NOT clever/unique angles nobody searches (that is why books fail to
  rank). If unsure a phrase is really searched, use the plainer, more obvious term.
- Anchor on the obvious searched terms + real buyer variants (audience, sub-topic,
  format, problem, synonym). Some word overlap between keywords is FINE if the phrases
  are genuinely searched — real search volume beats artificial word-diversity.
- Do NOT repeat words already present in the book title when a title is given (cover
  NEW searched terms/synonyms instead, to widen reach).
- 100% ORIGINAL wording — NEVER copy a competitor's title verbatim.
- Existing keywords the author already has (improve on / avoid duplicating): {have}.

Return ONLY a strict JSON object (no markdown fences) with this schema:
{_SCHEMA}"""
    try:
        text = _call_grounded(client, prompt, max_tokens=4000)
        data = _extract_json(text)
        if isinstance(data, dict) and data.get("optimized_keywords"):
            # normalize + hard-cap keyword length to KDP's 50 chars
            for k in data["optimized_keywords"]:
                k["keyword"] = str(k.get("keyword", "")).strip()[:50]
            data["optimized_keywords"] = [k for k in data["optimized_keywords"] if k["keyword"]]
            # ── ANCHOR on REAL Amazon autocomplete searches (same fix as the
            # book generator) → replace invented angles with terms buyers type.
            try:
                from modules.creation.content_generator import _optimize_keywords
                _cand = [k["keyword"] for k in data["optimized_keywords"]]
                _intent = {k["keyword"].lower(): k for k in data["optimized_keywords"]}
                s("🔎 Ancrage sur l'autocomplete Amazon réel...")
                _anchored = _optimize_keywords(niche, book_title, "", _cand, max_slots=10)
                if _anchored:
                    data["optimized_keywords"] = [
                        _intent.get(kw.lower(), {"keyword": kw,
                                                 "intent": "real search (autocomplete)"})
                        | {"keyword": kw[:50]}
                        for kw in _anchored
                    ]
            except Exception as _ae:
                logger.debug(f"autocomplete anchoring skipped: {_ae}")
            # ── SAFETY NET: never return a trademarked/brand keyword (KDP flags
            # them → account risk). Drops brand terms from keywords + trending.
            try:
                from modules.creation.content_generator import _has_brand
                data["optimized_keywords"] = [
                    k for k in data["optimized_keywords"]
                    if not _has_brand(k.get("keyword", ""))]
                if isinstance(data.get("trending"), list):
                    data["trending"] = [t for t in data["trending"]
                                        if not _has_brand(str(t))]
            except Exception as _be:
                logger.debug(f"brand filter (keyword_web) skipped: {_be}")
            s(f"✅ {len(data['optimized_keywords'])} keywords optimisés (autocomplete réel + web, sans marques)")
            return data
    except Exception as e:
        logger.warning(f"keyword web research failed: {e}")
        s(f"⚠️ Recherche web keywords échouée : {str(e)[:90]}")
    return {}
