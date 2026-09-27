"""Score aggregation. All the math is here and deterministic, so the number a
student sees can be traced back to rubric scores and head-to-head outcomes.

Final score = the posterior mode of a one-dimensional rating model:
  prior      ~ Normal(rubric score, PRIOR_SD)
  each match ~ Bernoulli(logistic((R - opponent_level) / SCALE))
The rubric alone can say "88", but if the essay then loses blind
head-to-heads against real published essays rated ~85, the posterior drops
it. An essay cannot claim to beat real exemplars on paper without beating
them in an actual comparison.
"""

from __future__ import annotations

import math
import re
import unicodedata

from .rubric import CATEGORIES, WEIGHTS

PRIOR_SD = 8.0
SCALE = 5.0
DISAGREE_AT = 3


def rubric_overall(cat_scores: dict[str, float]) -> float:
    return round(10 * sum(WEIGHTS[c] * cat_scores[c] for c in CATEGORIES), 1)


def merge_reviewers(reviews: list[dict]) -> tuple[dict[str, float], list[str]]:
    """Mean of reviewer scores per category, plus categories needing a tiebreak."""
    merged, disputed = {}, []
    for c in CATEGORIES:
        vals = [r["scores"][c]["score"] for r in reviews]
        merged[c] = sum(vals) / len(vals)
        if max(vals) - min(vals) >= DISAGREE_AT:
            disputed.append(c)
    return merged, disputed


def head_to_head_outcome(first_order_user_won: bool | None, second_order_user_won: bool | None) -> float | None:
    """1 = user won both orders, 0 = lost both, 0.5 = split (position bias)."""
    got = [x for x in (first_order_user_won, second_order_user_won) if x is not None]
    if not got:
        return None
    return sum(1.0 if x else 0.0 for x in got) / len(got)


def _loglik(r: float, prior_mu: float, matches: list[tuple[float, float]]) -> float:
    ll = -((r - prior_mu) ** 2) / (2 * PRIOR_SD ** 2)
    for level, outcome in matches:
        p = 1.0 / (1.0 + math.exp(-(r - level) / SCALE))
        p = min(max(p, 1e-9), 1 - 1e-9)
        ll += outcome * math.log(p) + (1 - outcome) * math.log(1 - p)
    return ll


def final_score(rubric: float, matches: list[tuple[float, float]]) -> float:
    """MAP rating on a 0.1 grid over [0, 100]. matches = [(opponent_level, outcome)]."""
    if not matches:
        return round(rubric, 1)
    best_r, best_ll = rubric, -math.inf
    for i in range(0, 1001):
        r = i / 10
        ll = _loglik(r, rubric, matches)
        if ll > best_ll:
            best_r, best_ll = r, ll
    return round(best_r, 1)


# ---- quote verification -------------------------------------------------

def _norm_char(ch: str) -> str:
    return {"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", " ": " "}.get(ch, ch)


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase, unify quotes/dashes, collapse whitespace; keep an index map back to the original."""
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(unicodedata.normalize("NFC", text)):
        ch = _norm_char(ch).lower()
        if ch.isspace():
            if prev_space:
                continue
            ch, prev_space = " ", True
        else:
            prev_space = False
        out.append(ch)
        idx.append(i)
    return "".join(out), idx


def locate(essay: str, quote: str) -> tuple[int, int] | None:
    """Find a model-provided quote in the essay, tolerating quote/dash/space differences.
    Returns (start, end) offsets in the original essay, or None if it is not really there."""
    q = quote.strip().strip('"').strip("“”").strip()
    if len(q) < 3:
        return None
    i = essay.find(q)
    if i >= 0:
        return i, i + len(q)
    ne, emap = _normalize_with_map(essay)
    nq, _ = _normalize_with_map(q)
    nq = nq.strip(" .,;:")
    if not nq:
        return None
    j = ne.find(nq)
    if j < 0:
        # Models sometimes drop an ellipsis or trailing words; accept a long unique prefix.
        words = nq.split()
        if len(words) >= 8:
            head = " ".join(words[: max(6, len(words) * 2 // 3)])
            j = ne.find(head)
            if j >= 0 and ne.find(head, j + 1) < 0:
                nq = head
            else:
                return None
        else:
            return None
    start = emap[j]
    end = emap[min(j + len(nq) - 1, len(emap) - 1)] + 1
    return start, end


def quote_ok(essay: str, quote: str) -> bool:
    return locate(essay, quote) is not None


def strip_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
