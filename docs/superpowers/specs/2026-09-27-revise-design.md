# Revise: a revision plan and draft that has to beat the original

Date: 2026-09-27. Status: approved by the owner's standing /goal instruction (autonomous mode).

## What the user asked for

"Gives the suggestions to change for the essay to get a lot better. Don't make the changes like some bullshit stuff, make sure that it'll actually change the essay to make it better and make it have a better voice."

Read as three requirements:

1. Suggestions that change what a reader takes away (structure, the moment the essay is built on, the reflection, the ending), not word swaps.
2. Evidence that the changes help, produced by the tool itself, not asserted.
3. A stronger voice that is still the student's: their facts, their memories, their way of talking. An essay that starts sounding like an adult editor or an AI is worse for an application even when it reads more smoothly.

## Observable result

`garyadmit revise essay.txt` and a "Make it a lot better" button on the web report both return:

- a diagnosis: what the essay is about at its best, what holds it back, and its best material (a verified quote);
- a voice profile built from the student's own best lines (verified quotes), plus the lines that break that voice;
- three to six ranked moves, each with the passage it targets, the change, a rewrite in the student's voice, and the effect on a reader;
- a full revised draft within the word limit, with at most four bracketed questions for details only the student knows;
- a verification block: blind judgments of original against revision in both orders, per-category winners, which draft sounds more like the student, anything the revision lost, a fidelity check for invented facts, and the mechanical checks (word limit, AI-tell and cliché phrases).

The draft is labeled verified only when the judge prefers it in both orders and every gate passes. Otherwise the result says plainly that it is not verified and why.

## Design

### Flow

```
review context (optional) ─┐
essay + meta + lint ───────┴─ reviser (Opus) ─ local gates ─ fidelity check ─ judge x2 (both orders)
                                   ▲                                                   │
                                   └──── one retry with the specific failures ◄────────┘
```

At most two rounds, so at most eight model calls. The better round is returned: a verified round beats an unverified one; between two unverified rounds, the one with fewer failed gates wins, and the first round wins ties.

### Components

- `garyadmit/rubric.py` gains the prompts and schemas: `REVISE_SYSTEM`, `REVISE_SCHEMA`, `revise_prompt()`, `FIDELITY_SYSTEM`, `FIDELITY_SCHEMA`, `fidelity_prompt()`, `REVISION_JUDGE_SYSTEM`, `REVISION_JUDGE_SCHEMA`, `revision_judge_prompt()`, and `POLISH_SYSTEM` for the bench control. That file already holds every prompt and schema.
- `garyadmit/revise.py` (new) owns the loop: `revise(essay, *, meta..., review=None, model, placeholders=True, max_rounds=2, progress)`, `review_context(review)`, `gates(original, revised, meta)`, `judge(original, revised, meta, model)`, `diff_segments(a, b)`, and `polish(essay, meta, model)` for the bench.
- `garyadmit/review.py`: a saved review records its history id in `result["id"]`.
- `garyadmit/server.py`: `POST /api/revise` with the same Host, Content-Type and Origin checks as `/api/review`, running as a job on the existing job table. Body `{review_id}` loads the saved review for context, and the revision is written back into that history file under `"revision"`, so reopening the review from History shows it. Body `{essay, prompt, essay_type, word_limit, school}` runs without context.
- `garyadmit/report.py`: `revision_to_text()`.
- `garyadmit/cli.py`: `garyadmit revise FILE` with the common options plus `--json`. It uses the most recent saved review of exactly the same text as context when one exists.
- `garyadmit/web/index.html`: the panel and a word-level change view (struck deletions, highlighted insertions), with "Copy draft" and "Edit this draft" (loads it into the editor for a real re-review).
- `garyadmit/bench.py`: `run_revise(n, seed, model, corpus_path)` behind `garyadmit bench --revise N`.

### The reviser prompt

The reviser is told to make the essay much stronger while keeping it the student's, and that polish alone changes no admissions decision. It works in this order of impact: build around the essay's best, most specific material; cut what a reader skims (throat-clearing openers, summaries, repeated points, résumé lists, generic claims); turn told traits and feelings into the moment that shows them, using details already in the essay or a bracketed question; make the reflection specific and earned instead of a stated moral; end on an image, action or line that carries the insight. Voice is modeled on the student's own best sentences: their diction, humor, rhythm and contractions, plain words, varied sentence length, nothing they would not say.

Hard rules: never invent events, people, places, dialogue, numbers, feelings or outcomes; reordering, cutting, compressing and expanding from what the essay states or clearly implies are allowed; brackets are questions the student can answer from memory, at most four; stay within the word limit; no AI-tell or cliché phrases from the lint lists; no added em dashes; no "I learned / I realized" moral as the ending. A strong essay gets fewer, smaller moves, and the diagnosis says it is already strong.

When a review exists, the reviser also gets its findings: the readers' impressions and committee line, the three weakest categories with what would raise each, the quoted problems and strengths, any AI suspicion, and what the stronger essays did in the comparisons the essay lost.

### Gates

Computed locally on each round's draft:

- word count within the limit;
- no AI-tell or cliché phrase that the original did not already contain;
- no moral ending unless the original ended that way;
- em dashes no denser than the larger of the original's rate and 1 per 100 words;
- at most four brackets;
- the draft is not empty or identical to the original.

Model-checked:

- fidelity: facts in the draft that the original neither states nor clearly implies, outside brackets, fail the round; so does voice drift rated high.
- judge: a revision-aware admissions judge sees "two drafts of the same student's essay" in both orders. It must pick a winner, and it reports per-category winners, a voice winner, the decisive difference, and one thing the losing draft does better (a quote to keep). It is told not to reward polish, sophistication or professional-sounding prose, to treat adult- or AI-sounding writing as a liability, and to read brackets as plain, true details of the kind described, no more impressive than the details around them.

Quotes in the diagnosis, voice profile and moves are checked against the original, as reviews already do; unverifiable quotes are dropped and counted.

### Failure handling

- A failed model call in the fidelity check or judge fails that gate for the round instead of crashing; a failed reviser call on the first round raises `LLMError` as reviews do.
- Round two receives every failed gate verbatim, the judge's decisive difference, and what the original did better.
- Essays under 50 words are refused with the same message reviews use.

## Is it actually better? The bench

Self-preference is the main threat: a Claude judge may favor Claude-written prose. `garyadmit bench --revise N` measures it with a polish-only control, a rewrite by the same model that keeps structure, content and ending and only smooths sentences. Per essay (drawn from weak, graded and published-example tiers, plus two admissions-office exemplars as a no-churn check), the bench runs the revision without placeholders so no new details can help it, then records:

- revision vs original, both orders;
- polish vs original, both orders: how much the judge rewards polish alone;
- revision vs polish, both orders: whether the substantive changes beat polish;
- the fidelity result, AI-tell and cliché deltas, and how much of the text changed.

The claim "it makes essays better" is made only if revisions beat originals clearly more often than polish does, and beat polish head to head. The numbers go in `docs/revise-bench.md`.

## Testing

The fake model in `tests/test_core.py` learns the new schemas. Tests cover: a verified round (judge prefers the revision in both orders); a split is not verified; a new AI-tell phrase, an over-limit draft, or an invented fact fails its gate and triggers a second round that sees the failure; quotes are verified; `review_context` includes lost-comparison lessons; `diff_segments` reconstructs both texts; the server runs a revise job and writes it back into the saved review; cross-site revise requests get 403.

## Out of scope

Rescoring the revised draft with the full pipeline (the student fills in the brackets, then runs a normal review, which is the honest score); multiple alternative drafts; tracking revisions over time.
