# Revision bench

One run of `garyadmit bench --revise 8` on 2026-09-27 with Opus: eight personal statements from the corpus, six graded B+ or below on AdmitReport and two admissions-office exemplars (Tufts and Emory). It took 104 model calls, $6.10 at API rates. The rows, with every draft and polish, are in `~/.garyadmit/bench/revise-20260927-132826.json` on the machine that ran it.

The run used the code from before the final review. Back then "verified" meant beating the original in both orders and passing the fact check and gates. It did not yet include the polish-only comparison that verification now requires, and this run is the reason that comparison was added.

| Six low-graded essays | Result |
|---|---|
| Revision beat the original in both orders | 6 of 6 |
| ...with its first draft | 6 of 6 |
| Polish-only rewrite beat the original in both orders | 5 of 6 |
| Revision beat an independent polish-only rewrite in both orders | 6 of 6 (lost 0) |
| Judge said the revision sounds more like one specific teenager | 6 of 6 |
| Final drafts with an invented fact | 0 of 6 |
| Share of the text new or moved | revisions 23%, polish 15% |
| Drafts that needed the second round | 6 of 6 |

On the two exemplars the revision also beat the original in both orders, changing 21% of the text. The fact checker rated voice drift low on all eight.

## Verdict: FAIL

The rule, fixed before the run, asks the revision's first draft to beat the original at least 25 points more often than the polish does. It beat it 17 points more often, 100% against 83%, so the run fails. It could not have passed: once polish alone wins five of six, the most any revision can add is 17 points.

The failure is still informative. The judge prefers almost any careful rewrite of these essays over the original, even one told to change nothing of substance. That is the self-preference the polish control exists to catch, and it means "a blind judge preferred it over your original" is weak evidence on its own.

The head-to-head separates the two. Against a polish of the same essay, the revision won all six in both orders, and the judge's reasons were specific: the revision cut stock lines the polish kept ("an incredible journey, and I am grateful for the opportunity"), ended on a scene where the polish stated a moral, and put a jumbled story in time order. After this run, a draft only counts as verified if it also beats a fresh polish-only rewrite in both orders.

## What the revisions changed

In the bench the reviser may not ask questions, so it can only cut, reorder, and expand what the essay already implies. That is what it did. Most of the gain came from cutting generic lines and replacing a stated lesson with a closing image. One essay (admitreport-9feceec616) was restructured, with 45% of it new or moved. Another (admitreport-4d15a6a5a7) changed only 11%, less than its polish did.

These are real edits, but they are edits. In the product, bracketed questions are how new material from the student's life gets in, and the bench does not measure that.

All six drafts took two rounds. This run did not save why round one failed. The bench now saves the first round's failures and invented-fact count, and the first live test failed round one for two invented realizations.

The exemplar result is ambiguous. The revisions beat both admissions-office picks by cutting phrases like "vibrant collection of individuals". Either published exemplars carry fixable filler, or the judge rewards Claude's edits of anything. This run cannot tell which.

## One run of the current code

After the fixes, `garyadmit revise` ran once on admitreport-87a34abb4f (603 words) with bracketed questions allowed, the way students use it. Round one failed on two counts. The fact check caught two invented claims, one of them that the writer "still pictures" the opening scene. The new bracket check caught a question that assumed the writer had come to understand her mother, when the original ends with her still "looking for answers." Round two passed everything. It beat the original in both orders and a fresh polish-only rewrite in both orders, with three bracketed questions and 55% of the original's words kept. That took 13 calls, $0.73 at API rates, and two and a half minutes.

Its six moves were a restructure, a scene, a new ending, two cuts, and a reflection prompt. The judge's reason against the polish names the gap the brackets fill: the polish "fills that space with clichés and generic resolve". It also shows the limit above, since the judge credited the brackets as if they were already answered.

## Limits

- One model family writes and judges. The polish control measures part of that bias, not all of it.
- Six essays is a small sample, and one essay moves a rate by about 17 points.
- Rows from this run do not record whether each first draft invented a fact. The recomputed verdict treats them as clean. Every final draft passed the fact check, but some first drafts may not have.
- The bench runs without bracketed questions, so the configuration students get is unmeasured. With brackets present, the judge assumes each one is filled in with a plain true detail.
- A confirmation run on the current code with a fresh `--seed` has not been done. It costs 12 to 18 calls per essay.
