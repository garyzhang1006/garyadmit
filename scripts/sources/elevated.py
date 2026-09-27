"""Human-rated Common App drafts (ElevatEd, via the jinwkim65/commonapp_aes Yale thesis repo).

1,177 real drafts, each with an expert consultant's holistic rating (4.0-9.0).
They are the only public college essays with human quality scores, so they
anchor GaryAdmit's scale and let `garyadmit bench` measure agreement with
human raters. They are private drafts: the text is never shown in the UI,
student first names are redacted, and every column except the essay and its
rating is dropped.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re

import requests

from ._common import UA, clean, words

URL = "https://raw.githubusercontent.com/jinwkim65/commonapp_aes/main/scored_essays_final.csv"

NAME_PATTERNS = [
    re.compile(r"^\s*([A-Z][a-zA-Z'-]+) has previously uploaded"),
    re.compile(r"\bHi,? ([A-Z][a-zA-Z'-]+)[!,.]"),
    re.compile(r"\bHello,? ([A-Z][a-zA-Z'-]+)[!,.]"),
    re.compile(r"\bHey,? ([A-Z][a-zA-Z'-]+)[!,.]"),
]
LINK = re.compile(r"https?://\S+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}")
NOT_NAMES = {"There", "Everyone", "All", "Team", "Again", "Friend"}


def redact(essay: str, document: str) -> str:
    names = set()
    for pat in NAME_PATTERNS:
        for m in pat.finditer(document):
            if m.group(1) not in NOT_NAMES:
                names.add(m.group(1))
    for n in names:
        essay = re.sub(rf"\b{re.escape(n)}\b", "[Name]", essay)
    essay = LINK.sub("[link]", essay)
    essay = EMAIL.sub("[email]", essay)
    return PHONE.sub("[phone]", essay)


def split_of(key: str) -> str:
    # 25% held out for benchmarking; anchors and bench never overlap.
    return "bench" if int(hashlib.sha1(key.encode()).hexdigest(), 16) % 4 == 0 else "anchor"


def _shingles(text: str) -> set:
    toks = re.findall(r"[a-z']+", text.lower())[:180]
    return {" ".join(toks[i:i + 3]) for i in range(len(toks) - 2)}


class DraftGroups:
    """Groups revisions of the same essay (the dataset has many) so that all
    drafts of one essay land in the same split and bench can compare them."""

    def __init__(self):
        self.reps: list[tuple[str, set]] = []

    def assign(self, rid: str, text: str) -> str:
        sh = _shingles(text)
        for gid, rep in self.reps:
            inter = len(sh & rep)
            if inter and inter / min(len(sh), len(rep)) > 0.25:
                return gid
        self.reps.append((rid, sh))
        return rid


def scrape(fetch=None, limit: int | None = None):  # noqa: ARG001 (fetch unused: raw CSV, not HTML)
    headers = {"User-Agent": UA}
    if limit:
        # Smoke test: first ~40 KB per requested row instead of the full 18 MB.
        headers["Range"] = f"bytes=0-{limit * 40000}"
    r = requests.get(URL, headers=headers, timeout=120)
    r.raise_for_status()
    csv.field_size_limit(10**9)
    reader = csv.DictReader(io.StringIO(r.content.decode("utf-8", errors="replace")))
    seen = set()
    groups = DraftGroups()
    try:
        for row in reader:
            text = clean(row.get("Essay Content") or "")
            try:
                rating = float(row.get("Essay Rating") or "")
            except ValueError:
                continue
            n = words(text)
            if not (250 <= n <= 800):
                continue
            text = redact(text, row.get("Document Content") or "")
            key = re.sub(r"\W+", " ", text.lower())[:300]
            if key in seen:
                continue
            seen.add(key)
            rid = "elevated-" + hashlib.sha1(key.encode()).hexdigest()[:10]
            gid = groups.assign(rid, text)
            yield {
                "id": rid, "source": "elevated", "text": text, "words": n,
                "rating": rating, "group": gid, "split": split_of(gid),
            }
    except csv.Error:
        if not limit:  # a truncated final row is expected only in smoke tests
            raise
