"""Revision plan and revised draft, checked against the original before it is called better.

  review notes (optional) ─┐
  essay + mechanical checks ┴─ reviser ─ gates ─ fact check ─ blind judge, both orders
                                  ▲                                     │
                                  └──── one retry with the failures ◄───┘

A draft is "verified" only when the judge prefers it over the original in both
orders and every gate passes. Anything else is reported as unverified, with the
reasons, so a plausible-sounding rewrite is never passed off as an improvement.
"""

from __future__ import annotations

import difflib
import re

from .lint import MORAL_ENDING, lint, word_count

MAX_BRACKETS = 4
BRACKET = re.compile(r"\[[^\[\]\n]{3,300}\]")
# Mechanical rules whose matched phrases a revision may not introduce.
PHRASE_RULES = {"cliche", "ai_tell", "thesaurus"}


def strip_brackets(text: str) -> str:
    return BRACKET.sub(" ", text)


def _phrases(text: str) -> set[str]:
    rep = lint(text, None)
    return {re.sub(r"\s+", " ", text[s:e].lower()) for h in rep["hits"] if h["rule"] in PHRASE_RULES for s, e in h["spans"]}


def _moral_ending(text: str) -> bool:
    paras = [p for p in re.split(r"\n\s*\n|\n(?=\s*\S)", text.strip()) if p.strip()]
    return bool(paras) and re.search(MORAL_ENDING, paras[-1], re.I) is not None


def _em_rate(text: str) -> float:
    return (text.count("—") + text.count(" -- ")) / max(1, word_count(text)) * 100


def gates(original: str, revised: str, meta: dict, placeholders: bool = True) -> list[str]:
    """Mechanical checks on a draft. Returns one plain-language failure per problem; empty means it passed."""
    if not revised.strip():
        return ["The draft is empty."]
    fails = []
    if " ".join(revised.split()) == " ".join(original.split()):
        fails.append("The draft is identical to the original.")
    limit = meta.get("word_limit")
    wc = word_count(revised)
    if limit and wc > limit:
        fails.append(f"The draft is {wc} words, over the {limit}-word limit. Brackets count toward the limit.")
    # Questions in brackets may quote the student's own phrasing, so only the prose is checked.
    prose = strip_brackets(revised)
    new = sorted(_phrases(prose) - _phrases(original))
    if new:
        fails.append("The draft adds stock or AI-sounding phrases the original did not have: "
                     + ", ".join(f'"{p}"' for p in new) + ".")
    if _moral_ending(prose) and not _moral_ending(original):
        fails.append('The draft now ends by stating the lesson ("I learned...", "I realized..."). End on a moment or image instead.')
    if _em_rate(revised) > max(_em_rate(original), 1.0):
        fails.append("The draft adds em dashes, which read as AI-polished prose. Use periods and commas.")
    n = len(BRACKET.findall(revised))
    if n and not placeholders:
        fails.append(f"The draft has {n} bracketed notes and this run allows none. Work only with what the essay says.")
    elif n > MAX_BRACKETS:
        fails.append(f"The draft has {n} bracketed questions; keep at most {MAX_BRACKETS}, the ones that matter most.")
    return fails


def diff_segments(a: str, b: str) -> dict:
    """Word-level changes from a to b. Equal and inserted segments rebuild b exactly."""
    ta, tb = re.findall(r"\S+\s*", a.strip()), re.findall(r"\S+\s*", b.strip())
    na, nb = [t.strip().lower() for t in ta], [t.strip().lower() for t in tb]
    sm = difflib.SequenceMatcher(None, na, nb, autojunk=False)
    segs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            segs.append({"op": "equal", "text": "".join(tb[j1:j2])})
            continue
        if i2 > i1:
            segs.append({"op": "delete", "text": "".join(ta[i1:i2])})
        if j2 > j1:
            segs.append({"op": "insert", "text": "".join(tb[j1:j2])})
    kept = sum(m.size for m in sm.get_matching_blocks())
    return {
        "segments": segs,
        "kept_share": round(kept / len(na), 3) if na else 0.0,
        "new_share": round(1 - kept / len(nb), 3) if nb else 0.0,
    }


def review_context(r: dict | None) -> str:
    """The parts of a saved review a reviser can act on. Tolerates reviews saved by older versions."""
    if not r:
        return ""
    lines = []
    if r.get("score") is not None:
        lines.append(f"Overall: {r['score']:.0f}/100 ({r.get('band', '')}).")
    readers = r.get("readers") or []
    for rd in readers:
        lines.append(f"{rd.get('name', 'Reader')} remembers: {rd.get('first_impression', '')}")
    if readers and readers[0].get("committee_line"):
        lines.append(f"What the admissions officer would say in committee: {readers[0]['committee_line']}")
    weakest = sorted((r.get("categories") or {}).items(), key=lambda kv: kv[1].get("score", 10))[:3]
    for c, s in weakest:
        lines.append(f"Weak category, {c} ({s.get('score')}/10). To gain a point: {s.get('to_raise', '')}")
    problems = r.get("problems") or [w for rd in readers for w in rd.get("weaknesses", [])]
    for w in problems[:8]:
        lines.append(f'Problem ({w.get("severity", "")}): {w.get("issue", "")} "{w.get("quote", "")}" {w.get("why_it_matters", "")}')
    for s in (r.get("strengths") or [])[:5]:
        lines.append(f'Works: {s.get("what", "")} "{s.get("quote", "")}"')
    ai = next((rd["ai_suspicion"] for rd in readers if (rd.get("ai_suspicion") or {}).get("level") in ("medium", "high")), None)
    if ai:
        lines.append(f"Reads as AI-written or adult-edited ({ai['level']}): {ai.get('evidence', '')}")
    lost = [h for h in (r.get("head_to_head") or []) + (r.get("calibration") or []) if h.get("verdict") == "loss" and h.get("lesson")]
    for h in lost[:4]:
        lines.append(f"Lost a blind comparison with a published essay: {h.get('decisive_difference', '')} Lesson: {h['lesson']}")
    return "\n".join(lines)
