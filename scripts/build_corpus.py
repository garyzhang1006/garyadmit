"""Build GaryAdmit's corpus of real, published college essays.

Writes:
  corpus/essays.jsonl   published essays (shown to the user, linked to their source)
  corpus/anchors.jsonl  human-rated drafts used only as hidden calibration anchors
  corpus/SOURCES.md     per-source counts and provenance

Runs in GitHub Actions (.github/workflows/build-corpus.yml). Locally:
  pip install requests beautifulsoup4 lxml
  python scripts/build_corpus.py                      # everything
  python scripts/build_corpus.py --only jhu --limit 2 --out /tmp/c   # smoke test one source
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sources._common import Fetcher, make_record  # noqa: E402

# Order matters for dedupe: the first source to publish an essay keeps it, so
# admissions offices come before re-hosts and counselor sites.
SOURCES = [
    "jhu", "connecticut", "hamilton", "tufts", "emory", "st_johns", "etwc",
    "harvard_crimson", "shemmassian", "collegevine", "the_tech", "prepscholar",
    "admitreport", "studynotes",
]
ANCHOR_SOURCES = ["elevated"]

ROOT = Path(__file__).resolve().parent.parent


def norm_key(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()[:220]


def run_source(name: str, fetch: Fetcher, limit: int | None) -> tuple[list[dict], str]:
    try:
        mod = importlib.import_module(f"sources.{name}")
    except ModuleNotFoundError:
        return [], "module missing"
    recs, errs = [], 0
    try:
        for r in mod.scrape(fetch, limit=limit):
            try:
                recs.append(r if "id" in r else make_record(**r))
            except (AssertionError, TypeError) as e:
                errs += 1
                print(f"  [{name}] bad record: {e}", file=sys.stderr)
    except Exception:
        traceback.print_exc()
        return recs, f"crashed after {len(recs)} records"
    return recs, f"ok ({errs} bad records)" if errs else "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated source names")
    ap.add_argument("--limit", type=int, default=None, help="max essay pages per source (smoke test)")
    ap.add_argument("--out", default=str(ROOT / "corpus"))
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()

    only = [s for s in a.only.split(",") if s]
    fetch = Fetcher(delay=a.delay)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    status, essays, seen = {}, [], set()
    for name in SOURCES:
        if only and name not in only:
            continue
        print(f"== {name}", file=sys.stderr, flush=True)
        recs, st = run_source(name, fetch, a.limit)
        kept = 0
        for r in recs:
            lo, hi = (40, 1400) if r["essay_type"] == "supplement" else (150, 1400)
            if not (lo <= r["words"] <= hi):
                continue
            k = norm_key(r["text"])
            if k in seen:
                continue
            seen.add(k)
            essays.append(r)
            kept += 1
        status[name] = (st, len(recs), kept)
        print(f"   {st}: {len(recs)} scraped, {kept} kept", file=sys.stderr, flush=True)

    anchors = []
    for name in ANCHOR_SOURCES:
        if only and name not in only:
            continue
        print(f"== {name}", file=sys.stderr, flush=True)
        try:
            mod = importlib.import_module(f"sources.{name}")
            anchors = list(mod.scrape(fetch, limit=a.limit))
            status[name] = ("ok", len(anchors), len(anchors))
        except Exception:
            traceback.print_exc()
            status[name] = ("crashed", 0, 0)
        print(f"   {status[name][0]}: {len(anchors)} anchors", file=sys.stderr, flush=True)

    if essays:
        with open(out / "essays.jsonl", "w", encoding="utf-8") as fh:
            for r in essays:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    if anchors:
        with open(out / "anchors.jsonl", "w", encoding="utf-8") as fh:
            for r in anchors:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_tier = Counter(r["tier"] for r in essays)
    by_type = Counter(r["essay_type"] for r in essays)
    schools = defaultdict(int)
    for r in essays:
        if r["school"]:
            schools[r["school"]] += 1
    lines = ["# Corpus sources", "", f"{len(essays)} published essays, {len(anchors)} hidden calibration anchors.", "",
             "| source | status | scraped | kept |", "|---|---|---|---|"]
    lines += [f"| {k} | {v[0]} | {v[1]} | {v[2]} |" for k, v in status.items()]
    lines += ["", "By tier: " + ", ".join(f"{k} {v}" for k, v in by_tier.most_common()),
              "", "By type: " + ", ".join(f"{k} {v}" for k, v in by_type.most_common()),
              "", "Top schools: " + ", ".join(f"{k} {v}" for k, v in sorted(schools.items(), key=lambda x: -x[1])[:25])]
    (out / "SOURCES.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines), file=sys.stderr)
    return 0 if essays or anchors else 1


if __name__ == "__main__":
    raise SystemExit(main())
