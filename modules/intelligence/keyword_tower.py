"""
Keyword Optimization Tower — Module B
=====================================
SEO scoring + actionable suggestions for the 5 KDP listing zones:

  1. TITLE        : mobile readability + main keyword + no stuffing
  2. SUBTITLE     : adjacent intent + numeric promise + no title overlap
  3. DESCRIPTION  : hook + length + keyword density + HTML compliance
  4. 7 KEYWORDS   : long-tail + distinct intents + autocomplete-validated
  5. 3 CATEGORIES : checked elsewhere (categories_optimizer.py)

Each zone gets a 0-100 score with a list of issues + concrete suggestions.
Aggregate listing score = weighted average.
"""
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
#  Scoring weights (sum = 100)
# ──────────────────────────────────────────────────────────────────────────────
SCORE_WEIGHTS = {
    "title":       0.30,
    "subtitle":    0.15,
    "description": 0.25,
    "keywords":    0.30,
}


# ──────────────────────────────────────────────────────────────────────────────
#  TITLE scoring
# ──────────────────────────────────────────────────────────────────────────────

def score_title(title: str, niche: str) -> Dict:
    issues, score = [], 100

    if not title or len(title) < 10:
        return {"score": 0, "issues": ["Title vide ou < 10 chars"],
                "suggestions": ["Génère un titre de 30-60 chars"]}

    # Mobile cut at 60 chars
    if len(title) > 60:
        score -= 12
        issues.append(f"📱 Title {len(title)} chars > 60 — coupé sur mobile (où 70% des achats se font)")

    # Stuffing patterns
    if title.count(":") >= 2:
        score -= 20
        issues.append("🚫 Multi-colons → KDP content team punit (vu sur des emails de rejet 2026)")
    if title.count(",") >= 2:
        score -= 18
        issues.append("🚫 Listes virgules → 'metadata manipulation' selon A10")
    if title.count(" — ") + title.count(" | ") >= 2:
        score -= 8
        issues.append("⚠️ Trop de séparateurs (— |) → fragmenté")

    # Main niche keyword present ?
    niche_words  = set(re.findall(r"\w{3,}", (niche or "").lower()))
    title_words  = set(re.findall(r"\w{3,}", title.lower()))
    overlap_pct  = len(niche_words & title_words) / max(len(niche_words), 1)
    if overlap_pct < 0.30:
        score -= 15
        issues.append(f"🎯 Mot-clé principal niche absent du title (overlap {overlap_pct*100:.0f}%) — Amazon ne sait pas matcher")

    # Long-tail with audience?
    has_audience_marker = any(m in title.lower() for m in
        ("for ", "kids", "adults", "seniors", "women", "men", "teens",
         "beginners", "professionals", "parents", "couples"))
    if not has_audience_marker:
        score -= 6
        issues.append("👥 Pas d'audience claire ('for X') — long-tail recommandé pour ranker en niche-specifique")

    # Conversational (NLP A10 check)
    cap_ratio = sum(1 for c in title if c.isupper()) / max(len(title), 1)
    if cap_ratio > 0.40 and len(title) > 30:
        score -= 5
        issues.append("📢 Trop de capitales → A10 NLP flag 'not human-written'")

    score = max(0, min(100, score))
    return {
        "score":       int(score),
        "length":      len(title),
        "issues":      issues,
        "suggestions": _title_suggestions(title, niche, issues),
    }


def _title_suggestions(title: str, niche: str, issues: List[str]) -> List[str]:
    sug = []
    if any("60" in i for i in issues):
        # Try to chop after first 'for'
        m = re.search(r"\s+for\s+", title, re.IGNORECASE)
        if m and m.start() >= 10:
            sug.append(f"✂️ Coupe après 'for' : '{title[:m.start()]}'")
        else:
            sug.append(f"✂️ Garde les ~50 premiers chars : '{title[:50]}'")
    if any("Multi-colons" in i for i in issues):
        first_colon = title.find(":")
        sug.append(f"✂️ Garde uniquement avant le premier ':' : '{title[:first_colon]}'")
    if any("Listes virgules" in i for i in issues):
        sug.append("✂️ Garde 2 keywords max — déplace le reste dans le subtitle")
    if any("absent" in i.lower() for i in issues):
        # Suggest niche keyword at start
        niche_main = (niche or "").split()[0] if niche else ""
        if niche_main:
            sug.append(f"🎯 Mets '{niche_main.title()}' au DÉBUT du titre")
    if any("audience" in i.lower() for i in issues):
        sug.append("👥 Ajoute 'for [audience]' à la fin (ex: 'for Beginners', 'for Working Moms')")
    return sug


# ──────────────────────────────────────────────────────────────────────────────
#  SUBTITLE scoring
# ──────────────────────────────────────────────────────────────────────────────

def score_subtitle(subtitle: str, title: str) -> Dict:
    issues, score = [], 100

    if not subtitle or len(subtitle.strip()) < 6:
        return {"score": 40, "issues": ["Subtitle vide (slot SEO gaspillé)"],
                "suggestions": ["Ajoute un sous-titre de 30-70 chars avec angle différent du title"]}

    if len(subtitle) > 80:
        score -= 10
        issues.append(f"📏 Subtitle {len(subtitle)} chars > 80 — risque spam filter")

    if subtitle.count(":") >= 2 or subtitle.count(",") >= 3:
        score -= 18
        issues.append("🚫 Stuffing pattern (colons / commas) → KDP penalty")

    # Overlap with title
    t_words = set(re.findall(r"\w{3,}", title.lower()))
    s_words = set(re.findall(r"\w{3,}", subtitle.lower()))
    if t_words and s_words:
        overlap = len(t_words & s_words) / len(s_words)
        if overlap >= 0.50:
            score -= 22
            issues.append(f"🔁 {int(overlap*100)}% des mots du subtitle déjà dans le title — slot SEO gaspillé")
        elif overlap >= 0.30:
            score -= 10
            issues.append(f"⚠️ {int(overlap*100)}% des mots dupliqués avec title — réduis l'overlap")

    # Numeric promise (pro practice)
    has_number = bool(re.search(r"\b\d{1,4}\b", subtitle))
    has_time_promise = bool(re.search(r"\b\d+\s*(day|week|month|page|prompt|puzzle)", subtitle, re.IGNORECASE))
    if not has_number and not has_time_promise:
        score -= 8
        issues.append("🔢 Pas de promesse numérique (ex: '90 Days', '100 Prompts') — convertit moins bien")

    # Audience signal
    if not any(m in subtitle.lower() for m in
        ("for ", "with ", "to ", "and ", "in ")):
        score -= 4
        issues.append("👥 Pas de connecteur de bénéfice clair — utilise 'for', 'with', 'to'")

    score = max(0, min(100, score))
    return {
        "score":       int(score),
        "length":      len(subtitle),
        "issues":      issues,
        "suggestions": _subtitle_suggestions(subtitle, title, issues),
    }


def _subtitle_suggestions(subtitle: str, title: str, issues: List[str]) -> List[str]:
    sug = []
    if any("dupliqu" in i for i in issues) or any("gaspillé" in i for i in issues):
        sug.append("🔄 Réécris en utilisant des SYNONYMES (ex: 'Daily' → 'Everyday', 'Tracker' → 'Log')")
    if any("numérique" in i for i in issues):
        sug.append("🔢 Ajoute un nombre concret : '90-Day...', '100 Prompts...', '52-Week...'")
    if any("80" in i for i in issues):
        sug.append("✂️ Coupe à 60-70 chars — l'essentiel d'abord")
    return sug


# ──────────────────────────────────────────────────────────────────────────────
#  DESCRIPTION scoring
# ──────────────────────────────────────────────────────────────────────────────

# HTML tags KDP keeps vs strips
HTML_ALLOWED = {"b", "i", "br", "p"}
HTML_STRIPPED = {"ul", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                 "div", "span", "style", "img", "a", "script"}


def score_description(desc: str, niche: str, keywords: List[str]) -> Dict:
    issues, score = [], 100

    if not desc or len(desc.strip()) < 100:
        return {"score": 30, "issues": ["Description < 100 chars (Amazon attend ≥ 200)"],
                "suggestions": ["Génère une description 150-300 mots avec hook + bullets + CTA"]}

    # Visible text length (strip HTML)
    visible = re.sub(r"<[^>]+>", " ", desc)
    visible = re.sub(r"\s+", " ", visible).strip()
    word_count = len(visible.split())

    # Sweet spot 150-300 words for mobile conversion
    if word_count < 100:
        score -= 12
        issues.append(f"📝 {word_count} mots — trop court (cible 150-300)")
    elif word_count > 400:
        score -= 8
        issues.append(f"📝 {word_count} mots — trop long pour conversion mobile (cible 150-300)")

    # Hook strength (first 200 chars visible — mobile "Read more")
    hook = visible[:200].lower()
    weak_hooks = ("are you tired of", "do you want to", "in this book", "welcome to",
                  "this book is", "this notebook", "introduction")
    if any(w in hook for w in weak_hooks):
        score -= 10
        issues.append("⚠️ Hook faible (commence par cliché) — A10 NLP détecte 'low-quality copy'")
    if len(visible[:200].split()) < 25:
        score -= 6
        issues.append("📱 Pré-Read-more vide < 25 mots — mobile users zappent")

    # HTML compliance
    stripped_found = []
    for tag in HTML_STRIPPED:
        if re.search(rf"<\s*{tag}\b", desc, re.IGNORECASE):
            stripped_found.append(tag)
    if stripped_found:
        score -= 14
        issues.append(f"🚫 HTML tags STRIPPÉS par KDP : {', '.join(f'<{t}>' for t in stripped_found)} — bullets s'affichent en bouillie")

    # Niche keyword density
    if niche:
        nw = set(re.findall(r"\w{4,}", niche.lower()))
        dw = set(re.findall(r"\w{4,}", visible.lower()))
        if nw and not (nw & dw):
            score -= 12
            issues.append("🎯 Mot-clé niche absent de la description — Amazon ne matche pas")

    # Long-tail keyword integration (from listing.keywords)
    kw_present = 0
    for kw in keywords[:7]:
        kw_main = kw.lower().split()[0] if kw else ""
        if kw_main and kw_main in visible.lower():
            kw_present += 1
    if keywords and kw_present < 2:
        score -= 8
        issues.append(f"🔗 Seulement {kw_present}/7 keywords du backend tissés dans la description — perte SEO")

    # Bullet-friendly structure (using <br>• or ☐ or - lines)
    has_bullets = bool(re.search(r"(<br\s*/?>)\s*[•▶◆\-\*]", desc))
    if not has_bullets and word_count > 80:
        score -= 5
        issues.append("📋 Pas de bullets visibles — mobile readers scannent, ils ne lisent pas un bloc")

    # CTA
    cta_markers = ("scroll up", "buy now", "add to cart", "get your copy", "start your", "today")
    if not any(m in visible.lower() for m in cta_markers):
        score -= 4
        issues.append("📢 Pas d'appel à l'action — conversion baisse")

    score = max(0, min(100, score))
    return {
        "score":       int(score),
        "word_count":  word_count,
        "issues":      issues,
        "suggestions": _desc_suggestions(desc, issues),
    }


def _desc_suggestions(desc: str, issues: List[str]) -> List[str]:
    sug = []
    if any("STRIPPÉS" in i for i in issues):
        sug.append("🔄 Remplace <ul>/<li> par <br>• item<br>• item<br><br>")
    if any("Hook faible" in i for i in issues):
        sug.append("✨ Démarre par une vérité émotionnelle spécifique, pas un cliché")
    if any("CTA" in i for i in issues):
        sug.append("📢 Ajoute en fin : '<b>Scroll up and add to cart now.</b>'")
    if any("trop court" in i.lower() for i in issues):
        sug.append("📝 Étoffe avec : What's inside + Perfect for + Why you'll love it")
    if any("trop long" in i.lower() for i in issues):
        sug.append("✂️ Coupe les paragraphes secondaires — garde hook + bullets + CTA")
    return sug


# ──────────────────────────────────────────────────────────────────────────────
#  KEYWORDS (7 slots) scoring
# ──────────────────────────────────────────────────────────────────────────────

def score_keywords(keywords: List[str], title: str) -> Dict:
    issues, score = [], 100
    keywords = [k for k in (keywords or []) if k]

    if len(keywords) < 7:
        score -= (7 - len(keywords)) * 8
        issues.append(f"📦 Seulement {len(keywords)}/7 slots utilisés — gaspillage SEO")
    if len(keywords) > 7:
        score -= 4
        issues.append(f"📦 {len(keywords)} keywords — KDP n'en prend que 7")

    # Per-keyword scoring
    too_short, too_long, broad = [], [], []
    for kw in keywords[:7]:
        n_words = len(kw.split())
        if n_words < 2:
            too_short.append(kw)
        if len(kw) > 50:
            too_long.append(kw)
        if n_words == 1:
            broad.append(kw)
    if too_short:
        score -= len(too_short) * 6
        issues.append(f"🪶 {len(too_short)} keyword(s) en 1 mot (ex: '{too_short[0]}') — trop broad, faible conversion")
    if too_long:
        score -= len(too_long) * 4
        issues.append(f"📏 {len(too_long)} keyword(s) > 50 chars — KDP tronque")

    # Title-keyword overlap (waste)
    t_words = set(re.findall(r"\w{3,}", title.lower()))
    wasted_overlap = []
    for kw in keywords[:7]:
        kw_words = set(re.findall(r"\w{3,}", kw.lower()))
        if kw_words and len(kw_words & t_words) / len(kw_words) >= 0.50:
            wasted_overlap.append(kw)
    if wasted_overlap:
        score -= len(wasted_overlap) * 5
        issues.append(f"🔁 {len(wasted_overlap)} keyword(s) répètent les mots du title — Amazon indexe 1 fois suffit")

    # Cross-keyword token reuse
    all_tokens = []
    for kw in keywords[:7]:
        all_tokens.extend(re.findall(r"\w{4,}", kw.lower()))
    if all_tokens:
        unique = len(set(all_tokens))
        density = unique / len(all_tokens)
        if density < 0.55:
            score -= 10
            issues.append(f"🔄 Faible diversité ({int(density*100)}%) — beaucoup de mots répétés entre keywords")

    score = max(0, min(100, score))
    return {
        "score":           int(score),
        "n_used":          len(keywords),
        "issues":          issues,
        "suggestions":     _keywords_suggestions(keywords, title, issues),
    }


def _keywords_suggestions(keywords: List[str], title: str, issues: List[str]) -> List[str]:
    sug = []
    if any("broad" in i.lower() or "1 mot" in i for i in issues):
        sug.append("🎯 Transforme les broad en long-tail (ex: 'journal' → 'gratitude journal for women')")
    if any("répètent" in i for i in issues):
        sug.append("🔄 Les mots du title sont déjà indexés — utilise des synonymes (ex: 'planner' → 'organizer')")
    if any("diversité" in i for i in issues):
        sug.append("🎲 Chaque keyword = un BUYER DIFFÉRENT (mère / gift / occasion / season / problem / format)")
    if any("Seulement" in i for i in issues):
        sug.append("📦 Remplis tous les 7 slots — chaque slot vide = perte de SEO")
    return sug


# ──────────────────────────────────────────────────────────────────────────────
#  Amazon autocomplete validation (optional, slow but real)
# ──────────────────────────────────────────────────────────────────────────────

def validate_keywords_amazon(keywords: List[str], delay_s: float = 0.4) -> Dict:
    """
    Hits Amazon's autocomplete for each keyword to verify it has REAL search volume.
    Returns per-keyword validation + count of validated. Slow (~3s for 7 kw).
    """
    import time as _t
    try:
        from modules.research.keywords import get_keyword_suggestions
    except Exception:
        return {"available": False, "validated": 0, "results": {}}

    out = {}
    for kw in (keywords or [])[:7]:
        toks = kw.split()
        prefix = " ".join(toks[:3]) if len(toks) >= 3 else " ".join(toks[:2])
        try:
            sugg = get_keyword_suggestions(prefix, limit=10) or []
        except Exception:
            sugg = []
        kw_low = kw.lower()
        is_match = any(kw_low == s.lower() or kw_low in s.lower() for s in sugg)
        partial_overlap = 0.0
        if not is_match and sugg:
            kw_set = set(re.findall(r"\w{4,}", kw_low))
            for s in sugg:
                s_set = set(re.findall(r"\w{4,}", s.lower()))
                overlap = len(kw_set & s_set) / max(len(kw_set), 1)
                partial_overlap = max(partial_overlap, overlap)
        out[kw] = {
            "validated":   is_match,
            "confidence":  1.0 if is_match else round(partial_overlap, 2),
            "suggestions": sugg[:5],
        }
        _t.sleep(delay_s)
    n_validated = sum(1 for v in out.values() if v["validated"] or v["confidence"] >= 0.5)
    return {"available": True, "validated": n_validated, "results": out}


# ──────────────────────────────────────────────────────────────────────────────
#  Aggregate tower
# ──────────────────────────────────────────────────────────────────────────────

def analyze_listing(listing: Dict, run_autocomplete: bool = False) -> Dict:
    """
    Full scan of the listing's SEO. Returns:
      {
        "global_score": 0-100,
        "title":     {score, issues, suggestions, length},
        "subtitle":  {score, issues, suggestions, length},
        "description": {score, issues, suggestions, word_count},
        "keywords":  {score, issues, suggestions, n_used,
                      autocomplete?: {available, validated, results}},
        "grade":     "A" | "B" | "C" | "D"
      }
    """
    title    = listing.get("title", "")
    subtitle = listing.get("subtitle", "")
    desc     = listing.get("description", "")
    kws      = listing.get("keywords", []) or []
    niche    = listing.get("niche", "")

    t_res = score_title(title, niche)
    s_res = score_subtitle(subtitle, title)
    d_res = score_description(desc, niche, kws)
    k_res = score_keywords(kws, title)

    if run_autocomplete:
        try:
            k_res["autocomplete"] = validate_keywords_amazon(kws)
        except Exception as e:
            logger.debug(f"autocomplete validation failed: {e}")

    global_score = int(round(
        t_res["score"] * SCORE_WEIGHTS["title"]
        + s_res["score"] * SCORE_WEIGHTS["subtitle"]
        + d_res["score"] * SCORE_WEIGHTS["description"]
        + k_res["score"] * SCORE_WEIGHTS["keywords"]
    ))
    grade = ("A" if global_score >= 85 else
             "B" if global_score >= 70 else
             "C" if global_score >= 55 else "D")

    return {
        "global_score": global_score,
        "grade":        grade,
        "title":        t_res,
        "subtitle":     s_res,
        "description":  d_res,
        "keywords":     k_res,
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Claude-powered listing rewrite (when score < 70)
# ──────────────────────────────────────────────────────────────────────────────

def rewrite_listing_zones(listing: Dict, anthropic_key: str,
                          zones: List[str] = None,
                          status_cb=None) -> Dict:
    """
    Asks Claude to rewrite the failing zones (title/subtitle/desc/keywords)
    based on the issues detected in analyze_listing(). Returns the new values.
    """
    if not anthropic_key:
        return {}
    try:
        import anthropic
    except ImportError:
        return {}

    analysis = analyze_listing(listing)
    zones    = zones or ["title", "subtitle", "description", "keywords"]
    fail_zones = [z for z in zones if analysis[z]["score"] < 70]
    if not fail_zones:
        return {}

    title    = listing.get("title", "")
    subtitle = listing.get("subtitle", "")
    desc     = listing.get("description", "")
    kws      = listing.get("keywords", []) or []
    niche    = listing.get("niche", "")
    p_type   = listing.get("product_type", "book")

    # Build prompt
    issues_text = ""
    for z in fail_zones:
        a = analysis[z]
        issues_text += f"\n## {z.upper()} — score {a['score']}/100\n"
        for i in a["issues"]:
            issues_text += f"  - {i}\n"
        if a.get("suggestions"):
            issues_text += f"  Suggestions :\n"
            for s in a["suggestions"]:
                issues_text += f"    • {s}\n"

    prompt = f"""You are a KDP listing surgeon. Rewrite only the failing zones
based on the AI scoring below. Output STRICT JSON with only the zones that
need rewriting. Keep working zones untouched.

NICHE: "{niche}"
PRODUCT_TYPE: {p_type}

CURRENT:
  title:    "{title}"
  subtitle: "{subtitle}"
  keywords: {kws}
  description (first 600 chars):
{desc[:600]}

FAILING ZONES (and why):
{issues_text}

REWRITE RULES (Amazon A10 2026 compliant):
- title       : max 60 chars, NO multi-colon, NO comma lists, long-tail
                with audience, niche-keyword in first 4 words
- subtitle    : max 80 chars, NO 2+-word overlap with title, numeric promise,
                synonyms not repeats
- description : 150-300 visible words, allowed HTML ONLY <b><i><br><p>,
                bullets as "<br>• item<br>", hook in first 3 lines (no cliché),
                end with explicit CTA, weave 2-3 keywords naturally
- keywords    : exactly 7 long-tail (3-7 words), distinct buyer intents,
                NO words already in title, NO cross-keyword token reuse

Return ONLY this JSON (omit zones that don't need rewriting):
{{
  "title":    "..." | null,
  "subtitle": "..." | null,
  "description": "..." | null,
  "keywords": ["...","...","...","...","...","...","..."] | null
}}"""

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        if status_cb:
            status_cb(f"✍️ Claude réécrit {len(fail_zones)} zone(s) faible(s)…")
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        import json as _json
        data = _json.loads(raw)
        # Filter only non-null fields
        return {k: v for k, v in data.items() if v}
    except Exception as e:
        logger.warning(f"rewrite_listing_zones failed: {e}")
        if status_cb:
            status_cb(f"⚠️ Rewrite échoué : {e}")
        return {}
