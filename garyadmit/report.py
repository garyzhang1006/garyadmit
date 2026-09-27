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
    return f"won {w}, lost {l}, split {s}" + (" (splits carry no weight)" if s else "")


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
            bits.append(f"{len(cal)} essays of known standing ({h2h_summary(cal)})")
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
    problems = r.get("problems") or sorted((w for rd in r["readers"] for w in rd["weaknesses"]),
                                           key=lambda x: x["severity"] != "major")
    for n, wk in enumerate(problems, 1):
        out.append(_wrap(f"{n}. [{wk['severity']}] {wk['issue']}", "  "))
        out.append(_wrap(f"\"{wk['quote']}\"", "     "))
        out.append(_wrap(wk["why_it_matters"], "     "))
    out.append("")

    strengths = r.get("strengths") or [s for rd in r["readers"] for s in rd["strengths"]]
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
        out.append("CALIBRATION VS ESSAYS OF KNOWN STANDING (blind, judged in both orders)")
        for c in sorted(cal, key=lambda c: c["level"]):
            label = {"win": "WIN  ", "loss": "LOSS ", "split": "SPLIT"}[c["verdict"]]
            o = c.get("opponent") or {}
            out.append(f"  {label} vs \"{o.get('title', '')}\", {c.get('label', '')} (~{c['level']:.0f} on this scale)")
            if o.get("url"):
                out.append(f"         {o['url']}")
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


def revision_to_text(v: dict) -> str:
    out = []
    bar = "=" * 96
    checks = v["checks"]
    jd = checks.get("judge") or {}
    out += [bar, f"  GARYADMIT REVISION  {'VERIFIED' if v['verified'] else 'NOT VERIFIED'}", bar]
    if v["verified"]:
        won = [c for c, s in jd.get("category_share", {}).items() if s > 0.5]
        lost = [c for c, s in jd.get("category_share", {}).items() if s < 0.5]
        line = "A blind judge preferred the revised draft over your original in both orders"
        line += f", winning on {', '.join(won)}" if won else ""
        line += f" and losing on {', '.join(lost)}" if lost else ""
        if checks.get("vs_polish"):  # revisions saved before this check existed do not have it
            line += (". It also preferred it in both orders over a polish-only rewrite of your original, so the gain is more "
                     "than smoother sentences")
        out.append(_wrap(f"{line}. {jd.get('decisive_difference', '')}", "  "))
        if jd.get("voice_share", 0) > 0.5:
            out.append(_wrap("The judge also said it sounds more like one specific real teenager than your original does.", "  "))
        if v["questions"]:
            n = len(v["questions"])
            out.append(_wrap(f"This verdict assumes you answer the {n} bracketed question{'s' if n > 1 else ''} with true details; "
                             "the judge read each as a plain detail of that kind.", "  "))
    else:
        out.append("  This draft did not pass every check, so treat it as a starting point, not a finished essay:")
        out += [_wrap(f"- {f}", "  ") for f in checks["failures"]]
    out.append("")

    d = v["diagnosis"]
    out.append("WHAT THE ESSAY IS REALLY ABOUT")
    if d.get("already_strong"):
        out.append(_wrap("The reviser judged this essay already strong, so the moves are small. Take only the ones you agree with."))
    out.append(_wrap(d.get("core", "")))
    out.append(_wrap(f"Holding it back: {d.get('holding_back', '')}"))
    if d.get("best_material"):
        out.append(_wrap(f"Best material: \"{d['best_material']}\""))
    out.append("")

    vc = v["voice"]
    out.append("YOUR VOICE")
    out.append(_wrap(vc.get("sounds_like", "")))
    for q in vc.get("best_lines", []):
        out.append(_wrap(f"+ \"{q}\"", "   "))
    for o in vc.get("off_voice", []):
        out.append(_wrap(f"- \"{o['quote']}\" ({o['why']})", "   "))
    out.append("")

    out.append("THE MOVES, BIGGEST FIRST")
    for i, m in enumerate(v["moves"], 1):
        out.append(_wrap(f"{i}. {m['title']} [{m['kind']}]", "  "))
        if m.get("target"):
            out.append(_wrap(f"Changes: \"{m['target']}\"", "     "))
        out.append(_wrap(f"Problem: {m['problem']}", "     "))
        out.append(_wrap(f"Do this: {m['change']}", "     "))
        if m.get("rewrite"):
            out.append(_wrap(f"New: {m['rewrite']}", "     "))
        out.append(_wrap(f"Effect: {m['reader_effect']}", "     "))
    out.append("")

    if v["questions"]:
        out.append("QUESTIONS ONLY YOU CAN ANSWER (fill these in before you use the draft)")
        for q in v["questions"]:
            out.append(_wrap(f"{q['placeholder']}  {q['question']}", "  "))
        out.append("")

    out.append(f"REVISED DRAFT ({checks.get('word_count', 0)} words"
               + (f" / {v['meta']['word_limit']}" if v["meta"].get("word_limit") else "") + ")")
    for para in [p for p in v["draft"].split("\n") if p.strip()]:
        out.append(_wrap(para, "  "))
        out.append("")
    for k in jd.get("keep", []):
        out.append(_wrap(f"Worth keeping from your original: \"{k['quote']}\" ({k['why']})", "  "))
    dsh = v.get("diff") or {}
    out.append(f"  Kept {dsh.get('kept_share', 0):.0%} of your words; {dsh.get('new_share', 0):.0%} of the draft is new or moved."
               + (f" Took {len(v['rounds'])} rounds." if len(v.get("rounds", [])) > 1 else ""))
    if checks.get("unverified_quotes_dropped"):
        out.append(f"  ({checks['unverified_quotes_dropped']} quote(s) dropped because they were not in your essay.)")
    return "\n".join(out)
