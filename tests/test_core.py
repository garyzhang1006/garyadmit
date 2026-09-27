import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from garyadmit import llm, rubric, scoring
from garyadmit.corpus import Anchor, Corpus, Essay, pick_anchors
from garyadmit.lint import lint

ESSAY = """Ever since I was little, I have had a passion for helping others. My grandmother taught me the value of hard work.

Every Sunday she rolled dumplings at the kitchen table while the radio played Cantonese opera too loud for anyone but her. I was in charge of the pleats, and I was bad at it. My dumplings leaked, split, and once exploded in the pot.

She never corrected me. She just ate the broken ones herself and served the good ones to guests.

Last spring she moved into a care home in Flushing. The first time I visited, I brought frozen dumplings from the supermarket. She looked at the bag, laughed, and asked who had taught me to cheat.

Through this experience I learned that hard work pays off and that I should always step out of my comfort zone. It truly shaped who I am today and I felt very proud."""


def test_lint_flags_cliches_with_valid_spans():
    rep = lint(ESSAY, 650)
    rules = {h["rule"]: h for h in rep["hits"]}
    assert "cliche" in rules
    for s, e in rules["cliche"]["spans"]:
        assert 0 <= s < e <= len(ESSAY)
    found = " ".join(ESSAY[s:e].lower() for s, e in rules["cliche"]["spans"])
    assert "comfort zone" in found and "ever since i was little" in found
    assert "moral_ending" in rules


def test_lint_over_limit_is_major():
    rep = lint("word " * 700, 650)
    hit = next(h for h in rep["hits"] if h["rule"] == "over_limit")
    assert hit["severity"] == "major" and "50 over" in hit["message"]


def test_final_score_pulls_inflated_rubric_down_when_it_loses():
    inflated = scoring.final_score(88.0, [(85.0, 0.0)] * 4)
    assert inflated < 82
    # Losing to much stronger essays is expected and barely moves a low score.
    assert abs(scoring.final_score(55.0, [(85.0, 0.0)] * 4) - 55.0) < 1.0
    # Beating strong essays consistently raises a modest rubric score.
    assert scoring.final_score(70.0, [(85.0, 1.0)] * 4) > 78
    assert scoring.final_score(66.6, []) == 66.6


def test_split_outcome_is_half():
    assert scoring.head_to_head_outcome(True, False) == 0.5
    assert scoring.head_to_head_outcome(True, True) == 1.0
    assert scoring.head_to_head_outcome(False, False) == 0.0


def test_locate_tolerates_smart_quotes_and_spacing():
    text = "She said, “Who taught   you to cheat?” and laughed."
    loc = scoring.locate(text, 'said, "Who taught you to cheat?"')
    assert loc and text[loc[0]:loc[1]].startswith("said")
    assert scoring.locate(text, "a sentence that is not in the essay at all") is None


def test_merge_reviewers_flags_disputes():
    mk = lambda v: {"scores": {c: {"score": v.get(c, 5)} for c in rubric.CATEGORIES}}
    merged, disputed = scoring.merge_reviewers([mk({"voice": 3}), mk({"voice": 7})])
    assert merged["voice"] == 5 and disputed == ["voice"]


def _corpus():
    return Corpus([
        Essay(id="a", text="My grandmother and I folded dumplings every Sunday in her kitchen. " * 5, url="https://x/a", source="t", tier="exemplar", title="Dumplings"),
        Essay(id="b", text="Robotics competition, soldering servos, and a failed autonomous run. " * 5, url="https://x/b", source="t", tier="admitted", title="Robots"),
        Essay(id="c", text="Cross country races taught me about pain and pacing on hills. " * 5, url="https://x/c", source="t", tier="exemplar", title="Running"),
    ])


def test_bm25_ranks_topical_essay_first_and_excludes_self():
    c = _corpus()
    res = c.search(ESSAY, k=3)
    assert res[0][0].id == "a"
    assert all(e.id != "a" for e, _ in c.search(c.essays[0].text, k=3, exclude_text=c.essays[0].text))


class FakeLLM:
    """Answers by schema so the whole pipeline runs without a model."""

    def __init__(self, essay, prefer_opponent=False):
        self.essay = essay
        self.prefer_opponent = prefer_opponent
        self.calls = []

    def __call__(self, system, prompt, schema, model, effort):
        props = schema["properties"]
        self.calls.append(list(props))
        if "scores" in props:
            voice = 3 if "trains new readers" in system else 7  # force a dispute
            return {
                "first_impression": "Dumplings and a grandmother; the ending goes generic.",
                "committee_line": "Warm details, canned lesson.",
                "weaknesses": [
                    {"issue": "Cliché opener", "quote": "Ever since I was little, I have had a passion for helping others.", "why_it_matters": "Readers skip it.", "severity": "major"},
                    {"issue": "Invented quote", "quote": "This sentence is not in the essay.", "why_it_matters": "x", "severity": "minor"},
                ],
                "strengths": [{"what": "Specific humor", "quote": "asked who had taught me to cheat"}],
                "scores": {c: {"score": voice if c == "voice" else 5, "justification": "j", "quote": "My dumplings leaked, split", "to_raise": "t"} for c in rubric.CATEGORIES},
                "ai_suspicion": {"level": "low", "evidence": "none"},
                "top_fixes": [{"fix": "Cut the first paragraph", "why": "It is generic."}],
            }
        if "edits" in props:
            return {"edits": [
                {"original": "Ever since I was little,", "kind": "cut", "problem": "cliché", "suggestion": "", "category": "hook", "severity": "major"},
                {"original": "not a real span", "kind": "rewrite", "problem": "x", "suggestion": "y", "category": "flow", "severity": "minor"},
            ], "paragraph_notes": [{"paragraph": 1, "note": "cut"}]}
        if "keywords" in props:
            return {"summary": "grandmother dumplings", "topic": "family cooking", "themes": ["family"], "structure": "narrative", "keywords": ["dumplings", "grandmother", "kitchen"]}
        if "matches" in props:
            return {"matches": [{"id": "a", "why_similar": "grandmother cooking"}, {"id": "zzz", "why_similar": "bad id"}]}
        if "winner" in props:
            winner = "1"  # default: pure position bias, which must come out as a split
            if self.prefer_opponent:
                user_first = prompt.index(self.essay[:40]) < prompt.index("<essay_2>")
                winner = "2" if user_first else "1"
            return {"winner": winner, "confidence": "low", "category_winners": {c: "tie" for c in rubric.CATEGORIES},
                    "decisive_difference": "d", "lesson_for_weaker": "l", "stronger_quote": "q"}
        # adjudication
        return {c: {"score": 4, "reason": "text supports the lower read"} for c in props}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    from garyadmit import review as rv
    f = FakeLLM(ESSAY)
    llm.set_backend(f)
    monkeypatch.setattr(rv, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(rv, "get_corpus", lambda path=None: _corpus())
    monkeypatch.setattr(rv, "load_anchors", lambda path=None: [
        Anchor(f"anc{i}", f"Anchor essay number {i} about a summer job at a bakery. " * 20, r, "anchor", f"g{i}")
        for i, r in enumerate([4.5, 5.0, 6.0, 6.0, 7.0, 7.25, 8.0, 8.5])
    ])
    yield f
    llm.set_backend(None)


def test_review_pipeline_end_to_end(fake):
    from garyadmit.review import review
    r = review(ESSAY, n_compare=2, n_similar=3)
    # Hallucinated evidence and edits are dropped.
    assert all(w["quote"] != "This sentence is not in the essay." for rd in r["readers"] for w in rd["weaknesses"])
    assert r["readers"][0]["_unverified_quotes_dropped"] == 1
    # Both readers flagged the same lines; the merged lists show each once.
    assert len(r["problems"]) == 1 and len(r["strengths"]) == 1
    assert [e["original"] for e in r["edits"]] == ["Ever since I was little,"]
    assert ESSAY[r["edits"][0]["start"]:r["edits"][0]["end"]] == "Ever since I was little,"
    # The 7-vs-3 voice split went to adjudication.
    assert r["categories"]["voice"]["adjudicated"] and r["categories"]["voice"]["score"] == 4
    # Position-biased judge yields splits, not wins.
    assert r["head_to_head"] and all(h["verdict"] == "split" for h in r["head_to_head"])
    assert r["head_to_head"][0]["opponent"]["id"] == "a"
    assert 0 <= r["score"] <= 100 and r["band"]


def test_calibration_losses_pull_score_down(fake):
    from garyadmit.review import review
    fake.prefer_opponent = True
    r = review(ESSAY, n_compare=2, n_similar=3)
    assert len(r["calibration"]) == 4 and all(c["verdict"] == "loss" for c in r["calibration"])
    got = sorted(c["rating"] for c in r["calibration"])
    assert all(abs(g - t) <= 0.25 for g, t in zip(got, [5.0, 6.0, 7.0, 8.25]))
    assert "text" not in r["calibration"][0]  # private drafts never reach the report
    assert r["score"] < r["rubric_score"]


def test_pick_anchors_spreads_and_skips_self():
    anchors = [Anchor(f"a{i}", f"text {i} " * 30, r, "anchor", f"g{i}") for i, r in enumerate([5.0, 5.0, 6.0, 7.0, 8.0])]
    got = pick_anchors(anchors, [5.0, 6.0, 7.0, 8.25], "seed")
    assert [a.rating for a in got] == [5.0, 6.0, 7.0, 8.0]
    got = pick_anchors(anchors, [6.0], "seed", exclude_text=anchors[2].text)
    assert got[0].id != "a2"


def test_server_runs_a_job(fake):
    from garyadmit.server import ThreadingHTTPServer, make_handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(None))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert b"GaryAdmit" in urllib.request.urlopen(base + "/").read()
        req = urllib.request.Request(base + "/api/review", data=json.dumps({"essay": ESSAY, "compare": 1}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        job = json.loads(urllib.request.urlopen(req).read())["job"]
        for _ in range(100):
            j = json.loads(urllib.request.urlopen(f"{base}/api/job/{job}").read())
            if j["status"] != "running":
                break
            time.sleep(0.05)
        assert j["status"] == "done", j.get("error")
        assert j["result"]["score"] > 0
        # Another site's page cannot start reviews or read saved essays.
        for headers in ({"Content-Type": "text/plain"},
                        {"Content-Type": "application/json", "Origin": "https://evil.example"}):
            bad = urllib.request.Request(base + "/api/review", data=b"{}", headers=headers, method="POST")
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(bad)
            assert err.value.code == 403
        rebound = urllib.request.Request(base + "/api/history", headers={"Host": "evil.example:80"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(rebound)
        assert err.value.code == 403
    finally:
        httpd.shutdown()


def test_spearman_and_bench_metrics():
    from garyadmit.bench import metrics, spearman
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    res = [
        {"kind": "pair", "group": "g", "rating": 5.0, "level": 45.0, "score": 50.0},
        {"kind": "pair", "group": "g", "rating": 7.0, "level": 65.0, "score": 72.0},
        {"kind": "rated", "group": "h", "rating": 6.0, "level": 55.0, "score": 75.0},
        {"kind": "weak", "score": 40.0},
        {"kind": "exemplar", "score": 80.0},
        {"kind": "ai", "score": 44.0},
    ]
    m = metrics(res)
    assert m["pairs_correct"] == 1.0 and m["tier_gap"] == 40.0
    assert m["glaze_rate"] == pytest.approx(1 / 3)  # the 6.0-rated draft scored 75
    assert m["rated_offset"] == pytest.approx((5 + 7 + 20) / 3)


def test_bench_sample_is_deterministic_and_covers_kinds():
    from garyadmit.bench import sample
    bench = [Anchor(f"b{i}", f"Draft {i} about robotics. " * 30, r, "bench", f"g{i // 2}")
             for i, r in enumerate([4.5, 6.0, 5.0, 5.0, 7.0, 8.5, 6.5, 6.5])]
    a = sample(_corpus(), bench, n_rated=2, n_pairs=1, n_tier=1)
    b = sample(_corpus(), bench, n_rated=2, n_pairs=1, n_tier=1)
    assert [x["id"] for x in a] == [x["id"] for x in b]
    kinds = [x["kind"] for x in a]
    assert kinds.count("pair") == 2 and "rated" in kinds and kinds[-1] == "ai"
