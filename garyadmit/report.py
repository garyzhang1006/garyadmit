"""Plain-text report for the terminal."""

from __future__ import annotations

import textwrap

from .rubric import CATEGORIES


def _wrap(s: str, indent: str = "   ", width: int = 96) -> str:
    return textwrap.fill(s, width=width, initial_indent=indent, subsequent_indent=indent)


def h2h_summary(h2h: list[dict]) -> str:
    w = sum(1 for h in h2h if h["verdict"] == "win")
    l = sum(1 for h in h2h if h["verdict"] == "loss")
    s = sum(1 for h in h2h if h["verdict"] == "split")
    return f"won {w}, lost {l}, split {s}"


def to_text(r: dict) -> str:
    out = []
    bar = "=" * 96
    out += [bar, f"  GARYADMIT  {r['score']:.0f}/100  {r['band'].upper()}", _wrap(r["band_description"], "  "), bar]
    cal = r.get("calibration") or []
    if r["head_to_head"] or cal:
        bits = []
        if r["head_to_head"]:
            bits.append(f"{len(r['head_to_head'])} similar published essays ({h2h_summary(r['head_to_head'])})")
        if cal:
            bits.append(f"{len(cal)} hidden human-rated essays ({h2h_summary(cal)})")
        out.append(_wrap(f"Rubric score {r['rubric_score']:.1f} -> final {r['score']:.1f} after blind comparisons against "
                         + " and ".join(bits) + ".", "  "))
    else:
        out.append("  No comparisons ran. Score is rubric-only.")
    out.append("")
    out.append(f"  {'CATEGORY':<14}{'SCORE':>6}{'R1':>5}{'R2':>5}")
    for c in CATEGORIES:
        cs = r["categories"][c]
        flag = "  (adjudicated)" if cs["adjudicated"] else ""
        out.append(f"  {c.title():<14}{cs['score']:>6.1f}{cs['reader_1']:>5}{cs['reader_2']:>5}{flag}")
    out.append("")

    out.append("WHAT A READER REMEMBERS")
    for rd in r["readers"]:
        out.append(_wrap(f"{rd['name']}: {rd['first_impression']}"))
    out.append(_wrap(f"In committee: \"{r['readers'][0]['committee_line']}\""))
    ai = [rd["ai_suspicion"] for rd in r["readers"] if rd["ai_suspicion"]["level"] in ("medium", "high")]
    if ai:
        out.append(_wrap(f"AI/over-editing flag ({ai[0]['level']}): {ai[0]['evidence']}"))
    out.append("")

    out.append("BIGGEST PROBLEMS")
    seen = set()
    n = 0
    for rd in r["readers"]:
        for wk in sorted(rd["weaknesses"], key=lambda x: x["severity"] != "major"):
            key = wk["quote"][:40]
            if key in seen:
                continue
            seen.add(key)
            n += 1
            out.append(_wrap(f"{n}. [{wk['severity']}] {wk['issue']}", "  "))
            out.append(_wrap(f"\"{wk['quote']}\"", "     "))
            out.append(_wrap(wk["why_it_matters"], "     "))
    out.append("")

    strengths = [s for rd in r["readers"] for s in rd["strengths"]]
    out.append("WHAT WORKS (only what the readers could quote)")
    if strengths:
        for s in strengths[:6]:
            out.append(_wrap(f"- {s['what']}: \"{s['quote']}\"", "  "))
    else:
        out.append("   Neither reader found a line worth quoting as a strength.")
    out.append("")

    out.append("HIGHEST-IMPACT FIXES")
    for i, f in enumerate(r["readers"][1]["top_fixes"][:3] or r["readers"][0]["top_fixes"][:3], 1):
        out.append(_wrap(f"{i}. {f['fix']}", "  "))
        out.append(_wrap(f['why'], "     "))
    out.append("")

    if r["head_to_head"]:
        out.append("HEAD-TO-HEAD VS SIMILAR PUBLISHED ESSAYS (blind, judged in both orders)")
        for h in r["head_to_head"]:
            o = h["opponent"]
            label = {"win": "WIN  ", "loss": "LOSS ", "split": "SPLIT"}[h["verdict"]]
            where = " · ".join(x for x in (o["school"], str(o["year"] or ""), o["tier"]) if x)
            out.append(f"  {label} vs \"{o['title']}\" ({where})")
            out.append(f"         {o['url']}")
            out.append(_wrap(f"Why: {h['decisive_difference']}", "         "))
            if h["verdict"] != "win":
                out.append(_wrap(f"Take from it: {h['lesson']}", "         "))
        out.append("")
    if cal:
        out.append("CALIBRATION VS HUMAN-RATED ESSAYS (blind; expert rating on a 4-9 scale)")
        for c in sorted(cal, key=lambda c: c["rating"]):
            label = {"win": "WIN  ", "loss": "LOSS ", "split": "SPLIT"}[c["verdict"]]
            out.append(f"  {label} vs an essay rated {c['rating']:g} (~{c['level']:.0f} on this scale)")
            out.append(_wrap(c["decisive_difference"], "         "))
        out.append("")
    if r["similar"]:
        extra = [s for s in r["similar"] if s["id"] not in {h["opponent"]["id"] for h in r["head_to_head"]}]
        if extra:
            out.append("MORE SIMILAR ESSAYS TO READ")
            for s in extra:
                out.append(f"  - {s['title']} ({s['school'] or s['source']}): {s['url']}")
                out.append(_wrap(s["why_similar"], "    "))
            out.append("")

    out.append(f"LINE EDITS ({len(r['edits'])})")
    for e in r["edits"]:
        out.append(_wrap(f"\"{e['original']}\"", "  "))
        if e["kind"] == "rewrite":
            out.append(_wrap(f"-> {e['suggestion']}", "     "))
        elif e["kind"] == "comment":
            out.append(_wrap(f"NOTE: {e['suggestion']}", "     "))
        else:
            out.append("     CUT")
        out.append(_wrap(f"({e['category']}, {e['severity']}) {e['problem']}", "     "))
    out.append("")

    lt = r["lint"]
    out.append(f"MECHANICAL CHECKS  {lt['word_count']} words" + (f" / {lt['word_limit']}" if lt["word_limit"] else "")
               + f", {lt['paragraphs']} paragraphs, reading grade {lt['reading_grade']}")
    for h in lt["hits"]:
        ex = f" ({', '.join(h['examples'][:5])})" if h["examples"] else ""
        out.append(_wrap(f"[{h['severity']}] {h['message']}{ex}", "  "))
    dropped = sum(rd.get("_unverified_quotes_dropped", 0) for rd in r["readers"])
    if dropped:
        out.append(f"  ({dropped} reviewer claim(s) dropped because their quotes were not in your essay.)")
    return "\n".join(out)
