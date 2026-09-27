# GaryAdmit

A local college essay reviewer modeled on MaxAdmit's human review: two independent readers, a score out of 100, category scores, line edits, and a ranked list of what to fix. It runs on your Claude subscription through the Claude Code CLI, so there is no API key and no per-review bill.

What it adds on top of MaxAdmit's format is a score you can check. Every review compares your essay, blind and in both orders, against real published essays on the same kind of topic and against drafts that experienced readers already rated. A rubric score that loses those comparisons gets pulled down. `garyadmit bench` measures how closely the scores track human ratings, so you can see for yourself how honest they are.

## Install

You need Python 3.10+ and the Claude Code CLI, logged in (`claude` should open a session).

```bash
git clone https://github.com/garyzhang1006/garyadmit
cd garyadmit
pip install -e .
```

`uv tool install --editable .` works too. The app itself has no Python dependencies.

## Use

```bash
garyadmit serve
```

That opens `http://127.0.0.1:8765`. Paste an essay, add the prompt and word limit, and wait one to three minutes. The server only listens on localhost.

From the terminal:

```bash
garyadmit review essay.txt --prompt "Share an essay on any topic of your choice."
garyadmit review why_us.txt --type supplement --school Tufts --limit 250
garyadmit similar essay.txt          # just list the closest published essays
garyadmit history                    # past reviews, stored in ~/.garyadmit/history
garyadmit bench                      # check the scoring against human ratings
```

`--fast` uses Sonnet for everything. `--no-compare` skips the comparisons and returns a rubric-only score, which is faster but less trustworthy.

## What a review contains

- An overall score and a plain-language band (Typical, Above average, Strong, and so on).
- Seven category scores: hook, voice, flow, conciseness, authenticity, uniqueness (MaxAdmit's six) and insight, each with both readers' numbers.
- What each reader would remember, the line they would say in committee, and whether anything reads as AI-written or adult-edited.
- The biggest problems and the strengths, each tied to a quote from your essay.
- Line edits shown inline on your essay: cuts, rewrites, and comments.
- Head-to-head results against similar published essays, with links, what decided each one, and what to take from the essays you lost to.
- Mechanical checks: word count, clichés, AI-tell vocabulary, told emotions, passive voice, résumé lists, moralizing endings, sentence rhythm.

## Why the score is hard to inflate

Language models flatter by default. GaryAdmit counters that in layers.

**Anchored rubric.** Category scores use written anchors: 5 is the median applicant, 7 is top quarter, 8 is top tenth, 9 is top 2%. Readers are told their scores are audited against admissions readers' ratings and that inflation counts as an error the same as harshness.

**Anonymous framing.** The model is told it is scoring an essay from the applicant pool for a calibration read. It never learns that the person asking wrote it, which removes the pull to be encouraging.

**Two readers, adjudicated.** A former admissions officer and a reader-trainer score independently. Any category where they differ by 3 or more goes to a third call that has to pick the reading the text supports.

**Quotes or it didn't happen.** Every strength and weakness has to quote your essay. Quotes that are not in the essay get dropped, and the report says how many were dropped.

**Blind comparisons in both orders.** Your essay is judged against published essays and against human-rated drafts, once as essay 1 and once as essay 2. Models favor whichever essay comes first; a win only counts if it survives the swap, and a disagreement counts as a split.

**Score from evidence.** The final score combines the rubric score (as a prior with SD 8) with the comparison results (a logistic model against each opponent's known level). If the rubric says 85 but the essay loses to 70-level essays, the final score comes down.

The hidden calibration drafts come from the ElevatEd dataset, where experienced readers rated each draft 4 to 9. They are never shown in the report; only their rating and the verdict appear. A quarter of them are held out for `garyadmit bench` and never used as anchors.

## The corpus

`corpus/essays.jsonl` holds published essays with their source links, from admissions offices (Johns Hopkins, Emory, Tufts, Connecticut College, Hamilton, St. John's), student newspapers (The Harvard Crimson, The Tech), and counseling sites that publish full examples (CollegeVine, Shemmassian, PrepScholar, AdmitReport, StudyNotes). Each essay keeps a tier: exemplar when an admissions office picked it, admitted when the writer got in, example or weak when a counselor published it as such. `corpus/SOURCES.md` has the per-source counts.

The corpus is built by a GitHub Action, not on your machine. Run it from the Actions tab or with:

```bash
gh workflow run build-corpus.yml
```

Then `git pull`. The scraper checks robots.txt, honors Crawl-delay, waits between requests, and reads pages that were taken down from their Internet Archive copies.

The essays belong to their writers and publishers. This repository is private and the corpus is for personal study. Don't publish it.

## Privacy

Essays go to Claude through your own Claude Code login and nowhere else. Each model call runs with `--safe-mode` and no tools, so your hooks, plugins, MCP servers, and CLAUDE.md files never see the essay. If `ANTHROPIC_API_KEY` is set in your shell it is removed for these calls, so reviews always bill the subscription (set `GARYADMIT_ALLOW_API_KEY=1` to override). Reviews are saved to `~/.garyadmit/history`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `GARYADMIT_MODEL` | `opus` | model for reading, editing, and judging |
| `GARYADMIT_FAST_MODEL` | `sonnet` | model for topic profiling and retrieval |
| `GARYADMIT_CORPUS` | `corpus/essays.jsonl` | published essay corpus |
| `GARYADMIT_ANCHORS` | `corpus/anchors.jsonl` | hidden human-rated drafts |

A full review makes about 20 model calls: two readers, one editor, a topic profile, a rerank, and two calls for each of seven comparisons.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The tests use a fake model, so they make no calls.
