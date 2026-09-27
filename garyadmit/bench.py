"""Honesty benchmark: does the score track human judgment, and does it glaze?

Scores a fixed, hash-chosen sample and compares against what humans said.
Primary (known standing, the scale GaryAdmit is built on):
  - admissions-office exemplars (85), essays published as weak (45),
    AdmitReport letter grades (their grade level)
  - one generic, AI-sounding essay that should score low
Secondary (reported, not tuned for):
  - ElevatEd drafts with a consultant's 4-9 rating, and revision pairs. In
    testing the blind judge agreed with these ratings at chance level, and the
    thesis that released them found them hard to model, so they are a weak yardstick.

Default mode is rubric-only (2-3 model calls per essay) so a run stays around
75 calls; --full runs the whole pipeline, comparisons included.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from . import llm
from .corpus import GRADE_LEVEL, TIER_LEVEL, Anchor, Corpus, load_anchors
from .review import get_corpus, review

BENCH_DIR = Path.home() / ".garyadmit" / "bench"
OFFICE_SOURCES = {"jhu", "emory", "tufts", "connecticut", "hamilton"}
GLAZE_AT = 70.0  # a score this high on a weak essay is flattery

GENERIC_AI_ESSAY = """Ever since I was young, I have always been passionate about making a difference in the world. Whether it was helping my classmates with their homework or volunteering at my local food bank, I have always found joy in serving others. This passion has shaped who I am today and continues to drive me toward my goals.

One of the most meaningful experiences of my life was when I volunteered at a summer camp for underprivileged children. At first, I was nervous and unsure of what to expect. However, as the weeks went by, I began to form deep connections with the campers. I realized that even small acts of kindness can have a profound impact on someone's life. Seeing the smiles on their faces made every challenge worthwhile.

This experience taught me the importance of empathy, resilience, and hard work. I learned that stepping out of my comfort zone allows me to grow as a person. I also discovered that leadership is not about being in charge, but about lifting others up and helping them reach their full potential.

In addition to my volunteer work, I have pursued my passion for science through various extracurricular activities. As president of my school's science club, I organized events that encouraged students to explore STEM fields. I also participated in research at a local university, where I gained valuable hands-on experience and developed my critical thinking skills.

Looking back, I am grateful for the challenges I have faced because they have made me stronger. Every obstacle has been an opportunity to learn and grow. I have learned that success is not defined by the destination, but by the journey and the lessons we learn along the way.

As I look toward the future, I am excited to continue my journey at a university that values diversity, innovation, and community. I hope to major in biology and eventually become a doctor so that I can help people in need. I believe that my passion, dedication, and unique perspective will allow me to make a meaningful contribution to your campus community.

Ultimately, my experiences have taught me that the most important thing in life is to make a positive impact on others. I am ready to take on new challenges and make a difference in the world, one step at a time."""


def _h(s: str) -> int:
    return int(hashlib.sha1(s.encode()).hexdigest(), 16)


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def _item(kind: str, id_: str, text: str, **kw) -> dict:
    return {"kind": kind, "id": id_, "text": text, "essay_type": kw.pop("essay_type", "personal"),
            "prompt": kw.pop("prompt", ""), **kw}


def sample(corpus: Corpus | None, bench: list[Anchor], n_rated: int = 12, n_pairs: int = 3, n_tier: int = 4,
           seed: str = "") -> list[dict]:
    """Deterministic for a given seed. Tune on one seed and confirm on another, so the
    reported numbers are not fitted to the essays they were measured on."""
    _hs = lambda s: _h(seed + s)
    items: list[dict] = []
    groups: dict[str, list[Anchor]] = defaultdict(list)
    for a in bench:
        groups[a.group or a.id].append(a)
    pair_groups = sorted((g for g, v in groups.items() if max(x.rating for x in v) - min(x.rating for x in v) >= 0.5),
                         key=lambda g: _hs("pair" + g))[:n_pairs]
    for g in pair_groups:
        v = sorted(groups[g], key=lambda a: a.rating)
        for a in (v[0], v[-1]):
            items.append(_item("pair", a.id, a.text, rating=a.rating, level=a.level, group=g))
    rest = sorted((a for a in bench if (a.group or a.id) not in pair_groups), key=lambda a: (a.rating, _hs(a.id)))
    if rest and n_rated:
        # Evenly spaced through the rating-sorted list so the whole 4-9 range is covered.
        step = max(1, len(rest) // n_rated)
        offset = _hs("offset") % step
        picked, seen_groups = [], set()
        for a in rest[offset::step]:
            if (a.group or a.id) in seen_groups:
                continue
            seen_groups.add(a.group or a.id)
            picked.append(a)
        for a in picked[:n_rated]:
            items.append(_item("rated", a.id, a.text, rating=a.rating, level=a.level, group=a.group))
    if corpus is not None:
        def pick(pred, n, salt):
            pool = sorted((e for e in corpus.essays if pred(e)), key=lambda e: _hs(salt + e.id))
            return pool[:n]
        for e in pick(lambda e: e.source in OFFICE_SOURCES and e.essay_type == "personal", n_tier, "ex"):
            items.append(_item("exemplar", e.id, e.text, source=e.source, url=e.url, level=TIER_LEVEL["exemplar"]))
        for e in pick(lambda e: e.tier == "weak", n_tier, "weak"):
            items.append(_item("weak", e.id, e.text, source=e.source, url=e.url, essay_type=e.essay_type, prompt=e.prompt,
                               level=float(GRADE_LEVEL.get(e.grade, TIER_LEVEL["weak"]))))
        graded = sorted((e for e in corpus.essays if e.grade in GRADE_LEVEL), key=lambda e: (GRADE_LEVEL[e.grade], _hs(e.id)))
        if graded and n_tier:
            step = max(1, len(graded) // n_tier)
            for e in graded[_hs("g") % step::step][:n_tier]:
                items.append(_item("graded", e.id, e.text, grade=e.grade, level=float(GRADE_LEVEL[e.grade]),
                                   source=e.source, url=e.url, essay_type=e.essay_type, prompt=e.prompt))
    items.append(_item("ai", "generic-ai", GENERIC_AI_ESSAY))
    return items


def metrics(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("score") is not None]
    human = [r for r in ok if r["kind"] in ("rated", "pair")]
    m: dict = {"n_scored": len(ok), "n_failed": len(results) - len(ok)}
    known = [r for r in ok if r["kind"] in ("exemplar", "weak", "graded")]
    if known:
        m["known_spearman"] = spearman([r["score"] for r in known], [r["level"] for r in known])
        m["known_offset"] = statistics.fmean(r["score"] - r["level"] for r in known)
        m["known_mae"] = statistics.fmean(abs(r["score"] - r["level"]) for r in known)
        m["n_known"] = len(known)
    if human:
        m["rated_spearman"] = spearman([r["score"] for r in human], [r["rating"] for r in human])
        m["rated_offset"] = statistics.fmean(r["score"] - r["level"] for r in human)
        m["rated_mae"] = statistics.fmean(abs(r["score"] - r["level"]) for r in human)
    pairs = defaultdict(list)
    for r in ok:
        if r["kind"] == "pair":
            pairs[r["group"]].append(r)
    ordered = [sorted(v, key=lambda r: r["rating"]) for v in pairs.values() if len(v) == 2]
    if ordered:
        m["pairs_correct"] = sum(1 for lo, hi in ordered if hi["score"] > lo["score"]) / len(ordered)
    ex = [r["score"] for r in ok if r["kind"] == "exemplar"]
    weak = [r["score"] for r in ok if r["kind"] == "weak"]
    if ex:
        m["exemplar_mean"] = statistics.fmean(ex)
    if weak:
        m["weak_mean"] = statistics.fmean(weak)
    if ex and weak:
        m["tier_gap"] = m["exemplar_mean"] - m["weak_mean"]
    graded = [r for r in ok if r["kind"] == "graded"]
    if graded:
        m["graded_spearman"] = spearman([r["score"] for r in graded], [r["level"] for r in graded])
    low = [r for r in ok if r["kind"] == "weak" or (r["kind"] in ("rated", "pair", "graded") and r["level"] <= 55)]
    if low:
        m["glaze_rate"] = sum(1 for r in low if r["score"] >= GLAZE_AT) / len(low)
        m["n_low"] = len(low)
    ai = [r["score"] for r in ok if r["kind"] == "ai"]
    if ai:
        m["generic_ai_score"] = ai[0]
    if len(ok) > 1:
        m["score_sd"] = statistics.pstdev(r["score"] for r in ok)
    return m


def verdicts(m: dict) -> list[str]:
    out = []
    if "known_offset" in m:
        off = m["known_offset"]
        tone = "inflated" if off > 5 else "harsh" if off < -5 else "on target"
        out.append(f"Level vs {m['n_known']} essays of known standing: {off:+.1f} points on average ({tone}; MAE {m['known_mae']:.1f}).")
    if m.get("known_spearman") is not None:
        out.append(f"Rank agreement with known standing: Spearman {m['known_spearman']:.2f} (0.5+ is useful, 0.7+ is strong).")
    if "tier_gap" in m:
        out.append(f"Admissions exemplars {m['exemplar_mean']:.0f} vs published weak essays {m['weak_mean']:.0f} (gap {m['tier_gap']:.0f}).")
    if m.get("graded_spearman") is not None:
        out.append(f"Rank agreement with AdmitReport letter grades: Spearman {m['graded_spearman']:.2f}.")
    if "glaze_rate" in m:
        out.append(f"Glaze rate: {m['glaze_rate']:.0%} of {m['n_low']} weak or below-median essays scored {GLAZE_AT:.0f}+.")
    if "generic_ai_score" in m:
        out.append(f"Generic AI-sounding essay: {m['generic_ai_score']:.0f} ({'pass' if m['generic_ai_score'] < 50 else 'FAIL: should be under 50'}).")
    if "score_sd" in m:
        out.append(f"Score spread (SD): {m['score_sd']:.1f}.")
    if "rated_offset" in m:
        out.append(f"Secondary, ElevatEd consultant ratings: offset {m['rated_offset']:+.1f}, "
                   + (f"Spearman {m['rated_spearman']:.2f}" if m.get("rated_spearman") is not None else "Spearman n/a")
                   + (f", revision pairs {m['pairs_correct']:.0%}" if "pairs_correct" in m else "") + ".")
    return out


def run(*, full: bool = False, n_rated: int = 8, n_pairs: int = 2, n_tier: int = 5, workers: int = 3, seed: str = "",
        model: str | None = None, corpus_path: str | None = None, anchors_path: str | None = None,
        progress: Callable[[str], None] | None = None) -> dict:
    say = progress or (lambda s: None)
    try:
        corpus = get_corpus(corpus_path)
    except FileNotFoundError:
        corpus = None
    bench = load_anchors(anchors_path, split="bench")
    items = sample(corpus, bench, n_rated, n_pairs, n_tier, seed)
    say(f"Scoring {len(items)} essays ({'full pipeline' if full else 'rubric only'})")

    def one(it: dict) -> dict:
        limit = 650 if it["essay_type"] == "personal" else None
        try:
            r = review(it["text"], prompt=it.get("prompt", ""), essay_type=it["essay_type"], word_limit=limit,
                       model=model, n_compare=3 if full else 0, n_anchor=4 if full else 0,
                       corpus_path=corpus_path, save=False, line_edits=False)
            out = {**{k: v for k, v in it.items() if k != "text"}, "score": r["score"], "rubric_score": r["rubric_score"],
                   "words": len(it["text"].split())}
        except (llm.LLMError, ValueError) as err:
            out = {**{k: v for k, v in it.items() if k != "text"}, "score": None, "error": str(err)}
        say(f"{it['kind']:<8} {it['id'][:28]:<28} -> {out['score'] if out['score'] is None else round(out['score'], 1)}")
        return out

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, items))
    m = metrics(results)
    report = {"created": dt.datetime.now().isoformat(timespec="seconds"), "full": full, "seed": seed, "model": model or llm.DEFAULT_MODEL,
              "metrics": m, "verdicts": verdicts(m), "results": results, "usage": dict(llm.usage)}
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / (dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")).write_text(json.dumps(report, indent=1))
    return report
