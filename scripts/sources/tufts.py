"""Tufts admissions "past essays" pages (2015-2023, via Internet Archive) plus the live "Essays That Worked" post.

Tufts published essays from admitted students under headings like
"Joseph Poirier '21 Concord, MA", with the essay paragraphs following until the
next heading. The pages were retired in 2025, so each yearly snapshot is read
from its raw (id_) archive copy.
"""

from __future__ import annotations

import json
import re

from ._common import paras_text, soup

SUBPAGES = {
    "common-application-essays": ("personal", "Common App essay"),
    "why-tufts-essays": ("supplement", "Why Tufts?"),
    "let-your-life-speak-essays": ("supplement", "Let your life speak"),
    "supplemental-essay-three": ("supplement", "Tufts supplement"),
}
LIVE = "https://admissions.tufts.edu/blogs/inside-admissions/post/essays-that-worked/"
NAME = re.compile(r"^([A-Z][\w.'’ -]{2,40}?)\s*[’']\s*(\d\d)\b")


def _page(sub: str) -> str:
    return "https://admissions.tufts.edu/apply/advice/past-essays/" + sub + "/"


def _snapshots_url(url: str) -> str:
    # One snapshot per year is enough; later years repeat or replace earlier essays.
    return ("https://web.archive.org/cdx/search/cdx?url=" + url
            + "&output=json&filter=statuscode:200&fl=timestamp&collapse=timestamp:4")


def _split(container, stop=("h2", "h3")) -> list[tuple[str, str, list, str]]:
    """(name, class year, paragraphs, author line) for each author heading in the container."""
    out, cur = [], None
    for el in container.find_all(["h2", "h3", "h4", "p"]):
        t = el.get_text(" ", strip=True)
        if not t:
            continue
        # Author lines are short bold paragraphs: "Name '21" then school or hometown.
        head = el.name in stop or (el.name == "p" and el.find(["strong", "b"]) is not None and len(t.split()) <= 16)
        m = NAME.match(t) if head else None
        if m:
            cur = (m.group(1).strip(), m.group(2), [], t)
            out.append(cur)
        elif head:
            cur = None  # a heading that is not an author ends the essay
        elif cur is not None and el.name == "p":
            cur[2].append(el)
    return out


def _archived(fetch, sub):
    try:
        stamps = [r[0] for r in json.loads(fetch(_snapshots_url(_page(sub))))[1:]]
    except (RuntimeError, PermissionError, json.JSONDecodeError):
        return
    for ts in stamps:
        try:
            page = soup(fetch("https://web.archive.org/web/" + ts + "id_/" + _page(sub)))
        except (RuntimeError, PermissionError):
            continue
        body = page.find("article", class_="content") or page.find("article")
        if body is not None:
            yield ts, body


def scrape(fetch, limit=None):
    n, seen = 0, set()

    def emit(name, yy, paras, url, essay_type, label):
        nonlocal n
        key = (name.lower(), yy)
        if key in seen or not paras or (limit is not None and n >= limit):
            return None
        text = paras_text(paras)
        # Tufts supplements were capped near 250 words; longer ones are two answers run together.
        if essay_type == "supplement" and len(text.split()) > 400:
            return None
        seen.add(key)
        n += 1
        return {
            "source": "tufts", "url": url, "tier": "exemplar", "school": "Tufts",
            "year": str(2000 + int(yy) - 4), "essay_type": essay_type,
            "title": label + ": " + name + " '" + yy, "text": text,
        }

    try:
        live = soup(fetch(LIVE))
        # The post's wrapper div closes early in the served HTML, so walk the whole page.
        body = live.find("main") or live.body or live
        for name, yy, paras, line in _split(body):
            kind = "personal" if re.search(r"common app", line, re.I) else "supplement"
            r = emit(name, yy, paras, LIVE, kind, "Essays That Worked")
            if r:
                yield r
    except (RuntimeError, PermissionError):
        pass
    for sub, (essay_type, label) in SUBPAGES.items():
        for ts, body in _archived(fetch, sub):
            for name, yy, paras, _ in _split(body):
                r = emit(name, yy, paras, "https://web.archive.org/web/" + ts + "/" + _page(sub), essay_type, label)
                if r:
                    yield r
