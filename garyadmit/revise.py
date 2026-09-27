"""Revision plan and revised draft, checked against the original before it is called better.

  review notes (optional) ─┐
  essay + mechanical checks ┴─ reviser ─ gates ─ fact check ─ blind judge vs original, both orders
                                  ▲                          └ blind judge vs a polish-only rewrite, both orders
                                  └──── one retry with the failures ◄───┘

A draft is "verified" only when the judge prefers it, in both orders, over the
original and over a polish-only rewrite of it by the same model, and every gate
passes. The judge also prefers mere polish over most originals, so beating the
original alone would not show the essay got stronger. Anything else is reported
as unverified, with the reasons, so a plausible-sounding rewrite is never passed
off as an improvement.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import llm, rubric, scoring
from .lint import MORAL_ENDING, lint, summarize_for_prompt, word_count

MAX_BRACKETS = 4
BRACKET = re.compile(r"\[[^\[\]\n]{3,300}\]")
# Mechanical rules whose matched phrases a revision may not introduce.
PHRASE_RULES = {"cliche", "ai_tell", "thesaurus"}
# A bracket asks; it never tells. A statement in brackets would carry an invented event past the fact check.
QUESTION_START = re.compile(r"(what|how|why|when|where|who|whom|whose|which|whether|did|do|does|was|were|is|are|have|has|had|"
                            r"can|could|would|will|name|describe|add|list|give|tell|say|share|write|include|fill)\b", re.I)
POLISH_NAMES = ("the polish-only rewrite", "the revision")


def strip_brackets(text: str) -> str:
    return BRACKET.sub(" ", text)


def _phrases(text: str) -> set[str]:
    rep = lint(text, None)
    return {re.sub(r"\s+", " ", text[s:e].lower()) for h in rep["hits"] if h["rule"] in PHRASE_RULES for s, e in h["spans"]}


def _moral_ending(text: str) -> bool:
    paras = [p for p in re.split(r"\n\s*\n|\n(?=\s*\S)", text.strip()) if p.strip()]
    return bool(paras) and re.search(MORAL_ENDING, paras[-1], re.I) is not None


def _asks(bracket: str) -> bool:
    inner = bracket[1:-1].strip()
    return inner.endswith("?") or QUESTION_START.match(inner) is not None


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
    told = [b for b in dict.fromkeys(BRACKET.findall(revised)) if not _asks(b)] if placeholders else []
    if told:
        fails.append("A bracketed note reads as a statement, not a question: " + ", ".join(f'"{b}"' for b in told)
                     + ". Ask the student instead, without assuming anything the essay does not say.")
    return fails


def diff_segments(a: str, b: str) -> dict:
    """Word-level changes from a to b. Equal and inserted segments rebuild b exactly."""
    # A bracketed question is one token, so it never splits across segments and the web can highlight it.
    tok = re.compile(BRACKET.pattern + r"\s*|\S+\s*")
    ta, tb = tok.findall(a.strip()), tok.findall(b.strip())
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


def _name_drafts(text: str, cand_label: str, names: tuple[str, str]) -> str:
    """The judge says "Draft 1" and "Draft 2"; the reader needs to know which draft that was."""
    base_name, cand_name = names
    other = "2" if cand_label == "1" else "1"
    text = re.sub(rf"\b[Dd]raft[ _]?{cand_label}\b", cand_name, text)
    text = re.sub(rf"\b[Dd]raft[ _]?{other}\b", base_name, text)
    return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)


def judge(base: str, candidate: str, meta: dict, model: str,
          names: tuple[str, str] = ("your original", "the revision")) -> dict:
    """Which draft makes the stronger case, judged in both orders; the candidate is
    "better" only if it wins both, because judges favor a position."""
    orders = []
    for cand_first in (True, False):
        d1, d2 = (candidate, base) if cand_first else (base, candidate)
        r = llm.ask_json(rubric.REVISION_JUDGE_SYSTEM, rubric.revision_judge_prompt(d1, d2, meta),
                         rubric.REVISION_JUDGE_SCHEMA, model=model)
        label = "1" if cand_first else "2"
        r["decisive_difference"] = _name_drafts(r["decisive_difference"], label, names)
        k = r.get("loser_does_better") or {}
        r["loser_does_better"] = {**k, "why": _name_drafts(k.get("why", ""), label, names)}
        orders.append({**r, "cand_label": label, "cand_won": r["winner"] == label})
    wins = sum(o["cand_won"] for o in orders)
    verdict = "better" if wins == 2 else "worse" if wins == 0 else "split"
    share = lambda w, lab: 0.5 if w == "tie" else float(w == lab)
    # On a split, explain with the order the candidate lost: that is what needs fixing.
    lead = next((o for o in orders if o["cand_won"] == (verdict == "better")), orders[0])
    keep, seen = [], set()
    for o in orders:
        k = o.get("loser_does_better") or {}
        q = (k.get("quote") or "").strip()
        if o["cand_won"] and q and q not in seen and scoring.quote_ok(base, q):
            seen.add(q)
            keep.append({"quote": q, "why": k.get("why", "")})
    return {
        "verdict": verdict,
        "confidence": [o["confidence"] for o in orders],
        "category_share": {c: sum(share(o["category_winners"][c], o["cand_label"]) for o in orders) / len(orders)
                           for c in rubric.CATEGORIES},
        "voice_share": sum(share(o["voice_winner"], o["cand_label"]) for o in orders) / len(orders),
        "decisive_difference": lead["decisive_difference"],
        "keep": keep,
    }


def fidelity(original: str, revised: str, model: str) -> dict:
    r = llm.ask_json(rubric.FIDELITY_SYSTEM, rubric.fidelity_prompt(original, revised), rubric.FIDELITY_SCHEMA, model=model)
    brackets = [(b.start(), b.end()) for b in BRACKET.finditer(revised)]
    invented = []
    for item in r.get("invented", []):
        loc = scoring.locate(revised, item.get("text", "")) if item.get("text") else None
        if not loc:
            continue  # the checker quoted something the draft does not say
        if any(a <= loc[0] and loc[1] <= b for a, b in brackets):
            continue  # a question for the student; what it presupposes is checked below
        if scoring.locate(original, revised[loc[0]:loc[1]]):
            continue  # the original says it too
        invented.append({"text": revised[loc[0]:loc[1]], "why_new": item.get("why_new", "")})
    in_draft = {b[1:-1].strip().lower(): b for b in BRACKET.findall(revised)}
    assumptions = []
    for a in r.get("bracket_assumptions", []):
        b = in_draft.get((a.get("bracket") or "").strip().strip("[]").strip().lower())
        if b:
            assumptions.append({"bracket": b, "why": a.get("why", "")})
    return {"invented": invented, "bracket_assumptions": assumptions,
            "voice_drift": r.get("voice_drift") or {"level": "none", "evidence": ""}}


def polish(essay: str, meta: dict, model: str) -> str:
    """Sentence-level smoothing with no substantive change: the control a revision has to beat."""
    r = llm.ask_json(rubric.POLISH_SYSTEM, rubric.polish_prompt(essay, meta), rubric.POLISH_SCHEMA, model=model)
    return r["polished_essay"].strip()


def _checked_plan(original: str, raw: dict, draft: str) -> tuple[dict, dict, list[dict], list[dict], int]:
    """Drop quotes the reviser attributed to the essay that are not in it, and tie
    questions to the brackets actually in the draft."""
    dropped = 0

    def found(q: str) -> tuple[int, int] | None:
        nonlocal dropped
        loc = scoring.locate(original, q) if q.strip() else None
        if q.strip() and not loc:
            dropped += 1
        return loc

    diag = dict(raw.get("diagnosis") or {})
    loc = found(diag.get("best_material", ""))
    diag["best_material"] = original[loc[0]:loc[1]] if loc else ""
    voice = dict(raw.get("voice") or {})
    voice["best_lines"] = [original[l[0]:l[1]] for q in voice.get("best_lines", []) if (l := found(q))]
    voice["off_voice"] = [{**o, "quote": original[l[0]:l[1]]} for o in voice.get("off_voice", []) if (l := found(o.get("quote", "")))]
    moves = []
    for m in raw.get("moves", []):
        loc = found(m.get("target", ""))
        moves.append({**m, "target": original[loc[0]:loc[1]] if loc else ""})
    asked = {}
    for q in raw.get("questions", []):
        ph = (q.get("placeholder") or "").strip()
        asked["[" + ph.strip("[]").strip() + "]"] = q.get("question", "")
    questions = [{"placeholder": b, "question": asked.get(b) or b[1:-1]} for b in dict.fromkeys(BRACKET.findall(draft))]
    return diag, voice, moves, questions, dropped


def _control(f) -> dict:
    try:
        text = f.result()
    except llm.LLMError as err:
        return {"error": str(err)}
    return {"text": text} if text else {"error": "it came back empty"}


def _evaluate(original: str, raw: dict, meta: dict, model: str, placeholders: bool, control: dict) -> dict:
    draft = unicodedata.normalize("NFC", (raw.get("revised_essay") or "").strip())
    diag, voice, moves, questions, dropped = _checked_plan(original, raw, draft)
    fails = gates(original, draft, meta, placeholders)
    fid = jd = jp = None
    if draft:
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_fid = pool.submit(fidelity, original, draft, model)
            f_jd = pool.submit(judge, original, draft, meta, model)
            f_jp = pool.submit(judge, control["text"], draft, meta, model, POLISH_NAMES) if control.get("text") else None
            try:
                fid = f_fid.result()
            except llm.LLMError as err:
                fails.append(f"The fact check could not run, so the draft cannot be verified: {err}")
            try:
                jd = f_jd.result()
            except llm.LLMError as err:
                fails.append(f"The blind comparison could not run, so the draft cannot be verified: {err}")
            if f_jp:
                try:
                    jp = f_jp.result()
                except llm.LLMError as err:
                    fails.append(f"The comparison with a polish-only rewrite could not run, so the draft cannot be verified: {err}")
            else:
                fails.append(f"The polish-only rewrite could not run, so the draft cannot be verified: {control.get('error')}")
    if fid and fid["invented"]:
        fails.append("The draft adds facts the original never states: "
                     + "; ".join(f'"{i["text"]}" ({i["why_new"]})' for i in fid["invented"])
                     + (". Remove each one or turn it into a bracketed question." if placeholders else ". Remove each one."))
    if fid and fid["bracket_assumptions"]:
        fails.append("A bracketed question assumes something your original never says: "
                     + "; ".join(f'"{a["bracket"]}" ({a["why"]})' for a in fid["bracket_assumptions"]) + ". Ask without assuming it.")
    if fid and fid["voice_drift"].get("level") == "high":
        fails.append(f"The draft no longer sounds like the same writer: {fid['voice_drift'].get('evidence', '')}")
    if jd and jd["verdict"] != "better":
        how = "preferred the original in both orders" if jd["verdict"] == "worse" else "split between the two orders"
        fails.append(f"The blind judge did not prefer the revision in both orders; it {how}. Its reason: {jd['decisive_difference']}")
    if jp and jp["verdict"] != "better":
        how = "preferred the polish-only rewrite in both orders" if jp["verdict"] == "worse" else "split between the two orders"
        fails.append("The revision did not beat a polish-only rewrite of the original in both orders, so its gain may be smoother "
                     f"sentences rather than a stronger essay; the judge {how}. Its reason: {jp['decisive_difference']}")
    return {
        "draft": draft, "diagnosis": diag, "voice": voice, "moves": moves, "questions": questions, "dropped": dropped,
        "failures": fails, "fidelity": fid, "judge": jd, "vs_polish": jp,
        "verified": not fails and jd is not None and jd["verdict"] == "better" and jp is not None and jp["verdict"] == "better",
    }


def _feedback(rnd: dict) -> str:
    lines = [f"- {f}" for f in rnd["failures"]]
    for k in (rnd["judge"] or {}).get("keep", []):
        lines.append(f'- The original did this better, so keep it: "{k["quote"]}" ({k["why"]})')
    return "\n".join(lines)


def revise(
    essay: str,
    *,
    prompt: str = "",
    essay_type: str = "personal",
    word_limit: int | None = 650,
    school: str = "",
    review: dict | None = None,
    model: str | None = None,
    placeholders: bool = True,
    max_rounds: int = 2,
    progress: Callable[[str], None] | None = None,
) -> dict:
    essay = unicodedata.normalize("NFC", essay.strip().replace("\r\n", "\n"))
    if len(essay.split()) < 50:
        raise ValueError("That is under 50 words. Paste the full essay.")
    model = model or llm.DEFAULT_MODEL
    say = progress or (lambda s: None)
    usage_before = dict(llm.usage)
    meta = {"prompt": prompt, "essay_type": essay_type, "word_limit": word_limit, "school": school}
    lint_text = summarize_for_prompt(lint(essay, word_limit))
    context = review_context(review)

    rounds: list[dict] = []
    control: dict = {}
    # The control rewrite is written while the reviser works; one serves every round.
    bg = ThreadPoolExecutor(max_workers=1)
    f_pol = bg.submit(polish, essay, meta, model)
    try:
        for n in range(1, max(1, max_rounds) + 1):
            prev = rounds[-1] if rounds else None
            say("Writing the revision plan and draft" if n == 1 else f"Round {n - 1} failed {len(prev['failures'])} check(s); revising again")
            try:
                raw = llm.ask_json(
                    rubric.REVISE_SYSTEM,
                    rubric.revise_prompt(essay, meta, lint_text, context, _feedback(prev) if prev else "",
                                         prev["draft"] if prev else "", placeholders),
                    rubric.REVISE_SCHEMA, model=model,
                )
            except llm.LLMError as err:
                if not rounds:
                    raise
                say(f"The second revision failed and was skipped: {err}")
                break
            say("Checking the draft: invented facts, mechanical checks, and blind comparisons with your original and a polish-only rewrite")
            control = control or _control(f_pol)
            rnd = {**_evaluate(essay, raw, meta, model, placeholders, control), "round": n}
            rounds.append(rnd)
            if rnd["verified"]:
                break
    finally:
        bg.shutdown(wait=False)
    # A verified round wins. Among the rest, a draft with text beats an empty one, a judged draft beats one the judge
    # never saw, and a draft without invented facts beats one with them; then fewer failures; then the earlier round.
    best = max(rounds, key=lambda r: (r["verified"], bool(r["draft"]), r["judge"] is not None,
                                      not (r["fidelity"] or {}).get("invented"), -len(r["failures"]), -r["round"]))
    say("Revision verified against your original and a polish-only rewrite" if best["verified"]
        else "Revision could not be verified; see the reasons")
    return {
        "version": 1,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "essay": essay,
        "verified": best["verified"],
        "diagnosis": best["diagnosis"],
        "voice": best["voice"],
        "moves": best["moves"],
        "draft": best["draft"],
        "questions": best["questions"],
        "diff": diff_segments(essay, best["draft"]),
        "checks": {
            "failures": best["failures"],
            "judge": best["judge"],
            "vs_polish": best["vs_polish"],
            "fidelity": best["fidelity"],
            "word_count": word_count(best["draft"]),
            "unverified_quotes_dropped": best["dropped"],
        },
        "rounds": [{"round": r["round"], "verified": r["verified"], "failures": r["failures"],
                    "verdict": (r["judge"] or {}).get("verdict"), "vs_polish": (r["vs_polish"] or {}).get("verdict"),
                    "invented": len((r["fidelity"] or {}).get("invented", []))}
                   for r in rounds],
        "used_review": bool(context),
        "usage": {k: round(llm.usage[k] - usage_before.get(k, 0), 4) for k in llm.usage},
        "models": {"reviser": model},
    }
