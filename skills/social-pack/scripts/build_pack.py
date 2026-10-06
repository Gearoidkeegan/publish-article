#!/usr/bin/env python
"""Render a social pack (carousel slides + single images) from a JSON spec.

Usage:
    python build_pack.py <deck.json> [--theme theme.json] [--out DIR] [--check]

  deck.json   the slides and single images (see ../SPEC.md)
  theme.json  colours, fonts, logo, brand line (default: neutral theme)
  --out       output folder (default: <deck dir>/social-pack)
  --check     run the fit check only, write no images

Output:
  01-<name>.png ...     one PNG per carousel slide
  carousel.pdf          the slides as one PDF (LinkedIn document posts want this)
  <name>.png            each single image (quote card, link image)
  contact-sheet.png     every output on one sheet, for a quick look

FIT CHECK. Before anything is rendered, every page is loaded in headless Chrome
and probed for content that overflows its box (text sliding under the band,
a table pushing the footer off the slide, a heading running off the right
edge). Flex layouts do not shrink content, they let it slide underneath, so
this is the only reliable way to catch it. Any overflow over 4px is reported
with the slide and the element, and the build stops (exit code 2). Sub-pixel
line-height rounding makes text report 1-2px forever, hence the threshold.
Text-only elements are checked for width only: their glyphs hang past a tight
line-height, which is ink, not a layout overflow.

Requires Python 3, Pillow, and Chrome or Edge.
"""
import argparse
import html
import io
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow not installed. Run: python -m pip install Pillow")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

FORMATS = {"square": (1080, 1080), "portrait": (1080, 1350)}
SINGLE_SIZES = {"quote": (1080, 1080), "link": (1200, 627)}

DEFAULT_THEME = {
    "colors": {
        "bg": "#FFFFFF", "ink": "#16181D", "body": "#454A54", "muted": "#8A8F99",
        "rule": "#E3E5E8", "accent": "#2563EB", "band": "#2563EB",
        "band_ink": "#FFFFFF", "paper": "#F7F8FA",
        # chart series: blue, orange, slate - distinguishable with common colour-vision deficiencies
        "series": ["#2563EB", "#D97706", "#475569"],
    },
    "fonts": {
        "heading": {"family": "Segoe UI, Helvetica Neue, Arial, sans-serif", "weight": 700},
        "body": {"family": "Segoe UI, Helvetica Neue, Arial, sans-serif"},
        "mono": {"family": "Consolas, SFMono-Regular, Menlo, monospace"},
    },
    "logo": None,
    "brand": "",
    "tagline": "",
    "url": "",
}

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge",
]

PROBE_JS = """<script>addEventListener('load',function(){document.fonts.ready.then(function(){
  var out=[], s=document.querySelector('.slide');
  var so=s.scrollHeight-s.clientHeight; if(so>4) out.push('whole slide:'+so);
  document.querySelectorAll('.mid, .mid *, .band, .foot, .foot *').forEach(function(e){
    if(e instanceof SVGElement) return;
    // a text-only element's glyphs hang past a tight line-height; that is ink, not
    // layout, so leaves are checked for width only and containers for both
    var leaf=!e.firstElementChild || e.tagName=='H1';
    var o=Math.max(leaf?0:e.scrollHeight-e.clientHeight, e.scrollWidth-e.clientWidth);
    if(o>4) out.push((e.className||e.tagName)+':'+o);
  });
  document.body.setAttribute('data-overflow', out.join('|'));
});});</script>"""


# ------------------------------------------------------------------ helpers
def file_url(path):
    return "file:///" + os.path.abspath(path).replace("\\", "/").lstrip("/")


def text(s):
    """Escape spec text, then allow **bold** (the only markup the spec takes)."""
    s = html.escape(str(s or ""), quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def mix(hex_c, a, onto):
    """Flatten hex_c at opacity a onto a surface, so the PDF carries no alpha."""
    def rgb(h):
        h = h.lstrip("#")
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    c, b = rgb(hex_c), rgb(onto)
    return "#%02X%02X%02X" % tuple(round(c[i] * a + b[i] * (1 - a)) for i in range(3))


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_theme(path):
    if not path:
        return DEFAULT_THEME, os.getcwd()
    with io.open(path, encoding="utf-8") as fh:
        return merge(DEFAULT_THEME, json.load(fh)), os.path.dirname(os.path.abspath(path))


def font_faces(theme, base):
    """@font-face rules for local font files named in the theme. Headless Chrome
    loads nothing over a relative path, so every src is an absolute file:/// URL."""
    rules, links = [], []
    for role in ("heading", "body", "mono"):
        f = theme["fonts"].get(role) or {}
        if f.get("css_url"):
            links.append("<link rel='stylesheet' href='%s'>" % html.escape(f["css_url"]))
        for weight, rel in (f.get("files") or {}).items():
            p = rel if os.path.isabs(rel) else os.path.join(base, rel)
            if not os.path.exists(p):
                sys.exit("font file not found: %s" % p)
            rules.append("@font-face { font-family:'%s'; src:url('%s'); font-weight:%s; }"
                         % (f["family"].split(",")[0].strip().strip("'\""), file_url(p), weight))
    return "\n".join(rules), "".join(links)


def family(theme, role):
    return theme["fonts"][role]["family"]


# --------------------------------------------------------------------- CSS
CSS = string.Template("""
$faces
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:${W}px; height:${H}px; }
body { background:$bg; color:$ink; font-family:$body_f; -webkit-font-smoothing:antialiased; }
b { color:$ink; font-weight:700; }
/* balanced wrapping: no single orphaned word on a heading's last line */
h1, .sub, .band, .quote .q, .card .t, .pt .t { text-wrap:balance; }
.slide { width:${W}px; height:${H}px; padding:64px 68px 56px; display:flex; flex-direction:column; }

.top { display:flex; justify-content:space-between; align-items:flex-start; }
.eyebrow { font-family:$mono_f; font-weight:600; font-size:18px; letter-spacing:.14em;
           text-transform:uppercase; color:$accent; border-bottom:3px solid $accent; padding-bottom:9px; }
.count { font-family:$mono_f; font-size:18px; letter-spacing:.14em; color:$muted; }
.rail { display:flex; gap:8px; margin-top:28px; }
.rail i { flex:1; height:8px; border-radius:2px; background:$rail; }
.rail i.on { background:$accent; }

.mid { flex:1; min-height:0; display:flex; flex-direction:column; }
.kicker { font-family:$mono_f; font-weight:600; font-size:17px; letter-spacing:.15em;
          text-transform:uppercase; color:$accent; margin-top:30px; }
h1 { font-family:$head_f; font-weight:$head_w; font-size:52px; line-height:1.08;
     letter-spacing:-.018em; margin-top:10px; }
/* the sub is pinned to two lines so the stage starts at the same y on every slide */
.sub { font-size:25px; color:$body; margin-top:12px; line-height:1.36; min-height:calc(2 * 1.36em); }
.stage { flex:1; min-height:0; margin-top:22px; display:flex; flex-direction:column; }

/* cover */
.t-cover .mid { justify-content:center; }
.t-cover h1 { font-size:80px; line-height:1.04; }
.t-cover .sub { font-size:30px; min-height:0; margin-top:24px; }

/* points: number | title | text rows */
.points { justify-content:center; }
.pt { display:grid; grid-template-columns:84px 290px minmax(0,1fr); align-items:center;
      padding:20px 0; border-top:1px solid $rule; }
.pt:last-child { border-bottom:1px solid $rule; }
.pt .n { font-family:$head_f; font-weight:$head_w; font-size:38px; color:$accent; }
.pt .t { font-family:$head_f; font-weight:$head_w; font-size:29px; line-height:1.12; padding-right:18px; }
.pt .d { font-size:23px; line-height:1.4; color:$body; }
.points.noti .pt { grid-template-columns:84px minmax(0,1fr); }

/* cards: 2-4 boxes */
.cards { display:grid; gap:16px; }
.card { background:$paper; border:1px solid $rule; border-top:5px solid $accent; padding:26px 28px; }
.card .l { font-family:$mono_f; font-weight:600; font-size:16px; letter-spacing:.12em;
           text-transform:uppercase; color:$accent; }
.card .t { font-family:$head_f; font-weight:$head_w; font-size:31px; line-height:1.12; margin-top:8px; }
.card .d { font-size:22px; line-height:1.42; color:$body; margin-top:10px; }

/* stat: 1-3 big numbers */
.stats { display:grid; gap:20px; align-content:center; }
.st { border-left:6px solid $accent; padding:6px 0 6px 26px; }
.st .v { font-family:$head_f; font-weight:$head_w; font-size:132px; line-height:1; color:$accent;
         letter-spacing:-.02em; }
.st .l { font-family:$head_f; font-weight:$head_w; font-size:32px; margin-top:20px; }
.st .d { font-size:23px; line-height:1.4; color:$body; margin-top:8px; }
.stats.many .st .v { font-size:84px; }

/* quote */
.quote { justify-content:center; }
.quote .mk { font-family:Georgia, serif; font-size:150px; line-height:.7; color:$accent; margin-bottom:-30px; }
.quote .q { font-family:$head_f; font-weight:$head_w; font-size:52px; line-height:1.2; letter-spacing:-.01em; }
.quote .by { font-family:$mono_f; font-size:18px; letter-spacing:.12em; text-transform:uppercase;
             color:$muted; margin-top:26px; }

/* table */
.tbl { width:100%; border-collapse:collapse; font-size:23px; }
.tbl th { font-family:$mono_f; font-weight:600; font-size:16px; letter-spacing:.1em;
          text-transform:uppercase; color:$muted; text-align:left; padding:0 14px 12px 0;
          border-bottom:2px solid $ink; }
.tbl td { padding:20px 14px 20px 0; border-bottom:1px solid $rule; line-height:1.35;
          color:$body; vertical-align:top; }
.tbl td:first-child { font-weight:700; color:$ink; }

/* bars */
.bars { justify-content:center; }
.br { display:grid; grid-template-columns:310px minmax(0,1fr) 130px; align-items:center;
      gap:20px; padding:16px 0; }
.br .t { font-size:24px; line-height:1.25; font-weight:600; }
.br .tr { height:44px; background:$track; border-radius:3px; }
.br .f { height:100%; background:$accent; border-radius:3px; }
.br .v { font-family:$head_f; font-weight:$head_w; font-size:34px; text-align:right; }
.note { font-size:18px; color:$muted; margin-top:14px; }

/* line chart */
.key { flex:none; display:flex; flex-wrap:wrap; gap:8px 26px; font-size:21px; color:$body; }
.key span { display:inline-flex; align-items:center; gap:9px; }
.key i { display:block; width:26px; height:4px; border-radius:2px; }
.plot { flex:1; min-height:0; margin-top:14px; }
.plot svg { width:100%; height:100%; display:block; overflow:visible; }
svg text { font-family:$mono_f; font-size:18px; fill:$muted; }
svg .ev { font-family:$body_f; font-weight:700; font-size:21px; paint-order:stroke;
          stroke:$bg; stroke-width:6px; stroke-linejoin:round; }

/* image */
.imgbox { flex:1; min-height:0; display:flex; align-items:center; justify-content:center; }
.imgbox img { max-width:100%; max-height:100%; object-fit:contain; border:1px solid $rule; }

/* call to action */
.t-cta .mid { justify-content:center; }
.t-cta h1 { font-size:70px; }
.t-cta .sub { font-size:28px; min-height:0; }
.t-cta .go { font-family:$mono_f; font-weight:600; font-size:26px; letter-spacing:.06em;
           color:$accent; margin-top:34px; word-break:break-all; }

/* the band is pinned so its top edge holds still as you swipe */
.band { background:$band; color:$band_ink; font-family:$head_f; font-weight:$head_w;
        font-size:27px; line-height:1.28; padding:22px 26px; margin-top:22px;
        min-height:${band_h}px; display:flex; align-items:center; }

.foot { margin-top:22px; padding-top:18px; border-top:1px solid $rule;
        display:flex; justify-content:space-between; align-items:center; gap:24px; }
.lock { display:flex; align-items:center; gap:16px; min-width:0; }
.lock img { height:40px; }
.brand { font-family:$head_f; font-weight:$head_w; font-size:26px; }
.tagline { font-family:$mono_f; font-size:13px; letter-spacing:.1em; text-transform:uppercase;
           color:$muted; line-height:1.45; }
.url { font-family:$mono_f; font-size:17px; letter-spacing:.06em; color:$muted; white-space:nowrap; }

/* link image (landscape, e.g. 1200x627) */
.slide.link { padding:56px 64px 44px; }
.slide.link h1 { font-size:66px; }
""")


def build_css(theme, base, size, band_lines):
    c = theme["colors"]
    faces, links = font_faces(theme, base)
    head = theme["fonts"]["heading"]
    css = CSS.substitute(
        faces=faces, W=size[0], H=size[1], bg=c["bg"], ink=c["ink"], body=c["body"],
        muted=c["muted"], rule=c["rule"], accent=c["accent"], band=c["band"],
        band_ink=c["band_ink"], paper=c["paper"],
        rail=mix(c["accent"], .22, c["bg"]), track=mix(c["accent"], .12, c["bg"]),
        body_f=family(theme, "body"), head_f=family(theme, "heading"),
        mono_f=family(theme, "mono"), head_w=head.get("weight", 700),
        band_h=round(27 * 1.28 * band_lines + 44))
    return css, links


# ------------------------------------------------------------------ stages
def st_points(s, theme, base):
    items = s["items"]
    noti = all(not it.get("title") for it in items)
    rows = []
    for i, it in enumerate(items, 1):
        cells = "<div class='n'>%02d</div>" % i
        if not noti:
            cells += "<div class='t'>%s</div>" % text(it.get("title"))
        cells += "<div class='d'>%s</div>" % text(it.get("text"))
        rows.append("<div class='pt'>%s</div>" % cells)
    return "<div class='stage points%s'>%s</div>" % (" noti" if noti else "", "".join(rows))


def st_cards(s, theme, base):
    items = s["items"]
    if not 2 <= len(items) <= 4:
        sys.exit("cards slide '%s' needs 2-4 items" % s.get("name"))
    cols = 2 if len(items) == 4 else len(items)
    rows = 2 if len(items) == 4 else 1
    cards = "".join(
        "<div class='card'>%s<div class='t'>%s</div><div class='d'>%s</div></div>"
        % (("<div class='l'>%s</div>" % text(it["label"])) if it.get("label") else "",
           text(it.get("title")), text(it.get("text"))) for it in items)
    return ("<div class='stage cards' style='grid-template-columns:repeat(%d,1fr);"
            "grid-template-rows:repeat(%d,1fr)'>%s</div>" % (cols, rows, cards))


def st_stat(s, theme, base):
    items = s["items"]
    many = " many" if len(items) > 1 else ""
    return "<div class='stage stats%s'>%s</div>" % (many, "".join(
        "<div class='st'><div class='v'>%s</div><div class='l'>%s</div>%s</div>"
        % (text(it["value"]), text(it.get("label")),
           ("<div class='d'>%s</div>" % text(it["text"])) if it.get("text") else "")
        for it in items))


def st_quote(s, theme, base):
    return ("<div class='stage quote'><div class='mk'>&ldquo;</div><div class='q'>%s</div>%s</div>"
            % (text(s["quote"]), ("<div class='by'>%s</div>" % text(s["by"])) if s.get("by") else ""))


def st_table(s, theme, base):
    head = "".join("<th>%s</th>" % text(c) for c in s["columns"])
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % text(v) for v in row)
                   for row in s["rows"])
    note = ("<div class='note'>%s</div>" % text(s["note"])) if s.get("note") else ""
    return ("<div class='stage' style='justify-content:center'><table class='tbl'><thead><tr>%s</tr></thead>"
            "<tbody>%s</tbody></table>%s</div>" % (head, body, note))


def st_bars(s, theme, base):
    items = s["items"]
    if any(it["value"] < 0 for it in items):
        sys.exit("bars slide '%s': negative values are not supported; use a table" % s.get("name"))
    top = max(it["value"] for it in items) or 1
    unit = s.get("unit", "")
    rows = "".join(
        "<div class='br'><div class='t'>%s</div><div class='tr'><div class='f' style='width:%.1f%%'>"
        "</div></div><div class='v'>%s</div></div>"
        % (text(it["label"]), 100.0 * it["value"] / top,
           text(it.get("display") or ("%s%s" % (fmt(it["value"]), unit)))) for it in items)
    note = ("<div class='note'>%s</div>" % text(s["note"])) if s.get("note") else ""
    return "<div class='stage bars'>%s%s</div>" % (rows, note)


def fmt(v):
    return ("%d" % v) if float(v).is_integer() else ("%g" % v)


def nice_ticks(lo, hi, n=5):
    span = (hi - lo) or abs(hi) or 1
    raw = span / n
    mag = 10 ** int(("%e" % raw).split("e")[1])
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    start = step * int(lo // step)
    ticks, t = [], start
    while t <= hi + step * 0.001:
        ticks.append(round(t, 10))
        t += step
    if ticks[-1] < hi:
        ticks.append(round(ticks[-1] + step, 10))
    return ticks


def st_line(s, theme, base, tall=False):
    """A line chart. x is categorical (labels in order); up to three series.
    The key names every series in full - a short label nobody can decode is worse
    than a long one."""
    series, xs = s["series"], s["x"]
    if not 1 <= len(series) <= 3:
        sys.exit("line slide '%s' takes 1-3 series" % s.get("name"))
    cols = theme["colors"]["series"]
    vals = [v for se in series for v in se["values"] if v is not None]
    ticks = nice_ticks(min(min(vals), 0) if s.get("zero", True) else min(vals), max(vals))
    W, H = 944, (640 if tall else 420)
    x0, x1, y0, y1 = 70, W - 150, 12, H - 44
    lo, hi = ticks[0], ticks[-1]

    def X(i):
        return x0 + (x1 - x0) * i / max(len(xs) - 1, 1)

    def Y(v):
        return y1 - (y1 - y0) * (v - lo) / ((hi - lo) or 1)
    unit = s.get("unit", "")
    o = []
    for t in ticks:
        o.append("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' stroke='%s'/>"
                 % (x0, Y(t), x1, Y(t), theme["colors"]["rule"]))
        o.append("<text x='%.1f' y='%.1f' text-anchor='end' dominant-baseline='middle'>%s%s</text>"
                 % (x0 - 10, Y(t), fmt(t), html.escape(unit)))
    every = max(1, -(-len(xs) // 8))                     # at most ~8 x labels
    for i, lab in enumerate(xs):
        if i % every == 0 or i == len(xs) - 1:
            o.append("<text x='%.1f' y='%.1f' text-anchor='middle'>%s</text>"
                     % (X(i), y1 + 32, html.escape(str(lab))))
    ends = []
    for k, se in enumerate(series):
        pts = [(X(i), Y(v)) for i, v in enumerate(se["values"]) if v is not None]
        d = " ".join("%s%.1f,%.1f" % ("M" if j == 0 else "L", x, y) for j, (x, y) in enumerate(pts))
        o.append("<path d='%s' fill='none' stroke='%s' stroke-width='3.5' stroke-linejoin='round'"
                 " stroke-linecap='round'/>" % (d, cols[k % len(cols)]))
        last = [v for v in se["values"] if v is not None][-1]
        ends.append([pts[-1][1], pts[-1], cols[k % len(cols)], "%s%s" % (fmt(last), unit)])
    ends.sort(key=lambda e: e[0])                        # nudge end labels apart
    for j in range(1, len(ends)):
        ends[j][0] = max(ends[j][0], ends[j - 1][0] + 28)
    for ly, (px, py), col, lab in ends:
        o.append("<circle cx='%.1f' cy='%.1f' r='5' fill='%s'/>" % (px, py, col))
        o.append("<text class='ev' x='%.1f' y='%.1f' dominant-baseline='middle' fill='%s'>%s</text>"
                 % (x1 + 16, ly, col, html.escape(lab)))
    key = "".join("<span><i style='background:%s'></i>%s</span>" % (cols[k % len(cols)], text(se["name"]))
                  for k, se in enumerate(series))
    note = ("<div class='note'>%s</div>" % text(s["note"])) if s.get("note") else ""
    return ("<div class='stage'><div class='key'>%s</div><div class='plot'><svg viewBox='0 0 %d %d'"
            " preserveAspectRatio='xMidYMid meet'>%s</svg></div>%s</div>" % (key, W, H, "".join(o), note))


def st_image(s, theme, base):
    p = s["src"] if os.path.isabs(s["src"]) else os.path.join(base, s["src"])
    if not os.path.exists(p):
        sys.exit("image not found: %s" % p)
    note = ("<div class='note'>%s</div>" % text(s["caption"])) if s.get("caption") else ""
    return "<div class='stage'><div class='imgbox'><img src='%s'></div>%s</div>" % (file_url(p), note)


STAGES = {"points": st_points, "cards": st_cards, "stat": st_stat, "quote": st_quote,
          "table": st_table, "bars": st_bars, "line": st_line, "image": st_image}


# ------------------------------------------------------------------- pages
def foot(theme, url):
    lock = []
    if theme.get("logo"):
        lock.append("<img src='%s'>" % file_url(theme["_logo"]))
    elif theme.get("brand"):
        lock.append("<div class='brand'>%s</div>" % text(theme["brand"]))
    if theme.get("tagline"):
        lock.append("<div class='tagline'>%s</div>" % text(theme["tagline"]))
    return ("<div class='foot'><div class='lock'>%s</div><div class='url'>%s</div></div>"
            % ("".join(lock), text(url)))


def slide_html(s, n, total, deck, theme, base):
    kind = s["type"]
    top = "<div class='top'><div class='eyebrow'>%s</div>%s</div>" % (
        text(deck.get("eyebrow", "")),
        ("<div class='count'>%02d / %d</div>" % (n, total)) if total > 1 else "")
    rail = ("<div class='rail'>%s</div>" % "".join(
        "<i class='on'></i>" if i == n else "<i></i>" for i in range(1, total + 1))) if total > 1 else ""
    kicker = ("<div class='kicker'>%s</div>" % text(s["kicker"])) if s.get("kicker") else ""
    h1 = ("<h1>%s</h1>" % text(s["title"])) if s.get("title") else ""
    sub = ("<div class='sub'>%s</div>" % text(s["sub"])) if s.get("sub") else ""
    if kind == "cover":
        mid = kicker + h1 + sub
    elif kind == "cta":
        mid = kicker + h1 + sub + "<div class='go'>%s</div>" % text(s.get("url") or deck.get("url", ""))
    elif kind == "line":
        mid = kicker + h1 + sub + st_line(s, theme, base, deck.get("format") == "portrait")
    elif kind in STAGES:
        mid = kicker + h1 + sub + STAGES[kind](s, theme, base)
    else:
        sys.exit("unknown slide type '%s' (use: cover, cta, %s)" % (kind, ", ".join(STAGES)))
    band = ("<div class='band'>%s</div>" % text(s["band"])) if s.get("band") else ""
    return ("<div class='slide t-%s'>%s%s<div class='mid'>%s</div>%s%s</div>"
            % (kind, top, rail, mid, band, foot(theme, s.get("url") or deck.get("url", ""))))


def link_html(s, deck, theme, base):
    kicker = ("<div class='kicker'>%s</div>" % text(s["kicker"])) if s.get("kicker") else ""
    return ("<div class='slide link'><div class='top'><div class='eyebrow'>%s</div></div>"
            "<div class='mid' style='justify-content:center'>%s<h1>%s</h1></div>%s</div>"
            % (text(deck.get("eyebrow", "")), kicker, text(s["title"]),
               foot(theme, s.get("url") or deck.get("url", ""))))


def page(css, links, body, probe):
    return ("<!doctype html><html><head><meta charset='utf-8'>%s<style>%s</style></head>"
            "<body>%s%s</body></html>" % (links, css, body, PROBE_JS if probe else ""))


# ------------------------------------------------------------------ chrome
def browser():
    for c in BROWSERS:
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        elif shutil.which(c):
            return shutil.which(c)
    sys.exit("No Chrome or Edge found. Install one, or add its path to BROWSERS.")


def chrome(b, args, hp):
    return subprocess.run(
        [b, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--allow-file-access-from-files", "--virtual-time-budget=8000"] + args + [file_url(hp)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe(b, hp, size):
    r = chrome(b, ["--window-size=%d,%d" % size, "--dump-dom"], hp)
    m = re.search(r'data-overflow="([^"]*)"', r.stdout)
    if m is None:
        return ["probe did not run (page failed to load?)"]
    return [x for x in html.unescape(m.group(1)).split("|") if x]


def shoot(b, hp, png, size):
    if os.path.exists(png):
        os.remove(png)
    chrome(b, ["--window-size=%d,%d" % size, "--screenshot=" + png], hp)
    for _ in range(80):
        if os.path.exists(png) and os.path.getsize(png) > 0:
            return
        time.sleep(0.25)
    sys.exit("screenshot failed: %s" % png)


def contact_sheet(pngs, out):
    thumbs = []
    for p in pngs:
        im = Image.open(p).convert("RGB")
        im.thumbnail((360, 450))
        thumbs.append(im)
    cols = min(4, len(thumbs))
    rows = -(-len(thumbs) // cols)
    cw, ch = 360 + 24, max(t.height for t in thumbs) + 24
    sheet = Image.new("RGB", (cols * cw + 24, rows * ch + 24), (200, 200, 200))
    for i, t in enumerate(thumbs):
        sheet.paste(t, (24 + (i % cols) * cw, 24 + (i // cols) * ch))
    sheet.save(out)


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("--theme")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    with io.open(a.deck, encoding="utf-8") as fh:
        deck = json.load(fh)
    base = os.path.dirname(os.path.abspath(a.deck))
    theme, tbase = load_theme(a.theme)
    if theme.get("logo"):
        lp = theme["logo"] if os.path.isabs(theme["logo"]) else os.path.join(tbase, theme["logo"])
        if not os.path.exists(lp):
            sys.exit("logo not found: %s" % lp)
        theme["_logo"] = lp
    deck.setdefault("url", theme.get("url", ""))
    size = FORMATS.get(deck.get("format", "square"))
    if size is None:
        sys.exit("format must be one of: %s" % ", ".join(FORMATS))
    out = os.path.abspath(a.out or os.path.join(base, "social-pack"))   # Chrome resolves relative paths from its own folder
    os.makedirs(out, exist_ok=True)
    b = browser()
    tmp = tempfile.mkdtemp(prefix="social-pack-")

    jobs = []                                            # (name, html, size)
    slides = deck.get("slides", [])
    css, links = build_css(theme, tbase, size, deck.get("band_lines", 2))
    for n, s in enumerate(slides, 1):
        name = "%02d-%s" % (n, re.sub(r"[^a-z0-9]+", "-", (s.get("name") or s["type"]).lower()).strip("-"))
        jobs.append((name, lambda p, s=s, n=n: page(css, links, slide_html(s, n, len(slides), deck, theme, tbase), p), size))
    for s in deck.get("singles", []):
        ssize = SINGLE_SIZES.get(s["type"])
        if ssize is None:
            sys.exit("single type must be one of: %s" % ", ".join(SINGLE_SIZES))
        scss, slinks = build_css(theme, tbase, ssize, deck.get("band_lines", 2))
        body = (link_html(s, deck, theme, tbase) if s["type"] == "link"
                else slide_html(dict(s, type="quote"), 1, 1, deck, theme, tbase))
        jobs.append((s.get("name") or s["type"], lambda p, c=scss, l=slinks, bd=body: page(c, l, bd, p), ssize))

    failed = False
    for name, make, sz in jobs:
        hp = os.path.join(tmp, name + ".html")
        with io.open(hp, "w", encoding="utf-8") as fh:
            fh.write(make(True))
        problems = probe(b, hp, sz)
        if problems:
            failed = True
            print("OVERFLOW %s: %s" % (name, "; ".join(problems)))
    if failed:
        print("Fit check FAILED. Shorten the text or split the slide, then rebuild.")
        sys.exit(2)
    print("fit check passed (%d pages)" % len(jobs))
    if a.check:
        return

    pngs, slide_pngs = [], []
    for name, make, sz in jobs:
        hp = os.path.join(tmp, name + ".html")
        with io.open(hp, "w", encoding="utf-8") as fh:
            fh.write(make(False))
        png = os.path.join(out, name + ".png")
        shoot(b, hp, png, sz)
        pngs.append(png)
        if name[:2].isdigit():
            slide_pngs.append(png)
    if len(slide_pngs) > 1:
        ims = [Image.open(p).convert("RGB") for p in slide_pngs]
        ims[0].save(os.path.join(out, "carousel.pdf"), "PDF", resolution=150.0,
                    save_all=True, append_images=ims[1:])
    contact_sheet(pngs, os.path.join(out, "contact-sheet.png"))
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote %d image(s)%s + contact-sheet.png -> %s"
          % (len(pngs), " + carousel.pdf" if len(slide_pngs) > 1 else "", out))


if __name__ == "__main__":
    main()
