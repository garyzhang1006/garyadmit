"""End-to-end review pipeline.

  lint ─┬─ reviewer A (admissions officer) ─┐
        ├─ reviewer B (editor) ─────────────┼─ adjudicate disputes ─┐
        ├─ line editor ─────────────────────┤                       ├─ final score + report
        └─ profile → BM25 → rerank → blind head-to-heads (both orders)┘

Model calls run concurrently, so a full review takes about as long as the
slowest chain (roughly 1-3 minutes on Opus).
"""

from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from itertools import chain, zip_longest
from pathlib import Path
from typing import Callable

from . import llm, rubric, scoring
from .corpus import Corpus, Essay, load_anchors, pick_anchors
from .lint import lint, summarize_for_prompt

HISTORY_DIR = Path.home() / ".garyadmit" / "history"
# Human ratings (4-9 scale) of the hidden anchors each essay is compared with:
# spread across the range so any essay gets informative wins and losses.
ANCHOR_TARGETS = [5.0, 6.0, 7.0, 8.25]

_corpus_cache: dict[str, Corpus] = {}


def get_corpus(path: str | None = None) -> Corpus:
    key = path or "default"
    if key not in _corpus_cache:
        _corpus_cache[key] = Corpus.load(path)
    return _corpus_cache[key]


def _checked_review(essay: str, raw: dict) -> dict:
    """Drop evidence the model invented: any weakness/strength whose quote is not in the essay."""
    raw = dict(raw)
    bad = 0
    for key in ("weaknesses", "strengths"):
        kept = []
        for item in raw.get(key, []):
            if scoring.quote_ok(essay, item.get("quote", "")):
                kept.append(item)
            else:
                bad += 1
        raw[key] = kept
    for c in rubric.CATEGORIES:
        s = raw["scores"][c]
        if s.get("quote") and not scoring.quote_ok(essay, s["quote"]):
            s["quote"] = ""
            bad += 1
    raw["_unverified_quotes_dropped"] = bad
    return raw


def _checked_edits(essay: str, raw: dict) -> list[dict]:
    edits, seen = [], []
    for e in raw.get("edits", []):
        loc = scoring.locate(essay, e.get("original", ""))
        if not loc:
            continue
        if any(not (loc[1] <= a or loc[0] >= b) for a, b in seen):
            continue  # overlapping spans cannot both be highlighted inline
        seen.append(loc)
        edits.append({**e, "start": loc[0], "end": loc[1], "original": essay[loc[0]:loc[1]]})
    edits.sort(key=lambda e: e["start"])
    return edits


def _dedupe_quoted(essay: str, *lists: list[dict]) -> list[dict]:
    """Interleave the readers' items and drop any whose quote mostly overlaps one already kept."""
    kept, spans = [], []
    for it in (x for x in chain.from_iterable(zip_longest(*lists)) if x):
        loc = scoring.locate(essay, it.get("quote", ""))
        if loc and any(min(loc[1], b) - max(loc[0], a) > 0.5 * min(loc[1] - loc[0], b - a) for a, b in spans):
            continue
        if loc:
            spans.append(loc)
        kept.append(it)
    return kept


def find_similar(essay: str, meta: dict, corpus: Corpus, k: int, fast_model: str) -> tuple[dict, list[dict]]:
    profile = llm.ask_json(rubric.PROFILE_SYSTEM, f"<essay>\n{essay}\n</essay>", rubric.PROFILE_SCHEMA, model=fast_model)
    query = " ".join([profile["topic"], " ".join(profile["themes"]), essay])
    pool = corpus.search(query, k=30, boost_terms=profile["keywords"], exclude_text=essay)
    want_type = meta.get("essay_type", "personal")
    same_type = [(e, s) for e, s in pool if e.essay_type == want_type]
    # Prefer same essay type but keep enough candidates for the reranker to choose from.
    pool = same_type if len(same_type) >= k * 2 else pool
    if not pool:
        return profile, []
    cands = [
        {"id": e.id, "title": e.title, "school": e.school, "type": e.essay_type, "opening": e.text[:900]}
        for e, _ in pool[:24]
    ]
    rr = llm.ask_json(
        rubric.RERANK_SYSTEM,
        f"Student essay profile:\n{json.dumps(profile, indent=1)}\n\nStudent essay opening:\n{essay[:1200]}\n\n"
        f"Candidates:\n{json.dumps(cands, indent=1)}\n\nReturn the {k} most similar, most similar first.",
        rubric.RERANK_SCHEMA, model=fast_model,
    )
    by_id = {e.id: e for e, _ in pool}
    out = []
    for m in rr["matches"]:
        e = by_id.get(m["id"])
        if e and all(o["essay"].id != e.id for o in out):
            out.append({"essay": e, "why_similar": m["why_similar"]})
        if len(out) >= k:
            break
    for e, _ in pool:  # reranker returned too few valid ids: backfill from BM25 order
        if len(out) >= k:
            break
        if all(o["essay"].id != e.id for o in out):
            out.append({"essay": e, "why_similar": "Lexical match on topic words."})
    return profile, out


def head_to_head(essay: str, opp_text: str, meta: dict, model: str) -> dict:
    """Blind pairwise judgment in both orders; a win only counts if it survives the swap."""
    results = []
    for user_first in (True, False):
        e1, e2 = (essay, opp_text) if user_first else (opp_text, essay)
        r = llm.ask_json(rubric.COMPARE_SYSTEM, rubric.compare_prompt(e1, e2, meta), rubric.COMPARE_SCHEMA, model=model)
        user_label = "1" if user_first else "2"
        r["user_won"] = r["winner"] == user_label
        r["user_label"] = user_label
        results.append(r)
    outcome = scoring.head_to_head_outcome(results[0]["user_won"], results[1]["user_won"])
    cat = {}
    for c in rubric.CATEGORIES:
        pts = 0.0
        for r in results:
            w = r["category_winners"][c]
            pts += 0.5 if w == "tie" else (1.0 if w == r["user_label"] else 0.0)
        cat[c] = pts / len(results)
    # Explanations come from the order whose verdict matches the majority.
    lead = next((r for r in results if r["user_won"] == (outcome >= 0.5)), results[0])
    return {
        "outcome": outcome,
        "verdict": "win" if outcome == 1 else "loss" if outcome == 0 else "split",
        "confidence": [r["confidence"] for r in results],
        "category_share": cat,
        "decisive_difference": lead["decisive_difference"],
        "lesson": lead["lesson_for_weaker"],
        "stronger_quote": lead["stronger_quote"],
    }


def review(
    essay: str,
    *,
    prompt: str = "",
    essay_type: str = "personal",
    word_limit: int | None = 650,
    school: str = "",
    model: str | None = None,
    fast_model: str | None = None,
    n_similar: int = 5,
    n_compare: int = 3,
    n_anchor: int = 4,
    corpus_path: str | None = None,
    anchors_path: str | None = None,
    progress: Callable[[str], None] | None = None,
    save: bool = True,
    line_edits: bool = True,
) -> dict:
    essay = essay.strip().replace("\r\n", "\n")
    if len(essay.split()) < 50:
        raise ValueError("That is under 50 words. Paste the full essay.")
    model = model or llm.DEFAULT_MODEL
    fast_model = fast_model or llm.FAST_MODEL
    say = progress or (lambda s: None)
    meta = {"prompt": prompt, "essay_type": essay_type, "word_limit": word_limit, "school": school}

    lint_report = lint(essay, word_limit)
    lint_text = summarize_for_prompt(lint_report)
    say("Mechanical checks done")
    try:
        corpus = get_corpus(corpus_path)
    except FileNotFoundError as err:
        corpus = None
        say(str(err))
    user_prompt = rubric.reviewer_prompt(essay, meta, lint_text)
    # Anchors are personal-statement drafts, so they only calibrate personal statements.
    anchors = pick_anchors(load_anchors(anchors_path), ANCHOR_TARGETS[:n_anchor], essay, exclude_text=essay) \
        if essay_type == "personal" and n_anchor else []

    with ThreadPoolExecutor(max_workers=8) as pool:
        fut_a = pool.submit(llm.ask_json, rubric.reviewer_system(rubric.PERSONA_AO), user_prompt, rubric.REVIEW_SCHEMA, model=model)
        fut_b = pool.submit(llm.ask_json, rubric.reviewer_system(rubric.PERSONA_EDITOR), user_prompt, rubric.REVIEW_SCHEMA, model=model)
        fut_e = pool.submit(llm.ask_json, rubric.EDITOR_SYSTEM, rubric.edits_prompt(essay, meta), rubric.EDITS_SCHEMA,
                            model=model) if line_edits else None
        fut_anchor = [pool.submit(head_to_head, essay, a.text, meta, model) for a in anchors]

        profile, similar, h2h = None, [], []
        if corpus is not None and len(corpus) and n_compare:
            profile, similar = find_similar(essay, meta, corpus, max(n_similar, n_compare), fast_model)
            say(f"Found {len(similar)} similar published essays")
            futs = [(s["essay"], pool.submit(head_to_head, essay, s["essay"].text, meta, model)) for s in similar[:n_compare]]
            for opp, f in futs:
                h2h.append({**f.result(), "opponent": opp})
            say("Head-to-head comparisons done")
        calib = [{**f.result(), "anchor": a} for a, f in zip(anchors, fut_anchor)]
        if calib:
            say("Calibration comparisons done")

        rev_a = _checked_review(essay, fut_a.result())
        say("Admissions-officer read done")
        rev_b = _checked_review(essay, fut_b.result())
        say("Editor read done")
        edits = _checked_edits(essay, fut_e.result()) if fut_e else []
        if fut_e:
            say("Line edits done")

    merged, disputed = scoring.merge_reviewers([rev_a, rev_b])
    adjudication = {}
    if disputed:
        say(f"Reviewers disagreed on {', '.join(disputed)}; adjudicating")
        detail = {
            c: {
                "reader_1": {"score": rev_a["scores"][c]["score"], "reason": rev_a["scores"][c]["justification"]},
                "reader_2": {"score": rev_b["scores"][c]["score"], "reason": rev_b["scores"][c]["justification"]},
            }
            for c in disputed
        }
        adjudication = llm.ask_json(
            rubric.adjudicator_system(),
            f"{user_prompt}\n\nDisputed categories:\n{json.dumps(detail, indent=1)}",
            rubric.adjudicate_schema(disputed), model=model,
        )
        for c in disputed:
            merged[c] = float(adjudication[c]["score"])

    rubric_score = scoring.rubric_overall(merged)
    matches = [(h["opponent"].level, h["outcome"]) for h in h2h if h["outcome"] is not None]
    matches += [(c["anchor"].level, c["outcome"]) for c in calib if c["outcome"] is not None]
    final = scoring.final_score(rubric_score, matches)
    band, band_desc = rubric.band(final)

    result = {
        "version": 1,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "essay": essay,
        "score": final,
        "rubric_score": rubric_score,
        "band": band,
        "band_description": band_desc,
        "categories": {
            c: {
                "score": round(merged[c], 1),
                "reader_1": rev_a["scores"][c]["score"],
                "reader_2": rev_b["scores"][c]["score"],
                "adjudicated": c in disputed,
                "adjudication_reason": adjudication.get(c, {}).get("reason", ""),
                "justification": [rev_a["scores"][c]["justification"], rev_b["scores"][c]["justification"]],
                "quote": rev_a["scores"][c]["quote"] or rev_b["scores"][c]["quote"],
                "to_raise": rev_b["scores"][c]["to_raise"] or rev_a["scores"][c]["to_raise"],
            }
            for c in rubric.CATEGORIES
        },
        "readers": [
            {"name": "Admissions officer", **{k: rev_a[k] for k in ("first_impression", "committee_line", "weaknesses", "strengths", "ai_suspicion", "top_fixes", "_unverified_quotes_dropped")}},
            {"name": "Senior editor", **{k: rev_b[k] for k in ("first_impression", "committee_line", "weaknesses", "strengths", "ai_suspicion", "top_fixes", "_unverified_quotes_dropped")}},
        ],
        # Both readers often flag the same line; the report shows each passage once.
        "problems": sorted(_dedupe_quoted(essay, rev_a["weaknesses"], rev_b["weaknesses"]),
                           key=lambda w: w.get("severity") != "major"),
        "strengths": _dedupe_quoted(essay, rev_a["strengths"], rev_b["strengths"]),
        "edits": edits,
        "lint": lint_report,
        "profile": profile,
        "similar": [
            {**_essay_card(s["essay"]), "why_similar": s["why_similar"]} for s in similar[:n_similar]
        ],
        "head_to_head": [
            {**{k: v for k, v in h.items() if k != "opponent"}, "opponent": _essay_card(h["opponent"])} for h in h2h
        ],
        # Anchor essays are private drafts: report only their human rating and the verdict.
        "calibration": [
            {"rating": c["anchor"].rating, "level": c["anchor"].level, "outcome": c["outcome"],
             "verdict": c["verdict"], "decisive_difference": c["decisive_difference"]}
            for c in calib
        ],
        "usage": dict(llm.usage),
        "models": {"judge": model, "fast": fast_model},
    }
    if save:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        (HISTORY_DIR / f"{stamp}.json").write_text(json.dumps(result, indent=1))
    return result


def _essay_card(e: Essay) -> dict:
    return {
        "id": e.id, "title": e.title, "school": e.school, "year": e.year, "url": e.url,
        "source": e.source, "tier": e.tier, "level": e.level, "essay_type": e.essay_type,
        "excerpt": e.text[:400], "text": e.text,
    }
