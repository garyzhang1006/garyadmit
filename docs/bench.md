# Scoring bench

One run of `garyadmit bench` on 2026-09-27 with Opus, in the default rubric-only mode (no comparisons), over 31 essays in 62 model calls. The raw results are in `~/.garyadmit/bench/20260927-010659.json` on the machine that ran it.

| Check | Result |
|---|---|
| Admissions-office exemplars vs essays published as weak | 51 vs 36 (gap 16) |
| Rank agreement with AdmitReport letter grades | Spearman 0.60 |
| Glaze rate (weak or below-median essays scored 70+) | 0% of 15 |
| Deliberately generic AI-sounding essay | 22 |
| Score spread (SD) | 8.1 |
| Rank agreement with ElevatEd consultant ratings | Spearman -0.30 |
| Offset from ElevatEd ratings | -12.6 points on average (MAE 14.4) |
| ElevatEd revision pairs ordered like the consultants | 33% |

The checks against sources with clear standing pass. Weak essays never scored 70 or higher, the generic essay scored 22, and the order of AdmitReport grades came through at 0.60.

The ElevatEd numbers are poor, which matches what the README already says about those ratings: the judge could not reproduce them in earlier testing either, so they stay a secondary check. The run also shows the rubric-only score is harsh. Admissions-office exemplars averaged 51, while the calibration ladder places those picks at about 86, and the spread is narrow at 8 points. The full pipeline pulls scores toward the comparison results, but this run did not use it (`--full` costs several times the calls), so how much that corrects the harshness is unmeasured.

Eight rated drafts and a few pairs are a small sample. Rerun with `--seed` before trusting a change to the scoring.
