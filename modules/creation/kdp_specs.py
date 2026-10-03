"""
KDP official paperback trim sizes and cover spec formulas.

Sources (verified 2026 Q2):
  https://kdp.amazon.com/en_US/help/topic/G201834180  (trim sizes)
  https://kdp.amazon.com/en_US/help/topic/G201953020  (cover dimensions)
  https://kdp.amazon.com/en_US/help/topic/G201834190  (paperback specs)

All sizes in inches. Spine multiplier depends on paper type:
  - White paper, B&W:           0.002252  (default for our low-content books)
  - Cream paper, B&W:           0.0025
  - White paper, premium color: 0.002347
  - White paper, standard color: 0.002347
  - Groundwood (eco) B&W:       0.002252

KDP requires bleed = 0.125" on top, bottom, and outer edge of cover.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class TrimSize:
    label:     str             # "6 x 9 in" — display name
    width_in:  float           # interior page width
    height_in: float           # interior page height
    popularity: int            # 1-10, higher = more common (UI sort)
    use_case:  str             # what it's typically used for


# Curated list of KDP-supported trim sizes (paperback)
TRIM_SIZES: List[TrimSize] = [
    # ── Most popular for low-content books ──
    TrimSize("6 x 9 in (15.24 x 22.86 cm)", 6.00, 9.00, 10,
             "Journals, logs, trivia — gold standard"),
    TrimSize("8.5 x 11 in (21.59 x 27.94 cm)", 8.5, 11.0, 9,
             "Large planners, workbooks, kids coloring"),
    TrimSize("8.5 x 8.5 in (21.59 x 21.59 cm)", 8.5, 8.5, 8,
             "Square coloring books, photo books"),
    TrimSize("7 x 10 in (17.78 x 25.40 cm)", 7.0, 10.0, 7,
             "Workbooks, study guides, adult coloring"),
    # ── Standard novel / non-fiction ──
    TrimSize("5 x 8 in (12.70 x 20.32 cm)", 5.0, 8.0, 7,
             "Compact novels, pocket books"),
    TrimSize("5.5 x 8.5 in (13.97 x 21.59 cm)", 5.5, 8.5, 8,
             "Standard novels, devotionals"),
    TrimSize("5.25 x 8 in (13.34 x 20.32 cm)", 5.25, 8.0, 6,
             "Trade paperbacks"),
    TrimSize("6.14 x 9.21 in (15.60 x 23.39 cm)", 6.14, 9.21, 6,
             "US trade paperback standard"),
    # ── Larger formats ──
    TrimSize("7.5 x 9.25 in (19.05 x 23.50 cm)", 7.5, 9.25, 5,
             "Textbooks, technical guides"),
    TrimSize("8 x 10 in (20.32 x 25.40 cm)", 8.0, 10.0, 6,
             "Photo books, art books"),
    TrimSize("8.25 x 11 in (20.96 x 27.94 cm)", 8.25, 11.0, 5,
             "Letter-style workbooks"),
    # ── Other supported ──
    TrimSize("5.06 x 7.81 in (12.85 x 19.84 cm)", 5.06, 7.81, 4,
             "Pocket-size guides"),
    TrimSize("6.69 x 9.61 in (16.99 x 24.41 cm)", 6.69, 9.61, 4,
             "International trade"),
    TrimSize("7.44 x 9.69 in (18.90 x 24.61 cm)", 7.44, 9.69, 3,
             "Specialty"),
    TrimSize("8.25 x 6 in (20.96 x 15.24 cm)", 8.25, 6.0, 3,
             "Landscape format"),
]


# Spine multipliers — inches per page, per paper type
SPINE_PER_PAGE: Dict[str, float] = {
    "white":     0.002252,   # B&W on white  (default)
    "cream":     0.0025,     # B&W on cream
    "groundwood":0.002252,   # B&W on groundwood
    "color":     0.002347,   # Standard color
    "premium_color": 0.002347,
}

BLEED_IN = 0.125     # 0.125" mandatory bleed on top/bottom/outer
DPI      = 300


def find_trim_by_label(label: str) -> TrimSize:
    """Look up trim size by label, fallback to 6×9."""
    for ts in TRIM_SIZES:
        if ts.label == label or label.lower() in ts.label.lower():
            return ts
    return TRIM_SIZES[0]   # 6 x 9 default


def trim_by_dimensions(w: float, h: float, tol: float = 0.05) -> TrimSize:
    """Find the closest KDP trim size matching the given dimensions."""
    for ts in TRIM_SIZES:
        if abs(ts.width_in - w) < tol and abs(ts.height_in - h) < tol:
            return ts
    return TRIM_SIZES[0]


# ── Hardcover (case laminate) constants — KDP cover calculator ────────────────
HC_WRAP_IN   = 0.625     # board overhang / wrap on all four outer edges
HC_HINGE_IN  = 0.375     # hinge channel on each side of the spine
HC_BOARD_IN  = 0.06      # fixed board/binding allowance added to the spine
HC_SPINE_PER_PAGE = 0.002252   # hardcover uses white paper only


def compute_cover_dims(
    page_count: int,
    trim_w: float = 6.0,
    trim_h: float = 9.0,
    paper_type: str = "white",
    binding: str = "paperback",
) -> Dict:
    """
    Returns ALL cover dimensions following KDP spec EXACTLY.
    https://kdp.amazon.com/en_US/help/topic/G201953020  (paperback)
    https://kdp.amazon.com/en_US/help/topic/GDTKFJPNQCBTMRV6  (hardcover)

    Paperback:  full_w = bleed + trim + spine + trim + bleed ; spine = pages × mult
    Hardcover:  full_w = (wrap+bleed) + trim + hinge + spine + hinge + trim + (wrap+bleed)
                spine  = pages × 0.002252 + 0.06 (board) ; wrap 0.625 ; hinge 0.375
    The returned keys are identical for both bindings so compose_cover can consume
    either; `hinge_px` is 0 for paperback (→ paperback layout unchanged).
    """
    hardcover = str(binding).lower() == "hardcover"

    if hardcover:
        if page_count < 75:
            page_count = 75      # KDP hardcover minimum
        if page_count > 550:
            page_count = 550     # KDP hardcover maximum
        spine = round(page_count * HC_SPINE_PER_PAGE + HC_BOARD_IN, 4)
        edge  = HC_WRAP_IN + BLEED_IN            # outer margin = wrap + bleed = 0.75"
        hinge = HC_HINGE_IN
        full_w = edge + trim_w + hinge + spine + hinge + trim_w + edge
        full_h = trim_h + edge * 2
        back_x = edge
        spine_x = edge + trim_w + hinge
        front_x = edge + trim_w + hinge + spine + hinge
    else:
        if page_count < 24:
            page_count = 24      # KDP paperback minimum
        if page_count > 828:
            page_count = 828     # KDP paperback maximum
        multiplier = SPINE_PER_PAGE.get(paper_type, SPINE_PER_PAGE["white"])
        spine = round(page_count * multiplier, 4)
        edge  = BLEED_IN
        hinge = 0.0
        full_w = edge + trim_w + spine + trim_w + edge
        full_h = trim_h + edge * 2
        back_x = edge
        spine_x = edge + trim_w
        front_x = edge + trim_w + spine

    return {
        "trim_w_in":   trim_w,
        "trim_h_in":   trim_h,
        "spine_in":    spine,
        "full_w_in":   round(full_w, 4),
        "full_h_in":   round(full_h, 4),
        "front_x_in":  round(front_x, 4),
        "back_x_in":   round(back_x, 4),
        "spine_x_in":  round(spine_x, 4),
        "bleed_in":    round(edge, 4),
        "hinge_in":    round(hinge, 4),
        "binding":     "hardcover" if hardcover else "paperback",
        "paper_type":  paper_type,
        "page_count":  page_count,
        # pixels at 300 DPI
        "full_w_px":   int(round(full_w * DPI)),
        "full_h_px":   int(round(full_h * DPI)),
        "front_w_px":  int(round(trim_w * DPI)),
        "front_h_px":  int(round(trim_h * DPI)),
        "spine_w_px":  max(int(round(spine * DPI)), 1),
        "bleed_px":    int(round(edge * DPI)),
        "hinge_px":    int(round(hinge * DPI)),
    }


# ── KDP Best Practices Cheat Sheet ────────────────────────────────────────────
KDP_BEST_PRACTICES = """
KDP Cover Best Practices (Amazon official guidance, 2026):

DIMENSIONS
- Cover = wrap-around PDF: back cover + spine + front cover, single file
- Bleed: 0.125" required on TOP, BOTTOM, OUTER edges
- Spine bleed: built into the formula (NOT extra)
- Minimum page count for spine text: 80 pages (below = no spine text)
- Maximum cover file: 650 MB

RESOLUTION
- 300 DPI minimum (we use 300)
- Embedded fonts ONLY (system fonts WILL be replaced by KDP)
- Use PDF/X-3:2002 or standard PDF
- Color: RGB or CMYK both accepted (we use RGB)

SAFE AREAS
- Text must be ≥0.25" from trim line (avoid cut-off)
- Critical text ≥0.5" from spine (gutter loss)
- Barcode area (back, lower-right): KDP places it ~2x1.2 in if absent

TYPOGRAPHY
- Title: bold, sans-serif or serif display, 60-120pt
- Subtitle: 24-36pt
- Author name: 18-30pt
- Spine text: rotates 90° clockwise, 12-18pt depending on spine width

CONTENT TIPS
- High contrast between background and text
- One focal point per cover (Amazon thumbnail is tiny)
- Avoid copyrighted images
- Test cover at thumbnail size (50x80px) — title should still be readable
"""
