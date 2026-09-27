"""Corpus of real, published college essays plus a BM25 index over them.

The corpus is `corpus/essays.jsonl`, one essay per line, built by
`scripts/build_corpus.py` (run it yourself or via the GitHub Action). Every
record keeps its source URL so the report can link to the original page.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = Path(os.environ.get("GARYADMIT_CORPUS") or REPO_ROOT / "corpus" / "essays.jsonl")

# Assumed strength of each tier on GaryAdmit's 0-100 scale, used as the
# opponent rating in head-to-head scoring. `garyadmit bench` checks these
# against what the rubric actually gives a sample of each tier.
TIER_LEVEL = {
    "exemplar": 85.0,   # picked by an admissions office as a model essay
    "admitted": 78.0,   # published as the essay of an admitted student
    "example": 70.0,    # published as a good example, admission unknown
    "weak": 45.0,       # published as a weak or before-revision draft
    "before": 45.0,
    "after": 65.0,
}
# Only these tiers are offered to the user as "similar essays to learn from".
SIMILAR_TIERS = {"exemplar", "admitted", "example"}

GRADE_LEVEL = {
    "A+": 90, "A": 86, "A-": 82, "B+": 76, "B": 72, "B-": 68, "C+": 62, "C": 58, "C-": 54,
    "D+": 48, "D": 44, "D-": 40, "F": 32,
}

# Hidden anchors are human-rated drafts on a 4-9 scale. level = 10*rating - 5
# puts their top drafts (9) level with published exemplars (85) and their
# median (~6) at the median-applicant band (55). This is an assumption, and
# `garyadmit bench` reports how the rubric's own scores line up with it.
ANCHOR_OFFSET = 5.0
ANCHORS_PATH = Path(os.environ.get("GARYADMIT_ANCHORS") or REPO_ROOT / "corpus" / "anchors.jsonl")

STOP = set("""a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her
here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of
off on once only or other our ours ourselves out over own same she should so some such than that the their theirs
them themselves then there these they this those through to too under until up very was we were what when where
which while who whom why will with would you your yours yourself yourselves also one would could us got get like
really even still much many every thing things something""".split())


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z][a-z']+", text.lower())
    out = []
    for t in toks:
        t = t.strip("'")
        if len(t) < 3 or t in STOP:
            continue
        # Light suffix stripping so "grandmother's"/"grandmothers" meet.
        for suf in ("'s", "ies", "ing", "ed", "es", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                t = t[: -len(suf)] + ("y" if suf == "ies" else "")
                break
        out.append(t)
    return out


@dataclass
class Essay:
    id: str
    text: str
    url: str
    source: str
    tier: str
    title: str = ""
    school: str = ""
    year: str = ""
    essay_type: str = "personal"
    prompt: str = ""
    grade: str = ""
    words: int = 0
    commentary: str = ""

    @property
    def level(self) -> float:
        if self.grade in GRADE_LEVEL:
            return float(GRADE_LEVEL[self.grade])
        return TIER_LEVEL.get(self.tier, 75.0)

    def label(self) -> str:
        bits = [self.title or self.id]
        if self.school:
            bits.append(self.school)
        if self.year:
            bits.append(str(self.year))
        return " · ".join(bits)


class Corpus:
    def __init__(self, essays: list[Essay]):
        self.essays = essays
        self._docs = [Counter(tokenize(e.title + " " + e.text)) for e in essays]
        self._lens = [sum(d.values()) for d in self._docs]
        self._avg = (sum(self._lens) / len(self._lens)) if self._lens else 1.0
        df: Counter = Counter()
        for d in self._docs:
            df.update(d.keys())
        n = len(essays)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Corpus":
        path = Path(path) if path else DEFAULT_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"No essay corpus at {path}. Build it with `python scripts/build_corpus.py` "
                "or pull the latest repo (the GitHub Action commits it)."
            )
        essays = []
        fields = Essay.__dataclass_fields__
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                essays.append(Essay(**{k: v for k, v in rec.items() if k in fields}))
        return cls(essays)

    def __len__(self) -> int:
        return len(self.essays)

    def search(self, query: str, k: int = 25, boost_terms: list[str] | None = None,
               exclude_text: str | None = None, tiers: set[str] | None = SIMILAR_TIERS) -> list[tuple[Essay, float]]:
        """BM25 over essay text; boost_terms (from the LLM profile) count double."""
        q = Counter(tokenize(query))
        for t in tokenize(" ".join(boost_terms or [])):
            q[t] += 2
        k1, b = 1.4, 0.75
        scores = []
        for i, d in enumerate(self._docs):
            if tiers and self.essays[i].tier not in tiers:
                continue
            s = 0.0
            for t, qf in q.items():
                f = d.get(t)
                if not f:
                    continue
                idf = self._idf.get(t, 0.0)
                s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * self._lens[i] / self._avg)) * min(qf, 3)
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        out = []
        norm_ex = _norm(exclude_text) if exclude_text else None
        for s, i in scores:
            e = self.essays[i]
            # Never compare an essay against itself (e.g. benchmarking a corpus essay).
            if norm_ex and _norm(e.text)[:300] == norm_ex[:300]:
                continue
            out.append((e, s))
            if len(out) >= k:
                break
        return out


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


@dataclass
class Anchor:
    id: str
    text: str
    rating: float
    split: str
    group: str = ""

    @property
    def level(self) -> float:
        return 10 * self.rating - ANCHOR_OFFSET


def load_anchors(path: Path | str | None = None, split: str | None = "anchor") -> list[Anchor]:
    path = Path(path) if path else ANCHORS_PATH
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                if split is None or r.get("split") == split:
                    out.append(Anchor(r["id"], r["text"], float(r["rating"]), r.get("split", ""), r.get("group", "")))
    return out


def pick_anchors(anchors: list[Anchor], targets: list[float], seed_text: str, exclude_text: str = "") -> list[Anchor]:
    """One anchor per target rating, nearest rating first, rotating among ties
    by a hash of the essay so repeated reviews do not always see the same file."""
    import hashlib

    h = int(hashlib.sha1(seed_text.encode()).hexdigest(), 16)
    ex = _norm(exclude_text)[:300] if exclude_text else None
    chosen, used_groups = [], set()
    for i, t in enumerate(targets):
        pool = [a for a in anchors if a.group not in used_groups and (not ex or _norm(a.text)[:300] != ex)]
        if not pool:
            break
        best = min(abs(a.rating - t) for a in pool)
        near = sorted((a for a in pool if abs(a.rating - t) <= best + 0.25), key=lambda a: a.id)
        a = near[(h >> (8 * i)) % len(near)]
        chosen.append(a)
        used_groups.add(a.group or a.id)
    return chosen
