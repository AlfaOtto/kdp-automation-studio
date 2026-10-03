"""
KDP Content Generator — Claude AI
Generates: title, subtitle, description, keywords, publisher name, content plan.
All content in English, all KDP character limits respected.
"""
import json
import logging
import re
import time
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def _robust_json_parse(raw: str) -> dict:
    """Tries multiple strategies to parse potentially malformed JSON from AI."""
    # Strategy 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2: remove control characters that break JSON
    cleaned = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 3: extract the largest {...} block (handles leading/trailing junk)
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Strategy 4: fix unescaped newlines/tabs inside JSON strings
    def _fix_string_literals(s: str) -> str:
        """Replace bare newlines/tabs inside JSON string values."""
        result, in_string, i = [], False, 0
        while i < len(s):
            ch = s[i]
            if ch == '"' and (i == 0 or s[i-1] != '\\'):
                in_string = not in_string
                result.append(ch)
            elif in_string and ch == '\n':
                result.append('\\n')
            elif in_string and ch == '\t':
                result.append('\\t')
            elif in_string and ch == '\r':
                result.append('\\r')
            else:
                result.append(ch)
            i += 1
        return ''.join(result)

    try:
        return json.loads(_fix_string_literals(cleaned))
    except json.JSONDecodeError:
        pass

    # If all strategies fail, raise a clear error
    raise ValueError(f"Could not parse JSON from AI response. First 200 chars: {raw[:200]!r}")


# ── KDP exact character limits ────────────────────────────────────────────────
TITLE_MAX       = 200
SUBTITLE_MAX    = 200
DESCRIPTION_MAX = 4000
KEYWORD_MAX     = 50    # per field
NUM_KEYWORDS    = 7

# ── Product type detection ────────────────────────────────────────────────────
# IMPORTANT: order matters. Puzzle-specific markers checked first so that
# "sudoku puzzle book" → puzzle, not journal.
_TYPE_PATTERNS = {
    "activity_book": ["activity book", "brain games", "brain health",
                      "ultimate brain", "all-in-one puzzle", "mixed puzzle"],
    "puzzle":   ["sudoku", "maze", "mazes ", "kakuro", "kenken", "ken-ken",
                 "nonogram", "picross", "cryptogram", "word search",
                 "wordsearch", "logic puzzle", "logic grid", "einstein puzzle",
                 "dot to dot", "dot-to-dot", "connect the dots",
                 "puzzle book", "puzzles for"],
    "quiz":     ["trivia", "quiz", "questions", "facts book", "did you know", "q&a"],
    "planner":  ["planner", "organizer", "scheduler", "agenda", "weekly plan"],
    "log":      ["log book", "log ", "tracker", "field notes", "record book",
                 "monitoring", "keeper log", "evidence log", "inspection log"],
    "coloring": ["coloring", "colouring", "color book", "art book"],
    "journal":  ["journal", "notebook", "diary", "notes", "writing"],
}

def detect_product_type(niche: str) -> str:
    nl = niche.lower()
    for ptype, patterns in _TYPE_PATTERNS.items():
        for p in patterns:
            if p in nl:
                return ptype
    return "journal"


def detect_puzzle_type(niche: str) -> Optional[str]:
    """Subtype detection for puzzle product_type. Returns one of the
    PUZZLE_REGISTRY keys, or None if generic."""
    nl = (niche or "").lower()
    # Map keywords → puzzle_type
    mapping = [
        ("sudoku", "sudoku"),
        ("nonogram", "nonogram"), ("picross", "nonogram"),
        ("kakuro", "kakuro"),
        ("kenken", "kenken"), ("ken-ken", "kenken"), ("ken ken", "kenken"),
        ("cryptogram", "cryptogram"),
        ("word search", "wordsearch"), ("wordsearch", "wordsearch"),
        ("logic grid", "logic_grid"), ("logic puzzle", "logic_grid"),
        ("einstein puzzle", "logic_grid"),
        ("dot to dot", "dot_to_dot"), ("dot-to-dot", "dot_to_dot"),
        ("connect the dots", "dot_to_dot"),
        ("maze", "mazes"), ("mazes", "mazes"), ("labyrinth", "mazes"),
    ]
    for kw, ptype in mapping:
        if kw in nl:
            return ptype
    return None


# ── Main listing generator ────────────────────────────────────────────────────

_KW_STOPWORDS = {"for", "the", "and", "of", "in", "to", "a", "with",
                 "book", "books", "by", "on", "from", "an"}


def _tokens(text: str) -> List[str]:
    return [t for t in re.sub(r"[^a-zA-Z0-9]+", " ", str(text or "").lower()).split()
            if t and t not in _KW_STOPWORDS and len(t) > 2]


def _strip_title_words_from_keywords(title: str, keywords: List[str]) -> List[str]:
    """
    Amazon already indexes title words — re-using them in backend keywords wastes slots.
    Returns rewritten keyword list where title tokens are removed from each kw
    (preserving the leftover phrase). Empty results are kept as-is to avoid total loss.
    """
    title_toks = set(_tokens(title))
    out = []
    for kw in keywords:
        words = kw.split()
        kept = [w for w in words if w.lower().strip(",.;:!?") not in title_toks]
        new_kw = " ".join(kept).strip()
        # If stripping made it useless (< 2 words), keep the original
        if len(new_kw.split()) < 2:
            out.append(kw)
        else:
            out.append(new_kw)
    return out


def _dedupe_cross_keyword_tokens(keywords: List[str]) -> List[str]:
    """
    Amazon indexes each word once across ALL 7 fields. Repeating "adhd" 5 times
    wastes 4 slots. Strategy: keep first occurrence of each token, strip repeats
    from later keywords (but never reduce a keyword to <2 words).
    """
    seen: set = set()
    out = []
    for kw in keywords:
        words = kw.split()
        kept = []
        for w in words:
            tk = w.lower().strip(",.;:!?")
            if tk in _KW_STOPWORDS or len(tk) <= 2:
                kept.append(w)   # always keep stopwords/short for grammar
                continue
            if tk in seen:
                continue
            seen.add(tk)
            kept.append(w)
        new_kw = " ".join(kept).strip()
        if len(new_kw.split()) < 2:
            # Don't strip below 2 meaningful words — keep original
            out.append(kw)
            for w in kw.split():
                seen.add(w.lower().strip(",.;:!?"))
        else:
            out.append(new_kw)
    return out


def _subtitle_too_similar(title: str, subtitle: str, threshold: float = 0.45) -> bool:
    """
    True if subtitle shares too many tokens with title (waste of subtitle slot).
    """
    t_toks = set(_tokens(title))
    s_toks = set(_tokens(subtitle))
    if not s_toks:
        return False
    overlap = len(t_toks & s_toks) / len(s_toks)
    return overlap >= threshold


def _rewrite_subtitle(client, title: str, current_sub: str, niche: str) -> str:
    """Ask Claude for a fresh subtitle that doesn't repeat title words."""
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=120,
            messages=[{"role": "user", "content":
                f"Title: \"{title}\"\nCurrent subtitle: \"{current_sub}\"\nNiche: {niche}\n\n"
                "Rewrite the subtitle. RULES:\n"
                f"- Max {SUBTITLE_MAX} chars\n"
                "- Do NOT reuse any 2+-word phrase from the title\n"
                "- Add a DIFFERENT angle: audience / transformation / numeric promise / trope\n"
                "- One line, no quotes, no explanation"}],
        )
        new_sub = msg.content[0].text.strip().strip('"').strip()
        if 5 < len(new_sub) <= SUBTITLE_MAX:
            return new_sub
    except Exception as e:
        logger.debug(f"Subtitle rewrite failed: {e}")
    return current_sub


def _validate_keywords_via_autocomplete(keywords: List[str],
                                        max_lookups: int = 7,
                                        delay_s: float = 0.4) -> Dict[str, Any]:
    """
    For each keyword, query Amazon autocomplete with its first 2-3 words and check
    whether the full keyword (or close) appears in suggestions. Returns dict with
    per-keyword score and a list of suggested alternatives Amazon offers.

    A keyword with NO autocomplete match has very low search volume — pros either
    drop it or replace it with one Amazon actually suggests.
    """
    import time as _t
    try:
        from modules.research.keywords import get_keyword_suggestions
    except Exception:
        return {"available": False, "results": {}}

    out = {}
    for kw in keywords[:max_lookups]:
        toks = kw.split()
        if len(toks) < 2:
            out[kw] = {"in_autocomplete": False, "suggestions": [], "confidence": 0.0}
            continue
        # Probe with the first 2-3 tokens to get a richer suggestion set
        prefix = " ".join(toks[:3] if len(toks) >= 3 else toks[:2])
        try:
            sugg = get_keyword_suggestions(prefix, limit=10) or []
        except Exception:
            sugg = []
        kw_low = kw.lower()
        match = any(kw_low == s.lower() or kw_low in s.lower() for s in sugg)
        # Partial token-overlap fallback (if exact missing)
        partial = 0
        if not match and sugg:
            kw_set = set(_tokens(kw))
            for s in sugg:
                overlap = len(kw_set & set(_tokens(s))) / max(len(kw_set), 1)
                partial = max(partial, overlap)
        confidence = 1.0 if match else round(partial, 2)
        out[kw] = {
            "in_autocomplete": match,
            "suggestions":     sugg[:5],
            "confidence":      confidence,
        }
        _t.sleep(delay_s)   # be polite to autocomplete endpoint
    return {"available": True, "results": out}


def _is_title_stuffed(text: str) -> bool:
    """
    Detect the patterns KDP content team flags as 'metadata manipulation' /
    'disappointing customer experience' :
      - More than one colon
      - 3+ comma-separated keywords after a colon ("A, B, C, and D")
      - Length over 60 chars (title) or 80 chars (any)
      - Multiple separators (— / | : ·) in the same field
    """
    if not text:
        return False
    t = text.strip()
    if len(t) > 80:
        return True
    if t.count(":") >= 2:
        return True
    # 3+ comma-separated items suggest keyword list
    if t.count(",") >= 2:
        return True
    if sum(t.count(c) for c in ("—", "|", "·")) >= 2:
        return True
    return False


def _rewrite_title_subtitle_clean(client, old_title: str, old_subtitle: str,
                                   niche: str, product_type: str):
    """One Claude call to rewrite a stuffed title+subtitle in compliance with KDP rules."""
    prompt = (
        f"Niche: \"{niche}\"\nType: {product_type}\n"
        f"Current title (stuffed/bad): \"{old_title}\"\n"
        f"Current subtitle (stuffed/bad): \"{old_subtitle}\"\n\n"
        "Rewrite TITLE + SUBTITLE following STRICT KDP rules to avoid the "
        "'disappointing customer experience' content block:\n"
        "- Title: MAX 60 chars, NO colon, NO comma-separated list, conversational\n"
        "- Subtitle: MAX 80 chars, same rules, must add a DIFFERENT angle than title\n"
        "- Both must sound human when read aloud (no SEO dump)\n\n"
        "Return STRICT JSON: {\"title\": \"...\", \"subtitle\": \"...\"} — no other text."
    )
    import json as _json
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    d = _json.loads(raw)
    return (d.get("title", "").strip()[:60],
            d.get("subtitle", "").strip()[:80])


def _keyword_intent_diversity(keywords: List[str]) -> float:
    """
    Returns 0-1 — ratio of unique tokens vs total tokens across the 7 keywords.
    Pro keywords should hit DIFFERENT buyer intents → low token overlap.
    Score < 0.55 means the 7 keywords are basically variations of the same root.
    """
    if not keywords:
        return 0.0
    stopwords = {"for", "the", "and", "of", "in", "to", "a", "with", "book", "books"}
    tokens_all, tokens_unique = [], set()
    for kw in keywords:
        toks = [t for t in kw.lower().split() if t not in stopwords and len(t) > 2]
        tokens_all.extend(toks)
        tokens_unique.update(toks)
    if not tokens_all:
        return 0.0
    return len(tokens_unique) / len(tokens_all)


_KW_STOP = {"for", "the", "and", "of", "in", "to", "a", "an", "with", "your",
            "book", "books", "guide", "beginners", "beginner", "how"}


def _sig_tokens(text: str) -> set:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
            if t not in _KW_STOP and len(t) > 2}


# ── Trademark / brand guard for keywords ──────────────────────────────────────
# Amazon flags keywords (and cover/title) that use a brand the seller has no
# rights to (e.g. "Diamine" ink, "Pilot Kakuno" pen, "Funko Pop", "Pokemon").
# The autocomplete anchoring pulls in whatever buyers type — brands included —
# so we filter them out here. Distinctive brand tokens are matched as whole
# words; ambiguous everyday words (pilot, parker…) only count next to a cue.
_BRAND_TOKENS = {
    # pens / inks / stationery
    "diamine", "kakuno", "iroshizuku", "noodler", "noodlers", "lamy", "montblanc",
    "twsbi", "kaweco", "waterman", "pelikan", "monteverde", "conklin", "moleskine",
    "leuchtturm", "rhodia", "tombow", "copic", "prismacolor", "posca", "cricut",
    "crayola", "sharpie", "fabercastell",
    # toys / games / media franchises
    "funko", "lego", "disney", "marvel", "pokemon", "pokemons", "nintendo",
    "playstation", "xbox", "minecraft", "roblox", "fortnite", "gundam", "barbie",
    "transformers", "sanrio", "bluey", "squishmallow", "squishmallows", "jjk",
    "naruto", "gojo", "katakuri",
    # health / pharma brands
    "ozempic", "wegovy", "mounjaro", "zepbound",
    # general consumer brands
    "stanley", "yeti", "nike", "adidas", "starbucks", "ikea", "lululemon",
}
_BRAND_PHRASES = {
    "hello kitty", "star wars", "harry potter", "one piece", "dragon ball",
    "demon slayer", "jujutsu kaisen", "breaking bad", "stranger things",
    "paw patrol", "hot wheels", "coca cola", "sailor moon", "my hero academia",
    "attack on titan", "cruel prince", "faber castell", "robert oster",
    "private reserve", "j herbin",
}
# everyday words that are brands only alongside a category cue
_BRAND_IN_CONTEXT = {
    "pilot":    ("pen", "pens", "ink", "fountain"),
    "parker":   ("pen", "pens", "ink", "fountain"),
    "sailor":   ("pen", "pens", "ink", "fountain"),
    "platinum": ("pen", "pens", "ink", "fountain"),
    "herbin":   ("pen", "pens", "ink", "fountain"),
    "sakura":   ("pen", "pens", "pigma", "gelly", "micron"),
    "micron":   ("pen", "pens", "pigma", "sakura"),
    "apple":    ("watch", "iphone", "ipad", "macbook", "airpods", "ipod", "imac"),
}


def _has_brand(keyword: str) -> bool:
    """True if a keyword contains a trademarked brand we can't use."""
    kl = re.sub(r"[^a-z0-9 ]", " ", str(keyword or "").lower())
    kl = " " + re.sub(r"\s+", " ", kl).strip() + " "
    words = set(kl.split())
    if words & _BRAND_TOKENS:
        return True
    for ph in _BRAND_PHRASES:
        if f" {ph} " in kl:
            return True
    for tok, cues in _BRAND_IN_CONTEXT.items():
        if tok in words and (not cues or (set(cues) & words)):
            return True
    return False


# Stable publisher IMPRINT per theme → a recognizable brand across the catalog
# (instead of a different random house name on every book). No person names.
_IMPRINTS = {
    "food":      "Copper Skillet Press",
    "nature":    "Fern & Field Press",
    "craft":     "Maker's Hearth Press",
    "fitness":   "Iron Oak Press",
    "wellness":  "Still Harbor Press",
    "business":  "Ledger & Lantern Press",
    "ocean":     "Blue Tide Press",
    "vintage":   "Old Quill Press",
    "stars":     "North Star Press",
    "geometry":  "Blueprint House Press",
    "religion":  "Sacred Path Press",
    "education": "Bright Desk Press",
    "stories":   "Lantern Tale Press",
    "default":   "Evergreen Quill Press",
}
_IMPRINT_KIDS = "Curious Cub Press"


def _imprint_for(niche: str) -> str:
    """A stable publisher imprint for this niche's theme (brand consistency)."""
    try:
        from modules.creation.highcontent.engine import is_facts_niche
        if is_facts_niche(niche):
            return _IMPRINT_KIDS
    except Exception:
        pass
    try:
        from modules.creation.niche_themes import detect_theme
        theme = detect_theme(niche or "").get("name", "default")
    except Exception:
        theme = "default"
    return _IMPRINTS.get(theme, _IMPRINTS["default"])


def _optimize_keywords(niche: str, title: str, subtitle: str,
                       claude_keywords: List[str], max_slots: int = 7) -> List[str]:
    """Anchor the 7 backend keywords on REAL Amazon autocomplete searches (what
    buyers actually type) instead of invented angles. Builds a pool from
    autocomplete on the niche + broader roots, prefers relevant, high-volume,
    title-complementary terms, and only falls back to Claude's keywords/pads."""
    try:
        from modules.research.keywords import get_keyword_suggestions
    except Exception:
        return claude_keywords[:max_slots]

    niche_sig = _sig_tokens(niche)
    title_sig = _sig_tokens(f"{title} {subtitle}")

    # seeds: the niche + broader roots + common book-search modifiers → a rich
    # pool of REAL searched phrases (thin niches need broader seeds to reach 7)
    words = [w for w in (niche or "").split()]
    core = re.sub(r"\s+(for beginners?|guide|book|handbook)$", "", (niche or "").strip())
    seeds = [niche, core]
    if len(words) >= 3:
        seeds.append(" ".join(words[:3]))
    if len(words) >= 2:
        seeds.append(" ".join(words[:2]))
        seeds.append(" ".join(words[-2:]))
    seeds += [f"{core} book", f"how to {core}", f"{core} for beginners"]
    # keep only seeds carrying a real topic word (drop "for beginners" etc.)
    seeds = list(dict.fromkeys([s for s in seeds if s and _sig_tokens(s)]))
    seen, pool = set(), []          # pool = [(phrase, rank)]  rank ~ search volume
    for s in seeds:
        try:
            for i, sug in enumerate(get_keyword_suggestions(s, limit=15) or []):
                k = re.sub(r"\s+", " ", (sug or "").strip().lower())
                # strip scraping artefacts (years, "paperback", "kindle"…)
                k = re.sub(r"\b(paperback|hardcover|kindle|ebook|by|edition|"
                           r"january|february|march|april|june|july|august|september|"
                           r"october|november|december|\d{4})\b", " ", k)
                k = re.sub(r"\s+", " ", k).strip()
                if (k and k not in seen and 2 <= len(k.split()) <= 6
                        and len(k) <= 50 and len(_sig_tokens(k)) >= 1
                        and not _has_brand(k)):          # drop trademarked terms
                    seen.add(k)
                    pool.append((k, i))
        except Exception:
            continue

    def relevant(k):
        return len(_sig_tokens(k) & niche_sig) >= 1

    def rank_score(item):
        k, rank = item
        rel = 3 if relevant(k) else 0
        new_words = min(len(_sig_tokens(k) - title_sig), 3)   # widen title reach
        return rel + new_words - rank * 0.06
    pool.sort(key=rank_score, reverse=True)

    def near_dup(k, chosen):
        ks = _sig_tokens(k)
        for e in chosen:
            es = _sig_tokens(e)
            if ks and es and len(ks & es) / max(len(ks | es), 1) > 0.8:
                return True
        return False

    final: List[str] = []
    # 1) real, relevant autocomplete phrases first
    for k, _ in pool:
        if len(final) >= max_slots:
            break
        if relevant(k) and k.lower() != (title or "").lower() and not near_dup(k, final):
            final.append(k)
    # 2) any remaining real autocomplete phrase (even if it shares the niche root)
    for k, _ in pool:
        if len(final) >= max_slots:
            break
        if k.lower() != (title or "").lower() and not near_dup(k, final):
            final.append(k)
    # 3) top up from Claude's keywords (topical, even if not autocomplete-proven)
    if len(final) < max_slots:
        for k in (claude_keywords or []):
            if len(final) >= max_slots:
                break
            kk = re.sub(r"\s+", " ", str(k).strip())
            if kk and not near_dup(kk, final) and not _has_brand(kk):
                final.append(kk)
    # final safety net: never return a brand keyword, even from claude fallback
    final = [k for k in final if not _has_brand(k)]
    return final[:max_slots] if final else \
        [k for k in (claude_keywords or []) if not _has_brand(k)][:max_slots]


# theme (detect_theme) → allowed top-level KDP category domains + curated fallbacks.
_CATEGORY_DOMAINS = {
    "food":     (("Cookbooks, Food & Wine", "Health, Fitness & Dieting"),
                 ["Cookbooks, Food & Wine > Cooking Methods > Quick & Easy",
                  "Cookbooks, Food & Wine > Main Courses & Side Dishes"]),
    "nature":   (("Crafts, Hobbies & Home", "Home & Garden", "Gardening"),
                 ["Crafts, Hobbies & Home > Gardening & Landscape Design > Vegetables",
                  "Crafts, Hobbies & Home > Gardening & Landscape Design > Techniques",
                  "Crafts, Hobbies & Home > Gardening & Landscape Design > Garden Design"]),
    "craft":    (("Crafts, Hobbies & Home",),
                 ["Crafts, Hobbies & Home > Crafts & Hobbies",
                  "Crafts, Hobbies & Home > Crafts & Hobbies > Reference"]),
    "fitness":  (("Health, Fitness & Dieting", "Sports & Outdoors"),
                 ["Health, Fitness & Dieting > Exercise & Fitness",
                  "Sports & Outdoors > Individual Sports"]),
    "wellness": (("Health, Fitness & Dieting", "Self-Help"),
                 ["Health, Fitness & Dieting > Alternative Medicine",
                  "Self-Help > Personal Transformation"]),
    "business": (("Business & Money",),
                 ["Business & Money > Personal Finance",
                  "Business & Money > Small Business & Entrepreneurship"]),
    "animals":  (("Crafts, Hobbies & Home",),
                 ["Crafts, Hobbies & Home > Pets & Animal Care"]),
    "kids":     (("Children's Books", "Humor & Entertainment"),
                 ["Children's Books > Education & Reference > Reference",
                  "Humor & Entertainment > Puzzles & Games > Trivia"]),
    "religion": (("Religion & Spirituality", "Christian Books & Bibles"),
                 ["Religion & Spirituality > Worship & Devotion > Devotionals",
                  "Christian Books & Bibles > Bible Study & Reference"]),
    "education":(("Education & Teaching", "Reference", "Foreign Language Study"),
                 ["Education & Teaching > Studying & Workbooks",
                  "Reference > Words, Language & Grammar"]),
    "stories":  (("History", "Humor & Entertainment", "Reference"),
                 ["History > World",
                  "Humor & Entertainment > Trivia & Fun Facts"]),
}


def _relevant_categories(niche: str, product_type: str, categories: List[Dict]) -> List[Dict]:
    """Drop OFF-DOMAIN categories (e.g. a gardening book landing in Self-Help >
    Self-Esteem) and top up from a curated per-theme set so all 3 categories are
    precise and in the book's actual domain."""
    try:
        from modules.creation.niche_themes import detect_theme
        theme = detect_theme(niche or "").get("name", "default")
    except Exception:
        theme = "default"
    _nl = (niche or "").lower()
    if any(m in _nl for m in ("facts for", "fun facts", "for kids", "for curious kids")):
        theme = "kids"
    domain = _CATEGORY_DOMAINS.get(theme)
    if not domain:
        return categories[:3]                       # unknown domain → leave as-is
    allowed_roots, fallback = domain

    def in_domain(path):
        top = str(path).split(">")[0].strip()
        return any(r.lower() in str(path).lower() or top == r for r in allowed_roots)

    kept, seen = [], set()
    for c in categories:
        p = c.get("path", "")
        if in_domain(p) and p not in seen:
            seen.add(p)
            kept.append(c)
    # top up with curated in-domain categories until we have 3
    for p in fallback:
        if len(kept) >= 3:
            break
        if p not in seen:
            seen.add(p)
            kept.append({"path": p, "primary": False})
    if kept and not any(c.get("primary") for c in kept):
        kept[0]["primary"] = True
    return kept[:3] if kept else categories[:3]


def generate_listing(
    niche: str,
    product_type: str,
    api_key: str,
    status_cb=None,
    style_variant: Optional[Dict] = None,
    learning_dir: Optional[Path] = None,
) -> Dict:
    """
    Claude Sonnet generates the full KDP listing + interior content plan.

    Three layers shape the output:
      - product_type  : base layout (journal/log/quiz/planner/coloring)
      - style_variant : visual+editorial style (anti-duplicate rotation)
      - learning      : user profile + competitor insights for this niche
                        (loaded from learning_dir if provided)
    """
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    if status_cb:
        status_cb(f"📝 Génération listing KDP pour \"{niche}\"...")

    # High-content books (recipe_book / how_to) are REAL content books people
    # cook/learn from — NOT low-content journals. They need a cookbook/guide
    # listing voice, never the poetic "journal" tone.
    is_hc = product_type in ("recipe_book", "how_to")
    is_cookbook = product_type == "recipe_book"
    # A "fun facts for kids" niche routes to how_to for the pipeline but is really
    # a colorful CHILDREN'S FACTS BOOK — it needs a kid title, not a how-to guide title.
    _nl = (niche or "").lower()
    is_facts = product_type == "how_to" and any(
        m in _nl for m in ("facts for", "facts about", "fun facts", "amazing facts",
                           "did you know", "for kids", "for curious"))
    # Adult short-true-stories / anecdotes collection → NOT a how-to guide; it is
    # an "encyclopedia of fascinating true stories" (needs a collection-style title).
    is_anecdotes = product_type == "how_to" and not is_facts and any(
        m in _nl for m in ("anecdotes", "true stories", "short stories", "fascinating",
                           "mind blowing", "strange but true", "unbelievable",
                           "little known", "interesting facts for adults", "tales"))

    type_desc = {
        "journal":  "a lined journal/notebook with writing prompts (120 pages)",
        "log":      "a specialized log book with tracking tables (120 pages)",
        "quiz":     "a trivia/quiz book with questions & answers (150 pages)",
        "planner":  "a daily/weekly planner with scheduling layouts (120 pages)",
        "coloring": "a coloring book with illustrated pages (50 illustrations)",
        "recipe_book": "a FULL-COLOR COOKBOOK with real recipes — ingredients, step-by-step "
                       "instructions, nutrition facts and full-color food photos (people COOK from it)",
        "how_to":   "a practical HOW-TO GUIDE book with real written chapters people LEARN from",
    }.get(product_type, "a journal/notebook (120 pages)")

    # Anti-duplicate variant hints (tone, title style)
    variant_hint = ""
    if style_variant and not is_hc:
        variant_hint = (
            f"\nVARIANT INSTRUCTION (critical — gives this book its unique voice):\n"
            f"  - TONE: Write the description and welcome text with a {style_variant['tone']} voice.\n"
            f"  - TITLE STYLE: Make the title {style_variant['title_style']}.\n"
            f"  - Avoid clichés that other journals in this niche overuse.\n"
        )
    elif is_hc:
        # Cookbook/guide voice — confident, appetizing, benefit-driven. Never poetic.
        variant_hint = (
            "\nSTYLE: Write like a BESTSELLING Amazon "
            + ("COOKBOOK" if is_cookbook else "HOW-TO GUIDE") +
            " — confident, clear, benefit-driven and appetizing. "
            "This is NOT a journal, NOT poetic, NOT a 'guided space for reflection'.\n"
        )

    # ── Learning layer: user preferences + competitor + sample insights ──
    learning_hint = ""
    if learning_dir:
        try:
            from modules.learning.profile       import build_profile, profile_summary_for_prompt
            from modules.learning.insights      import insights_for_prompt
            from modules.learning.edit_learner  import patterns_for_prompt
            from modules.learning.transfer      import transfer_prompt
            from modules.learning.competitor    import get_insights, insights_summary_for_prompt
            from modules.learning.sample_reader import get_sample_insights, sample_insights_for_prompt as sample_summary
            profile = build_profile(learning_dir)
            comp    = get_insights(learning_dir, niche)
            sample  = get_sample_insights(learning_dir, niche)
            bits = []
            ps = profile_summary_for_prompt(profile)
            if ps: bits.append(ps)
            # Deep insights from pattern extraction
            ins = insights_for_prompt(learning_dir)
            if ins: bits.append(ins)
            # NEW: edit-based learning — past corrections become future rules
            ep = patterns_for_prompt(learning_dir)
            if ep: bits.append(ep)
            # NEW: cross-niche transfer — winning patterns from similar themes
            try:
                from modules.creation.niche_themes import detect_theme as _det
                _t = _det(niche).get("name") if _det else None
                tp = transfer_prompt(learning_dir, _t)
                if tp: bits.append(tp)
            except Exception:
                pass
            cs = insights_summary_for_prompt(comp)
            if cs: bits.append(cs)
            ss = sample_summary(sample)
            if ss: bits.append(ss)
            if bits:
                learning_hint = (
                    "\n\nLEARNED CONTEXT (adapt the listing to these signals):\n"
                    + "\n".join(f"  · {b}" for b in bits)
                )
                if status_cb:
                    status_cb(f"🧠 Apprentissage injecté ({len(bits)} signal(s))")
        except Exception as e:
            logger.debug(f"Learning injection skipped: {e}")

    _book_kind = ("HIGH-CONTENT cookbook" if is_cookbook
                  else "HIGH-CONTENT guide" if is_hc else "low-content")
    prompt = f"""You are a top Amazon KDP publisher with 15 years of experience on the US market.
Create a COMPLETE KDP listing for this {_book_kind} book:

NICHE: "{niche}"
PRODUCT TYPE: {type_desc}{variant_hint}{learning_hint}

Return a single JSON object with EXACTLY these fields:

{{
  "title": "...",
  "subtitle": "...",
  "description": "...",
  "keywords": ["...", "...", "...", "...", "...", "...", "..."],
  "publisher_name": "...",
  "page_count": 120,
  "categories": [
    {{"path": "Crafts, Hobbies & Home > ...", "primary": true}},
    {{"path": "Self-Help > Journaling", "primary": false}},
    {{"path": "Health, Fitness & Dieting > ...", "primary": false}}
  ],
  "content_sections": [
    {{
      "title": "...",
      "type": "welcome|toc|content|tracker|qa|reference|closing",
      "pages": 2,
      "description": "...",
      "items": []
    }}
  ]
}}

STRICT RULES FOR EACH FIELD (Amazon A10 algorithm 2026 compliant):

- title: ABSOLUTE MAX 60 CHARS. NO COLON anywhere in the title (use subtitle for any
  ": after" content). NO comma-separated lists ("for X, Y, Z..." is a metadata
  manipulation pattern KDP BANS — it triggers a content-block rejection email).
  LONG-TAIL with a specific AUDIENCE or USE-CASE baked in
  (ex: "ADHD Daily Planner for Working Moms"). Clean, creative, conversational —
  read it aloud, if it sounds like a SEO keyword dump, REWRITE.
  A10 + Rufus voice search + KDP content team penalize keyword stuffing.
  ❌ BANNED PATTERNS — automatic rejection:
    • Two or more colons : "X: Y: Z"
    • Comma-separated keyword lists (3+ items)
    • "Comprehensive guide to A, B, C, D, and E"
    • "Tracking pages for Date, Time, Location..."
    • Any title over 60 chars
  ✅ GOOD: "ADHD Daily Planner for Working Moms"
  ✅ GOOD: "UFO Sighting Log Book for Skywatchers"
  ❌ BAD : "UFO Sighting Log: Structured Documentation: Comprehensive Tracking Pages for Date, Time, Location, Witnesses, and Weather"

- subtitle: MAX 80 CHARS (NOT 200 — long subtitles trigger spam filters). CRITICAL :
  do NOT repeat any 2+-word phrase from the title. Do NOT use comma-separated lists.
  Same anti-stuffing rules as title — read it aloud, must sound like a human wrote it.
  Add ADJACENT relevance: a different audience facet OR transformation OR benefit OR
  setting OR trope. Include a numeric promise when natural ("90 Days", "100 Prompts").
  ❌ Bad: "Structured Documentation System: Comprehensive Tracking Pages for Date, Time, Location"
  ✅ Good: "90-Day Sky Watch Companion with Sketch Pages"

- description: MAX {DESCRIPTION_MAX} chars but TARGET 150-300 visible words (longer kills mobile
  conversion). KDP sweet spot.
  ALLOWED HTML TAGS ONLY: <b>, <i>, <br>, <p>. (Amazon STRIPS <ul>, <li>, <h1-h6>, <div>,
  <span>, <style>, <img>, <a> silently — do NOT use them or the description renders as garbage.)
  For bulleted lists, write each item on its own line prefixed with "• " (bullet character)
  and wrap with <br><br>. NEVER use <ul> or <li>.
  MOBILE-FIRST structure (only first 3-4 lines are visible before "Read more" tap):
    Line 1-2 : POWERFUL emotional HOOK (the reader-pain or transformation in one sentence)
    Line 3-4 : One concrete promise / contrast / surprising fact that proves you understand them
    Then <br><br>
    <b>What's inside:</b><br>
    • Item 1 (concrete, scannable)<br>
    • Item 2<br>
    • Item 3<br>
    • Item 4<br>
    • Item 5<br><br>
    <b>Perfect for:</b><br>
    • Audience 1<br>
    • Audience 2<br>
    • Audience 3<br><br>
    <i>Short closing line — call to action or invitation.</i>
  Weave 2-4 long-tail keywords NATURALLY into the prose. Never a keyword dump at the end.

- keywords: Exactly 7 strings, each MAX {KEYWORD_MAX} chars, 2-5 words each.
  ⚑ THE #1 RULE: each keyword MUST be a phrase REAL SHOPPERS ACTUALLY TYPE into the
    Amazon search box for this kind of book — common, high-volume searches and their
    close variants. NOT clever/unique angles nobody searches (that is why books fail
    to rank). If unsure a phrase is really searched, use the plainer, more obvious term.
  RULES:
    1. ANCHOR on the obvious searched terms for the niche + real buyer variants
       (audience, sub-topic, format, problem, synonym). Think: "what would I type to
       FIND this book?" — e.g. for an air-fryer book: "air fryer cookbook for beginners",
       "healthy air fryer recipes", "air fryer meal prep", "high protein recipes".
    2. DO NOT repeat words already in the TITLE (Amazon already indexed those) — cover
       NEW searched terms/synonyms instead, to widen reach.
    3. Some overlap between keywords is FINE if the phrases are genuinely searched —
       real search volume beats artificial word-diversity.
  ❌ Bad (invented, unsearched): ["GLP-1 Ozempic weight loss meals", "women over 40 lean muscle",
       "backyard food production system", "harvest preservation methods home"]
  ✅ Good (real searches): for gardening → ["raised bed gardening for beginners",
       "container gardening vegetables", "how to grow vegetables", "square foot gardening book",
       "organic vegetable garden", "gardening books for beginners", "backyard homestead guide"]
- publisher_name: A professional themed publishing house (2-4 words, NO person name).
  Examples: "Shadow Crown Press", "Fern & Stone Publishing", "Ember Quill Press".
- page_count: realistic integer for the product type.
- categories: Exactly 3 REAL Amazon KDP browse categories that this book BEST fits.
  Use Amazon's actual category tree. Format each as a path "Top > Sub > Sub-sub" — 2 to 4 levels deep.
  The FIRST one is marked primary=true (the most relevant). The other two are secondary.
  Examples of real KDP category paths:
    "Crafts, Hobbies & Home > Crafts & Hobbies > Coloring Books for Grown-Ups"
    "Self-Help > Journal Writing"
    "Health, Fitness & Dieting > Diseases & Physical Ailments > Diabetes"
    "Humor & Entertainment > Puzzles & Games > Trivia"
    "Sports & Outdoors > Outdoor Recreation > Hunting & Fishing > Fishing"
    "Children's Books > Activities, Crafts & Games > Activity Books > Coloring Books"
  Pick categories that have proven sales for this kind of book. NEVER invent fake paths.
- content_sections: 5-8 sections covering the full book.
  For "content" type sections, add 8-12 sample items in the "items" array
  (writing prompts for journals, table headers for logs, Q&A for quiz, etc.)

ALL TEXT MUST BE IN ENGLISH. Return ONLY the JSON object, no explanation."""

    if is_facts:
        prompt += """

═══════════════════════════════════════════════════════════════════════════
CHILDREN'S FUN-FACTS BOOK RULES — these OVERRIDE the generic guidance above:
═══════════════════════════════════════════════════════════════════════════
- This is a colorful FUN FACTS book FOR KIDS. The title must sound playful and
  kid/parent-appealing — NOT a how-to guide, NOT a journal.
  ❌ FORBIDDEN: "how to", "guide", "handbook", "journal", "notebook", "workbook".
- TITLE formula: fun + topic + kids. ✅ "Fun Facts for Curious Kids"
  ✅ "Amazing Facts Every Curious Kid Should Know"
- SUBTITLE: a NUMBER of facts + the topics + age. ✅ "300 Amazing Facts About Space,
  Animals, Nature and the Human Body — for Ages 6-10". Use a round number (100/200/300).
- description: excite PARENTS and KIDS — surprising facts, full-color illustrations,
  perfect gift, screen-free learning, builds curiosity.
- categories: use REAL Children's Books KDP paths, e.g.:
    "Children's Books > Education & Reference > Science, Nature & How It Works"
    "Children's Books > Education & Reference > Reference"
    "Children's Books > Science, Nature & How It Works > How Things Work"
- content_sections: keep to 2-3 light entries ONLY; real content comes from the engine.
- page_count: 60.
"""
    elif is_anecdotes:
        prompt += """

═══════════════════════════════════════════════════════════════════════════
ADULT TRUE-STORIES / ANECDOTES COLLECTION RULES — these OVERRIDE the above:
═══════════════════════════════════════════════════════════════════════════
- This is an ADULT "encyclopedia of fascinating TRUE stories/anecdotes" — a
  COLLECTION, NOT a how-to guide, NOT a kids book, NOT a journal.
  ❌ FORBIDDEN in the title: "how to", "guide", "handbook", "for beginners",
     "step-by-step", "workbook", "journal".
- TITLE formula: a collection name. ✅ "The Book of Fascinating True Stories"
  ✅ "Incredible True Stories for Curious Minds" ✅ "Strange but True: Astonishing
  Real Events from History and Science".
- SUBTITLE formula: "A Collection of [adjective] True Stories About [topics]" +
  optional hook. ✅ "A Collection of Astonishing Real Events from History, Science,
  and the Strange Corners of Our World".
- description: intrigue ADULTS — surprising, verified true stories; perfect for
  trivia lovers, curious minds, coffee-table reading, and gifts.
- categories: use REAL adult KDP paths, e.g.:
    "History > World"
    "Humor & Entertainment > Trivia & Fun Facts"
    "Reference > Encyclopedias & Subject Guides"
- content_sections: keep to 2-3 light entries ONLY; real content comes from the engine.
- page_count: 140.
"""
    elif is_hc:
        prompt += f"""

═══════════════════════════════════════════════════════════════════════════
HIGH-CONTENT {'COOKBOOK' if is_cookbook else 'GUIDE'} RULES — these OVERRIDE the generic guidance above:
═══════════════════════════════════════════════════════════════════════════
- The title MUST read like a TOP-SELLING Amazon {'cookbook' if is_cookbook else 'how-to guide'},
  never a journal. ❌ FORBIDDEN words in title/subtitle: "journal", "notebook", "log",
  "diary", "guided space", "reflections", "companion", "mindful", "whispers".
{'''- recipe_book TITLE formula: the FOOD/METHOD + "Cookbook" + audience.
  ✅ "High-Protein Air Fryer Cookbook for Beginners"
  ✅ "Osteoporosis Diet Cookbook for Seniors"
- recipe_book SUBTITLE formula: a NUMBER of recipes + core benefit + audience/outcome.
  ✅ "75 Quick High-Protein Recipes to Build Muscle and Save Time"
  Use a concrete recipe count around 75-100 (a round, believable number).''' if is_cookbook else '''- how_to GUIDE TITLE formula: the SKILL/TOPIC + "Guide"/"Handbook" + "for Beginners".
  ✅ "Cold Plunge Therapy Guide for Beginners"
- how_to SUBTITLE: a clear transformation/benefit + what they'll be able to do.'''}
- description: sell the {'COOKBOOK — appetizing, results-driven. Mention full-color photos, nutrition facts per recipe, and a meal plan.' if is_cookbook else 'GUIDE — practical, confidence-building. Mention step-by-step chapters and real results.'}
- categories: use REAL {'Cookbooks, Food & Wine' if is_cookbook else 'How-To / self-help / hobby'} KDP paths, e.g.:
{'''    "Cookbooks, Food & Wine > Special Diet > High Protein"
    "Cookbooks, Food & Wine > Kitchen Appliances > Air Fryers"
    "Cookbooks, Food & Wine > Cooking by Ingredient > Meat & Poultry"''' if is_cookbook else '''    "Health, Fitness & Dieting > ..." or "Crafts, Hobbies & Home > ..." matching the topic.'''}
- content_sections: keep to 2-3 light front/back-matter entries ONLY (welcome + closing);
  the real content is produced by the dedicated high-content engine, NOT here.
- page_count: {'150' if is_cookbook else '120'}.
"""

    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = msg.content[0].text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    data = _robust_json_parse(raw)

    # ── Anti-stuffing enforcement (KDP content block prevention) ────────
    raw_title = data["title"].strip()
    raw_sub   = data["subtitle"].strip()
    if _is_title_stuffed(raw_title) or _is_title_stuffed(raw_sub):
        logger.warning(f"[{niche}] title/subtitle has stuffing pattern — rewriting")
        try:
            new_title, new_sub = _rewrite_title_subtitle_clean(
                client, raw_title, raw_sub, niche, product_type)
            if new_title: data["title"] = new_title
            if new_sub:   data["subtitle"] = new_sub
        except Exception as e:
            logger.warning(f"Title cleanup rewrite failed: {e}")
    # Hard caps : 60 chars title, 80 chars subtitle
    data["title"]       = data["title"].strip()[:60]
    data["subtitle"]    = data["subtitle"].strip()[:80]
    data["description"] = data["description"].strip()[:DESCRIPTION_MAX]
    data["keywords"]    = [k.strip()[:KEYWORD_MAX] for k in data["keywords"][:NUM_KEYWORDS]]
    # Pad to 7 keywords if Claude returned fewer
    while len(data["keywords"]) < NUM_KEYWORDS:
        data["keywords"].append(f"{niche} book")

    # ── Anti-overlap post-process (A10 listing optimization) ────────────
    try:
        before = list(data["keywords"])
        data["keywords"] = _strip_title_words_from_keywords(data["title"], data["keywords"])
        data["keywords"] = _dedupe_cross_keyword_tokens(data["keywords"])
        # Re-enforce 50-char cap after rewrites
        data["keywords"] = [k.strip()[:KEYWORD_MAX] for k in data["keywords"]]
        # Pad if some keyword shrank to <2 words and got reset (we keep originals)
        if data["keywords"] != before:
            logger.debug(f"[{niche}] keywords rewritten (anti-overlap): {before} → {data['keywords']}")
    except Exception as e:
        logger.warning(f"Keyword anti-overlap step failed: {e}")

    # Subtitle ≠ title rephrase
    try:
        if _subtitle_too_similar(data["title"], data.get("subtitle", "")):
            old_sub = data.get("subtitle", "")
            new_sub = _rewrite_subtitle(client, data["title"], old_sub, niche)
            if new_sub and new_sub != old_sub:
                data["subtitle"] = new_sub[:SUBTITLE_MAX]
                logger.info(f"[{niche}] subtitle rewritten — too similar to title")
    except Exception as e:
        logger.warning(f"Subtitle similarity rewrite failed: {e}")

    # ── Diversity check: log when intents overlap too much ──────────────
    try:
        diversity = _keyword_intent_diversity(data["keywords"])
        if diversity < 0.55:
            logger.warning(
                f"[{niche}] low keyword diversity ({diversity:.2f}) — "
                f"7 keywords share too many tokens"
            )
        data["_keyword_diversity"] = round(diversity, 2)
    except Exception:
        pass

    # ── SEARCH-ANCHORED keywords (the ranking lever) ────────────────────
    # Replace invented "unique angles" with phrases buyers ACTUALLY type,
    # grounded in real Amazon autocomplete for this niche.
    try:
        _opt = _optimize_keywords(niche, data.get("title", ""),
                                  data.get("subtitle", ""), data.get("keywords", []))
        if _opt:
            data["keywords"] = _opt
    except Exception as _ke:
        logger.debug(f"keyword optimization skipped: {_ke}")

    # ── Autocomplete validation (Amazon search-volume proof) ────────────
    try:
        validation = _validate_keywords_via_autocomplete(data["keywords"])
        if validation.get("available"):
            # Compress to a compact summary stored in listing
            data["_keyword_autocomplete"] = {
                kw: {"in_autocomplete": v["in_autocomplete"],
                     "confidence":      v["confidence"]}
                for kw, v in validation["results"].items()
            }
            n_validated = sum(1 for v in validation["results"].values()
                              if v["in_autocomplete"] or v["confidence"] >= 0.5)
            if n_validated < 3:
                logger.warning(
                    f"[{niche}] only {n_validated}/7 keywords validated by autocomplete "
                    "— most likely low search volume"
                )
            else:
                logger.info(f"[{niche}] {n_validated}/7 keywords validated by autocomplete")
    except Exception as e:
        logger.debug(f"Autocomplete validation skipped: {e}")

    # ── Categories: validate / sanitise ──────────────────────────────────
    raw_cats = data.get("categories", []) or []
    clean_cats = []
    for c in raw_cats:
        if isinstance(c, dict) and c.get("path"):
            path = str(c["path"]).strip()
            if " > " in path and 5 < len(path) < 250:
                clean_cats.append({
                    "path":    path,
                    "primary": bool(c.get("primary", False)),
                })
        elif isinstance(c, str) and " > " in c:
            clean_cats.append({"path": c.strip(), "primary": False})
    # Ensure exactly one primary (first one if none marked)
    if clean_cats and not any(c["primary"] for c in clean_cats):
        clean_cats[0]["primary"] = True
    # Cap to 3 (KDP max)
    data["categories"] = clean_cats[:3]
    # PRECISION: drop off-domain categories (e.g. gardening → Self-Esteem) and
    # top up with curated in-domain ones so all 3 are relevant to the book.
    try:
        data["categories"] = _relevant_categories(niche, product_type, data["categories"])
    except Exception as _ce:
        logger.debug(f"category domain filter skipped: {_ce}")

    data["product_type"] = product_type
    data["niche"]        = niche
    # Stable imprint per theme (brand consistency across the catalog)
    try:
        data["publisher_name"] = _imprint_for(niche)
    except Exception as _ie:
        logger.debug(f"imprint override skipped: {_ie}")

    if status_cb:
        status_cb(f"✅ Listing généré : \"{data['title'][:60]}...\"")

    return data


# ── Universal chunked section expander ────────────────────────────────────────

def _strip_markdown_and_numbering(line: str) -> str:
    """Iteratively strips leading markdown, numbering, bullets, and wrapping markdown.
    Repeats until the line is stable — handles nested cases like **1.** prompt
    and 1.** prompt where digit+punct is followed directly by markdown."""
    if not line:
        return ""
    previous = None
    iterations = 0
    while line != previous and iterations < 10:
        previous = line
        iterations += 1
        # Strip leading markdown: **, __, *, _
        line = re.sub(r"^[\*_]+\s*", "", line)
        # Strip trailing markdown
        line = re.sub(r"\s*[\*_]+$", "", line)
        # Strip leading numbering — accepts:
        #   "1. " / "1) " / "(1) " / "•" / "-"  (with whitespace)
        #   "1." / "1)" / "(1)"                 (followed by * or _ or end)
        line = re.sub(r"^\s*\(\d+\)\s*(?:[\*_]+\s*)?", "", line)
        line = re.sub(r"^\s*[\d]+[.\)]\s*(?:[\*_]+\s*)?", "", line)
        line = re.sub(r"^\s*[-•]\s+", "", line)
        # Strip wrapping markdown: **X** → X, __X__ → X
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"__([^_]+)__", r"\1", line)
        # Strip wrapping quotes and lingering markdown chars
        line = line.strip("*_ \"'")
    return line.strip()


# Compiled regexes for performance
_Q_PATTERN = re.compile(
    r"^(?:Q\d*[\s.:)\]]|Question\s*\d*[\s.:)\]])\s*",
    re.I,
)
_A_PATTERN = re.compile(
    r"^(?:A\d*[\s.:)\]]|Answer\s*\d*[\s.:)\]])\s*",
    re.I,
)


def _parse_quiz_pairs(text: str, seen_questions: set) -> List[str]:
    """
    Robust Q/A parser. Handles:
      - "Q: ..." / "A: ..."
      - "Q1: ..." / "A1: ..."
      - "Question 1: ..." / "Answer 1: ..."
      - "**Q1:** ..." / "**A1:** ..." (markdown)
      - "1. Q: ..." / "1. A: ..." (numbered)
      - "1)" / "(1)" / "•" / "-" prefixes
    Drops orphan Q (no answer) — guarantees every kept Q has an A.
    """
    pairs: List[List[str]] = []
    pending_q = None
    for raw_line in text.splitlines():
        line = _strip_markdown_and_numbering(raw_line)
        if not line or line.startswith("#"):
            continue

        # Question line?
        q_match = _Q_PATTERN.match(line)
        if q_match:
            q_text = line[q_match.end():].strip()
            # Strip trailing markdown / quotes if any
            q_text = q_text.strip("*_ \"'")
            if q_text and q_text.lower() not in seen_questions:
                pending_q = q_text
            continue

        # Answer line?
        if pending_q:
            a_match = _A_PATTERN.match(line)
            if a_match:
                a_text = line[a_match.end():].strip().strip("*_ \"'")
                if a_text:
                    seen_questions.add(pending_q.lower())
                    pairs.append([f"Q: {pending_q}", f"A: {a_text}"])
                    pending_q = None
                continue

    # Flatten
    out: List[str] = []
    for p in pairs:
        out.extend(p)
    return out


def _parse_quiz_pairs_loose(text: str, seen_questions: set) -> List[str]:
    """
    Fallback parser when strict parser returns nothing.
    Looks for any line ending with '?' as a question, takes the next non-empty
    line as the answer. Lossy but recovers content when Claude formats weirdly.
    """
    pairs: List[List[str]] = []
    lines = [_strip_markdown_and_numbering(l) for l in text.splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]

    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        # Question heuristic: ends with '?' and reasonable length
        if line.endswith("?") and 10 < len(line) < 250:
            q_text = line.strip("*_ \"'")
            # Strip leading Q-markers if any sneaked through
            q_text = _Q_PATTERN.sub("", q_text).strip()
            if q_text and q_text.lower() not in seen_questions:
                a_text = lines[i + 1].strip("*_ \"'")
                a_text = _A_PATTERN.sub("", a_text).strip()
                if a_text and 1 < len(a_text) < 500 and not a_text.endswith("?"):
                    seen_questions.add(q_text.lower())
                    pairs.append([f"Q: {q_text}", f"A: {a_text}"])
                    i += 2
                    continue
        i += 1

    out: List[str] = []
    for p in pairs:
        out.extend(p)
    return out


def _parse_simple_lines(text: str, seen: set) -> List[str]:
    """
    Robust parser for plain one-per-line content (journal prompts, coloring
    titles, planner prompts, etc.).

    Handles all the messy formats Claude might return:
      - "1. Describe..." / "(1) Describe..." / "• Describe..."
      - "**Describe...**" / "_Describe..._" (markdown bold/italic)
      - "**1.** Describe..." (numbered + bolded)
      - Wrapping quotes "..." or '...'
      - Trailing trailing markdown like "...*" or "...**"
    """
    out: List[str] = []
    for raw_line in text.splitlines():
        line = _strip_markdown_and_numbering(raw_line)
        if not line or line.startswith("#"):
            continue
        # Strip lingering markdown anywhere in the line
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"__([^_]+)__", r"\1", line)
        # Strip wrapping quotes
        line = line.strip("*_ \"'")
        # Drop preamble / header-like lines
        if line.lower().startswith((
            "here are", "here is", "below are", "below is",
            "the following", "list of", "okay", "sure", "great",
        )):
            continue
        if len(line) < 8:
            continue
        if line.endswith(":") and len(line) < 50:
            continue   # likely a section header, not content
        key = line.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _parse_simple_lines_loose(text: str, seen: set) -> List[str]:
    """
    Fallback parser when strict simple-lines returns nothing.
    Splits on sentence boundaries and picks anything that looks like a
    standalone prompt/title (10-250 chars, starts with capital or verb).
    """
    import re as _re
    # Split on newlines AND on sentence terminators
    candidates = _re.split(r"(?:\n|(?<=[.!?])\s+(?=[A-Z]))", text)
    out: List[str] = []
    for raw in candidates:
        line = _strip_markdown_and_numbering(raw)
        line = _re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = _re.sub(r"__([^_]+)__", r"\1", line)
        line = line.strip("*_ \"'").strip()
        if not line:
            continue
        if not (10 < len(line) < 250):
            continue
        # Must start with a capital letter or a question word
        if not (line[0].isupper() or line[0].isdigit()):
            continue
        key = line.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _expand_section_chunked(
    client,
    *,
    niche: str,
    section: Dict,
    n_target: int,
    prompt_builder,                   # callable(niche, section, n) -> prompt str
    parser,                           # callable(text, seen_set) -> list of valid lines
    counter,                          # callable(items_list) -> int (counts produced units)
    loose_parser=None,                # optional fallback parser
    model: str = "claude-sonnet-4-5",
    chunk_size: int = 30,
    beat_hint: str = "",
    status_cb=None,
    max_chunks: int = 12,
    stall_threshold: int = 4,
) -> List[str]:
    """
    Universal chunked expander — works for QUIZ, JOURNAL, PLANNER, COLORING.

    Defensive features:
      - Strict parser tried first, loose fallback if strict returns 0
      - Verbose status logging: shows count returned per chunk
      - Per-chunk validation: if return < 50% expected → retry once
      - Stall threshold 4 (instead of 2) — gives more room before giving up
      - Caps at max_chunks to prevent runaway costs
    """
    title = section.get("title", "section")
    items: List[str] = []
    seen: set = set()
    chunk_idx = 0
    last_count = -1
    stalls = 0

    while counter(items) < n_target and chunk_idx < max_chunks:
        produced = counter(items)
        if produced == last_count:
            stalls += 1
            if stalls >= stall_threshold:
                if status_cb:
                    status_cb(f"  ⚠️ {title[:38]} — stall après {stalls} chunks vides, on s'arrête à {produced}")
                logger.warning(f"Chunked expand stalled for '{title}' at {produced}")
                break
        else:
            stalls = 0
        last_count = produced

        remaining = n_target - produced
        ask = min(chunk_size, remaining)
        chunk_idx += 1
        if status_cb:
            status_cb(f"  · {title[:38]} · chunk {chunk_idx} (target +{ask}, total {produced}/{n_target})")

        # Show last few items as anti-duplication context
        anti_dup = ""
        if items:
            sample = items[-min(10, len(items)):]
            anti_dup = (
                "\n\nALREADY GENERATED — do NOT repeat these or anything similar:\n"
                + "\n".join(sample)
            )

        # Build prompt with STRICT format directive to maximize parser success
        base_prompt = prompt_builder(niche, section, ask)
        strict_format = (
            "\n\nOUTPUT FORMAT (mandatory):\n"
            "Each item on its own line. Use the EXACT format shown in the prompt above. "
            "NO markdown (no **bold**, no _italics_). NO numbered list prefixes (no '1.', no '(1)'). "
            "Plain text only. Start each Q with 'Q:' and each A with 'A:' if Q&A format. "
            "Just the content lines — no preamble, no explanation, no closing remarks."
        )
        prompt = base_prompt + strict_format + anti_dup
        if beat_hint:
            prompt += "\n\n" + beat_hint

        try:
            msg = client.messages.create(
                model=model,
                max_tokens=min(8000, 500 + ask * 80),
                messages=[{"role": "user", "content": prompt}],
            )
            chunk_text = msg.content[0].text.strip()

            # Save raw response to disk for diagnostics
            try:
                _debug_dir = Path("output/debug")
                _debug_dir.mkdir(parents=True, exist_ok=True)
                _ts = int(time.time())
                _slug = re.sub(r"[^a-z0-9]+", "_", title.lower())[:30]
                _debug_file = _debug_dir / f"chunk_{_slug}_{chunk_idx}_{_ts}.txt"
                _debug_file.write_text(
                    f"NICHE: {niche}\nSECTION: {title}\nCHUNK: {chunk_idx}\nASKED: {ask}\n\n"
                    f"--- RAW RESPONSE ---\n{chunk_text}\n",
                    encoding="utf-8",
                )
            except Exception as _e:
                logger.debug(f"Debug write failed: {_e}")

            # Try strict parser first
            new_items = parser(chunk_text, seen)
            parser_used = "strict"

            # If strict returned nothing AND we have a loose fallback → try loose
            if not new_items and loose_parser is not None:
                logger.info(f"Strict parser empty for '{title}' chunk {chunk_idx}, trying loose")
                new_items = loose_parser(chunk_text, seen)
                if new_items:
                    parser_used = "loose"

            if new_items:
                items.extend(new_items)
                gained = counter(new_items) if counter is not _count_lines else len(new_items)
                if status_cb:
                    status_cb(f"     ↳ +{gained} items (parser: {parser_used})")
            else:
                # Log raw output preview for diagnostics
                preview = chunk_text[:300].replace("\n", " ⏎ ")
                logger.warning(
                    f"Chunk {chunk_idx} for '{title}' produced 0 items. "
                    f"Raw preview: {preview!r}"
                )
                if status_cb:
                    status_cb(f"     ↳ ⚠️ 0 items extraits — preview Claude: {preview[:120]}")

        except Exception as e:
            err = str(e)[:150]
            logger.warning(f"Chunk {chunk_idx} for '{title}' API call failed: {err}")
            if status_cb:
                status_cb(f"     ↳ ❌ API error: {err}")
            # Don't break immediately — let the stall counter decide
            continue

    final_count = counter(items)
    if status_cb:
        if final_count >= n_target * 0.75:
            status_cb(f"  ✅ {title[:38]} — {final_count}/{n_target} items en {chunk_idx} chunk(s)")
        elif final_count > 0:
            status_cb(f"  ⚠️ {title[:38]} — seulement {final_count}/{n_target} items (sous-cible)")
        else:
            status_cb(f"  ❌ {title[:38]} — 0 items générés ! section sera vide")
    return items


# Type-specific counters
def _count_qa_pairs(items: List[str]) -> int:
    return sum(1 for l in items if l.startswith("Q:"))

def _count_lines(items: List[str]) -> int:
    return len(items)


# ── Parallel quiz generator ───────────────────────────────────────────────────

def _generate_subtopics(client, niche: str, n: int = 30,
                        model: str = "claude-sonnet-4-5") -> List[str]:
    """Ask Claude for N distinct sub-topics for a quiz niche (one API call)."""
    prompt = (
        f'List exactly {n} distinct sub-topics for a trivia/quiz book about: "{niche}"\n\n'
        "Rules:\n"
        "- Each sub-topic is 3-8 words, specific and distinct\n"
        "- Cover different angles: history, famous names, records, techniques, culture, etc.\n"
        "- ALL in English\n"
        "- Return ONLY the sub-topics, one per line, no numbering, no blank lines"
    )
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Save subtopics debug file
        try:
            _debug_dir = Path("output/debug")
            _debug_dir.mkdir(parents=True, exist_ok=True)
            _ts = int(time.time())
            _slug = re.sub(r"[^a-z0-9]+", "_", niche.lower())[:30]
            (_debug_dir / f"subtopics_{_slug}_{_ts}.txt").write_text(
                f"NICHE: {niche}\nREQUESTED: {n}\n\n--- RAW ---\n{raw}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        lines = [_strip_markdown_and_numbering(l) for l in lines]
        lines = [l for l in lines if 3 < len(l) < 120]
        result = lines[:n]
        logger.info(f"_generate_subtopics for '{niche}': requested {n}, got {len(result)}")
        if len(result) < max(3, n // 3):
            logger.warning(
                f"Very few subtopics returned for '{niche}': {len(result)}/{n}. "
                f"Check output/debug/subtopics_*.txt"
            )
        return result
    except Exception as e:
        logger.warning(f"Sub-topic generation failed for '{niche}': {e}")
        return [f"{niche} facts {i + 1}" for i in range(n)]


def _parse_separator_format(text: str) -> List[str]:
    """
    Parse the strict Q/A/--- format used by _generate_qa_for_subtopic.
    Split on ---, extract Q: and A: from each block.
    Falls back to loose ? heuristic on malformed blocks.
    Returns flat list: ["Q: ...", "A: ...", ...]
    """
    result: List[str] = []
    blocks = re.split(r"\n?-{2,}\n?", text)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        q_text = ""
        a_text = ""
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            if line[:2].upper() == "Q:":
                q_text = line[2:].strip()
            elif line[:2].upper() == "A:":
                a_text = line[2:].strip()
        if q_text and a_text:
            result.append(f"Q: {q_text}")
            result.append(f"A: {a_text}")
            continue
        # Loose fallback: line ending with '?' → next non-empty line
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        for i, line in enumerate(lines[:-1]):
            if line.endswith("?") and 10 < len(line) < 300:
                next_line = lines[i + 1]
                if next_line and not next_line.endswith("?"):
                    result.append(f"Q: {line}")
                    result.append(f"A: {next_line}")
                    break
    return result


def _generate_qa_for_subtopic(
    client,
    niche: str,
    subtopic: str,
    n: int = 10,
    model: str = "claude-sonnet-4-5",
    chunk_idx: int = 0,
) -> List[str]:
    """
    Generate exactly N Q&A pairs for one sub-topic.
    Uses strict separator format so parsing is bulletproof.
    Saves raw response to output/debug/ for every call.
    """
    prompt = (
        f'You are a trivia book author. Write exactly {n} trivia Q&A pairs about:\n'
        f'Niche: "{niche}"\n'
        f'Sub-topic: "{subtopic}"\n\n'
        "Return ONLY this format. No markdown. No numbering. No preamble. No closing remarks.\n"
        "Q: [question text]\n"
        "A: [answer text]\n"
        "---\n"
        "Q: [question text]\n"
        "A: [answer text]\n"
        "---\n"
        f"(repeat for all {n} pairs, ending the last one with ---)\n\n"
        "Rules:\n"
        "- Factually accurate; questions end with a question mark\n"
        "- Answers are 1-2 sentences max\n"
        "- ALL in English"
    )
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Save debug file
        try:
            _debug_dir = Path("output/debug")
            _debug_dir.mkdir(parents=True, exist_ok=True)
            _ts = int(time.time())
            _slug = re.sub(r"[^a-z0-9]+", "_", subtopic.lower())[:30]
            (_debug_dir / f"qa_{_slug}_{chunk_idx}_{_ts}.txt").write_text(
                f"NICHE: {niche}\nSUBTOPIC: {subtopic}\nCHUNK: {chunk_idx}\n\n"
                f"--- RAW RESPONSE ---\n{raw}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

        return _parse_separator_format(raw)
    except Exception as e:
        logger.warning(f"Q&A generation failed for sub-topic '{subtopic}': {e}")
        return []


def _parallel_quiz_generator(
    client,
    niche: str,
    section: Dict,
    n_target: int,
    model: str = "claude-sonnet-4-5",
    status_cb=None,
) -> List[str]:
    """
    Generate quiz Q&A using parallel sub-topic calls.
    1. One Claude call to get N sub-topics.
    2. ThreadPoolExecutor(max_workers=5) — each worker gets 10 Q&A per sub-topic.
    3. Post-generation exact-match dedup (no dedup during generation).
    Returns flat list: ["Q: ...", "A: ...", ...]
    """
    section_title = section.get("title", "Quiz")
    n_subtopics = max(5, (n_target // 10) + 3)

    if status_cb:
        status_cb(f"  · {section_title[:38]} — génération de {n_subtopics} sous-sujets...")

    subtopics = _generate_subtopics(client, niche, n=n_subtopics, model=model)
    if not subtopics:
        if status_cb:
            status_cb(f"  ❌ Impossible de générer les sous-sujets pour '{niche}'")
        return []

    if status_cb:
        status_cb(
            f"  · {section_title[:38]} — {len(subtopics)} sous-sujets, génération parallèle..."
        )

    all_items: List[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                _generate_qa_for_subtopic, client, niche, subtopic, 10, model, idx,
            ): (idx, subtopic)
            for idx, subtopic in enumerate(subtopics)
        }
        for future in concurrent.futures.as_completed(futures):
            idx, subtopic = futures[future]
            try:
                chunk_items = future.result()
                n_pairs = sum(1 for l in chunk_items if l.startswith("Q:"))
                if n_pairs < 3:
                    logger.warning(f"Low yield for sub-topic '{subtopic}': {n_pairs} pairs")
                    if status_cb:
                        status_cb(
                            f"     ⚠️ '{subtopic[:30]}': seulement {n_pairs} paires"
                        )
                else:
                    if status_cb:
                        status_cb(f"     ✅ '{subtopic[:30]}': +{n_pairs} Q&A")
                all_items.extend(chunk_items)
            except Exception as e:
                logger.warning(f"Sub-topic '{subtopic}' future failed: {e}")

    # Post-generation exact-match dedup
    seen_q: set = set()
    deduped: List[str] = []
    i = 0
    while i < len(all_items):
        line = all_items[i]
        if line.startswith("Q:") and i + 1 < len(all_items) and all_items[i + 1].startswith("A:"):
            q_key = line[2:].strip().lower()
            if q_key not in seen_q:
                seen_q.add(q_key)
                deduped.append(line)
                deduped.append(all_items[i + 1])
            i += 2
        else:
            i += 1

    final_pairs = sum(1 for l in deduped if l.startswith("Q:"))
    if status_cb:
        if final_pairs >= n_target * 0.75:
            status_cb(f"  ✅ {section_title[:38]} — {final_pairs}/{n_target} Q&A paires")
        elif final_pairs > 0:
            status_cb(f"  ⚠️ {section_title[:38]} — seulement {final_pairs}/{n_target} paires")
        else:
            status_cb(f"  ❌ {section_title[:38]} — 0 paires ! section sera vide")

    return deduped


# ── Content expander (prompts, Q&A, tracker headers) ─────────────────────────

def expand_content(
    listing: Dict,
    api_key: str,
    status_cb=None,
    learning_dir: Optional[Path] = None,
) -> Dict:
    """
    Generates section content scaled to the section's claimed page count.
    Critical for KDP: a 36-page Q&A section needs ~90 Q&A pairs, not 20.

    Scaling rules:
      - quiz    : 5 questions per page  (10 Q per round × 2 pages = 5 Q/page)
      - journal : 1 prompt per page     (one prompt = one page with writing lines)
      - log     : column headers (count doesn't scale, layout repeats)
    """
    niche        = listing["niche"]
    product_type = listing["product_type"]
    sections     = listing.get("content_sections", [])

    # Puzzle / activity_book books have algorithmic content, not Claude-generated.
    # Skip Claude expansion entirely for these types.
    if product_type in ("puzzle", "activity_book"):
        if status_cb:
            status_cb(f"⏭️ expand_content sauté ({product_type}) — contenu algorithmique")
        return listing

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # Build a "beat-the-competition" hint if we've done a deep sample analysis
    beat_hint = ""
    if learning_dir is not None:
        try:
            from modules.learning.sample_reader import get_sample_insights, sample_insights_for_prompt
            sample = get_sample_insights(learning_dir, niche)
            beat_hint = sample_insights_for_prompt(sample) or ""
        except Exception:
            pass

    if status_cb:
        status_cb(f"🧠 Génération du contenu intérieur pour \"{niche}\"...")
        if beat_hint:
            status_cb(f"🔬 Intel concurrence injecté dans les prompts de contenu")

    for sec in sections:
        sec_type = sec.get("type", "")
        if sec_type not in ("content", "tracker", "qa", "reference"):
            continue

        # Quiz books: tracker sections are notes pages, not Q&A — skip them.
        if product_type == "quiz" and sec_type == "tracker":
            continue

        # Listing generator adds 8-12 sample items to many sections.
        # Force-regenerate sections where those samples are always inadequate:
        #   - quiz "qa" : samples are tiny; need full parallel expansion
        #   - log content/tracker/reference: generic column headers need niche-specific ones
        #   - reference (any type): generic bullet items need niche-specific guide content
        force_regen = (
            (product_type == "quiz" and sec_type == "qa")
            or (product_type == "log" and sec_type in ("content", "tracker"))
            or sec_type == "reference"
        )
        if sec.get("items") and not force_regen:
            continue

        pages = sec.get("pages", 4)

        # ── Reference sections: generate niche-specific guide content ────
        if sec_type == "reference":
            n_target = max(10, pages * 4)
            sec["items"] = _expand_section_chunked(
                client, niche=niche, section=sec, n_target=n_target,
                prompt_builder=lambda n, s, c: _reference_prompt(n, s, n_items=c),
                parser=_parse_simple_lines,
                loose_parser=_parse_simple_lines_loose,
                counter=_count_lines,
                beat_hint=beat_hint, status_cb=status_cb,
                chunk_size=15,
            )
            continue

        # ── UNIVERSAL chunked expansion for content types that scale ─────
        # Splits large generations into chunks of ≤30 items, validates each
        # chunk, dedupes, and ensures Q&A pairs are complete (for quiz).
        if product_type == "quiz":
            n_target = max(20, pages * 5)   # 5 Q per page
            sec["items"] = _parallel_quiz_generator(
                client, niche=niche, section=sec, n_target=n_target,
                status_cb=status_cb,
            )
            continue

        if product_type == "journal":
            n_target = max(40, pages)
            sec["items"] = _expand_section_chunked(
                client, niche=niche, section=sec, n_target=n_target,
                prompt_builder=lambda n, s, c: _journal_prompt(n, s, n_prompts=c),
                parser=_parse_simple_lines,
                loose_parser=_parse_simple_lines_loose,
                counter=_count_lines,
                beat_hint=beat_hint, status_cb=status_cb,
                chunk_size=30,
            )
            continue

        if product_type == "planner":
            n_target = max(30, pages)
            sec["items"] = _expand_section_chunked(
                client, niche=niche, section=sec, n_target=n_target,
                prompt_builder=lambda n, s, c: _planner_prompt(n, s, n_prompts=c),
                parser=_parse_simple_lines,
                loose_parser=_parse_simple_lines_loose,
                counter=_count_lines,
                beat_hint=beat_hint, status_cb=status_cb,
                chunk_size=30,
            )
            continue

        if product_type == "coloring":
            n_target = max(20, pages)
            sec["items"] = _expand_section_chunked(
                client, niche=niche, section=sec, n_target=n_target,
                prompt_builder=lambda n, s, c: _coloring_prompt(n, s, n_titles=c),
                parser=_parse_simple_lines,
                loose_parser=_parse_simple_lines_loose,
                counter=_count_lines,
                beat_hint=beat_hint, status_cb=status_cb,
                chunk_size=25,
            )
            continue

        # log: short structured output (column headers + 10 examples) — single call OK
        if product_type == "log":
            prompt     = _log_prompt(niche, sec)
            max_tokens = 1500
        else:
            n_target   = max(40, pages)
            prompt     = _journal_prompt(niche, sec, n_prompts=n_target)
            max_tokens = min(4000, 400 + n_target * 30)

        # Append the "beat the competition" intel to each section prompt
        if beat_hint:
            prompt = (
                prompt + "\n\n" + beat_hint +
                "\nIMPORTANT: produce content that exceeds the competition — same coverage, "
                "deeper specificity, more original voice. Never reuse competitor wording."
            )

        if status_cb:
            status_cb(f"  · {sec.get('title','section')[:40]} ({pages} pages target)")

        try:
            msg = client.messages.create(
                model="claude-sonnet-4-5",   # Sonnet for non-chunked too (log)
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            lines = [
                l.strip() for l in msg.content[0].text.strip().splitlines()
                if l.strip() and not l.strip().startswith("#")
            ]
            sec["items"] = lines
        except Exception as e:
            logger.warning(f"Content expand error for section '{sec['title']}': {e}")
            sec["items"] = []

    if status_cb:
        status_cb("✅ Contenu intérieur généré")

    return listing


# ── Prompt builders ───────────────────────────────────────────────────────────

def _journal_prompt(niche: str, section: Dict, n_prompts: int = 40) -> str:
    return f"""You are an expert journal designer for the US market.
Generate EXACTLY {n_prompts} unique, powerful writing prompts for a journal about: "{niche}"
Section: {section.get('description', '')}

Rules:
- Each prompt starts with a verb or question word (e.g., "Describe...", "What would...", "Today I...")
- Directly relevant to the "{niche}" theme — be SPECIFIC to the niche
- Emotionally engaging and unique — NO repetition or generic prompts
- 1-2 sentences max per prompt
- ALL in English
- Produce all {n_prompts} prompts — don't stop early

Return ONLY the prompts, one per line, no numbering, no blank lines between them."""


def _log_prompt(niche: str, section: Dict) -> str:
    return f"""You are an expert log book designer for the US market.
Design the column headers and entry fields for a log book about: "{niche}"
Section: {section.get('description', '')}

Generate:
1. First line: comma-separated column headers SPECIFIC to "{niche}" (e.g., for mushroom foraging: "Date, Location, Species, Cap Color, Edible?, Notes")
2. Then 10 example complete log entries (one per line, comma-separated values matching the headers)

The headers MUST be tailored to "{niche}" — not generic. Use field-specific terminology.
ALL in English. Return ONLY the structured data, no preamble."""


def _quiz_prompt(niche: str, section: Dict, n_questions: int = 20) -> str:
    return f"""You are an expert trivia book author for the US market.
Write EXACTLY {n_questions} trivia questions with answers about: "{niche}"
Category: {section.get('description', '')}

Format EXACTLY as (one Q and one A per line):
Q: [question text]
A: [answer text]
Q: [question text]
A: [answer text]
...

Rules:
- Mix of easy (40%), medium (40%), hard (20%)
- Factually accurate — double-check dates, names, facts
- Engaging and surprising — avoid obvious trivia
- Vary topics within the category: don't ask 5 questions about the same person/event
- Keep questions to 1 sentence, answers to 1-2 sentences MAX
- ALL in English
- Produce all {n_questions} Q&A pairs — DO NOT stop early or repeat

Return ONLY the Q&A pairs in the format above."""


def _planner_prompt(niche: str, section: Dict, n_prompts: int = 30) -> str:
    return f"""You are an expert planner designer for the US market.
Generate EXACTLY {n_prompts} unique daily gratitude / intention prompts
for a planner themed around: "{niche}"
Section: {section.get('description', '')}

Rules:
- Each prompt is short (under 12 words), action-oriented, and specific
- Start with phrases like "Today I'm grateful for...", "One thing I want to manifest...", "My intention is..."
- Tie each prompt back to the "{niche}" theme when possible
- ALL in English

Return ONLY the prompts, one per line, no numbering."""


def _reference_prompt(niche: str, section: Dict, n_items: int = 15) -> str:
    return f"""You are an expert non-fiction book designer for the US market.
Write exactly {n_items} specific, useful reference items for the section "{section.get('title','Reference')}"
in a book about: "{niche}"
Section purpose: {section.get('description', 'Quick reference guide')}

Rules:
- Each item is a self-contained fact, tip, conversion, or guideline SPECIFIC to "{niche}"
- No generic advice — every item must be directly applicable to this niche
- 1-2 sentences per item, clear and actionable
- ALL in English
- No numbering, one item per line, no blank lines

Return ONLY the items, one per line."""


def _coloring_prompt(niche: str, section: Dict, n_titles: int = 20) -> str:
    return f"""You are an expert coloring book illustrator for the US market.
Generate EXACTLY {n_titles} unique illustration titles/themes
for a coloring book about: "{niche}"
Section: {section.get('description', '')}

Rules:
- Each title is 3-7 words, evocative and visual
- Directly tied to "{niche}" — be specific (e.g., for "botanical": "Wildflower Meadow at Dawn", "Tangled Rose Garden")
- Vary subject, mood, and complexity
- ALL in English

Return ONLY the titles, one per line, no numbering."""
