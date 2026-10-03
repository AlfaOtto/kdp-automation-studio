"""
Niche Design Brief — adaptive interior layout spec
====================================================
For ANY niche, Claude analyzes it and returns a JSON spec that drives the
interior PDF rendering. This replaces hard-coded keyword→preset mapping with
an AI that genuinely understands the niche.

Output schema (stored as listing._design_brief):
{
  "tone": "calm" | "professional" | "playful" | "clinical" | "spiritual" | "rugged" | "scholarly",
  "daily_layouts": ["wellness", "a", "b", "focus"],   # ordered cycle pool
  "tracker_fields": [
    {"label": "Hive #",         "input": "line"},
    {"label": "Queen sighted",  "input": "checkbox"},
    {"label": "Brood pattern",  "input": "stars"},
    {"label": "Honey weight",   "input": "line"}
  ],
  "reflection_prompts": ["20+ niche-specific prompts..."],
  "weekly_review_blocks": ["WINS", "PATTERNS", "ADJUSTMENTS", "NEXT WEEK"]
}

The 9 generic + niche layouts in pdf_interior become NICHE-AWARE by consuming
this spec — the tracker_fields render the daily tracker table, the prompts
populate every reflection box, the layout pool defines rotation.
"""
import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


_VALID_LAYOUTS = {"a", "b", "c", "d", "wellness", "focus"}
_VALID_INPUTS  = {
    "line",          # ___________________
    "lines3",        # 3 narrow lines
    "checkbox",      # single ☐
    "multi_choice",  # ☐ optA  ☐ optB  ☐ optC  (uses "options" field)
    "stars",         # ★★★★★ rating
    "scale10",       # 1 2 3 4 5 6 7 8 9 10
    "circles5",      # ○ ○ ○ ○ ○ rating
    "bars5",         # █ █ █ ░ ░ energy bars
    "ampm",          # ___:___  ☐ AM ☐ PM
    "table3",        # 3-cell mini-table
    "yes_no",        # ☐ Yes  ☐ No
    "compass",       # N / NE / E / SE / S / SW / W / NW
}
_VALID_TONES   = {"calm", "professional", "playful", "clinical",
                  "spiritual", "rugged", "scholarly", "warm", "minimal"}


def generate_design_brief(niche: str, product_type: str,
                          anthropic_key: str,
                          status_cb=None) -> Optional[Dict]:
    """
    Ask Claude to design a niche-specific interior spec.
    Returns a sanitized dict or None on failure (caller falls back to defaults).
    """
    if not anthropic_key or not niche:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    prompt = f"""You are a top KDP interior designer with 15 years of experience.
Design the perfect daily interior page for this {product_type} book.

NICHE: "{niche}"

Return STRICT JSON. NO markdown fences. Schema:

{{
  "tone": "calm | professional | playful | clinical | spiritual | rugged | scholarly | warm | minimal",
  "daily_layouts": [pick 3-5 from "a", "b", "c", "d", "wellness", "focus"],
  "tracker_fields": [
    {{"label": "...", "input": "<see input types below>", "options": ["...","..."]}},
    ...4-7 fields total...
  ],
  // INPUT TYPES (PREFER checkbox-style — low-content buyers want to TAP not WRITE):
  //   "multi_choice" + "options"=[3-6 short choices]  ← USE THIS A LOT, default for any categorical field
  //   "checkbox"      single Yes/checkmark
  //   "yes_no"        ☐ Yes  ☐ No
  //   "stars" | "circles5" | "bars5"   ratings
  //   "scale10"       1-10 scale
  //   "compass"       N/E/S/W direction
  //   "ampm"          time + AM/PM box
  //   "line"          ONLY when free-form text is truly needed
  //   "lines3"        3 lines for short paragraph
  "reflection_prompts": [...20 niche-specific prompts, each 6-14 words, ending in '?'...],
  "weekly_review_blocks": [4 SHORT-CAP headers e.g. "WINS", "PATTERNS", "ADJUSTMENTS", "NEXT WEEK"]
}}

LAYOUT GUIDE (pick the right mix for this niche):
- "a"         classic priorities + 2-col time blocks (general daily planner)
- "b"         single big focus + brain dump (deep work / ADHD)
- "c"         morning/afternoon/evening sections (balanced day)
- "d"         habit grid + gratitude trio (visual habit tracking)
- "wellness"  mood scale + body scan + grounding (mental health / medical)
- "focus"     energy bars + 1 priority + 4 pomodoros (productivity / focused work)

TRACKER FIELDS GUIDE — these become the page's data-entry FORM.
GOLDEN RULE: low-content books sell because users can TAP a checkbox, not because they
write paragraphs. PREFER `multi_choice` / `checkbox` / `stars` / `scale10` / `compass` /
`yes_no` over `line` (free text). Use `line` ONLY when a number or single word is truly needed.

EXAMPLES of PRO low-content tracker fields:

- UFO Sighting Log:
  [{{"label":"Object shape","input":"multi_choice","options":["Disc","Triangle","Sphere","Cigar","Cluster","Other"]}},
   {{"label":"Number of objects","input":"multi_choice","options":["1","2-3","4-9","10+"]}},
   {{"label":"Direction of movement","input":"compass"}},
   {{"label":"Weather","input":"multi_choice","options":["Clear","Cloudy","Foggy","Rainy","Stormy"]}},
   {{"label":"Witnesses","input":"multi_choice","options":["Alone","1","2-4","5+"]}},
   {{"label":"Time","input":"ampm"}},
   {{"label":"Sound heard","input":"yes_no"}}]

- Fishing log:
  [{{"label":"Bait used","input":"multi_choice","options":["Worm","Lure","Fly","Live bait","Other"]}},
   {{"label":"Weather","input":"multi_choice","options":["Sunny","Cloudy","Rainy","Windy"]}},
   {{"label":"Water condition","input":"multi_choice","options":["Calm","Choppy","Murky","Clear"]}},
   {{"label":"Catch count","input":"line"}},
   {{"label":"Biggest fish (lb)","input":"line"}},
   {{"label":"Released","input":"yes_no"}}]

- Beekeeper hive inspection:
  [{{"label":"Hive #","input":"line"}},
   {{"label":"Queen sighted","input":"yes_no"}},
   {{"label":"Brood pattern","input":"stars"}},
   {{"label":"Temperament","input":"multi_choice","options":["Calm","Active","Defensive","Hot"]}},
   {{"label":"Honey stores","input":"multi_choice","options":["Plenty","Adequate","Low","Critical"]}},
   {{"label":"Pests seen","input":"multi_choice","options":["None","Varroa","Hive beetle","Wax moth","Other"]}}]

- Anxiety journal:
  [{{"label":"Anxiety today","input":"scale10"}},
   {{"label":"Main trigger","input":"multi_choice","options":["Work","People","Health","Money","Family","Other"]}},
   {{"label":"Coping used","input":"multi_choice","options":["Breathing","Walk","Talk to someone","Music","Journaled","Other"]}},
   {{"label":"Sleep hours","input":"line"}},
   {{"label":"Mood evening","input":"circles5"}}]

INVENT 5-7 tracker fields that PERFECTLY match the niche. Default to `multi_choice` /
`checkbox` / `stars` / `yes_no` whenever a value can be categorized. Reserve `line` for
free numbers or proper names.

REFLECTION PROMPTS GUIDE (20 niche-specific, varied angles):
- For a sobriety journal: "What triggered a craving today and how did I respond?",
  "Who am I becoming as I stay sober?", etc.
- For a fitness journal: "Which exercise felt strongest today?",
  "What did my body ask for that I ignored?", etc.

ENGLISH only. Return ONLY the JSON object."""

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        if status_cb:
            status_cb(f"🎨 Design brief Claude pour \"{niche}\"...")
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        clean = _sanitize_brief(data)
        if status_cb and clean:
            n_fields = len(clean.get("tracker_fields", []))
            n_prompts = len(clean.get("reflection_prompts", []))
            layouts = "/".join(clean.get("daily_layouts", []))
            status_cb(
                f"✅ Design brief : tone={clean.get('tone','?')} · "
                f"{n_fields} champs niche · {n_prompts} prompts · layouts=[{layouts}]"
            )
        return clean
    except Exception as e:
        logger.warning(f"Design brief failed for '{niche}': {e}")
        if status_cb:
            status_cb(f"⚠️ Design brief sauté : {e}")
        return None


def _sanitize_brief(d: Dict) -> Optional[Dict]:
    """Validate types, clamp lengths, drop garbage entries."""
    if not isinstance(d, dict):
        return None
    out: Dict = {}

    tone = str(d.get("tone", "warm")).lower().strip()
    out["tone"] = tone if tone in _VALID_TONES else "warm"

    layouts = d.get("daily_layouts") or []
    if isinstance(layouts, list):
        kept = [str(l).lower().strip() for l in layouts
                if str(l).lower().strip() in _VALID_LAYOUTS]
        out["daily_layouts"] = kept[:5] or ["a", "b", "c", "d"]
    else:
        out["daily_layouts"] = ["a", "b", "c", "d"]

    fields = d.get("tracker_fields") or []
    clean_fields = []
    if isinstance(fields, list):
        for f in fields[:8]:
            if not isinstance(f, dict): continue
            lbl = str(f.get("label", "")).strip()[:32]
            inp = str(f.get("input", "line")).lower().strip()
            if not lbl: continue
            if inp not in _VALID_INPUTS:
                inp = "line"
            field = {"label": lbl, "input": inp}
            # multi_choice carries an "options" list
            if inp == "multi_choice":
                opts = f.get("options") or []
                if isinstance(opts, list):
                    opts = [str(o).strip()[:18] for o in opts if str(o).strip()][:6]
                if not opts:
                    inp = "line"   # fallback if Claude forgot options
                    field["input"] = inp
                else:
                    field["options"] = opts
            clean_fields.append(field)
    out["tracker_fields"] = clean_fields

    prompts = d.get("reflection_prompts") or []
    clean_prompts = []
    if isinstance(prompts, list):
        for p in prompts[:30]:
            s = str(p).strip().strip('"')
            if 10 <= len(s) <= 200:
                clean_prompts.append(s)
    out["reflection_prompts"] = clean_prompts

    blocks = d.get("weekly_review_blocks") or ["WINS", "LESSONS", "ENERGY MAP", "NEXT WEEK"]
    if isinstance(blocks, list):
        out["weekly_review_blocks"] = [str(b).strip()[:24].upper() for b in blocks[:4]
                                       if str(b).strip()] or ["WINS", "LESSONS", "ENERGY MAP", "NEXT WEEK"]
    else:
        out["weekly_review_blocks"] = ["WINS", "LESSONS", "ENERGY MAP", "NEXT WEEK"]

    return out


# ── Renderers for the dynamic tracker field row ─────────────────────────────

def render_field_html(field: Dict) -> str:
    """Returns an inline HTML snippet for one tracker field (for ReportLab Paragraph)."""
    lbl = field.get("label", "")
    inp = field.get("input", "line")
    if inp == "checkbox":
        return f"<b>{lbl}</b>  &#9744;"
    if inp == "yes_no":
        return f"<b>{lbl}</b>  &#9744; Yes  &#9744; No"
    if inp == "stars":
        return f"<b>{lbl}</b>  &#9734; &#9734; &#9734; &#9734; &#9734;"
    if inp == "circles5":
        return f"<b>{lbl}</b>  &#9675; &#9675; &#9675; &#9675; &#9675;"
    if inp == "bars5":
        return f"<b>{lbl}</b>  &#9608; &#9608; &#9608; &#9633; &#9633;"
    if inp == "scale10":
        return f"<b>{lbl}</b>  1 2 3 4 5 6 7 8 9 10"
    if inp == "ampm":
        return f"<b>{lbl}</b>  ___:___ &#9744; AM &#9744; PM"
    if inp == "compass":
        return f"<b>{lbl}</b>  &#9744;N &#9744;NE &#9744;E &#9744;SE &#9744;S &#9744;SW &#9744;W &#9744;NW"
    if inp == "multi_choice":
        opts = field.get("options") or []
        return f"<b>{lbl}</b>  " + "  ".join(f"&#9744; {o}" for o in opts)
    if inp == "lines3":
        return f"<b>{lbl}</b>  __________________________________"
    if inp == "table3":
        return f"<b>{lbl}</b>  [___][___][___]"
    # default: single line
    return f"<b>{lbl}</b>  ________________________"
