"""``reports/eval-<run>.html``: one self-contained page (PLAN §9.6), readable in 15 minutes.

Summary of the hard checks with pass or fail, the held-out table with intervals and the paired
differences behind the adoption rule, calibration curves, the by-paper-type split, the other
checks, and a sortable per-topic table with, for each topic, 10 random, 10 lowest-confidence and
10 strongest-disagreement works linked to DOI and DBLP. No script is loaded from outside, no
abstract is included: titles and links are public metadata (CLAUDE.md rule 2).
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable
from dataclasses import dataclass

from flatatlas.evaluate.variants import KEYS, LABELS

E = html.escape

CSS = """
body{font:15px/1.45 system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#1b1b1b}
h1{font-size:1.6rem}h2{margin-top:2.2rem;border-bottom:1px solid #ccc;padding-bottom:.2rem}
table{border-collapse:collapse;margin:.6rem 0;font-size:13.5px}
th,td{border:1px solid #d0d0d0;padding:.25rem .5rem;text-align:right}
th{background:#f3f3f3;cursor:default}table.sortable th{cursor:pointer}
td.l,th.l{text-align:left}.pass{color:#0a6b2d;font-weight:600}.fail{color:#b00020;font-weight:600}
.note{background:#fff8e1;border:1px solid #f0d27a;padding:.5rem .8rem;margin:.8rem 0}
.warn{background:#fdecea;border:1px solid #e0a0a0;padding:.5rem .8rem;margin:.8rem 0}
.adopted{background:#eaf6ea}details{margin:.2rem 0}summary{cursor:pointer}
.small{font-size:12.5px;color:#444}ul.works{margin:.2rem 0 .6rem 1.2rem;padding:0;font-size:13px}
svg{border:1px solid #ddd;margin:2px}
"""

JS = """
document.querySelectorAll('table.sortable').forEach(function(t){
 t.querySelectorAll('th').forEach(function(th,i){
  th.addEventListener('click',function(){
   var rows=Array.from(t.tBodies[0].rows),dir=th.dataset.dir=th.dataset.dir==='asc'?'desc':'asc';
   rows.sort(function(a,b){
    var x=a.cells[i].dataset.v||a.cells[i].textContent,y=b.cells[i].dataset.v||b.cells[i].textContent;
    var nx=parseFloat(x),ny=parseFloat(y);
    var c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y);
    return dir==='asc'?c:-c;});
   rows.forEach(function(r){t.tBodies[0].appendChild(r);});});});});
"""


def f3(x: float | None) -> str:
    return "n/a" if x is None or x != x else f"{x:.3f}"


def est(e: list[float]) -> str:
    return f"{e[0]:.3f} <span class='small'>({e[1]:.3f}–{e[2]:.3f})</span>"


def mark(ok: bool) -> str:
    return f"<span class='{'pass' if ok else 'fail'}'>{'pass' if ok else 'FAIL'}</span>"


@dataclass
class WorkLink:
    title: str
    year: int | None
    doi: str | None
    dblp_key: str | None


def link(w: WorkLink, extra: str = "") -> str:
    parts = [E(w.title or "(no title)")]
    if w.year:
        parts.append(f"({w.year})")
    links = []
    if w.doi:
        links.append(f"<a href='https://doi.org/{E(w.doi)}'>DOI</a>")
    if w.dblp_key:
        links.append(f"<a href='https://dblp.org/rec/{E(w.dblp_key)}'>DBLP</a>")
    return f"<li>{' '.join(parts)} {' · '.join(links)} <span class='small'>{extra}</span></li>"


def hard_table(frozen: dict, adopted: str) -> str:
    rows = []
    for key in KEYS:
        c = frozen["variants"][key]["checks"]
        h = c["hard"]
        cls = " class='adopted'" if key == adopted else ""
        rows.append(
            f"<tr{cls}><td class='l'>{E(LABELS[key])}</td>"
            f"<td>{c['anchors']['hit']}/{c['anchors']['n']} = {f3(c['anchors']['rate'])} {mark(h['anchors'])}</td>"
            f"<td>{f3(c['coverage']['strict'])} {mark(h['coverage'])}<br><span class='small'>with fallback tag {f3(c['coverage']['any'])}</span></td>"
            f"<td>{f3(c['stability']['unchanged'])} {mark(h['stability'])}</td>"
            f"<td>{c['venue_sanity']['met']}/{c['venue_sanity']['total']} {mark(h['venue_sanity'])}</td>"
            f"<td>{f3(c['citation_consistency']['mean'])}</td></tr>"
        )
    return (
        "<table><tr><th class='l'>method</th><th>anchors (≥ 0.90)</th><th>coverage (≥ 0.85)</th>"
        "<th>stability (≥ 0.95)</th><th>venue sanity (all)</th><th>citation consistency</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def heldout_table(h: dict, adopted: str) -> str:
    cols = ["p0", "r0", "f0", "p1", "r1", "f1", "mf0", "mf1", "mean_f"]
    heads = ["P", "R", "F1", "P", "R", "F1", "macro F1", "macro F1", "mean F1"]
    body = []
    for key in KEYS:
        cls = " class='adopted'" if key == adopted else ""
        body.append(
            f"<tr{cls}><td class='l'>{E(LABELS[key])}</td>"
            + "".join(f"<td>{est(h['estimates'][key][c])}</td>" for c in cols)
            + "</tr>"
        )
    return (
        f"<table><tr><th class='l' rowspan='2'>method</th><th colspan='3'>level 0</th>"
        f"<th colspan='3'>level 1</th><th>level 0</th><th>level 1</th><th rowspan='2'>mean of F1s</th></tr>"
        f"<tr>{''.join(f'<th>{x}</th>' for x in heads[:8])}</tr>" + "".join(body) + "</table>"
    )


def rung_table(h: dict) -> str:
    body = []
    for key, r in h["decision"]["rungs"].items():
        worse = [k for k, v in r["hard"].items() if isinstance(v, dict) and v["worse"]]
        hard = "<br>".join(
            f"<span class='small'>{k} {v['complex']:.3f} vs {v['simple']:.3f}</span>"
            for k, v in r["hard"].items()
            if isinstance(v, dict)
        )
        body.append(
            f"<tr><td class='l'>{E(LABELS[key])}</td><td class='l'>{E(LABELS[r['against']])}</td>"
            f"<td>{r['diff']:+.3f}</td><td>{r['lo']:+.3f} to {r['hi']:+.3f}</td>"
            f"<td>{'yes' if r['excludes_zero'] else 'no'}</td>"
            f"<td>{('FAILS: ' + ', '.join(worse)) if worse else 'none fails'}<br>{hard}</td>"
            f"<td>{mark(r['adopt']) if r['adopt'] else 'not adopted'}</td></tr>"
        )
    extra = []
    for k, d in h["differences"].items():
        if " vs " in k:
            e = d["mean_f"]
            extra.append(
                f"<tr><td class='l'>{E(k)}</td><td>{e[0]:+.3f}</td><td>{e[1]:+.3f} to {e[2]:+.3f}</td></tr>"
            )
    return (
        "<table><tr><th class='l'>more complex</th><th class='l'>against</th><th>Δ mean F1</th>"
        "<th>90 % interval</th><th>excludes 0</th><th>hard checks (this vs simpler)</th><th>verdict</th></tr>"
        + "".join(body)
        + "</table><p class='small'>Baseline (b), not on the ladder:</p><table><tr><th class='l'>comparison</th>"
        "<th>Δ mean F1</th><th>90 % interval</th></tr>" + "".join(extra) + "</table>"
    )


def calibration_svg(curve: list[dict], title: str) -> str:
    w = 190
    pts = " ".join(
        f"{10 + c['stated'] * (w - 20):.1f},{w - 10 - c['observed'] * (w - 20):.1f}" for c in curve
    )
    dots = "".join(
        f"<circle cx='{10 + c['stated'] * (w - 20):.1f}' cy='{w - 10 - c['observed'] * (w - 20):.1f}' "
        f"r='{2 + min(c['n'], 400) ** 0.5 / 5:.1f}' fill='#2a6fb0'><title>stated {c['stated']:.2f}, "
        f"observed {c['observed']:.2f}, n={c['n']}</title></circle>"
        for c in curve
    )
    return (
        f"<svg width='{w}' height='{w + 14}' viewBox='0 0 {w} {w + 14}'>"
        f"<rect x='10' y='10' width='{w - 20}' height='{w - 20}' fill='none' stroke='#bbb'/>"
        f"<line x1='10' y1='{w - 10}' x2='{w - 10}' y2='10' stroke='#bbb' stroke-dasharray='3'/>"
        f"<polyline points='{pts}' fill='none' stroke='#2a6fb0'/>{dots}"
        f"<text x='12' y='{w + 8}' font-size='10'>{E(title)}</text></svg>"
    )


def by_type_table(h: dict) -> str:
    out = []
    for kind, groups in h["by_type"].items():
        head = "".join(f"<th>{E(LABELS[k])}</th>" for k in ("noisy_or", "fusion", "fusion+dm"))
        rows = "".join(
            f"<tr><td class='l'>{E(g)}</td><td>{d['n']}</td>"
            f"<td>{f3(d['noisy_or'])}</td><td>{f3(d['fusion'])}</td><td>{f3(d['fusion+dm'])}</td></tr>"
            for g, d in groups.items()
        )
        out.append(
            f"<h3>by {E(kind)}</h3><table><tr><th class='l'>group</th><th>works</th>{head}</tr>{rows}</table>"
        )
    return "".join(out)


def topic_table(topics: list[dict]) -> str:
    rows = []
    for t in topics:
        rows.append(
            f"<tr><td class='l'>{E(t['id'])}</td><td>{t['level']}</td><td>{t['n']}</td>"
            f"<td>{f3(t['mean_conf'])}</td><td>{f3(t['agreement'])}</td><td>{f3(t['npmi'])}</td>"
            f"<td>{f3(t['cosine'])}</td><td>{'⚑' if t['flag'] else ''}</td></tr>"
        )
    return (
        "<table class='sortable'><thead><tr><th class='l'>topic</th><th>level</th><th>works</th>"
        "<th>mean confidence</th><th>method agreement</th><th>NPMI</th><th>intra-topic cosine</th>"
        "<th>flag</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def spot_section(spot: dict[str, dict[str, list[str]]]) -> str:
    out = []
    for topic, lists in spot.items():
        body = "".join(
            f"<p class='small'>{E(name)}</p><ul class='works'>{''.join(items)}</ul>"
            for name, items in lists.items()
            if items
        )
        out.append(f"<details><summary>{E(topic)}</summary>{body}</details>")
    return "".join(out)


def render(
    frozen: dict,
    heldout: dict | None,
    topics: list[dict],
    spot: dict,
    *,
    adopted: str,
    notes: Iterable[str] = (),
) -> str:
    parts = [
        f"<!doctype html><meta charset='utf-8'><title>Tagger evaluation {E(frozen['run_id'])}</title>"
        f"<style>{CSS}</style><h1>Tagger evaluation <span class='small'>{E(frozen['run_id'])}</span></h1>",
        "<p class='small'>Every precision, recall and F1 is <b>agreement with the labelled set</b>, "
        "which is Claude's reading of the papers (500 random works approved by Guilherme without "
        "changes, 182 top-up works reviewed by Claude), not agreement with the truth.</p>",
    ]
    for n in notes:
        parts.append(f"<div class='note'>{E(n)}</div>")
    if heldout and heldout["optimistic"]:
        parts.append(
            "<div class='warn'><b>Optimistic.</b> This is not the first opening of the held-out set; "
            "the settings were free to change in between.</div>"
        )
    parts += [
        f"<h2>1. Summary: the hard checks</h2><p>Adopted variant (highlighted): <b>{E(LABELS[adopted])}</b>. "
        "These checks use no held-out label.</p>",
        hard_table(frozen, adopted),
    ]
    if heldout:
        parts += [
            f"<h2>2. Held-out set ({heldout['n_works']} works, opened once)</h2>"
            f"<p class='small'>Bootstrap over works, {heldout['bootstrap']['n']} resamples, "
            f"{int(heldout['bootstrap']['interval'] * 100)} % intervals in brackets. Gold labels: "
            f"{heldout['n_gold_labels']['level0']} at level 0, {heldout['n_gold_labels']['level1']} at level 1.</p>",
            heldout_table(heldout, adopted),
            "<h2>3. The adoption rule (PLAN §9.6)</h2><p>A more complex option is adopted only if the "
            "paired interval of the difference in mean F1 excludes zero <b>and</b> no hard check got "
            "worse (a check the simpler method passes and this one fails; drops that stay above the "
            "threshold are shown, not blocking).</p>",
            rung_table(heldout),
            "<h2>4. Calibration (stated confidence against observed precision, levels 0 and 1)</h2>"
            + "".join(calibration_svg(heldout["calibration"][k], LABELS[k][:26]) for k in KEYS),
            "<h2>5. By paper type (mean of level 0 and level 1 F1)</h2>",
            by_type_table(heldout),
        ]
    else:
        parts.append(
            "<p class='note'>The held-out set has not been opened yet: no held-out table.</p>"
        )
    ag = frozen["method_agreement"]
    parts.append(
        "<h2>6. Other checks</h2><h3>Method agreement (level 0, top-1)</h3><table><tr><th class='l'>pair</th><th>top-1 agreement</th><th>works</th></tr>"
    )
    for k, v in ag["pairs"].items():
        parts.append(
            f"<tr><td class='l'>{E(k)}</td><td>{f3(v['top1_agreement'])}</td><td>{v['n_works']}</td></tr>"
        )
    parts.append("</table>")
    parts.append(
        f"<p class='small'>Flagged (agreement below the line): {E(', '.join(ag['flagged']) or 'none')}</p>"
    )
    lt = {k: frozen["variants"][k]["checks"].get("leak_test") for k in ("noisy_or", "fusion")}
    parts.append(
        "<h3>Hold-out leak test (lex_title hidden on unlabelled works)</h3><table><tr><th class='l'>method</th><th>tags recovered</th><th>primary unchanged</th><th>works</th></tr>"
    )
    for k, v in lt.items():
        if v:
            parts.append(
                f"<tr><td class='l'>{E(LABELS[k])}</td><td>{f3(v['tags_recovered'])}</td><td>{f3(v['primary_unchanged'])}</td><td>{v['n_works']}</td></tr>"
            )
    parts.append(
        "</table><h3>Venue sanity (adopted variant)</h3><table><tr><th class='l'>venue : topic</th><th>rank</th><th>share of venue</th><th></th></tr>"
    )
    vs = frozen["variants"][adopted]["checks"]["venue_sanity"]["detail"]
    for k, v in vs.items():
        parts.append(
            f"<tr><td class='l'>{E(k)}</td><td>{v['rank']}</td><td>{f3(v['share'])}</td><td>{mark(v['ok'])}</td></tr>"
        )
    parts.append("</table>")
    parts.append(
        f"<h2>7. Topics (adopted variant; click a header to sort)</h2>{topic_table(topics)}"
    )
    parts.append(
        "<h2>8. Spot check</h2><p class='small'>Per topic: 10 random works, the 10 with the lowest "
        "confidence, and the 10 on which the adopted method and the other method disagree most. "
        "A 15-minute read, not labelling.</p>" + spot_section(spot)
    )
    parts.append(f"<script>{JS}</script>")
    return "".join(parts)


def dump(path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
