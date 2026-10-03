"""
Cryptogram generator — REWRITTEN.

Each puzzle = short quote (≤120 chars) encoded with a random substitution cipher.

Difficulty levels are NOW respected with real solving aids:
  - easy   : 4 most-frequent letters pre-revealed + letter frequency hint +
             solving tips box + alphabet decoder grid
  - medium : 2 letters pre-revealed (E, T) + letter frequency hint
  - hard   : 1 letter pre-revealed (E)
  - expert : 0 letters pre-revealed (pure puzzle)

Pages are filled top-to-bottom — encoded quote (top) · pre-fills (middle) ·
frequency analysis + tips box + decoder grid (bottom).

Quotes come from Claude (themed per niche) or fallback bank, deduplicated by
plaintext so 106 puzzles never get the same quote twice.
"""
from typing import Dict, List, Optional, Set
from collections import Counter
import logging
import string

from reportlab.lib import colors
from reportlab.lib.units import inch as IN
from reportlab.platypus import Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from ._common import rng_for, puzzle_header, normalize_difficulties, solutions_banner, is_large_print

logger = logging.getLogger(__name__)


# ── Expanded fallback bank (60 quotes — enough variety even at 100+ puzzles) ─
_FALLBACK_QUOTES = [
    ("The journey of a thousand miles begins with one step.", "Lao Tzu"),
    ("Be the change you wish to see in the world.", "Mahatma Gandhi"),
    ("In the middle of difficulty lies opportunity.", "Albert Einstein"),
    ("The only way to do great work is to love what you do.", "Steve Jobs"),
    ("Life is what happens when you are busy making other plans.", "John Lennon"),
    ("The best way out is always through.", "Robert Frost"),
    ("It is during our darkest moments that we must focus to see the light.", "Aristotle"),
    ("Whether you think you can or you think you can not, you are right.", "Henry Ford"),
    ("Do not let what you cannot do interfere with what you can do.", "John Wooden"),
    ("Success is not final, failure is not fatal.", "Winston Churchill"),
    ("The future belongs to those who believe in the beauty of their dreams.", "Eleanor Roosevelt"),
    ("Do one thing every day that scares you.", "Eleanor Roosevelt"),
    ("Spread love everywhere you go.", "Mother Teresa"),
    ("When you have a dream, you have got to grab it.", "Cobi Jones"),
    ("The mind is everything. What you think you become.", "Buddha"),
    ("An unexamined life is not worth living.", "Socrates"),
    ("Eighty percent of success is showing up.", "Woody Allen"),
    ("Your time is limited, do not waste it living someone else life.", "Steve Jobs"),
    ("Winners never quit and quitters never win.", "Vince Lombardi"),
    ("Believe you can and you are halfway there.", "Theodore Roosevelt"),
    ("Hardships often prepare ordinary people for an extraordinary destiny.", "C.S. Lewis"),
    ("You miss one hundred percent of the shots you do not take.", "Wayne Gretzky"),
    ("I have not failed. I just found ten thousand ways that do not work.", "Thomas Edison"),
    ("The only impossible journey is the one you never begin.", "Tony Robbins"),
    ("In the end, we will remember not the words of our enemies, but the silence of our friends.", "Martin Luther King Jr."),
    ("Life is ten percent what happens to me and ninety percent how I react to it.", "Charles Swindoll"),
    ("The only person you are destined to become is the person you decide to be.", "Ralph Waldo Emerson"),
    ("Go confidently in the direction of your dreams.", "Henry David Thoreau"),
    ("When everything seems to be going against you, remember that the airplane takes off against the wind.", "Henry Ford"),
    ("It is never too late to be what you might have been.", "George Eliot"),
    ("Either you run the day or the day runs you.", "Jim Rohn"),
    ("Everything you have ever wanted is on the other side of fear.", "George Addair"),
    ("Do what you can with all you have, wherever you are.", "Theodore Roosevelt"),
    ("Limitations live only in our minds.", "Jamie Paolinetti"),
    ("Dream big and dare to fail.", "Norman Vaughan"),
    ("Our greatest weakness lies in giving up.", "Thomas Edison"),
    ("If you can dream it, you can achieve it.", "Zig Ziglar"),
    ("Quality is not an act, it is a habit.", "Aristotle"),
    ("All our dreams can come true if we have the courage to pursue them.", "Walt Disney"),
    ("Do not watch the clock. Do what it does. Keep going.", "Sam Levenson"),
    ("Build your own dreams, or someone else will hire you to build theirs.", "Farrah Gray"),
    ("Strive not to be a success, but rather to be of value.", "Albert Einstein"),
    ("Two roads diverged in a wood and I took the one less traveled by.", "Robert Frost"),
    ("Do not go where the path may lead, go instead where there is no path.", "Ralph Waldo Emerson"),
    ("Try not to become a man of success, but rather try to become a man of value.", "Albert Einstein"),
    ("The way to get started is to quit talking and begin doing.", "Walt Disney"),
    ("If life were predictable it would cease to be life, and be without flavor.", "Eleanor Roosevelt"),
    ("Spread your wings and let yourself fly.", "Anonymous"),
    ("The harder you work for something, the greater you will feel when you achieve it.", "Anonymous"),
    ("Dreams do not work unless you do.", "John C. Maxwell"),
    ("Wake up with determination, go to bed with satisfaction.", "Anonymous"),
    ("Little things make big days.", "Anonymous"),
    ("Push yourself, because no one else is going to do it for you.", "Anonymous"),
    ("Great things never come from comfort zones.", "Anonymous"),
    ("Sometimes later becomes never. Do it now.", "Anonymous"),
    ("Success does not just find you. You have to go out and get it.", "Anonymous"),
    ("The key to success is to focus on goals, not obstacles.", "Anonymous"),
    ("Doubt kills more dreams than failure ever will.", "Suzy Kassem"),
    ("What you get by achieving your goals is not as important as what you become.", "Zig Ziglar"),
    ("The pain you feel today will be the strength you feel tomorrow.", "Anonymous"),
]


def _claude_quotes(theme: str, n: int, anthropic_key: str) -> List[Dict]:
    """Returns list of {quote, author} sourced by Claude. Length 30-120 chars."""
    if not anthropic_key or not theme:
        return []
    try:
        import anthropic, json, re
        client = anthropic.Anthropic(api_key=anthropic_key)
        prompt = (
            f"Give me exactly {n} short inspiring quotes related to '{theme}'. "
            "Each quote MUST be 30-120 characters, in English, with proper attribution. "
            "All quotes MUST be DIFFERENT — no repeats, no near-duplicates. "
            'Return a JSON array: [{"quote": "...", "author": "..."}, ...]. '
            "Use only ASCII letters and basic punctuation (. , ! ? -). "
            "No markdown, no explanation, just the JSON array."
        )
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        out = []
        for item in data:
            q = re.sub(r"[^\x20-\x7E]", "", str(item.get("quote", "")))
            a = re.sub(r"[^\x20-\x7E]", "", str(item.get("author", "")))
            if 30 <= len(q) <= 120:
                out.append({"quote": q.strip(), "author": a.strip() or "Anonymous"})
        return out
    except Exception as e:
        logger.warning(f"Claude cryptogram quotes failed: {e}")
        return []


def _build_cipher(rng) -> Dict[str, str]:
    """Random substitution cipher with no letter mapping to itself."""
    alpha = list(string.ascii_uppercase)
    while True:
        cipher = alpha[:]
        rng.shuffle(cipher)
        if all(p != c for p, c in zip(alpha, cipher)):
            return dict(zip(alpha, cipher))


def _encode(text: str, cipher: Dict[str, str]) -> str:
    out = []
    for ch in text.upper():
        out.append(cipher.get(ch, ch))
    return "".join(out)


def _reveals_for_difficulty(d: str, plaintext: str) -> Set[str]:
    """
    Returns the set of UPPER-CASE plaintext letters that will be pre-revealed
    to the solver, scaled by difficulty.

    Strategy: pick the N most-frequent letters in THIS specific quote.
    That guarantees the reveals actually help the solver progress.
    """
    n_by_diff = {"easy": 4, "medium": 2, "hard": 1, "expert": 0}
    n = n_by_diff.get(d, 2)
    if n <= 0:
        return set()
    counts = Counter(ch for ch in plaintext.upper() if ch.isalpha())
    return set(letter for letter, _ in counts.most_common(n))


def generate(n: int, difficulty, niche: str, volume: int = 1,
             anthropic_key: str = "") -> List[Dict]:
    difficulties = normalize_difficulties(difficulty, n)

    # ── Step 1 : harvest a deduplicated pool of quotes (Claude + fallback) ──
    # Request 1.5× the target from Claude to absorb dedup losses; cap at 100
    # per call to keep latency reasonable.
    pool: List[Dict] = []
    seen_plain: Set[str] = set()

    # Try Claude in chunks if n is large (one call ≤ 100)
    remaining = n
    while remaining > 0 and anthropic_key:
        ask = min(int(remaining * 1.5) + 5, 100)
        batch = _claude_quotes(niche, ask, anthropic_key)
        if not batch:
            break
        for rec in batch:
            key = rec["quote"].strip().lower()
            if key in seen_plain:
                continue
            seen_plain.add(key)
            pool.append(rec)
        if len(pool) >= n:
            break
        remaining = n - len(pool)
        if not batch:
            break  # Claude empty — stop

    # Top up from fallback (also deduped)
    for q, a in _FALLBACK_QUOTES:
        if len(pool) >= n:
            break
        key = q.strip().lower()
        if key in seen_plain:
            continue
        seen_plain.add(key)
        pool.append({"quote": q, "author": a})

    # If still not enough (e.g. n > 60 and Claude unavailable), cycle remaining
    # but tag them so we know there will be dupes (rare path)
    while len(pool) < n:
        pool.append(_FALLBACK_QUOTES[len(pool) % len(_FALLBACK_QUOTES)])
        pool[-1] = {"quote": pool[-1][0] if isinstance(pool[-1], tuple) else pool[-1]["quote"],
                    "author": pool[-1][1] if isinstance(pool[-1], tuple) else pool[-1]["author"]}

    # ── Step 2 : build puzzles ──
    out = []
    for i in range(n):
        d_i = difficulties[i]
        rng = rng_for(niche, volume, i)
        rec  = pool[i]
        cipher = _build_cipher(rng)
        encoded = _encode(rec["quote"], cipher)
        out.append({
            "kind":     "cryptogram",
            "plain":    rec["quote"],
            "author":   rec["author"],
            "encoded":  encoded,
            "cipher":   cipher,
            "difficulty": d_i,
            "reveals":  sorted(_reveals_for_difficulty(d_i, rec["quote"])),
        })
    return out


# ── Rendering helpers ────────────────────────────────────────────────────────
_DIFF_LABEL = {
    "easy":   "EASY — 4 letters revealed",
    "medium": "MEDIUM — 2 letters revealed",
    "hard":   "HARD — 1 letter revealed",
    "expert": "EXPERT — solve from scratch",
}

_DIFF_TIPS = {
    "easy": [
        "Single-letter words are almost always A or I.",
        "Two-letter words: most common are OF, TO, IN, IT, IS, BE.",
        "Look for the most frequent letter — likely E.",
        "Apostrophe followed by S = 's (possessive or contraction).",
    ],
    "medium": [
        "The letter E is the most common in English — find it first.",
        "Common three-letter words: THE, AND, FOR, ARE, BUT, NOT, YOU.",
        "Double letters are often LL, EE, SS, OO, TT, FF.",
        "Words ending in -ING are common.",
    ],
    "hard": [
        "Try identifying THE first (3 letters, very common).",
        "Look for patterns: -ION, -ING, -ED endings.",
        "Vowels (A, E, I, O, U) make up about 40% of all letters.",
    ],
    "expert": [
        "Start with letter frequency: E, T, A, O, I, N are most common.",
        "Look for short common words: THE, OF, TO, AND, A, IN, IS, IT.",
        "Build from there — each letter you decode unlocks more.",
    ],
}


def _frequency_table(encoded: str) -> List[List[str]]:
    """Returns a 2-row table: row 0 = ciphered letters sorted by frequency,
    row 1 = count.  Helps solver attack the puzzle methodically."""
    counts = Counter(ch for ch in encoded.upper() if ch.isalpha())
    if not counts:
        return [[""], [""]]
    # Top 8 most frequent
    top = counts.most_common(8)
    row_letters = [letter for letter, _ in top]
    row_counts  = [str(c)    for _, c in top]
    return [row_letters, row_counts]


def render_pages(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                 content_w: float, content_h: float) -> List:
    elems = []
    total = len(puzzles)
    large = is_large_print(listing)
    font_main = 18 if large else 15
    font_clue = 10 if large else 9

    instr_st = ParagraphStyle(
        "CGinstr", fontName="Helvetica-Oblique", fontSize=10,
        textColor=colors.HexColor("#555555"), alignment=TA_LEFT, spaceAfter=8,
    )
    diff_st = ParagraphStyle(
        "CGdiff", fontName="Helvetica-Bold", fontSize=11,
        textColor=colors.HexColor("#1A252F"), alignment=TA_LEFT, spaceAfter=10,
    )
    section_st = ParagraphStyle(
        "CGsection", fontName="Helvetica-Bold", fontSize=10,
        textColor=colors.HexColor("#1A252F"), alignment=TA_LEFT,
        spaceBefore=14, spaceAfter=4,
    )
    tip_st = ParagraphStyle(
        "CGtip", fontName="Helvetica", fontSize=9.5,
        textColor=colors.HexColor("#333333"), alignment=TA_LEFT,
        leftIndent=14, spaceAfter=2, leading=12,
    )
    decoder_label_st = ParagraphStyle(
        "CGdec", fontName="Helvetica-Bold", fontSize=9,
        textColor=colors.HexColor("#1A252F"), alignment=TA_LEFT, spaceAfter=4,
    )

    cell_style = ParagraphStyle(
        "CGcell", fontName="Courier-Bold", fontSize=font_main,
        alignment=TA_CENTER, leading=font_main + 2,
    )
    reveal_style = ParagraphStyle(
        "CGreveal", fontName="Courier-Bold", fontSize=font_main,
        alignment=TA_CENTER, leading=font_main + 2,
        textColor=colors.HexColor("#C0392B"),  # red = pre-revealed
    )

    for i, p in enumerate(puzzles, 1):
        diff = p["difficulty"]
        reveals = set(p.get("reveals", []))  # plaintext letters revealed
        # Build reverse cipher : encoded_letter → plaintext (so we know which
        # ciphered letters to show un-blanked)
        rev_cipher = {v: k for k, v in p["cipher"].items()}

        elems.extend(puzzle_header(i, total, diff, "Cryptogram", pal, styles,
                                   avail_w=content_w))
        elems.append(Paragraph(_DIFF_LABEL.get(diff, diff.upper()), diff_st))
        elems.append(Paragraph(
            "Each letter has been replaced with another letter. "
            "Decode the quote below.", instr_st))

        # Wrap encoded into lines of ≤26 chars
        words = p["encoded"].split(" ")
        lines: List[List[str]] = []
        cur, cur_len = [], 0
        max_chars = 20 if large else 26
        for w in words:
            if cur and cur_len + 1 + len(w) > max_chars:
                lines.append(cur)
                cur, cur_len = [w], len(w)
            else:
                if cur:
                    cur_len += 1
                cur.append(w)
                cur_len += len(w)
        if cur:
            lines.append(cur)

        # ── Render each line : ciphered top, blank-or-reveal bottom ──
        for line_words in lines:
            line = " ".join(line_words)
            n_chars = len(line)
            col_w = content_w / max(n_chars, 1)
            top_row = []
            bot_row = []
            for ch in line:
                if ch == " ":
                    top_row.append("")
                    bot_row.append("")
                elif ch.isalpha():
                    top_row.append(Paragraph(ch, cell_style))
                    plain = rev_cipher.get(ch, "")
                    if plain in reveals:
                        # Pre-revealed letter — show in red
                        bot_row.append(Paragraph(plain, reveal_style))
                    else:
                        bot_row.append(Paragraph("___", cell_style))
                else:
                    # Punctuation: keep as-is, no slot underneath
                    top_row.append(Paragraph(ch, cell_style))
                    bot_row.append("")
            tbl = Table([top_row, bot_row], colWidths=[col_w] * n_chars,
                        rowHeights=[font_main + 4, font_main + 6])
            tbl.setStyle(TableStyle([
                ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))
            elems.append(tbl)
            elems.append(Spacer(1, 8))

        elems.append(Spacer(1, 8))

        # ── Author hint ──
        if p.get("author"):
            au_st = ParagraphStyle("CGau", fontName="Helvetica-Oblique", fontSize=10,
                                   textColor=colors.HexColor("#666666"),
                                   alignment=TA_LEFT)
            elems.append(Paragraph(f"— Quote attributed to: <b>{p['author']}</b>", au_st))

        # ── Letter frequency analysis (medium / hard / expert) ──
        if diff in ("medium", "hard", "expert"):
            elems.append(Paragraph("Letter Frequency in This Puzzle", section_st))
            freq = _frequency_table(p["encoded"])
            n_cols = len(freq[0])
            freq_table = Table(freq, colWidths=[content_w / max(n_cols, 1)] * n_cols,
                               rowHeights=[font_clue + 8, font_clue + 6])
            freq_table.setStyle(TableStyle([
                ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME",      (0, 0), (-1, 0), "Courier-Bold"),
                ("FONTSIZE",      (0, 0), (-1, 0), font_clue + 2),
                ("FONTNAME",      (0, 1), (-1, 1), "Helvetica"),
                ("FONTSIZE",      (0, 1), (-1, 1), font_clue),
                ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#888888")),
                ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                ("TEXTCOLOR",     (0, 1), (-1, 1), colors.HexColor("#555555")),
                ("LEFTPADDING",   (0, 0), (-1, -1), 2),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elems.append(freq_table)

        # ── Solving tips box (all difficulties) ──
        elems.append(Paragraph("Solving Tips", section_st))
        for tip in _DIFF_TIPS.get(diff, _DIFF_TIPS["medium"]):
            elems.append(Paragraph(f"• {tip}", tip_st))

        # ── Alphabet decoder grid (your worksheet for the cipher) ──
        elems.append(Paragraph("Your Decoder — Fill in as you solve:", decoder_label_st))
        # 2 rows × 13 columns = full alphabet, each cell shows cipher_letter top,
        # blank below for the solver to write the plaintext.
        n_per_row = 13
        rows: List[List] = []
        # Row 0 + 1 : first half A-M
        # Row 2 + 3 : second half N-Z
        for start in (0, 13):
            cipher_row = []
            blank_row  = []
            for k in range(n_per_row):
                letter = string.ascii_uppercase[start + k]
                cipher_row.append(Paragraph(f"<b>{letter}</b>",
                                            ParagraphStyle("dec_top",
                                                fontName="Helvetica-Bold",
                                                fontSize=font_clue + 1,
                                                alignment=TA_CENTER)))
                # If this cipher_letter decodes to a revealed plain, show it
                plain_for = rev_cipher.get(letter, "")
                if plain_for in reveals:
                    blank_row.append(Paragraph(f"<b>{plain_for}</b>",
                                                ParagraphStyle("dec_rev",
                                                    fontName="Courier-Bold",
                                                    fontSize=font_clue + 1,
                                                    alignment=TA_CENTER,
                                                    textColor=colors.HexColor("#C0392B"))))
                else:
                    blank_row.append(Paragraph("___",
                                                ParagraphStyle("dec_blank",
                                                    fontName="Courier",
                                                    fontSize=font_clue,
                                                    alignment=TA_CENTER)))
            rows.append(cipher_row)
            rows.append(blank_row)
        col_w_dec = content_w / n_per_row
        decoder = Table(rows, colWidths=[col_w_dec] * n_per_row,
                        rowHeights=[font_clue + 8, font_clue + 10,
                                    font_clue + 8, font_clue + 10])
        decoder.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
            ("BACKGROUND",    (0, 2), (-1, 2), colors.HexColor("#EFEFEF")),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        elems.append(Spacer(1, 4))
        elems.append(decoder)

        elems.append(PageBreak())
    return elems


def render_solutions(puzzles: List[Dict], listing: Dict, pal: Dict, styles: Dict,
                     content_w: float, content_h: float) -> List:
    elems = solutions_banner("Cryptogram", pal, styles)
    body = ParagraphStyle("CGSol", fontName="Helvetica", fontSize=11, leading=14,
                          spaceAfter=10)
    num_st = ParagraphStyle("CGSolN", fontName="Helvetica-Bold", fontSize=11,
                            textColor=colors.HexColor("#1A252F"))
    for i, p in enumerate(puzzles, 1):
        elems.append(Paragraph(f"#{i} — <i>{p['author']}</i>", num_st))
        elems.append(Paragraph(f"&ldquo;{p['plain']}&rdquo;", body))
        if i % 14 == 0:
            elems.append(PageBreak())
    elems.append(PageBreak())
    return elems
