"""Command line entry point: `garyadmit review|serve|similar|corpus|history`."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import llm


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"garyadmit: no such file: {path}")
    return p.read_text(encoding="utf-8")


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--prompt", default="", help="the essay prompt you are answering")
    p.add_argument("--type", dest="essay_type", choices=["personal", "supplement"], default="personal")
    p.add_argument("--limit", type=int, default=None, help="word limit (default 650 for personal statements)")
    p.add_argument("--school", default="", help="target school, for supplements")
    p.add_argument("--corpus", default=None, help="path to an essays.jsonl corpus")


def cmd_review(a) -> int:
    from .report import to_text
    from .review import review

    text = _read(a.file)
    limit = a.limit if a.limit is not None else (650 if a.essay_type == "personal" else None)
    model = "sonnet" if a.fast else a.model
    try:
        r = review(
            text, prompt=a.prompt, essay_type=a.essay_type, word_limit=limit, school=a.school,
            model=model, fast_model="sonnet", n_compare=0 if a.no_compare else a.compare,
            n_anchor=0 if a.no_compare else min(a.anchors, 4),
            corpus_path=a.corpus, progress=lambda s: print(f"  · {s}", file=sys.stderr, flush=True),
        )
    except (llm.LLMError, ValueError) as err:
        print(f"garyadmit: {err}", file=sys.stderr)
        return 1
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1))
    print(to_text(r))
    return 0


def cmd_similar(a) -> int:
    from .review import find_similar, get_corpus

    text = _read(a.file)
    corpus = get_corpus(a.corpus)
    meta = {"essay_type": a.essay_type, "prompt": a.prompt}
    profile, sim = find_similar(text, meta, corpus, a.k, "sonnet")
    print(f"Profile: {profile['summary']}\nKeywords: {', '.join(profile['keywords'])}\n")
    for s in sim:
        e = s["essay"]
        print(f"- {e.label()} [{e.tier}]\n  {e.url}\n  {s['why_similar']}")
    return 0


def cmd_corpus(a) -> int:
    from .corpus import Corpus

    c = Corpus.load(a.corpus)
    print(f"{len(c)} essays")
    for label, key in (("By source", "source"), ("By tier", "tier"), ("By type", "essay_type")):
        print(f"\n{label}:")
        for k, n in Counter(getattr(e, key) for e in c.essays).most_common():
            print(f"  {n:>5}  {k}")
    return 0


def cmd_history(a) -> int:
    from .review import HISTORY_DIR

    files = sorted(HISTORY_DIR.glob("*.json"))
    if not files:
        print("No saved reviews yet.")
        return 0
    for f in files[-a.n:]:
        r = json.loads(f.read_text())
        first = r["essay"].strip().split("\n")[0][:70]
        print(f"{f.stem}  {r['score']:>5.1f}  {r['band']:<16} {first}")
    return 0


def cmd_bench(a) -> int:
    from .bench import run

    try:
        rep = run(full=a.full, n_rated=a.rated, n_pairs=a.pairs, n_tier=a.tier, workers=a.workers, model=a.model,
                  corpus_path=a.corpus, progress=lambda s: print(f"  · {s}", file=sys.stderr, flush=True))
    except llm.LLMError as err:
        print(f"garyadmit: {err}", file=sys.stderr)
        return 1
    print("\n".join(rep["verdicts"]))
    print(f"\n{rep['usage'].get('calls', 0)} model calls. Full results in ~/.garyadmit/bench/.")
    return 0


def cmd_serve(a) -> int:
    from .server import serve

    serve(port=a.port, open_browser=not a.no_open, corpus_path=a.corpus)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="garyadmit", description="Honest college essay reviews on your Claude subscription.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("review", help="review an essay file ('-' for stdin)")
    p.add_argument("file")
    _common(p)
    p.add_argument("--model", default=None, help="Claude model alias for judging (default: opus)")
    p.add_argument("--fast", action="store_true", help="use sonnet for everything (faster, lighter on usage)")
    p.add_argument("--compare", type=int, default=3, help="head-to-heads against similar published essays (default 3)")
    p.add_argument("--anchors", type=int, default=4, help="blind comparisons against hidden human-rated drafts (default 4, max 4)")
    p.add_argument("--no-compare", action="store_true", help="skip all comparisons (rubric-only score)")
    p.add_argument("--json", default=None, help="also write the full result to this JSON file")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("similar", help="list the most similar published essays")
    p.add_argument("file")
    _common(p)
    p.add_argument("-k", type=int, default=8)
    p.set_defaults(fn=cmd_similar)

    p = sub.add_parser("serve", help="open the local web app")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--corpus", default=None)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("corpus", help="show what is in the essay corpus")
    p.add_argument("--corpus", default=None)
    p.set_defaults(fn=cmd_corpus)

    p = sub.add_parser("bench", help="check the scores against human ratings (about 75 model calls)")
    p.add_argument("--full", action="store_true", help="run the full pipeline with comparisons (several times the calls)")
    p.add_argument("--rated", type=int, default=12, help="held-out expert-rated drafts (default 12)")
    p.add_argument("--pairs", type=int, default=3, help="revision pairs with different ratings (default 3)")
    p.add_argument("--tier", type=int, default=4, help="essays each from exemplar, weak, and graded sets (default 4)")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--model", default=None)
    p.add_argument("--corpus", default=None)
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("history", help="list past reviews")
    p.add_argument("-n", type=int, default=20)
    p.set_defaults(fn=cmd_history)

    a = ap.parse_args(argv)
    return a.fn(a)
