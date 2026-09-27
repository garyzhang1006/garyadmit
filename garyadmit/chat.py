"""Chat edits: the student asks for a change in their own words ("make the hook a
10/10") and gets the essay back with that change made, held to the revision checks.

  message + current draft ─ editor ─ gates ─ fact check against the original and the student's own chat messages
                              ▲       └──── blind 1-10 rating of the part asked about, before vs after, both orders
                              └──── one retry with the failures ◄───┘

A question ("is my ending too abrupt?") gets an answer and no edit, for one call.
The judge never sees the request or which draft is new, so a change only counts
as an improvement when the part scores higher in both orders on average.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import llm, rubric, scoring
from .lint import lint, summarize_for_prompt, word_count
from .revise import BRACKET, _name_drafts, diff_segments, fidelity, gates, review_context

MAX_TURNS = 8  # the most recent messages the editor sees; every student message still counts as a fact
MAX_TURN_CHARS = 1500
NAMES = ("the previous version", "the new version")
WHOLE = "the essay as a whole"  # rated when the student asked for a fact or mechanical change, not a quality gain


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", (text or "").strip().replace("\r\n", "\n"))


def _num(x: float) -> str:
    return f"{x:g}"


def _score(x) -> int:
    try:
        return max(1, min(10, round(float(x))))
    except (TypeError, ValueError):
        raise llm.LLMError(f"the judge returned a score that is not a number: {x!r}") from None


def rate(base: str, candidate: str, meta: dict, aspect: str, category: str, model: str) -> dict:
    """Score the asked-about part of both drafts, blind, in both orders. Judges favor a
    position, so a change only shows as a gain when it survives the swap."""
    def one(cand_first: bool) -> dict:
        d1, d2 = (candidate, base) if cand_first else (base, candidate)
        r = llm.ask_json(rubric.ASPECT_JUDGE_SYSTEM, rubric.aspect_judge_prompt(d1, d2, meta, aspect, category),
                         rubric.ASPECT_JUDGE_SCHEMA, model=model)
        c, b = ("1", "2") if cand_first else ("2", "1")
        name = lambda t: _name_drafts(t or "", c, NAMES)
        return {"after": _score(r[f"score_{c}"]), "before": _score(r[f"score_{b}"]), "to_ten": name(r[f"to_ten_{c}"]),
                "why_after": name(r[f"why_{c}"]), "cand_won": r["overall_winner"] == c, "reason": name(r["overall_reason"])}

    with ThreadPoolExecutor(max_workers=2) as pool:
        orders = list(pool.map(one, (True, False)))
    wins = sum(o["cand_won"] for o in orders)
    overall = "better" if wins == 2 else "worse" if wins == 0 else "split"
    lead = next((o for o in orders if o["cand_won"] == (overall == "better")), orders[0])
    # The advice comes from the order that scored the new version lower: that is what still holds it back.
    low = min(orders, key=lambda o: o["after"])
    return {"aspect": aspect, "category": category,
            "before": sum(o["before"] for o in orders) / 2, "after": sum(o["after"] for o in orders) / 2,
            "overall": overall, "reason": lead["reason"], "to_ten": low["to_ten"], "why_after": low["why_after"]}


def _questions(raw: dict, draft: str) -> list[dict]:
    asked = {"[" + (q.get("placeholder") or "").strip().strip("[]").strip() + "]": q.get("question", "") for q in raw.get("questions", [])}
    return [{"placeholder": b, "question": asked.get(b) or b[1:-1]} for b in dict.fromkeys(BRACKET.findall(draft))]


def _evaluate(original: str, facts: str, base: str, raw: dict, meta: dict, model: str) -> dict:
    draft = _norm(raw.get("revised_essay") if raw.get("edit") else "")
    # Every edit is rated, so the editor cannot skip the judge by leaving the aspect empty; only a
    # requested quality gain has to score higher, while a fact or mechanical change only must not score lower.
    asked = (raw.get("aspect") or "").strip()
    aspect = asked or WHOLE
    category = raw.get("category") if asked and raw.get("category") in rubric.CATEGORIES else ""
    fails = gates(original, draft, meta, base=base)
    fid = rating = None
    inherited = []
    if draft:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_fid = pool.submit(fidelity, facts, draft, model)
            f_rate = pool.submit(rate, base, draft, meta, aspect, category, model)
            try:
                fid = f_fid.result()
            except llm.LLMError as err:
                fails.append(f"The fact check could not run, so invented details may have slipped in: {err}")
            try:
                rating = f_rate.result()
            except llm.LLMError as err:
                fails.append(f"The blind rating could not run, so there is no before and after score: {err}")
    if fid:
        # Details the working draft already carried (say, from an unverified revision) are not this edit's doing.
        inherited = [i for i in fid["invented"] if scoring.locate(base, i["text"], prefix=False)]
        fid = {**fid, "invented": [i for i in fid["invented"] if i not in inherited],
               "bracket_assumptions": [a for a in fid["bracket_assumptions"] if a["bracket"] not in base]}
    if fid and fid["invented"]:
        fails.append("The new version adds facts that neither your essay nor this chat states: "
                     + "; ".join(f'"{i["text"]}" ({i["why_new"]})' for i in fid["invented"])
                     + ". Remove each one or turn it into a bracketed question.")
    if fid and fid["bracket_assumptions"]:
        fails.append("A bracketed question assumes something your essay never says: "
                     + "; ".join(f'"{a["bracket"]}" ({a["why"]})' for a in fid["bracket_assumptions"]) + ". Ask without assuming it.")
    if fid and fid["voice_drift"].get("level") == "high":
        fails.append(f"The new version no longer sounds like the same writer: {fid['voice_drift'].get('evidence', '')}")
    if rating and (rating["after"] < rating["before"] or (asked and rating["after"] == rating["before"])):
        fails.append(f"The blind judge did not score {aspect} {'higher' if asked else 'as high'} after this change "
                     f"({_num(rating['before'])} → {_num(rating['after'])}). Its reason: {rating['why_after']}")
    if rating and rating["overall"] == "worse":
        fails.append(f"The blind judge preferred the whole essay before this change, in both orders. Its reason: {rating['reason']}")
    return {"draft": draft, "reply": (raw.get("reply") or "").strip(), "changes": [str(c) for c in raw.get("changes", []) if str(c).strip()],
            "questions": _questions(raw, draft), "failures": fails, "fidelity": fid, "inherited": inherited, "rating": rating,
            "target": _target(raw.get("target"))}


def _target(x) -> int:
    try:
        return max(0, min(10, round(float(x or 0))))
    except (TypeError, ValueError):
        return 0


def _feedback(rnd: dict) -> str:
    lines = [f"- {f}" for f in rnd["failures"]]
    if rnd["rating"] and rnd["rating"]["to_ten"]:
        lines.append(f"- The judge said this would raise {rnd['rating']['aspect']} to a 10: {rnd['rating']['to_ten']}")
    return "\n".join(lines)


def chat(
    original: str,
    draft: str,
    message: str,
    *,
    history: list[dict] | None = None,
    meta: dict | None = None,
    review: dict | None = None,
    model: str | None = None,
    advice: str = "",
    max_rounds: int = 2,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """`advice` is the judge's note from an earlier turn that the student asked the editor to act on;
    it steers the editor but, unlike the student's own messages, never counts as a fact."""
    original, base, message = _norm(original), _norm(draft) or _norm(original), _norm(message)
    if not message:
        raise ValueError("Type what you want changed, or ask a question about the essay.")
    if len(original.split()) < 50:
        raise ValueError("That is under 50 words. Paste the full essay.")
    model = model or llm.DEFAULT_MODEL
    say = progress or (lambda s: None)
    usage_before = dict(llm.usage)
    meta = {"prompt": "", "essay_type": "personal", "word_limit": 650, "school": "", **(meta or {})}
    history = [{"role": h["role"], "text": _norm(str(h.get("text", "")))} for h in (history or [])
               if isinstance(h, dict) and h.get("role") in ("user", "assistant") and str(h.get("text", "")).strip()]
    # What the student typed in this chat is theirs to state, so the fact check accepts it, in full, alongside the original.
    told = [h["text"] for h in history if h["role"] == "user"] + [message]
    shown = [{**h, "text": h["text"][:MAX_TURN_CHARS]} for h in history[-MAX_TURNS:]]
    facts = original + "\n\nThe student also told their editor, in their own words:\n" + "\n".join(f"- {t}" for t in told)
    lint_text = summarize_for_prompt(lint(base, meta.get("word_limit")))
    context = review_context(review)

    rounds: list[dict] = []
    for n in range(1, max(1, max_rounds) + 1):
        prev = rounds[-1] if rounds else None
        say("Making the change" if n == 1 else f"The first try failed {len(prev['failures'])} check(s); trying again")
        try:
            raw = llm.ask_json(rubric.CHAT_SYSTEM,
                               rubric.chat_prompt(original, base, message, meta, lint_text, shown, context,
                                                  _feedback(prev) if prev else "", prev["draft"] if prev else "", _norm(advice)),
                               rubric.CHAT_SCHEMA, model=model)
        except llm.LLMError as err:
            if not rounds:
                raise
            say(f"The second try failed and was skipped: {err}")
            break
        if n == 1 and not raw.get("edit"):
            say("Answered without changing the essay")
            return _result(message, base, {"draft": "", "reply": (raw.get("reply") or "").strip(), "changes": [], "questions": [],
                                           "failures": [], "fidelity": None, "inherited": [], "rating": None, "target": 0},
                           [], usage_before, model)
        say("Checking it: invented facts, mechanical checks, and a blind before-and-after rating of "
            + ((raw.get("aspect") or "").strip() or WHOLE))
        rnd = {**_evaluate(original, facts, base, raw, meta, model), "round": n}
        rounds.append(rnd)
        if not rnd["failures"]:
            break
    # A clean round wins; then a round with a draft, one without invented facts, fewer failures, and the earlier round.
    best = max(rounds, key=lambda r: (not r["failures"], bool(r["draft"]), not (r["fidelity"] or {}).get("invented"),
                                      -len(r["failures"]), -r["round"]))
    say("Change made and checked" if not best["failures"] else "Change made, but some checks failed; see below")
    return _result(message, base, best, rounds, usage_before, model)


def _result(message: str, base: str, best: dict, rounds: list[dict], usage_before: dict, model: str) -> dict:
    edited = bool(best["draft"])
    draft = best["draft"] or base
    rating = {**best["rating"], "target": best["target"] or None} if best["rating"] else None
    return {
        "version": 1,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "message": message,
        "reply": best["reply"],
        "edited": edited,
        "base": base,
        "draft": draft,
        "diff": diff_segments(base, draft) if edited else None,
        "changes": best["changes"],
        "questions": best["questions"],
        "rating": rating,
        "passed": not best["failures"],
        "checks": {"failures": best["failures"], "fidelity": best["fidelity"], "inherited": best["inherited"],
                   "word_count": word_count(draft)},
        "rounds": [{"round": r["round"], "failures": r["failures"], "invented": len((r["fidelity"] or {}).get("invented", [])),
                    "before": (r["rating"] or {}).get("before"), "after": (r["rating"] or {}).get("after")} for r in rounds],
        "usage": {k: round(llm.usage[k] - usage_before.get(k, 0), 4) for k in llm.usage},
        "models": {"editor": model},
    }
