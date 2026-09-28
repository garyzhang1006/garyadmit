"""Make every line edit at once, from one button on the web report.

  edits located in the essay ─┬─ cuts and plain rewrites: made as written ────────────┐
                              └─ notes and bracketed rewrites ─ editor ─ checks ───────┤
                                          ▲                                   │        │
                                          └─── one retry for unusable answers ┘        │
  splice into the essay ─ tidy the joins ─ fact check marks undeclared details ◄───────┘

Where an edit asks for a detail only the student knows, the editor writes one and
declares it, and a fact check looks for any it did not declare, so made-up details
are marked for the student to replace. This is the one place GaryAdmit makes things
up on purpose. The result never says the essay got better; it says which changes
were made and what was invented.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Callable

from . import llm, rubric, scoring
from .lint import word_count
from .revise import diff_segments, fidelity

# The editor's dashes become commas: em dashes read as AI-polished prose.
DASH = re.compile(r"\s*—\s*|\s+--\s+")
BRACKETED = re.compile(r"\[[^\[\]\n]*\]")
FEEDBACK = {"missing": "Your answer left it out.",
            "empty": "Your text was empty. Write the replacement, or return the passage unchanged if it needs no change.",
            "bracket": "Your text still has a question in square brackets. Write the detail itself."}
REASON = {"missing": "The editor skipped it, so this passage stays as you wrote it.",
          "empty": "The editor's text came back empty, so this passage stays as you wrote it.",
          "bracket": "The editor's text still asked a question, so this passage stays as you wrote it.",
          "failed": "The second try failed, so this passage stays as you wrote it."}
PARTIAL = "The line editor's quote only partly matches your essay, so make this one yourself."
# An instruction like this, asking for the whole passage to go, may be carried out by returning no text at all.
CUT_ASK = re.compile(r"\b(?:cut|cutting|delete|deleting|remove|removing|drop|dropping|omit|omitting)\s+"
                     r"(?:it|this|that|the\s+(?:(?:whole|entire)\s+)?(?:line|sentence|paragraph|passage|clause|thing))\b", re.I)
NOT_CUT = re.compile(r"\b(?:don['’]t|do\s+not|not|never|instead\s+of|without)\s+$", re.I)
SENTENCE_END = re.compile(r"[.!?][\"”’')\]]*(?=\s|$)|\n")

# Join repairs, made only in and next to changed text, so the student's own spacing elsewhere stays as it was.
# Line-edge whitespace gets a tighter window: an indent on the line after a change is the student's, not a leftover.
LEAD, TRAIL = re.compile(r"^[ \t]+", re.M), re.compile(r"[ \t]+$", re.M)
TIDY = [
    (re.compile(r"(?<=\S)[ \t]{2,}"), " "),  # between words only: a run at a line start is an indent
    (LEAD, ""),
    (TRAIL, ""),
    (re.compile(r"[ \t]+(?=[,.;:!?)])"), ""),
    (re.compile(r",(?=[.;:!?])"), ""),
    (re.compile(r",{2,}"), ","),
    (re.compile(r"(?<!\.)\.\.(?!\.)"), "."),
    (re.compile(r"\n{3,}"), "\n\n"),
    (re.compile(r"\A\s+|\s+\Z"), ""),
]


END_MARK = re.compile(r"([.!?]+)[\"”’')\]]*\s*$")


def _starts_sentence(before: str) -> bool:
    b = before.rstrip(" \t")
    return not b or b.endswith("\n") or re.search(r"[.!?][\"”’')\]]*$", b) is not None


def _opens_sentence(after: str) -> bool:
    a = after.lstrip(" \t")
    m = re.match(r"[\"“‘'(]*(\w)", a)
    return not a or a.startswith("\n") or bool(m and m.group(1).isupper())


def _capital_first(text: str) -> bool:
    m = re.match(r"[\s\"“‘'(]*(\w)", text)
    return bool(m and m.group(1).isupper())


def _capitalized(text: str) -> str:
    m = re.match(r"[\s\"“‘'(]*(\w)(\w*)", text)
    if not m or not m.group(1).islower() or len(m.group(1).upper()) != 1:
        return text
    if any(ch.isupper() for ch in m.group(2)):
        return text  # a name styled with a later capital, such as "iPhone", keeps its lowercase first letter
    k = m.start(1)
    return text[:k] + text[k].upper() + text[k + 1:]


def splice(essay: str, changes: list[dict]) -> tuple[str, list[dict], list[tuple[int, int]]]:
    """Put each change's text in place of essay[start:end]. Changes are sorted and never overlap; each may carry
    marks whose start and end index its text. Returns the new text, the marks moved into it, and where each
    change's text now sits. Where a passage began a sentence, what replaces it starts with a capital; text that
    only follows a quoted question or an abbreviation such as "a.m." is left as written."""
    parts, marks, regions, caps, n, pos = [], [], [], [], 0, 0
    for k, c in enumerate(changes):
        keep = essay[pos:c["start"]]
        parts.append(keep)
        n += len(keep)
        text, end, passage = c["text"], c["end"], essay[c["start"]:c["end"]]
        if not text.strip():
            before = "".join(parts)
            rest = essay[end:changes[k + 1]["start"] if k + 1 < len(changes) else len(essay)]
            comma = re.match(r"[ \t]*[,;][ \t]*", rest)
            stop = END_MARK.search(passage)
            if comma and _starts_sentence(before):
                end += comma.end()  # cutting "Honestly" from "Honestly, it was fine" takes its comma too
            elif stop and not _starts_sentence(before) and _opens_sentence(essay[end:]):
                # The cut took the end of a sentence that began before it, so the sentence keeps its end mark:
                # "approached, and for me, so young. We" becomes "approached. We", never "approached, We".
                text = stop.group(1)
            elif re.search(r"(?:\A|\n)[ \t]*\Z", before):
                end += len(re.match(r"[ \t]*", rest).group(0))  # a cut after the indent takes its space, not the indent
        caps.append(_starts_sentence(essay[:c["start"]]) and _capital_first(passage))
        marks += [{**m, "start": n + m["start"], "end": n + m["end"]} for m in c.get("marks", [])]
        regions.append((n, n + len(text)))
        parts.append(text)
        n += len(text)
        pos = end
    parts.append(essay[pos:])
    out = "".join(parts)
    for (a, _), cap in zip(regions, caps):
        if cap:
            out = out[:a] + _capitalized(out[a:])
    return out, marks, regions


def _moved(x: int, subs: list[tuple[int, int, int]]) -> int:
    """Where position x lands after the replacements (start, end, new length), which are sorted and disjoint."""
    d = 0
    for s, e, k in subs:
        if x <= s:
            break
        if x < e:
            return s + d + min(x - s, k)
        d += k - (e - s)
    return x + d


def _near(pattern: re.Pattern, m: re.Match, a: int, b: int) -> bool:
    """Whether a repair's match m touches the changed region [a, b)."""
    if pattern is LEAD:
        return m.end() > a and m.start() <= b
    if pattern is TRAIL:
        return m.end() >= a and m.start() < b
    return m.start() <= b + 1 and m.end() >= a - 1


def tidy(text: str, marks: list[dict], regions: list[tuple[int, int]]) -> tuple[str, list[dict], list[tuple[int, int]]]:
    """Repair spacing and punctuation in and next to the changed regions, keeping every mark and region on its characters."""
    for pattern, repl in TIDY:
        subs = [(m.start(), m.end(), len(repl)) for m in pattern.finditer(text)
                if any(_near(pattern, m, a, b) for a, b in regions)]
        if not subs:
            continue
        pieces, pos = [], 0
        for s, e, _ in subs:
            pieces += [text[pos:s], repl]
            pos = e
        text = "".join(pieces) + text[pos:]
        marks = [{**m, "start": _moved(m["start"], subs), "end": _moved(m["end"], subs)} for m in marks]
        marks = [m for m in marks if m["end"] > m["start"]]
        regions = [(_moved(a, subs), _moved(b, subs)) for a, b in regions]
    return text, marks, regions


def usable(e) -> bool:
    """A line edit that can change the essay: a cut, a rewrite, or a note with advice."""
    return isinstance(e, dict) and (e.get("kind") in ("cut", "rewrite")
                                    or (e.get("kind") == "comment" and bool(str(e.get("suggestion") or "").strip())))


def _asks(text: str, essay: str) -> bool:
    """Whether text has a square bracket the essay itself does not have, which means a question is left."""
    rest = BRACKETED.sub(lambda m: "" if m.group(0) in essay else "[", text)
    return "[" in rest or "]" in rest


def _asks_cut(instruction: str) -> bool:
    """Whether an instruction asks for the whole passage to go, so an empty answer carries it out."""
    return any(not NOT_CUT.search(instruction[:m.start()]) for m in CUT_ASK.finditer(instruction))


def _looks_partial(e: dict, essay: str, s: int, t: int) -> bool:
    """Whether an edit saved before reviews flagged partial quotes looks like only the head of one: a long
    passage that stops mid-sentence, where a rewrite finishes the sentence the head began."""
    passage, suggestion = essay[s:t].strip(), str(e.get("suggestion") or "").strip()
    if e["kind"] not in ("rewrite", "cut") or len(passage.split()) < 6 or END_MARK.search(passage):
        return False
    nxt = re.match(r"\s*(.)", essay[t:], re.S)
    if not nxt or not (nxt.group(1).islower() or nxt.group(1) == ","):
        return False
    return e["kind"] == "cut" or END_MARK.search(suggestion) is not None


def flag_partial(essay: str, edits: list) -> list:
    """The edits with a partial flag on each, worked out for reviews saved before the review wrote one, so the page
    counts the edits this module will make."""
    out = []
    for e in edits:
        if isinstance(e, dict) and "partial" not in e:
            s, t = e.get("start"), e.get("end")
            ok = isinstance(s, int) and isinstance(t, int) and 0 <= s < t <= len(essay) and essay[s:t] == e.get("original")
            e = {**e, "partial": bool(ok and _looks_partial(e, essay, s, t))}
        out.append(e)
    return out


def _located(essay: str, edits: list) -> tuple[list[dict], list[dict]]:
    """The usable edits whose passage is in the essay, in order and never overlapping, and the ones that are not."""
    found, lost = [], []
    for i, e in enumerate(edits):
        if not usable(e):
            continue
        orig = str(e.get("original") or "")
        base = {"i": i, "kind": e["kind"], "problem": str(e.get("problem") or ""), "suggestion": str(e.get("suggestion") or "")}
        if e.get("partial") is True:
            # The review matched only the head of the line editor's quote; making it would leave the tail behind.
            lost.append({**base, "passage": orig, "reason": PARTIAL})
            continue
        s, t = e.get("start"), e.get("end")
        if isinstance(s, int) and isinstance(t, int) and 0 <= s < t <= len(essay) and essay[s:t] == orig:
            loc = (s, t)
        else:
            # A prefix match would replace only the head of the passage and leave its tail behind.
            loc = scoring.locate(essay, orig, prefix=False) if orig.strip() else None
        if not loc:
            lost.append({**base, "passage": orig, "reason": "Its passage is no longer in the essay."})
            continue
        if "partial" not in e and _looks_partial(e, essay, *loc):
            # Reviews saved before the flag existed hold head-only matches with nothing to say so.
            lost.append({**base, "passage": orig, "reason": PARTIAL})
            continue
        found.append({**base, "start": loc[0], "end": loc[1], "passage": essay[loc[0]:loc[1]]})
    found.sort(key=lambda x: (x["start"], x["end"]))
    kept = []
    for x in found:
        if kept and x["start"] < kept[-1]["end"]:
            lost.append({**x, "reason": "It overlaps an earlier edit."})
        else:
            kept.append(x)
    return kept, lost


def _open(x: dict, essay: str) -> bool:
    """Needs the editor: a note, or a rewrite that still asks for something."""
    return x["kind"] == "comment" or _asks(x["suggestion"], essay)


def _padded(text: str, passage: str) -> str:
    """text in place of passage, keeping the whitespace passage had at either end so words never glue together."""
    core = text.strip()
    if not core:
        return ""
    return passage[:len(passage) - len(passage.lstrip())] + core + passage[len(passage.rstrip()):]


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _whole(hay: str, k: int, n: int) -> bool:
    """Whether hay[k:k + n] stands as whole words, so "hum" never matches inside "hummed"."""
    return not (k > 0 and _is_word(hay[k]) and _is_word(hay[k - 1])) and \
        not (k + n < len(hay) and _is_word(hay[k + n - 1]) and _is_word(hay[k + n]))


def _occurrences(text: str, needle: str, taken: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Every place needle stands as whole words in text outside the taken spans. Failing that, the first place it
    occurs ignoring case, inside a longer word, or by locate's looser match (quote style, trailing punctuation)."""
    if not needle:
        return []
    hits: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken + hits)

    same_len = len(text.lower()) == len(text) and len(needle.lower()) == len(needle)
    for hay, pin in [(text, needle)] + ([(text.lower(), needle.lower())] if same_len else []):
        k = hay.find(pin)
        while k >= 0:
            if _whole(hay, k, len(pin)) and free(k, k + len(pin)):
                hits.append((k, k + len(pin)))
            k = hay.find(pin, k + 1)
        if hits:
            return hits
    k = text.find(needle)
    while k >= 0:
        if free(k, k + len(needle)):
            return [(k, k + len(needle))]
        k = text.find(needle, k + 1)
    loc = scoring.locate(text, needle, prefix=False)
    return [loc] if loc and free(*loc) else []


def _undashed(text: str, passage: str) -> str:
    """The editor's em dashes become commas; a dash the student wrote, in the passage the editor kept, stays."""
    kept = passage.strip()
    if text.strip() == kept:
        return text
    k = text.find(kept) if kept else -1
    if k < 0:
        return DASH.sub(", ", text)
    return DASH.sub(", ", text[:k]) + kept + DASH.sub(", ", text[k + len(kept):])


def _accepted(a: dict, passage: str) -> dict:
    """The editor's text for one edit, with every place each detail it declared appears in that text located."""
    text = _padded(_undashed(unicodedata.normalize("NFC", str(a.get("text") or "")), passage), passage)
    marks, taken = [], []
    for m in a.get("made_up") or []:
        if not isinstance(m, dict):
            continue
        t = DASH.sub(", ", unicodedata.normalize("NFC", str(m.get("text") or "").strip()))
        for k, e in _occurrences(text, t, taken):  # none: it declared a detail its text does not contain
            taken.append((k, e))
            marks.append({"start": k, "end": e, "stands_for": str(m.get("stands_for") or "").strip()})
    return {"text": text, "marks": marks, "note": DASH.sub(", ", str(a.get("note") or "").strip())}


def _flat(text: str) -> str:
    """text with runs of spaces folded, so a new paragraph break still counts as a change."""
    return re.sub(r"[ \t]*\n[ \t]*", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def _extent(draft: str, s: int, e: int, regions: list[tuple[int, int]]) -> int:
    """Where a flagged passage the checker quoted only by its head really ends: at the end of the last change in its
    sentence, never past that sentence, and never short of the head."""
    # From e - 1, so a head that already ends its sentence stays put instead of reaching into the next one.
    stop = SENTENCE_END.search(draft, max(s, e - 1))
    end = (stop.start() if stop.group(0) == "\n" else stop.end()) if stop else len(draft)
    ends = [b for a, b in regions if a < end and s < b]
    if not ends:
        return e
    end = min(end, max(ends))
    while end > e and draft[end - 1].isspace():
        end -= 1
    return max(e, end)


def _merged(draft: str, marks: list[dict], s: int, e: int, why: str) -> list[dict]:
    """marks with a fact-check span added. A span the declared marks already cover is dropped; one they cover only
    in part absorbs them, so no undeclared word is left outside a mark."""
    over = sorted((m for m in marks if m["start"] < e and s < m["end"]), key=lambda m: m["start"])
    gaps, pos = [], s
    for m in over:
        if m["start"] > pos:
            gaps.append(draft[pos:m["start"]])
        pos = max(pos, m["end"])
    gaps.append(draft[pos:e])
    if not any(re.search(r"\w", g) for g in gaps):
        return marks
    return [m for m in marks if all(m is not o for o in over)] + [{
        "start": min([s] + [m["start"] for m in over]), "end": max([e] + [m["end"] for m in over]),
        "stands_for": "; ".join(dict.fromkeys(m["stands_for"] for m in over if m.get("stands_for"))), "why": why,
        "edit": next((m["edit"] for m in over if m.get("edit") is not None), None), "source": "check"}]


def _segments(essay: str, located: list[dict], texts: dict, asking: set) -> list[tuple[str, int | None]]:
    """The draft as the editor sees it: finished changes in place, and each passage still asked about tagged with its id.
    It goes through splice and tidy like the finished essay, so the editor matches its joins to the seams the student
    will read, such as "split." where a cut took a sentence's end, never "split, "."""
    changes = [{"start": x["start"], "end": x["end"], "text": texts[x["i"]]["text"] if x["i"] in texts else x["passage"]}
               for x in located]
    draft, _, regions = tidy(*splice(essay, changes))
    segs, pos = [], 0
    for x, (a, b) in zip(located, regions):
        if x["i"] in asking and x["i"] not in texts:
            segs += [(draft[pos:a], None), (draft[a:b], x["i"])]
            pos = b
    segs.append((draft[pos:], None))
    return [s for s in segs if s[0] or s[1] is not None]


def _n(k: int, word: str) -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def apply_all(
    essay: str,
    edits: list,
    *,
    meta: dict,
    model: str | None = None,
    max_rounds: int = 2,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Make every usable line edit. `edits` are a saved review's line edits, whose offsets index `essay`.
    Raises ValueError when there is nothing to make."""
    essay = unicodedata.normalize("NFC", (essay or "").strip().replace("\r\n", "\n"))
    if len(essay.split()) < 50:
        raise ValueError("That is under 50 words. Paste the full essay.")
    located, lost = _located(essay, edits if isinstance(edits, list) else [])
    if not located:
        if lost and all(x["reason"] == PARTIAL for x in lost):
            raise ValueError("The line editor's quotes in this review only partly match your essay, so none of its edits "
                             "can be made here. Make them yourself from the Line edits tab.")
        raise ValueError("None of this review's line edits match the essay anymore. Run the review again."
                         if lost else "This review has no line edits to make.")
    model = model or llm.DEFAULT_MODEL
    say = progress or (lambda s: None)
    usage_before = dict(llm.usage)

    texts = {x["i"]: {"text": _padded(x["suggestion"], x["passage"]) if x["kind"] == "rewrite" else "", "marks": []}
             for x in located if not _open(x, essay)}
    asking = [x for x in located if _open(x, essay)]
    if texts:
        say(f"Making {_n(len(texts), 'edit')} exactly as written")
    reasons: dict[int, str] = {}
    feedback = ""
    for rnd in range(1, max(1, max_rounds) + 1):
        if not asking:
            break
        say(f"Writing {_n(len(asking), 'change')} that need new words, with the editor listing each detail it makes up"
            if rnd == 1 else f"Asking again for {_n(len(asking), 'change')} that came back unusable")
        segs = _segments(essay, located, texts, {x["i"] for x in asking})
        items = [{"id": x["i"], "kind": x["kind"], "problem": x["problem"], "suggestion": x["suggestion"]} for x in asking]
        try:
            raw = llm.ask_json(rubric.APPLY_SYSTEM,
                               rubric.apply_prompt(segs, meta, items, word_count("".join(t for t, _ in segs)), feedback),
                               rubric.APPLY_SCHEMA, model=model)
        except llm.LLMError as err:
            if rnd == 1:
                raise
            say(f"The second try failed and was skipped: {err}")
            reasons.update({x["i"]: REASON["failed"] for x in asking})
            break
        answers: dict[int, dict] = {}
        for a in raw.get("applied") or []:
            if isinstance(a, dict) and isinstance(a.get("id"), int):
                answers.setdefault(a["id"], a)
        still, notes = [], []
        for x in asking:
            a = answers.get(x["i"])
            text = str(a.get("text") or "") if a is not None else ""
            empty = not text.strip() and not _asks_cut(x["suggestion"])
            why = "missing" if a is None else "empty" if empty else "bracket" if _asks(text, essay) else ""
            if why or a is None:
                still.append(x)
                notes.append(f"- id {x['i']}: {FEEDBACK[why]}")
                reasons[x["i"]] = REASON[why]
            else:
                texts[x["i"]] = _accepted(a, x["passage"])
                reasons.pop(x["i"], None)
        asking, feedback = still, "\n".join(notes)

    changes = [{"start": x["start"], "end": x["end"], "text": texts[x["i"]]["text"],
                "marks": [{**m, "edit": x["i"], "source": "editor"} for m in texts[x["i"]]["marks"]]}
               for x in located if x["i"] in texts]
    draft, marks, regions = tidy(*splice(essay, changes))

    # A declared detail the original never says, in any letter case, is made up wherever it appears, including
    # where a retry or another edit reused it without declaring it again.
    for m in list(marks):
        t = draft[m["start"]:m["end"]]
        if t and t.lower() not in essay.lower():
            marks += [{**m, "start": a, "end": b} for a, b in _occurrences(draft, t, [(x["start"], x["end"]) for x in marks])
                      if _whole(draft, a, b - a)]

    # The editor's declarations are its own word, and the line editor's rewrites were never fact-checked,
    # so the whole draft goes through the same invented-fact check as a rewrite.
    fact = {"ran": False, "error": "", "voice_drift": None}
    if draft != essay:
        say("Checking the new essay for made-up details that were not marked")
        try:
            fid = fidelity(essay, draft, model, keep_heads=True)
        except llm.LLMError as err:
            fact["error"] = str(err)
        else:
            fact.update(ran=True, voice_drift=fid["voice_drift"])
            for item in fid["invented"]:
                # The checker's quote can drift at its end; fidelity then keeps only the head it could find, which
                # may be the student's own words, so what counts is the head carried to the end of the change.
                for s, e in _occurrences(draft, item["text"], []):
                    end = _extent(draft, s, e, regions) if item.get("head_only") else e
                    if item.get("head_only") and scoring.locate(essay, draft[s:end], prefix=False):
                        continue
                    marks = _merged(draft, marks, s, end, item.get("why_new", ""))
    marks.sort(key=lambda m: m["start"])

    report = []
    for x in located + lost:
        entry = {"i": x["i"], "kind": x["kind"], "original": x["passage"], "status": "not made", "text": "",
                 "reason": x.get("reason") or reasons.get(x["i"], "")}
        if x["i"] in texts:
            t = texts[x["i"]]["text"]
            # Judged by what the change does to the essay: a period the essay already has after the passage is no change.
            same = _flat(t) == _flat(x["passage"]) or \
                tidy(*splice(essay, [{"start": x["start"], "end": x["end"], "text": t}]))[0] == essay
            # A passage the editor left alone carries its note, such as a paragraph move only the student can make.
            entry.update(status="unchanged" if same else "made", text=t, reason=texts[x["i"]].get("note", "") if same else "")
        report.append(entry)
    report.sort(key=lambda r: r["i"])
    counts = {"made": 0, "unchanged": 0, "not_made": 0}
    for r in report:
        counts[r["status"].replace(" ", "_")] += 1
    wc, limit = word_count(draft), meta.get("word_limit")
    say(f"Made {counts['made']} of {_n(len(report), 'change')}")
    return {
        "version": 1,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "meta": dict(meta),
        "essay": essay,
        "draft": draft,
        "diff": diff_segments(essay, draft),
        "made_up": [{"start": m["start"], "end": m["end"], "text": draft[m["start"]:m["end"]],
                     "stands_for": m.get("stands_for", ""), "why": m.get("why", ""), "edit": m.get("edit"),
                     "source": m["source"]} for m in marks],
        "edits": report,
        "counts": counts,
        "checks": {"word_count": wc, "over_limit": bool(limit and wc > limit), "fact_check": fact},
        "usage": {k: round(llm.usage[k] - usage_before.get(k, 0), 4) for k in llm.usage},
        "models": {"editor": model},
    }
