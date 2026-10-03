"""
High-content generation engine — recipes & guides with WEB-GROUNDED facts.

How the web verification works (user requirement — "recherche web pour chaque
recette"): every generation call enables the Claude server-side `web_search`
tool. The prompt instructs the model to VERIFY key facts (cooking temperatures,
times, ratios, safety-relevant numbers) against real sources found via search,
while writing 100% ORIGINAL text (copying web content is forbidden — copyright).

Model: claude-sonnet-4-6 (cost-conscious project default; supports the
web_search_20260209 server tool). Batched calls keep cost/latency sane.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

_WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 4,
}


# ── Type detection ───────────────────────────────────────────────────────────
_RECIPE_MARKERS = ("recipe", "recipes", "cookbook", "meals", "dinners",
                   "smoothie", "soup recipes", "dessert", "cooking for")
_GUIDE_MARKERS = ("guide", "how to", "how-to", "for beginners", "step by step",
                  "beginner", "basics", "techniques", "patterns")


def detect_highcontent_type(niche: str) -> Optional[str]:
    """
    Returns "recipe_book", "how_to", or None (not a high-content niche).
    Only fires when autopilot's is_high_content_niche() agrees — we never
    hijack a template-book niche.
    """
    try:
        from modules.research.autopilot import is_high_content_niche
        if not is_high_content_niche(niche):
            return None
    except Exception:
        return None
    nl = (niche or "").lower()
    if any(m in nl for m in _RECIPE_MARKERS):
        return "recipe_book"
    if any(m in nl for m in _GUIDE_MARKERS):
        return "how_to"
    # High-content but neither → default to guide (facts books read as guides)
    return "how_to"


# ── Shared plumbing ──────────────────────────────────────────────────────────
def _repair_truncated_array(s: str):
    """A truncated JSON array (max_tokens hit) → keep whole objects only.
    Cuts at the last complete '}' and closes the array."""
    if not s or s[0] != "[":
        return None
    last = s.rfind("}")
    if last == -1:
        return None
    return s[:last + 1] + "]"


def _extract_json(text: str):
    """Robust JSON array/object extraction from a (possibly web-grounded,
    possibly truncated) model response. web_search interleaves narration text
    before the JSON, and long outputs get cut off — handle both."""
    raw = (text or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    # 1. direct parse
    try:
        return json.loads(raw)
    except Exception:
        pass
    # 2. outermost array, then outermost object — with truncation repair
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start = raw.find(open_c)
        end = raw.rfind(close_c)
        if start == -1:
            continue
        candidate = raw[start:end + 1] if end > start else raw[start:]
        try:
            return json.loads(candidate)
        except Exception:
            repaired = _repair_truncated_array(candidate)
            if repaired:
                try:
                    return json.loads(repaired)
                except Exception:
                    pass
    raise ValueError("No JSON found in model response")


def _call_grounded(client, prompt: str, max_tokens: int = 12000) -> str:
    """
    One generation call WITH web search enabled. Returns the final text.

    Uses STREAMING — required by the Anthropic SDK for long operations
    (web_search + large output can exceed the 10-min non-streaming limit and
    raise "Request timed out or interrupted"). Handles pause_turn (server tool
    loop) by resuming, and joins ALL text blocks (web_search interleaves text
    blocks in the response).
    """
    messages = [{"role": "user", "content": prompt}]
    for _hop in range(4):  # pause_turn resume guard
        with client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            tools=[_WEB_SEARCH_TOOL],
            messages=messages,
        ) as stream:
            final = stream.get_final_message()
        if getattr(final, "stop_reason", None) == "pause_turn":
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": final.content},
            ]
            continue
        parts = [b.text for b in final.content if getattr(b, "type", "") == "text"]
        return "\n".join(parts)
    return ""


def _verified_facts(niche: str, client, kind: str = "recipe",
                    status_cb: Optional[Callable[[str], None]] = None) -> str:
    """
    ONE web-grounded call that establishes the safety-critical VERIFIED facts for
    the whole book (internal temps, cook times, ratios, condition guidance).

    Why: these facts are IDENTICAL across every recipe/chapter, so re-running
    web_search on all 75 recipes re-injects huge web results into context ~15×
    (the real cost driver — measured ~27$/book). Verifying ONCE and reusing the
    facts is quality-neutral (same numbers everywhere, more consistent even) and
    cuts web-search token cost ~10-15×. Facts stay web-verified — the user's
    fact-checking requirement is preserved, just done once instead of redundantly.
    """
    def s(m):
        if status_cb: status_cb(m)
    s("🔎 Vérification web des faits-clés (une seule fois pour tout le livre)...")
    topic = {"recipe": "cooking temperatures/times, safe internal temps, key ratios, "
                        "and typical per-serving nutrition ranges",
             "guide": "quantities, timings, measurements, safety notes, tool/product specifics",
             "facts": "the accuracy of the facts to be written"}.get(kind, "key facts")
    prompt = f"""Using the web_search tool, establish the KEY VERIFIED FACTS a writer must
get right for a {kind} book on the niche: "{niche}".

Focus on: {topic}.

Return a COMPACT plain-text reference sheet (max ~350 words) of the verified numbers
and rules, each with a short source note. This sheet will be reused for the whole book,
so include everything safety-critical. Do NOT copy prose from sources — facts only."""
    try:
        facts = _call_grounded(client, prompt, max_tokens=2000).strip()
        if facts:
            s("✅ Faits vérifiés établis — réutilisés pour tout le livre (0 recherche répétée)")
            return facts
    except Exception as e:
        logger.warning(f"verified-facts call failed: {e}")
    return ""


def _call_cached(client, system_text: str, user_text: str, max_tokens: int = 12000) -> str:
    """
    Plain (non-grounded) generation with PROMPT CACHING on the large stable system
    block (schema + rules + verified facts). The system prefix is written once then
    read at ~0.1× on every later batch — big input-token saving with zero quality
    impact. Streaming to avoid HTTP timeouts on large outputs.
    """
    with client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_text,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        final = stream.get_final_message()
    parts = [b.text for b in final.content if getattr(b, "type", "") == "text"]
    return "\n".join(parts)


# Niche → the nutrient the BUYER cares about most (the whole promise of the
# niche). Drives a highlighted "key nutrient" line on every recipe.
_KEY_NUTRIENT_MAP = {
    "osteoporosis": "Calcium (mg)", "high calcium": "Calcium (mg)",
    "high protein": "Protein (g)", "protein": "Protein (g)",
    "low sodium": "Sodium (mg)", "heart health": "Sodium (mg)",
    "low cholesterol": "Cholesterol (mg)", "diabetic": "Carbs (g)",
    "diabetes": "Carbs (g)", "keto": "Net carbs (g)",
    "low carb": "Net carbs (g)", "renal": "Potassium (mg)",
    "kidney": "Potassium (mg)", "low potassium": "Potassium (mg)",
    "high fiber": "Fiber (g)", "anti inflammatory": "Antioxidants",
    "weight loss": "Calories", "low calorie": "Calories",
    "gout": "Purines", "anemia": "Iron (mg)",
    "thyroid": "Selenium (mcg)", "pcos": "Carbs (g)",
    "bariatric": "Protein (g)", "gluten free": "Gluten",
    "celiac": "Gluten", "low fodmap": "FODMAP",
}


def _niche_key_nutrient(niche: str) -> str:
    n = (niche or "").lower()
    for k, v in _KEY_NUTRIENT_MAP.items():
        if k in n:
            return v
    return "Calories"


# ── RECIPES ──────────────────────────────────────────────────────────────────
_RECIPE_SCHEMA_HINT = """[
  {
    "title": "...",
    "category": "Breakfast|Lunch|Dinner|Snack|Dessert|Side",
    "intro": "1-2 appetizing sentences",
    "servings": 2,
    "prep_time": "10 min",
    "cook_time": "18 min",
    "difficulty": "Easy",
    "ingredients": ["2 lbs chicken wings", "1 tbsp olive oil", "..."],
    "steps": ["Pat the wings dry...", "..."],
    "nutrition": {
      "calories": 320, "protein_g": 28, "carbs_g": 12, "fat_g": 18,
      "key_nutrient_label": "Calcium", "key_nutrient_value": "410 mg"
    },
    "tip": "one practical pro tip",
    "verified_facts": "temps/times checked: 380F 22min per <source topic>"
  }
]"""


def generate_recipes(
    niche: str,
    n: int,
    anthropic_key: str,
    status_cb: Optional[Callable[[str], None]] = None,
    batch_size: int = 5,
) -> List[Dict]:
    """
    Generate n web-grounded, 100% original recipes for the niche.
    Batched (batch_size per call, small enough to fit max_tokens with nutrition).
    Dedup by title. Each batch retried up to 2x. Cost ≈ $0.03-0.05/batch.
    """
    def s(m):
        if status_cb: status_cb(m)

    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=600.0)

    key_nutrient = _niche_key_nutrient(niche)
    # COST FIX: verify the safety facts ONCE (web), then generate every batch with
    # PLAIN cached calls injecting those facts — no per-batch web_search.
    facts = _verified_facts(niche, client, "recipe", status_cb=s)
    facts_block = (f"\n\nVERIFIED REFERENCE FACTS (already web-checked — rely on these, "
                   f"do NOT invent numbers that contradict them):\n{facts}\n" if facts else "")

    # Large STABLE system block (cached across all batches at ~0.1× read cost).
    system_text = f"""You are an expert cookbook author writing for the niche: "{niche}".

Write reliable, appetizing, 100% ORIGINAL recipes (never copy text from anywhere).
{facts_block}
NUTRITION (buyer's #1 expectation): fill "nutrition" per serving with realistic
calories, protein_g, carbs_g, fat_g, consistent with the verified reference facts.
The niche's KEY nutrient is **{key_nutrient}** — set "key_nutrient_label" and
"key_nutrient_value" accordingly (e.g. "Calcium" / "410 mg"). Favor recipes that
genuinely score well on this nutrient. Put a one-line note in "verified_facts".

QUALITY RULES:
- Match the niche exactly (audience, constraint, equipment).
- Set "category" (Breakfast/Lunch/Dinner/Snack/Dessert/Side) — spread across meals.
- Simple, reliable, beginner-appropriate recipes. Common ingredients.
- US units (cups, tbsp, °F). Steps: 4-8 clear imperative sentences.
- Titles: appetizing, specific, ≤ 60 chars.

Return ONLY a strict JSON array following this schema (no markdown fences):
{_RECIPE_SCHEMA_HINT}"""

    out: List[Dict] = []
    seen_titles = set()
    batch_num = 0
    while len(out) < n and batch_num < (n // batch_size) + 4:
        batch_num += 1
        want = min(batch_size, n - len(out))
        avoid = ", ".join(list(seen_titles)[-30:]) or "none yet"
        s(f"🍳 Recettes {len(out)}/{n} — batch {batch_num} ({want} recettes)...")
        user_text = (f"Write exactly {want} NEW recipes now. Already written "
                     f"(do NOT repeat or make near-duplicates): {avoid}. "
                     f"Return ONLY the strict JSON array.")
        added = 0
        for attempt in range(2):   # retry a failed/empty batch once
            try:
                text = _call_cached(client, system_text, user_text, max_tokens=12000)
                data = _extract_json(text)
                for r in data:
                    t = str(r.get("title", "")).strip()
                    key = t.lower()
                    if not t or key in seen_titles:
                        continue
                    if not r.get("ingredients") or not r.get("steps"):
                        continue
                    seen_titles.add(key)
                    r["kind"] = "recipe"
                    out.append(r)
                    added += 1
                if added:
                    break
                s(f"⚠️ Batch {batch_num} vide (essai {attempt+1}/2) — on réessaie")
            except Exception as e:
                logger.warning(f"recipe batch {batch_num} attempt {attempt+1} failed: {e}")
                s(f"⚠️ Batch {batch_num} échoué (essai {attempt+1}/2) : {str(e)[:70]}")
        s(f"✅ Batch {batch_num}: +{added} recettes (total {len(out)}/{n})")
    return out[:n]


# ── BONUS front/back matter for recipe books ─────────────────────────────────
# The single biggest value lift: best-selling condition cookbooks open with a
# short "understanding <niche>" intro + a ready-to-use 7-day meal plan + a
# categorized shopping list. Cheap to generate, hugely raises perceived value.
def generate_bonus(niche: str, recipes: List[Dict], anthropic_key: str,
                   status_cb: Optional[Callable[[str], None]] = None) -> Dict:
    def s(m):
        if status_cb: status_cb(m)
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=600.0)

    key_nutrient = _niche_key_nutrient(niche)
    titles = [str(r.get("title", "")) for r in (recipes or [])][:40]
    s("🎁 Sections bonus (intro + plan 7 jours + liste de courses)...")
    prompt = f"""You are the author of a practical cookbook for the niche: "{niche}".
The book contains these recipes (use ONLY these titles in the meal plan):
{json.dumps(titles, ensure_ascii=False)}

Produce helpful BONUS front-matter. Write accurate, 100% original text (never copy).

Return ONLY strict JSON (no fences) with this schema:
{{
  "intro_title": "Understanding {niche} — a Quick Start",
  "intro_paragraphs": ["2-4 short, reassuring, factual paragraphs about the diet/
     approach, why the key nutrient ({key_nutrient}) matters, and how to use this book"],
  "eat_more": ["6-10 foods to favor for this niche"],
  "eat_less": ["5-8 foods to limit/avoid for this niche"],
  "meal_plan": [
     {{"day": "Day 1", "breakfast": "<a recipe title>", "lunch": "<title>", "dinner": "<title>", "snack": "<title or simple idea>"}}
     /* exactly 7 days, reuse the recipe titles above */
  ],
  "shopping_list": [
     {{"category": "Produce", "items": ["...", "..."]}},
     {{"category": "Protein", "items": ["..."]}},
     {{"category": "Pantry", "items": ["..."]}},
     {{"category": "Dairy & Alternatives", "items": ["..."]}}
  ],
  "verified_facts": "one line on what was checked"
}}"""
    try:
        with client.messages.stream(model=MODEL, max_tokens=4000,
                                    messages=[{"role": "user", "content": prompt}]) as st:
            final = st.get_final_message()
        text = "\n".join(b.text for b in final.content if getattr(b, "type", "") == "text")
        data = _extract_json(text)
        if isinstance(data, dict):
            s("✅ Sections bonus générées")
            return data
    except Exception as e:
        logger.warning(f"bonus generation failed: {e}")
        s(f"⚠️ Sections bonus échouées : {str(e)[:80]}")
    return {}


# ── FACTS books (kids / trivia-style written content) ────────────────────────
_FACTS_MARKERS = ("facts for", "facts about", "fun facts", "amazing facts",
                  "did you know", "trivia facts")


def is_facts_niche(niche: str) -> bool:
    return any(m in (niche or "").lower() for m in _FACTS_MARKERS)


def generate_facts(niche: str, anthropic_key: str, n_sections: int = 12,
                   status_cb: Optional[Callable[[str], None]] = None) -> Dict:
    """
    A facts book = themed groups of short, punchy, VERIFIED fun facts — the
    right format for "fun facts for curious kids" (guide chapters read wrong here).
    Returns {"sections": [{"title": "...", "facts": ["...", ...]}]}.
    """
    def s(m):
        if status_cb: status_cb(m)
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=600.0)

    sections: List[Dict] = []
    # Ask for themes first so sections are coherent and non-overlapping.
    s(f"🧠 Thèmes du livre de faits ({n_sections} sections)...")
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1200,
            messages=[{"role": "user", "content":
                f'List exactly {n_sections} distinct, kid-friendly THEMES for a book '
                f'titled around "{niche}". Return ONLY a JSON array of short theme '
                f'strings, no fences.'}],
        )
        themes = _extract_json(next(b.text for b in resp.content if b.type == "text"))
        themes = [str(t)[:70] for t in themes][:n_sections]
    except Exception as e:
        logger.warning(f"facts themes failed: {e}")
        return {"sections": []}

    # COST FIX: verify facts ONCE (web), then write sections with plain cached calls.
    facts = _verified_facts(niche, client, "facts", status_cb=s)
    facts_block = (f"\nVERIFIED REFERENCE FACTS (already web-checked — stay consistent "
                   f"with these, do not contradict them):\n{facts}\n" if facts else "")
    system_text = f"""You write a FUN FACTS book for the niche "{niche}".
{facts_block}
Every fact must be TRUE and accurate. Write 100% ORIGINAL, kid-friendly wording —
never copy phrasing from anywhere. Per section: 8-12 short punchy facts (1-2 sentences
each), surprising, memorable, age-appropriate.

Return ONLY strict JSON (no fences):
[{{"title": "<theme>", "facts": ["fact one", "fact two", "..."]}}]"""

    B = 3
    for i in range(0, len(themes), B):
        batch = themes[i:i + B]
        s(f"🧠 Faits {i+1}-{i+len(batch)}/{len(themes)}...")
        user_text = f"Write the sections for these themes now: {json.dumps(batch)}"
        try:
            text = _call_cached(client, system_text, user_text, max_tokens=6000)
            data = _extract_json(text)
            for sec in data:
                if sec.get("title") and sec.get("facts"):
                    sections.append(sec)
        except Exception as e:
            logger.warning(f"facts batch failed: {e}")
            s(f"⚠️ Batch faits échoué : {str(e)[:80]} — on continue")

    s(f"✅ Livre de faits : {len(sections)}/{len(themes)} sections générées")
    return {"sections": sections}


# ── ANECDOTES / SHORT TRUE STORIES (adult, captivating) ──────────────────────
_ANECDOTES_MARKERS = (
    "anecdotes", "true stories", "short stories", "fascinating", "mind blowing",
    "strange but true", "unbelievable", "little known", "interesting facts for adults",
    "history stories", "tales", "did you know for adults",
)


def is_anecdotes_niche(niche: str) -> bool:
    """Adult short-story / anecdote collections (NOT kids facts, which win first)."""
    nl = (niche or "").lower()
    if is_facts_niche(niche):
        return False
    return any(m in nl for m in _ANECDOTES_MARKERS)


def generate_anecdotes(niche: str, anthropic_key: str, n_sections: int = 10,
                       status_cb: Optional[Callable[[str], None]] = None) -> Dict:
    """A collection of short, CAPTIVATING, TRUE anecdotes/stories for ADULTS,
    grouped by theme. Web-verified once (cost fix), adult narrative tone.
    Returns {"sections": [{"title", "anecdotes": [{"title", "story"}]}]}."""
    def s(m):
        if status_cb: status_cb(m)
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=600.0)

    s(f"🧠 Thèmes du recueil d'anecdotes ({n_sections} sections)...")
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1200,
            messages=[{"role": "user", "content":
                f'List exactly {n_sections} distinct, intriguing THEMES for an ADULT '
                f'book of short TRUE anecdotes titled around "{niche}" (e.g. eras, '
                f'fields, categories of surprising stories). Return ONLY a JSON array '
                f'of short theme strings, no fences.'}],
        )
        themes = _extract_json(next(b.text for b in resp.content if b.type == "text"))
        themes = [str(t)[:70] for t in themes][:n_sections]
    except Exception as e:
        logger.warning(f"anecdote themes failed: {e}")
        return {"sections": []}

    facts = _verified_facts(niche, client, "anecdotes", status_cb=s)
    ref = (f"\nVERIFIED REFERENCE FACTS (web-checked — stay consistent, do not "
           f"contradict):\n{facts}\n" if facts else "")
    system_text = f"""You write an ADULT book of short, CAPTIVATING, TRUE anecdotes for
the niche "{niche}".{ref}
Each anecdote MUST be TRUE and accurate (real events, people, discoveries). Write in a
100% ORIGINAL, vivid, engaging narrative voice for grown-ups — never copy phrasing.
Per section: 5-8 anecdotes, each a short punchy story of 3-5 sentences with a hook and
a satisfying twist or takeaway. Give each anecdote a short intriguing TITLE.

Return ONLY strict JSON (no fences):
[{{"title": "<theme>", "anecdotes": [{{"title": "<hook title>", "story": "<3-5 sentence true story>"}}]}}]"""

    sections: List[Dict] = []
    B = 3
    for i in range(0, len(themes), B):
        batch = themes[i:i + B]
        s(f"🧠 Anecdotes {i+1}-{i+len(batch)}/{len(themes)}...")
        user_text = f"Write the sections for these themes now: {json.dumps(batch)}"
        try:
            text = _call_cached(client, system_text, user_text, max_tokens=7000)
            for sec in (_extract_json(text) or []):
                if sec.get("title") and sec.get("anecdotes"):
                    sections.append(sec)
        except Exception as e:
            logger.warning(f"anecdotes batch failed: {e}")
            s(f"⚠️ Batch anecdotes échoué : {str(e)[:80]} — on continue")

    s(f"✅ Recueil d'anecdotes : {len(sections)}/{len(themes)} sections générées")
    return {"sections": sections}


# ── GUIDES (how-to) ──────────────────────────────────────────────────────────
def generate_guide(
    niche: str,
    anthropic_key: str,
    n_chapters: int = 14,
    status_cb: Optional[Callable[[str], None]] = None,
) -> Dict:
    """
    Generate a complete beginner guide: outline first, then chapters in
    batches of 3-4, each web-grounded. Returns {"outline": [...], "chapters": [...]}
    """
    def s(m):
        if status_cb: status_cb(m)

    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=600.0)

    # 1. Outline
    s(f"📖 Plan du guide ({n_chapters} chapitres)...")
    outline_prompt = f"""You are an expert author planning a practical BEGINNER guide book
for the niche: "{niche}".

Design a logical progression of exactly {n_chapters} chapters — from absolute
basics to a confident first success. Each chapter must be practical and
actionable (not filler).

Return ONLY a strict JSON array of chapter titles (strings), no fences."""
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1500,
            messages=[{"role": "user", "content": outline_prompt}],
        )
        outline = _extract_json(next(b.text for b in resp.content if b.type == "text"))
        outline = [str(t)[:90] for t in outline][:n_chapters]
    except Exception as e:
        logger.warning(f"outline failed: {e}")
        return {"outline": [], "chapters": []}

    # COST FIX: verify facts ONCE (web), then write chapters with plain cached calls.
    facts = _verified_facts(niche, client, "guide", status_cb=s)
    facts_block = (f"\nVERIFIED REFERENCE FACTS (already web-checked — rely on these, "
                   f"do not contradict them):\n{facts}\n" if facts else "")
    system_text = f"""You write chapters for a practical BEGINNER guide on "{niche}".
Full outline for context: {json.dumps(outline)}
{facts_block}
Write 100% ORIGINAL content — never copy text from anywhere. Per chapter: an engaging
intro (2-4 sentences), 3-6 sections with practical detail, concrete steps where relevant,
and one "Pro tip". Beginner-friendly, concrete, zero fluff. 450-700 words per chapter.

Return ONLY a strict JSON array (no fences):
[
 {{"title": "...", "intro": "...",
   "sections": [{{"heading": "...", "body": "...", "steps": ["...", "..."]}}],
   "tip": "...", "verified_facts": "one line on what was checked"}}
]
"steps" is optional per section (omit or empty when not step-based)."""

    # 2. Chapters in batches (plain cached calls)
    chapters: List[Dict] = []
    B = 3
    for i in range(0, len(outline), B):
        batch = outline[i:i + B]
        s(f"📖 Chapitres {i+1}-{i+len(batch)}/{len(outline)}...")
        user_text = f"Write FULL content for these chapters now: {json.dumps(batch)}"
        try:
            text = _call_cached(client, system_text, user_text, max_tokens=9000)
            data = _extract_json(text)
            for c in data:
                if c.get("title") and c.get("sections"):
                    c["kind"] = "chapter"
                    chapters.append(c)
        except Exception as e:
            logger.warning(f"chapter batch failed: {e}")
            s(f"⚠️ Batch chapitres échoué : {str(e)[:80]} — on continue")

    s(f"✅ Guide : {len(chapters)}/{len(outline)} chapitres générés")
    return {"outline": outline, "chapters": chapters}


# ── EXPLANATORY DIAGRAMS (code-drawn infographics + optional AI illustration) ──
_DIAGRAM_SCHEMA = """Return ONLY a strict JSON array (no fences) of 4 to 6 diagram
specs that VISUALLY EXPLAIN the most important, hardest-to-grasp concepts of this
book — the ideas or phenomena a beginner struggles to picture from text alone.

Pick the best type for each concept:
- "cycle"      : a repeating loop of steps.        → "nodes": [ordered steps]
- "process"    : a linear sequence of steps.       → "nodes": [ordered steps]
- "comparison" : 2-3 options contrasted.           → "items": [{"label","points":[...]}]
- "pyramid"    : a hierarchy, FOUNDATION first → PEAK last. → "nodes": [tiers]
- "timeline"   : milestones over time.             → "nodes": [milestones]
- "illustration": a purely VISUAL phenomenon best shown as a drawing with NO text
                  labels (e.g. how something looks/flows). → "image_prompt": "a clean,
                  simple labelled-free instructional illustration of ..." (NO words in image)

Each spec object:
{"type", "title" (<=8 words), "caption" (one short sentence, optional),
 then EITHER "nodes":[...] OR "items":[...] OR "image_prompt":"...",
 "chapter": <1-based chapter number this best fits>}

Rules: node labels <=9 words; comparison points <=7 words. Accurate and genuinely
useful — NO filler. At most ONE "illustration" spec (the rest code-drawable).
Spread diagrams across different chapters. JSON array only."""


def generate_diagrams(niche: str, section_titles: List[str], anthropic_key: str,
                      kind: str = "guide",
                      status_cb: Optional[Callable[[str], None]] = None) -> List[Dict]:
    """Ask Claude for 4-6 explanatory diagram specs (plain + prompt caching, no
    web search). Returns a cleaned list of specs, each tagged with a 'chapter'
    index. Cheap: a single small text call."""
    def s(m):
        if status_cb: status_cb(m)

    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key, timeout=300.0)
    outline = "\n".join(f"{i}. {t}" for i, t in enumerate(section_titles, 1))
    system_text = (f"You are an expert instructional designer for a {kind} about "
                   f"\"{niche}\".\n{_DIAGRAM_SCHEMA}")
    user_text = f"Book sections:\n{outline}\n\nCreate the diagram specs now."
    s("📊 Schémas explicatifs (structure)...")
    try:
        text = _call_cached(client, system_text, user_text, max_tokens=3500)
        raw = _extract_json(text) or []
    except Exception as e:
        logger.warning(f"diagram generation failed: {e}")
        return []

    n_sec = len(section_titles)
    clean: List[Dict] = []
    for spec in raw:
        if not isinstance(spec, dict):
            continue
        t = str(spec.get("type", "")).lower().strip()
        has_body = bool(spec.get("nodes") or spec.get("items") or spec.get("image_prompt"))
        if not t or not spec.get("title") or not has_body:
            continue
        # clamp chapter into range
        try:
            ch = int(spec.get("chapter", 0))
        except Exception:
            ch = 0
        spec["chapter"] = min(max(ch, 1), n_sec) if n_sec else 1
        clean.append(spec)
    s(f"✅ {len(clean)} schéma(s) proposé(s)")
    return clean
