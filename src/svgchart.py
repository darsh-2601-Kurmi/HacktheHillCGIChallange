"""SVG chart kit for the diagnosis report (src/report.py): line, horizontal bar, column and scatter charts.

Pure Python, no dependencies, no JavaScript. Every colour comes from a CSS class (s-a, s-b, ...) defined in the
report's stylesheet, so the light and dark themes restyle every chart. Hover text sits in data-tip attributes,
which the report's small script shows as a tooltip. Sizes are in viewBox units (px at the designed width).
"""
from __future__ import annotations

import html
import math


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def nice(lo: float, hi: float, n: int = 5, zero: bool = False) -> tuple[float, float, list[float]]:
    """Round domain [a, b] covering [lo, hi] and its ticks."""
    if zero:
        lo = min(lo, 0.0)
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw * 0.999)
    a = math.floor(lo / step + 1e-9) * step
    b = math.ceil(hi / step - 1e-9) * step
    return a, b, [round(a + i * step, 10) for i in range(round((b - a) / step) + 1)]


def fixed(lo: float, hi: float, n: int = 5) -> tuple[float, float, list[float]]:
    """A given domain with round ticks inside it."""
    return lo, hi, [t for t in nice(lo, hi, n)[2] if lo - 1e-9 <= t <= hi + 1e-9]


class Frame:
    """Maps data to viewBox pixels. m = (top, right, bottom, left) margins."""

    def __init__(self, w, h, m, xd, yd):
        self.w, self.h = w, h
        self.t, self.r, self.b, self.l = m
        self.x0, self.x1 = self.l, w - self.r
        self.y0, self.y1 = h - self.b, self.t          # y0 is the bottom of the plot
        self.xd, self.yd = xd, yd

    def x(self, v):
        a, b = self.xd
        return self.x0 + (v - a) / (b - a) * (self.x1 - self.x0)

    def y(self, v):
        a, b = self.yd
        return self.y0 - (v - a) / (b - a) * (self.y0 - self.y1)


def _svg(w, h, body, label, cls=""):
    return (f'<svg class="chart {cls}" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}">'
            + "".join(body) + "</svg>")


def _ygrid(f, tv, fmt):
    out = []
    for v in tv:
        y = f.y(v)
        out.append(f'<line class="{"bl" if v == 0 else "gl"}" x1="{f.x0}" x2="{f.x1}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="ax" x="{f.x0 - 8}" y="{y + 4.5:.1f}" text-anchor="end">{esc(fmt(v))}</text>')
    return out


def _xgrid(f, tv, fmt):
    out = []
    for v in tv:
        x = f.x(v)
        out.append(f'<line class="{"bl" if v == 0 else "gl"}" x1="{x:.1f}" x2="{x:.1f}" y1="{f.y1}" y2="{f.y0}"/>')
        out.append(f'<text class="ax" x="{x:.1f}" y="{f.y0 + 17}" text-anchor="middle">{esc(fmt(v))}</text>')
    return out


def _spread(items, gap, lo, hi):
    """Push label y positions apart (items: list of [y, ...], sorted in place) inside [lo, hi]."""
    items.sort(key=lambda it: it[0])
    for i in range(1, len(items)):
        items[i][0] = max(items[i][0], items[i - 1][0] + gap)
    over = items[-1][0] - hi if items else 0
    if over > 0:
        for it in items:
            it[0] -= over
        for i in range(len(items) - 2, -1, -1):
            items[i][0] = min(items[i][0], items[i + 1][0] - gap)
    if items and items[0][0] < lo:
        shift = lo - items[0][0]
        for it in items:
            it[0] += shift
    return items


def _tip_rows(rows):
    """Tooltip body: [(css class or None, label, value)]."""
    out = []
    for cls, name, value in rows:
        sw = f'<i class="sw {cls}"></i>' if cls else ""
        out.append(f"<span>{sw}{esc(name)}</span><b>{esc(value)}</b>")
    return "".join(out)


def tip(title, rows) -> str:
    return esc(f"<strong>{esc(title)}</strong><div class=tr>{_tip_rows(rows)}</div>")


def line_chart(xlabels, series, *, fmt, label, xtick=None, xlong=None, domain=None, zero=False, refs=(),
               w=600, h=280, left=50, right=130, top=16, bottom=30, tick_every=4, tip_fmt=None, n_ticks=5,
               end_value=True, end_fmt=None):
    """series: [{key, name, values, cls, end (label), weight: 'thin'|'bold'|None}]; refs: [(value, text)]."""
    n = len(xlabels)
    xtick = xtick or (lambda s: s)
    xlong = xlong or xtick
    tip_fmt = tip_fmt or fmt
    vals = [v for s in series for v in s["values"] if v is not None] + [r[0] for r in refs]
    a, b, tv = fixed(*domain, n_ticks) if domain else nice(min(vals), max(vals), n_ticks, zero)
    f = Frame(w, h, (top, right, bottom, left), (0, n - 1), (a, b))
    out = _ygrid(f, tv, fmt)
    idx = list(range(0, n, tick_every))
    if n - 1 - idx[-1] >= tick_every * 0.6:
        idx.append(n - 1)
    elif idx[-1] != n - 1:
        idx[-1] = n - 1
    for i in idx:
        out.append(f'<text class="ax" x="{f.x(i):.1f}" y="{f.y0 + 19}" text-anchor="middle">{esc(xtick(xlabels[i]))}</text>')
    for v, text in refs:
        y = f.y(v)
        out.append(f'<line class="ref" x1="{f.x0}" x2="{f.x1}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text class="refl" x="{f.x1 - 4}" y="{y - 6:.1f}" text-anchor="end">{esc(text)}</text>')
    # hover bands (under the lines so the lines stay crisp)
    step = (f.x1 - f.x0) / max(1, n - 1)
    for i in range(n):
        rows = [(s["cls"], s["name"], tip_fmt(s["values"][i])) for s in series if s["values"][i] is not None]
        x = f.x(i) - step / 2
        out.append(f'<rect class="hov" x="{max(f.x0 - 4, x):.1f}" y="{f.y1}" width="{step:.1f}" '
                   f'height="{f.y0 - f.y1}" data-tip="{tip(xlong(xlabels[i]), rows)}"/>')
    ends = []
    for s in series:
        pts = [(f.x(i), f.y(v)) for i, v in enumerate(s["values"]) if v is not None]
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        wcls = s.get("weight") or ""
        g = [f'<g class="{s["cls"]}" data-s="{esc(s["key"])}">',
             f'<path class="ln {wcls}" d="{d}"/>']
        if wcls != "thin":
            g.append(f'<circle class="dot" cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="4"/>')
        g.append("</g>")
        out.extend(g)
        last = next(v for v in reversed(s["values"]) if v is not None)
        text = s.get("end", s["name"])
        if text is not None:
            ends.append([pts[-1][1], pts[-1][1], s, text, last])
    if ends:
        _spread(ends, 15, f.y1 + 4, f.y0)
        for ly, py, s, text, last in ends:
            x = f.x1
            val = f' <tspan class="v">{esc((end_fmt or tip_fmt)(last))}</tspan>' if end_value else ""
            out.append(f'<g class="{s["cls"]}" data-s="{esc(s["key"])}">'
                       + (f'<line class="lead" x1="{x + 5}" x2="{x + 9}" y1="{py:.1f}" y2="{ly:.1f}"/>'
                          if abs(ly - py) > 3 else "")
                       + f'<text class="dl" x="{x + 11}" y="{ly + 4.5:.1f}">{esc(text)}{val}</text></g>')
    return _svg(w, h, out, label, "multi" if len(series) > 1 else "")


def hbar_chart(rows, *, fmt, label, domain=None, w=600, row_h=30, label_w=180, right=64, top=6, bottom=26,
               refs=(), bar=0.64, n_ticks=5, axis=True, tip_fmt=None, vfmt=None, value_col=False):
    """rows: [{label, value, cls, tip (optional list of extra (name, value))}]; refs: [(value, text)]."""
    tip_fmt, vfmt = tip_fmt or fmt, vfmt or fmt
    vals = [r["value"] for r in rows] + [r[0] for r in refs]
    a, b, tv = fixed(*domain, n_ticks) if domain else nice(0, max(vals), n_ticks, True)
    h = top + len(rows) * row_h + (bottom if axis else 6)
    f = Frame(w, h, (top, right, bottom if axis else 6, label_w), (a, b), (0, 1))
    out = _xgrid(f, tv, fmt) if axis else []
    bh = row_h * bar
    for i, r in enumerate(rows):
        yc = top + (i + 0.5) * row_h
        x0, x1 = f.x(max(a, 0)), f.x(r["value"])
        extra = [(None, k, v) for k, v in r.get("tip", [])]
        t = tip(r["label"], [(r["cls"], r.get("measure", label), tip_fmt(r["value"]))] + extra)
        out.append(f'<g class="{r["cls"]}" data-tip="{t}">'
                   f'<rect class="hov" x="0" y="{yc - row_h / 2:.1f}" width="{w}" height="{row_h}"/>'
                   f'<text class="cl" x="{label_w - 10}" y="{yc + 4.5:.1f}" text-anchor="end">{esc(r["label"])}</text>'
                   f'<rect class="bar" x="{min(x0, x1):.1f}" y="{yc - bh / 2:.1f}" width="{max(abs(x1 - x0), 1.5):.1f}" height="{bh:.1f}" rx="2"/>'
                   f'<text class="vl" x="{(f.x1 + 8) if value_col else (max(x0, x1) + 6):.1f}" y="{yc + 4.5:.1f}">'
                   f'{esc(vfmt(r["value"]))}</text></g>')
    for v, text in refs:
        x = f.x(v)
        out.append(f'<line class="ref" x1="{x:.1f}" x2="{x:.1f}" y1="{f.y1 - 2}" y2="{f.y0}"/>'
                   + (f'<text class="refl" x="{x + 5:.1f}" y="{f.y0 + 17}">{esc(text)}</text>' if text else ""))
    return _svg(w, h, out, label)


def column_chart(rows, *, fmt, label, domain=None, w=600, h=260, left=50, right=12, top=22, bottom=34, refs=(),
                 n_ticks=5, bar=0.6, tip_fmt=None, vfmt=None):
    """rows: [{label, value, cls, tip (optional list of extra (name, value))}]."""
    tip_fmt, vfmt = tip_fmt or fmt, vfmt or fmt
    vals = [r["value"] for r in rows] + [r[0] for r in refs]
    a, b, tv = fixed(*domain, n_ticks) if domain else nice(0, max(vals), n_ticks, True)
    f = Frame(w, h, (top, right, bottom, left), (0, len(rows)), (a, b))
    out = _ygrid(f, tv, fmt)
    cw = (f.x1 - f.x0) / len(rows)
    for i, r in enumerate(rows):
        xc = f.x0 + (i + 0.5) * cw
        y0, y1 = f.y(max(a, 0)), f.y(r["value"])
        extra = [(None, k, v) for k, v in r.get("tip", [])]
        t = tip(r["label"], [(r["cls"], r.get("measure", label), tip_fmt(r["value"]))] + extra)
        out.append(f'<g class="{r["cls"]}" data-tip="{t}">'
                   f'<rect class="hov" x="{xc - cw / 2:.1f}" y="{f.y1 - top}" width="{cw:.1f}" height="{h - f.y1 + top}"/>'
                   f'<rect class="bar" x="{xc - cw * bar / 2:.1f}" y="{min(y0, y1):.1f}" width="{cw * bar:.1f}" height="{max(abs(y1 - y0), 1.5):.1f}" rx="2"/>'
                   f'<text class="vl" x="{xc:.1f}" y="{min(y0, y1) - 7:.1f}" text-anchor="middle">{esc(vfmt(r["value"]))}</text>'
                   f'<text class="cl" x="{xc:.1f}" y="{f.y0 + 20}" text-anchor="middle">{esc(r["label"])}</text></g>')
    for v, text in refs:
        y = f.y(v)
        out.append(f'<line class="ref" x1="{f.x0}" x2="{f.x1}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text class="refl" x="{f.x1}" y="{y - 6:.1f}" text-anchor="end">{esc(text)}</text>')
    return _svg(w, h, out, label)


def scatter(points, *, x_fmt, y_fmt, label, x_title, y_title, x_domain=None, y_domain=None, fit=None,
            fit_text=None, callouts=(), w=600, h=300, left=50, right=24, top=30, bottom=46, cls="s-a"):
    """points: [{x, y, tip_title}]; fit: (slope, intercept); callouts: [(index, text, dx, dy)]."""
    xs, ys = [p["x"] for p in points], [p["y"] for p in points]
    xa, xb, xt = fixed(*x_domain) if x_domain else nice(min(xs), max(xs))
    ya, yb, yt = fixed(*y_domain) if y_domain else nice(min(ys), max(ys))
    f = Frame(w, h, (top, right, bottom, left), (xa, xb), (ya, yb))
    out = _ygrid(f, yt, y_fmt)
    for v in xt:
        x = f.x(v)
        out.append(f'<line class="gl" x1="{x:.1f}" x2="{x:.1f}" y1="{f.y1}" y2="{f.y0}"/>'
                   f'<text class="ax" x="{x:.1f}" y="{f.y0 + 18}" text-anchor="middle">{esc(x_fmt(v))}</text>')
    out.append(f'<text class="at" x="{(f.x0 + f.x1) / 2:.1f}" y="{h - 6}" text-anchor="middle">{esc(x_title)}</text>'
               f'<text class="at" x="{f.x0 - 8}" y="{top - 14}">{esc(y_title)}</text>')
    if fit:
        m, c0 = fit
        xa_, xb_ = min(xs), max(xs)
        out.append(f'<line class="fit" x1="{f.x(xa_):.1f}" y1="{f.y(m * xa_ + c0):.1f}" '
                   f'x2="{f.x(xb_):.1f}" y2="{f.y(m * xb_ + c0):.1f}"/>')
        if fit_text:                                   # top-right: the empty corner when the slope is negative
            out.append(f'<text class="refl" x="{f.x1 - 4}" y="{f.y1 + 14}" text-anchor="end">{esc(fit_text)}</text>')
    out.append(f'<g class="{cls}">')
    for p in points:
        t = tip(p["tip_title"], [(cls, y_title, y_fmt(p["y"])), (None, x_title, x_fmt(p["x"]))])
        out.append(f'<circle class="pt" cx="{f.x(p["x"]):.1f}" cy="{f.y(p["y"]):.1f}" r="6" data-tip="{t}"/>')
    out.append("</g>")
    for i, text, dx, dy in callouts:
        p = points[i]
        x, y = f.x(p["x"]), f.y(p["y"])
        out.append(f'<text class="dl" x="{x + dx:.1f}" y="{y + dy:.1f}" text-anchor="{"end" if dx < 0 else "start"}">'
                   f'{esc(text)}</text>')
    return _svg(w, h, out, label)
