"""Visual gallery: render every flat pattern of a run into one HTML page.

    python -m benchmarks gallery [run]

Writes gallery.html into the run directory. Requires the run to have been
executed with --keep-artifacts (otherwise passing files have no DXFs).
"""

import html
import json
import math
import os

import ezdxf
from ezdxf.math import bulge_to_arc

from . import metrics

ARC_STEP_DEG = 4.0   # tessellation step; visual only
ROUND = 2            # coordinate decimals


# ---------------------------------------------------------------------------
# DXF -> SVG
# ---------------------------------------------------------------------------

def _tessellate(points_xyb):
    """LWPOLYLINE points [(x, y, bulge)] -> flat polyline vertex list."""
    out = []
    n = len(points_xyb)
    for i, (x, y, bulge) in enumerate(points_xyb):
        out.append((x, y))
        if bulge and i < n - 1 or (bulge and i == n - 1):
            p1 = (x, y)
            p2 = (points_xyb[(i + 1) % n][0], points_xyb[(i + 1) % n][1])
            if p1 == p2:
                continue
            try:
                center, _, _, radius = bulge_to_arc(p1, p2, bulge)
            except Exception:
                continue
            sweep = 4.0 * math.atan(bulge)
            theta1 = math.atan2(p1[1] - center[1], p1[0] - center[0])
            steps = max(2, int(abs(math.degrees(sweep)) / ARC_STEP_DEG))
            for k in range(1, steps):
                angle = theta1 + sweep * k / steps
                out.append((center[0] + radius * math.cos(angle),
                            center[1] + radius * math.sin(angle)))
    return out


def dxf_to_svg(dxf_path):
    """Render outline/bend/engraving layers of a DXF to a compact SVG string."""
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as exc:
        return None, "unreadable: %s" % exc

    elements = []
    xs, ys = [], []

    def add_points(points, role, closed):
        if len(points) < 2:
            return
        xs.extend(p[0] for p in points)
        ys.extend(p[1] for p in points)
        coords = " ".join("%s,%s" % (round(p[0], ROUND), round(-p[1], ROUND)) for p in points)
        tag = "polygon" if closed else "polyline"
        elements.append('<%s class="%s" points="%s"/>' % (tag, role, coords))

    for entity in doc.modelspace():
        role = metrics.layer_role(entity.dxf.layer)
        if role == "other":
            continue
        kind = entity.dxftype()
        if kind == "LWPOLYLINE":
            points = [(p[0], p[1], p[4]) for p in entity.get_points("xyseb")]
            closed = bool(entity.closed)
            add_points(_tessellate(points), role, closed)
        elif kind == "CIRCLE":
            c, r = entity.dxf.center, entity.dxf.radius
            xs.extend((c[0] - r, c[0] + r))
            ys.extend((c[1] - r, c[1] + r))
            elements.append('<circle class="%s" cx="%s" cy="%s" r="%s"/>'
                            % (role, round(c[0], ROUND), round(-c[1], ROUND), round(r, ROUND)))
        elif kind == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            xs.extend((s[0], e[0]))
            ys.extend((s[1], e[1]))
            elements.append('<line class="%s" x1="%s" y1="%s" x2="%s" y2="%s"/>'
                            % (role, round(s[0], ROUND), round(-s[1], ROUND),
                               round(e[0], ROUND), round(-e[1], ROUND)))

    if not xs:
        return None, "no drawable geometry"

    margin = 0.03 * max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    vx = min(xs) - margin
    vy = -max(ys) - margin
    vw = (max(xs) - min(xs)) + 2 * margin
    vh = (max(ys) - min(ys)) + 2 * margin
    svg = ('<svg viewBox="%s %s %s %s" preserveAspectRatio="xMidYMid meet">%s</svg>'
           % (round(vx, ROUND), round(vy, ROUND), round(vw, ROUND), round(vh, ROUND),
              "".join(elements)))
    return svg, None


# ---------------------------------------------------------------------------
# Gallery HTML
# ---------------------------------------------------------------------------

def _slug(rel_path):
    return rel_path.replace("/", "__").replace("\\", "__").rsplit(".", 1)[0]


def _card(record, run_dir):
    rel = record["path"]
    slug = _slug(rel)
    artifacts = run_dir / "artifacts" / slug
    status = record["status"]
    category = record.get("category") or "?"
    metrics_data = record.get("metrics") or {}
    timings = record.get("timings") or {}

    drawings = []
    if artifacts.is_dir():
        for name in sorted(os.listdir(artifacts)):
            if name.lower().endswith(".dxf"):
                svg, error = dxf_to_svg(str(artifacts / name))
                drawings.append((name, svg, error))

    facts = []
    if metrics_data.get("thickness") is not None:
        facts.append(("t", "%.2f mm" % metrics_data["thickness"]))
    if metrics_data.get("bend_count") is not None:
        facts.append(("bends", str(metrics_data["bend_count"])))
    if metrics_data.get("volume_rel_error") is not None:
        facts.append(("vol err", "%.3f%%" % (100 * metrics_data["volume_rel_error"])))
    if record.get("parts_found") is not None:
        facts.append(("parts", "%d (%ds/%dt)" % (record["parts_found"],
                                                 record.get("sheets") or 0,
                                                 record.get("tubes") or 0)))
    if timings.get("wall_total"):
        facts.append(("wall", "%.1f s" % timings["wall_total"]))
    if record.get("message_codes"):
        facts.append(("codes", ",".join("%03d" % c for c in record["message_codes"])))

    failing = [c for c in record.get("checks") or [] if c.get("status") == "fail"]

    parts = ['<article class="card" data-status="%s" data-category="%s" data-name="%s">'
             % (status, html.escape(category), html.escape(rel.lower()))]
    parts.append('<header><h3 title="%s">%s</h3>'
                 % (html.escape(rel), html.escape(os.path.basename(rel))))
    parts.append('<span class="chip status-%s">%s</span></header>' % (status, status.replace("_", " ")))
    parts.append('<p class="meta">%s</p>' % html.escape(category))

    if drawings:
        parts.append('<div class="drawings">')
        for name, svg, error in drawings:
            if svg:
                parts.append('<figure class="pattern" tabindex="0" data-title="%s">%s'
                             '<figcaption>%s</figcaption></figure>'
                             % (html.escape("%s — %s" % (rel, name)), svg, html.escape(name)))
            else:
                parts.append('<figure class="pattern empty"><div class="nodraw">%s</div>'
                             '<figcaption>%s</figcaption></figure>'
                             % (html.escape(error or "no drawing"), html.escape(name)))
        parts.append('</div>')
    else:
        reason = "no DXF produced"
        if status == "timeout":
            reason = "timed out"
        elif record.get("crash_stage"):
            reason = "crashed in %s" % record["crash_stage"]
        parts.append('<div class="drawings"><figure class="pattern empty">'
                     '<div class="nodraw">%s</div></figure></div>' % html.escape(reason))

    if facts:
        parts.append('<dl class="facts">')
        for key, value in facts:
            parts.append("<div><dt>%s</dt><dd>%s</dd></div>" % (html.escape(key), html.escape(value)))
        parts.append("</dl>")

    if failing:
        summary = "; ".join(sorted({c["name"] for c in failing}))
        detail = " | ".join(
            "%s: %s" % (c["name"], (c.get("detail") or str(c.get("measured") or ""))[:160])
            for c in failing[:6])
        parts.append('<p class="fails" title="%s">%s</p>'
                     % (html.escape(detail), html.escape(summary)))

    parts.append("</article>")
    return "".join(parts)


def build_gallery(run_dir, run_meta, results):
    counts = run_meta.get("counts", {})
    order = {"fail": 0, "crash": 0, "timeout": 0, "warn": 1, "known_failure": 2, "pass": 3}
    results = sorted(results, key=lambda r: (order.get(r["status"], 9), r["path"].lower()))
    categories = sorted({r.get("category") or "?" for r in results})

    cards = "\n".join(_card(r, run_dir) for r in results)
    chips = "".join(
        '<button class="filter chip status-%s" data-filter="%s">%s <b>%d</b></button>'
        % (s, s, s.replace("_", " "), counts.get(s, 0))
        for s in ("pass", "warn", "known_failure", "fail", "crash", "timeout")
        if counts.get(s))
    options = "".join('<option value="%s">%s</option>' % (c, c) for c in categories)

    return HTML_TEMPLATE % {
        "title": "InstaPart flat patterns — %s" % run_dir.name,
        "run": html.escape(run_dir.name),
        "sha": html.escape(str(run_meta.get("sha"))),
        "pythonocc": html.escape(str(run_meta.get("pythonocc"))),
        "n_files": run_meta.get("n_files", len(results)),
        "wall": "%.0f" % run_meta.get("total_wall", 0.0),
        "chips": chips,
        "options": options,
        "cards": cards,
    }


def cmd_gallery(args):
    from .runner import find_run
    from . import manifest as manifest_mod
    run_dir = find_run(args.args[0] if args.args else "latest")
    with open(run_dir / "run.json", "r", encoding="utf-8") as fh:
        run_meta = json.load(fh)
    results = manifest_mod.load_results(run_dir / "results.jsonl")
    page = build_gallery(run_dir, run_meta, results)
    out = run_dir / "gallery.html"
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print("Wrote %s (%.1f MB)" % (out, out.stat().st_size / 1e6))
    return 0


HTML_TEMPLATE = """<title>%(title)s</title>
<style>
:root {
  --paper: #fafaf8; --panel: #ffffff; --ink: #1c2733; --ink-soft: #5a6a7a;
  --rule: #dfe3e0; --outline: #2b6cb0; --bend: #c2452d; --engraving: #2f855a;
  --pass: #216e39; --pass-bg: #e4f2e7; --warn: #8a6100; --warn-bg: #fbf0d3;
  --fail: #a02c1e; --fail-bg: #fbe4e0; --known: #4a5568; --known-bg: #e8ebef;
  --accent: #2b6cb0;
}
@media (prefers-color-scheme: dark) { :root {
  --paper: #10161d; --panel: #18202a; --ink: #dfe7ee; --ink-soft: #8fa1b3;
  --rule: #2a3542; --outline: #7db3e8; --bend: #e88a76; --engraving: #7cc9a0;
  --pass: #7cc9a0; --pass-bg: #1d3227; --warn: #e6c37a; --warn-bg: #38301a;
  --fail: #e88a76; --fail-bg: #3d211c; --known: #a7b4c2; --known-bg: #252f3b;
  --accent: #7db3e8;
} }
:root[data-theme="light"] {
  --paper: #fafaf8; --panel: #ffffff; --ink: #1c2733; --ink-soft: #5a6a7a;
  --rule: #dfe3e0; --outline: #2b6cb0; --bend: #c2452d; --engraving: #2f855a;
  --pass: #216e39; --pass-bg: #e4f2e7; --warn: #8a6100; --warn-bg: #fbf0d3;
  --fail: #a02c1e; --fail-bg: #fbe4e0; --known: #4a5568; --known-bg: #e8ebef;
  --accent: #2b6cb0;
}
:root[data-theme="dark"] {
  --paper: #10161d; --panel: #18202a; --ink: #dfe7ee; --ink-soft: #8fa1b3;
  --rule: #2a3542; --outline: #7db3e8; --bend: #e88a76; --engraving: #7cc9a0;
  --pass: #7cc9a0; --pass-bg: #1d3227; --warn: #e6c37a; --warn-bg: #38301a;
  --fail: #e88a76; --fail-bg: #3d211c; --known: #a7b4c2; --known-bg: #252f3b;
  --accent: #7db3e8;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 14px/1.5 "Segoe UI", system-ui, sans-serif;
}
.mono, dd, .meta, .fails { font-family: "Cascadia Mono", Consolas, monospace; font-variant-numeric: tabular-nums; }
.topbar {
  position: sticky; top: 0; z-index: 5; background: var(--paper);
  border-bottom: 1px solid var(--rule); padding: 12px 20px;
  display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center;
}
.topbar h1 { font-size: 16px; margin: 0 8px 0 0; font-weight: 600; letter-spacing: .01em; }
.topbar .runmeta { color: var(--ink-soft); font-size: 12px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-left: auto; }
.chip {
  display: inline-block; padding: 2px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 600; letter-spacing: .02em; border: 1px solid transparent;
}
.status-pass { color: var(--pass); background: var(--pass-bg); }
.status-warn { color: var(--warn); background: var(--warn-bg); }
.status-fail, .status-crash, .status-timeout { color: var(--fail); background: var(--fail-bg); }
.status-known_failure { color: var(--known); background: var(--known-bg); }
button.filter { cursor: pointer; font: inherit; font-size: 12px; }
button.filter.off { opacity: .35; }
button.filter b { font-weight: 700; }
select, input[type=search] {
  font: inherit; font-size: 13px; color: var(--ink); background: var(--panel);
  border: 1px solid var(--rule); border-radius: 6px; padding: 4px 8px;
}
input[type=search] { width: 200px; }
.grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px; padding: 16px 20px 60px;
}
.card {
  background: var(--panel); border: 1px solid var(--rule); border-radius: 8px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 8px;
}
.card.hidden { display: none; }
.card header { display: flex; align-items: baseline; gap: 8px; justify-content: space-between; }
.card h3 { margin: 0; font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { margin: 0; font-size: 11px; color: var(--ink-soft); }
.drawings { display: flex; gap: 8px; overflow-x: auto; }
.pattern {
  margin: 0; flex: 1 0 200px; max-width: 100%%; min-width: 0; cursor: zoom-in;
  border: 1px solid var(--rule); border-radius: 6px; padding: 6px; background: var(--paper);
}
.pattern svg { width: 100%%; height: 150px; display: block; }
.pattern figcaption { font-size: 10px; color: var(--ink-soft); text-align: center; margin-top: 4px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pattern.empty { cursor: default; display: flex; flex-direction: column; justify-content: center; }
.nodraw { height: 150px; display: grid; place-items: center; color: var(--ink-soft); font-size: 12px; }
.pattern:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
svg polygon, svg polyline { fill: none; stroke-linejoin: round; }
svg .outline { stroke: var(--outline); }
svg circle.outline { fill: none; }
svg .bends { stroke: var(--bend); stroke-dasharray: 6 4; }
svg .engraving { stroke: var(--engraving); }
svg * { stroke-width: 1; vector-effect: non-scaling-stroke; }
.facts { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0; }
.facts div { display: flex; gap: 5px; align-items: baseline; }
.facts dt { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-soft); }
.facts dd { margin: 0; font-size: 12px; }
.fails { margin: 0; font-size: 11px; color: var(--fail); }
dialog {
  border: 1px solid var(--rule); border-radius: 10px; background: var(--panel); color: var(--ink);
  width: min(92vw, 1100px); padding: 16px;
}
dialog::backdrop { background: rgba(10, 14, 19, .55); }
dialog svg { width: 100%%; height: min(74vh, 800px); }
dialog h2 { margin: 0 0 10px; font-size: 14px; font-weight: 600; }
dialog form { text-align: right; margin-top: 8px; }
dialog button { font: inherit; padding: 4px 14px; border-radius: 6px; border: 1px solid var(--rule);
  background: var(--paper); color: var(--ink); cursor: pointer; }
.legend { display: flex; gap: 14px; font-size: 11px; color: var(--ink-soft); align-items: center; }
.legend i { display: inline-block; width: 18px; height: 0; border-top: 2px solid; margin-right: 4px; vertical-align: middle; }
.legend .l-outline i { border-color: var(--outline); }
.legend .l-bend i { border-color: var(--bend); border-top-style: dashed; }
.legend .l-engraving i { border-color: var(--engraving); }
</style>

<div class="topbar">
  <h1>InstaPart flat patterns</h1>
  <span class="runmeta mono">%(run)s · git %(sha)s · pythonocc %(pythonocc)s · %(n_files)s files · %(wall)s s pipeline</span>
  <span class="legend">
    <span class="l-outline"><i></i>outline</span>
    <span class="l-bend"><i></i>bend</span>
    <span class="l-engraving"><i></i>engraving</span>
  </span>
  <div class="controls">
    %(chips)s
    <select id="category"><option value="">all categories</option>%(options)s</select>
    <input type="search" id="search" placeholder="filter by name&hellip;" aria-label="filter by name">
  </div>
</div>

<main class="grid">
%(cards)s
</main>

<dialog id="zoom"><h2 id="zoom-title"></h2><div id="zoom-body"></div>
<form method="dialog"><button>Close</button></form></dialog>

<script>
(function () {
  var active = {};
  document.querySelectorAll("button.filter").forEach(function (b) {
    active[b.dataset.filter] = true;
    b.addEventListener("click", function () {
      active[b.dataset.filter] = !active[b.dataset.filter];
      b.classList.toggle("off", !active[b.dataset.filter]);
      apply();
    });
  });
  var category = document.getElementById("category");
  var search = document.getElementById("search");
  category.addEventListener("change", apply);
  search.addEventListener("input", apply);

  function apply() {
    var cat = category.value, q = search.value.toLowerCase();
    document.querySelectorAll(".card").forEach(function (c) {
      var show = (active[c.dataset.status] !== false)
        && (!cat || c.dataset.category === cat)
        && (!q || c.dataset.name.indexOf(q) !== -1);
      c.classList.toggle("hidden", !show);
    });
  }

  var dialog = document.getElementById("zoom");
  var body = document.getElementById("zoom-body");
  var title = document.getElementById("zoom-title");
  function open(fig) {
    var svg = fig.querySelector("svg");
    if (!svg) return;
    title.textContent = fig.dataset.title || "";
    body.innerHTML = svg.outerHTML;
    dialog.showModal();
  }
  document.querySelectorAll("figure.pattern").forEach(function (fig) {
    fig.addEventListener("click", function () { open(fig); });
    fig.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(fig); }
    });
  });
})();
</script>
"""
