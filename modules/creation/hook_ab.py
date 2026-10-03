"""
Hook A/B optimizer
====================
The first 3-4 lines of the KDP description are the only thing visible on mobile
before "Read more". They are also weighted by the A10 algorithm for engagement
depth scoring. Conclusion : the hook is the single highest-leverage line of copy
in the whole listing.

This module generates 3 hook variants for a given listing, asks Claude to score
them on hook strength + genre fit + mobile readability, and rewrites the
description in place using the winner.

Also handles welcome-page polish for the interior PDF first sample (engagement
signal #11).
"""
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _existing_hook(description: str) -> str:
    """Extract the first 3 lines (or first <br><br> chunk) of the description."""
    if not description:
        return ""
    visible = re.sub(r"<[^>]+>", " ", description)
    visible = re.sub(r"\s+", " ", visible).strip()
    # Take first ~200 chars or up to first 2 sentences
    parts = re.split(r"(?<=[.!?])\s+", visible)
    return " ".join(parts[:2])[:240]


def _replace_hook(description: str, new_hook: str) -> str:
    """Replace the leading block of description before the first <br><br>."""
    if not description:
        return new_hook
    # Find the first <br><br> (or <br/><br/> variant)
    m = re.search(r"<br\s*/?>\s*<br\s*/?>", description, re.IGNORECASE)
    if not m:
        # Fallback: split on first paragraph break
        m = re.search(r"\n\n", description)
    if m:
        return new_hook + description[m.start():]
    # No body — replace the whole thing
    return new_hook


def optimize_hook(listing: Dict, anthropic_key: str,
                  status_cb=None) -> Optional[Dict]:
    """
    Generate 3 hook variants and rewrite the listing description with the winner.
    Returns {'before': str, 'after': str, 'score': int, 'variants': [...]} or None.
    """
    if not anthropic_key or not listing.get("description"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    title    = listing.get("title", "")
    subtitle = listing.get("subtitle", "")
    niche    = listing.get("niche", "")
    p_type   = listing.get("product_type", "book")
    current  = _existing_hook(listing["description"])

    prompt = f"""You are a top KDP copywriter. Generate 3 ALTERNATIVE OPENING HOOKS
for this book description, then score each one.

BOOK
  title:    "{title}"
  subtitle: "{subtitle}"
  niche:    "{niche}"
  type:     {p_type}
  current hook: "{current}"

EACH HOOK must:
- Be 1-2 sentences MAX (35-50 words total)
- Speak to a specific pain or transformation
- Pass the "3-second mobile test" (the reader decides in 3 seconds)
- Use NO HTML, NO emojis, NO clichés like "Are you tired of...?"
- Each variant takes a DIFFERENT angle (problem-first, identity-first, outcome-first)

THEN SCORE EACH on:
  - hook_power (0-100) : will it stop a scroll?
  - genre_fit  (0-100) : right tone for {p_type}?
  - mobile_clarity (0-100) : crystal clear in <3 seconds?

Return STRICT JSON only:
{{"variants": [
   {{"angle": "problem-first",   "hook": "...",
     "hook_power": 0-100, "genre_fit": 0-100, "mobile_clarity": 0-100}},
   {{"angle": "identity-first",  "hook": "...", ...}},
   {{"angle": "outcome-first",   "hook": "...", ...}}
]}}"""

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        if status_cb:
            status_cb("✍️ Hook A/B : 3 variantes générées + scorées par Claude...")
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        variants = data.get("variants", [])
        if not variants:
            return None
        # Composite score
        def composite(v):
            return (int(v.get("hook_power", 0)) * 0.5
                    + int(v.get("genre_fit", 0)) * 0.25
                    + int(v.get("mobile_clarity", 0)) * 0.25)
        winner = max(variants, key=composite)
        winner_hook = (winner.get("hook") or "").strip()
        if not winner_hook:
            return None
        # Rewrite description
        before = listing["description"]
        listing["description"] = _replace_hook(before, winner_hook)
        if status_cb:
            status_cb(
                f"🏆 Hook gagnant ({winner.get('angle','?')}, score "
                f"{composite(winner):.0f}/100) — description réécrite"
            )
        return {
            "before":   before,
            "after":    listing["description"],
            "variants": variants,
            "winner":   winner,
        }
    except Exception as e:
        logger.warning(f"Hook A/B failed: {e}")
        if status_cb:
            status_cb(f"⚠️ Hook A/B sauté : {e}")
        return None


# ── #11 — First sample / welcome polish ─────────────────────────────────────

def polish_welcome_copy(listing: Dict, anthropic_key: str,
                        status_cb=None) -> Optional[str]:
    """
    KDP samples expose the welcome page to free preview. A boring welcome
    kills the engagement signal. We polish the welcome section's description
    so the first sample page hooks the reader.

    Returns the new welcome description or None.
    """
    if not anthropic_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    sections = listing.get("content_sections", [])
    welcome = next((s for s in sections if s.get("type") == "welcome"), None)
    if not welcome:
        return None
    cur_desc = welcome.get("description", "")
    title    = listing.get("title", "")
    niche    = listing.get("niche", "")
    p_type   = listing.get("product_type", "")

    prompt = f"""You are writing the WELCOME PAGE intro of a KDP {p_type} called
"{title}" (niche: {niche}).

The KDP free sample shows this page. It is the first thing a potential buyer reads.
A bland welcome KILLS the A10 engagement signal. Rewrite the current copy so the
reader feels seen in the first 2 lines and immediately wants to use the book.

CURRENT:
{cur_desc[:400]}

NEW WELCOME COPY MUST:
- 60-110 words, 3 short paragraphs separated by blank lines
- Open with a specific emotional truth (NOT "Welcome to...")
- Promise a concrete result by page 10
- End with one short call-to-action sentence
- No HTML, no emojis, no marketing buzzwords ("transform your life", "unlock", "unleash")

Return ONLY the new copy, plain text, no preamble."""

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        if status_cb:
            status_cb("✨ Polish welcome page (engagement A10)...")
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=380,
            messages=[{"role": "user", "content": prompt}],
        )
        new_copy = msg.content[0].text.strip()
        # Strip wrapping quotes if any
        new_copy = new_copy.strip('"').strip("'").strip()
        if 40 <= len(new_copy.split()) <= 200:
            welcome["description"] = new_copy
            if status_cb:
                status_cb(f"✅ Welcome page poli ({len(new_copy.split())} mots)")
            return new_copy
    except Exception as e:
        logger.debug(f"Welcome polish failed: {e}")
    return None
