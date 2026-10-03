"""Code-drawn explanatory infographics for high-content books.

The image models garble label text, so concept diagrams that NEED readable
labels (cycles, processes, comparisons, timelines, pyramids) are drawn in code
with ReportLab — crisp text, niche-coloured, matching the interior design.

A "diagram spec" (produced by Claude, see engine.generate_diagrams) drives it:
    {
      "type": "cycle" | "process" | "comparison" | "timeline" | "pyramid" | "callout",
      "title": "How the BRRRR Method Works",
      "caption": "A repeatable loop that recycles your capital.",   # optional
      "nodes": ["Buy", "Rehab", "Rent", "Refinance", "Repeat"],     # step-based
      "items": [                                                    # comparison
          {"label": "Epoxy Resin", "points": ["Self-levels", "Deep pours"]},
          {"label": "UV Resin",    "points": ["Cures in seconds"]}
      ]
    }
"""
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch as IN
from reportlab.platypus import Flowable, KeepTogether, Paragraph, Spacer

_INK = colors.HexColor("#222222")
_MUTE = colors.HexColor("#5B5B5B")


def _tint(color, amount: float = 0.88):
    r, g, b = color.red, color.green, color.blue
    return colors.Color(r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)


def _shade(color, amount: float = 0.72):
    return colors.Color(color.red * amount, color.green * amount, color.blue * amount)


def _wrap_lines(text, font, size, maxw):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if stringWidth(t, font, size) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines or [str(text)]


class _Diagram(Flowable):
    """Base: draws a titled panel; subclasses implement _body()."""
    def __init__(self, spec: Dict, content_w: float, design: Dict):
        Flowable.__init__(self)
        self.spec = spec
        self.cw = content_w
        self.accent = design.get("accent", colors.HexColor("#1A3A5C"))
        self.accent2 = design.get("accent2") or _shade(self.accent, 0.6)
        self.tfont = design.get("title_font", "Helvetica-Bold")
        self.motif = design.get("motif", "◆")
        self._h = 0

    # subclasses set self._body_h in wrap and draw in _body(y_top)
    def _measure_body(self) -> float:
        return 1.0 * IN

    def _draw_body(self, top: float):
        pass

    def wrap(self, aw, ah):
        self.cw = aw
        self._title_lines = _wrap_lines(self.spec.get("title", ""), self.tfont, 13, aw - 24)
        self._body_h = self._measure_body()
        cap = self.spec.get("caption")
        self._cap_lines = _wrap_lines(cap, "Helvetica-Oblique", 9, aw - 28) if cap else []
        self._h = (14 + len(self._title_lines) * 17 + 10 + self._body_h +
                   (len(self._cap_lines) * 12 + 8 if self._cap_lines else 0) + 14)
        return (aw, self._h)

    def draw(self):
        c = self.canv
        h, w = self._h, self.cw
        # panel
        c.setFillColor(_tint(self.accent, 0.94))
        c.roundRect(0, 0, w, h, 8, fill=1, stroke=0)
        c.setFillColor(self.accent)
        c.rect(0, h - 5, w, 5, fill=1, stroke=0)
        # title (eyebrow motif + title)
        c.setFillColor(self.accent)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(14, h - 18, f"{self.motif}  HOW IT WORKS")
        c.setFont(self.tfont, 13)
        c.setFillColor(_shade(self.accent, 0.75))
        y = h - 34
        for ln in self._title_lines:
            c.drawString(14, y, ln); y -= 17
        y -= 6
        # body
        self._draw_body(y)
        # caption
        if self._cap_lines:
            cy = 12 + (len(self._cap_lines) - 1) * 12
            c.setFont("Helvetica-Oblique", 9)
            c.setFillColor(_MUTE)
            for ln in self._cap_lines:
                c.drawCentredString(w / 2, cy, ln); cy -= 12


class _Steps(_Diagram):
    """Vertical numbered steps with a connecting spine — process / cycle."""
    def __init__(self, spec, content_w, design, loop=False):
        super().__init__(spec, content_w, design)
        self.loop = loop
        self.nodes = [str(n) for n in (spec.get("nodes") or []) if str(n).strip()][:8]

    def _measure_body(self):
        self._rows = []
        for n in self.nodes:
            lines = _wrap_lines(n, "Helvetica-Bold", 11, self.cw - 90)
            self._rows.append(lines)
        row_h = [max(34, len(l) * 15 + 16) for l in self._rows]
        self._row_h = row_h
        extra = 26 if self.loop else 0
        return sum(row_h) + extra

    def _draw_body(self, top):
        c = self.canv
        x_badge = 30
        y = top
        for i, (n, lines, rh) in enumerate(zip(self.nodes, self._rows, self._row_h), 1):
            cyc = y - rh / 2
            # connector spine to next badge
            if i < len(self.nodes):
                c.setStrokeColor(self.accent2)
                c.setLineWidth(2.2)
                c.line(x_badge, cyc - 13, x_badge, cyc - rh + 13)
            # badge
            c.setFillColor(self.accent)
            c.circle(x_badge, cyc, 13, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 12)
            c.drawCentredString(x_badge, cyc - 4.5, str(i))
            # label
            c.setFillColor(_INK)
            c.setFont("Helvetica-Bold", 11)
            ty = cyc + (len(lines) - 1) * 7.5
            for ln in lines:
                c.drawString(x_badge + 26, ty - 4, ln); ty -= 15
            y -= rh
        if self.loop and len(self.nodes) > 1:
            c.setFillColor(self.accent2)
            c.setFont("Helvetica-BoldOblique", 9)
            c.drawString(x_badge + 26, y - 4, "↻  then repeat the cycle")


class _Comparison(_Diagram):
    """Two (or three) labelled cards side by side with bullet points."""
    def __init__(self, spec, content_w, design):
        super().__init__(spec, content_w, design)
        self.items = (spec.get("items") or [])[:3]

    def _measure_body(self):
        n = max(1, len(self.items))
        gap = 12
        self._colw = (self.cw - gap * (n - 1)) / n
        heights = []
        self._wrapped = []
        for it in self.items:
            pts = [str(p) for p in (it.get("points") or [])][:6]
            wl = [_wrap_lines(f"• {p}", "Helvetica", 9.5, self._colw - 20) for p in pts]
            self._wrapped.append(wl)
            body = sum(len(w) * 13 for w in wl) + 6 * len(wl)
            heights.append(34 + body)
        self._cardh = max(heights) if heights else 60
        return self._cardh + 6

    def _draw_body(self, top):
        c = self.canv
        n = max(1, len(self.items))
        gap = 12
        x = 0
        palette = [self.accent, self.accent2, _shade(self.accent, 0.5)]
        for idx, it in enumerate(self.items):
            col = palette[idx % len(palette)]
            y0 = top - self._cardh
            c.setFillColor(colors.white)
            c.roundRect(x, y0, self._colw, self._cardh, 6, fill=1, stroke=0)
            c.setStrokeColor(col); c.setLineWidth(1.2)
            c.roundRect(x, y0, self._colw, self._cardh, 6, fill=0, stroke=1)
            # header
            c.setFillColor(col)
            c.roundRect(x, top - 26, self._colw, 26, 6, fill=1, stroke=0)
            c.rect(x, top - 26, self._colw, 13, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 10.5)
            lbl = _wrap_lines(it.get("label", ""), "Helvetica-Bold", 10.5, self._colw - 12)[0]
            c.drawCentredString(x + self._colw / 2, top - 18, lbl)
            # points
            ty = top - 40
            c.setFillColor(_INK)
            for wl in self._wrapped[idx]:
                c.setFont("Helvetica", 9.5)
                for ln in wl:
                    c.drawString(x + 10, ty, ln); ty -= 13
                ty -= 6
            x += self._colw + gap


class _Pyramid(_Diagram):
    """Stacked tiers (foundation → top), widest at the bottom."""
    def __init__(self, spec, content_w, design):
        super().__init__(spec, content_w, design)
        self.nodes = [str(n) for n in (spec.get("nodes") or []) if str(n).strip()][:5]

    def _measure_body(self):
        self._tierh = 34
        return len(self.nodes) * (self._tierh + 6)

    def _draw_body(self, top):
        c = self.canv
        n = len(self.nodes)
        if not n:
            return
        cxm = self.cw / 2
        maxw = self.cw * 0.9
        minw = self.cw * 0.34
        y = top - self._tierh
        # draw bottom (foundation) first = last node; nodes[0] is the apex
        for i, label in enumerate(reversed(self.nodes)):
            frac = (i + 1) / n
            w = minw + (maxw - minw) * frac
            col = _shade(self.accent, 0.55 + 0.4 * (1 - frac))
            c.setFillColor(col)
            c.roundRect(cxm - w / 2, y, w, self._tierh, 5, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 10.5)
            lbl = _wrap_lines(label, "Helvetica-Bold", 10.5, w - 16)[0]
            c.drawCentredString(cxm, y + self._tierh / 2 - 4, lbl)
            y -= (self._tierh + 6)


class _Timeline(_Diagram):
    """Horizontal-ish milestone list with a vertical rail and dots."""
    def __init__(self, spec, content_w, design):
        super().__init__(spec, content_w, design)
        self.nodes = [str(n) for n in (spec.get("nodes") or []) if str(n).strip()][:8]

    def _measure_body(self):
        self._rows = [_wrap_lines(n, "Helvetica", 10, self.cw - 70) for n in self.nodes]
        self._rh = [max(26, len(r) * 14 + 10) for r in self._rows]
        return sum(self._rh)

    def _draw_body(self, top):
        c = self.canv
        railx = 24
        c.setStrokeColor(self.accent2); c.setLineWidth(2.5)
        c.line(railx, top - 6, railx, top - sum(self._rh) + 6)
        y = top
        for i, (r, rh) in enumerate(zip(self._rows, self._rh)):
            cyc = y - rh / 2
            c.setFillColor(self.accent)
            c.circle(railx, cyc, 6, fill=1, stroke=0)
            c.setFillColor(_INK)
            c.setFont("Helvetica", 10)
            ty = cyc + (len(r) - 1) * 7
            for ln in r:
                c.drawString(railx + 18, ty - 3.5, ln); ty -= 14
            y -= rh


_TYPES = {
    "process": lambda s, w, d: _Steps(s, w, d, loop=False),
    "steps":   lambda s, w, d: _Steps(s, w, d, loop=False),
    "cycle":   lambda s, w, d: _Steps(s, w, d, loop=True),
    "comparison": _Comparison,
    "vs":         _Comparison,
    "pyramid": _Pyramid,
    "timeline": _Timeline,
}


def build_infographic(spec: Dict, content_w: float, design: Dict) -> Optional[Flowable]:
    """Return a KeepTogether flowable for a diagram spec, or None if unusable."""
    if not isinstance(spec, dict):
        return None
    t = str(spec.get("type", "")).lower().strip()
    maker = _TYPES.get(t)
    if maker is None:
        # unknown type with nodes → default to a process list
        if spec.get("nodes"):
            maker = _TYPES["process"]
        elif spec.get("items"):
            maker = _TYPES["comparison"]
        else:
            return None
    try:
        flow = maker(spec, content_w, design)
        return KeepTogether([flow, Spacer(1, 10)])
    except Exception:
        return None
