"""EssaysThatWorked.com: essays by students admitted to selective schools, with the schools that
admitted each writer. The public example pages embed every essay as JSON in __NEXT_DATA__.

The site also grades each essay on its own A+ to C scale. That grade is left out on purpose:
corpus grades are read as AdmitReport grades and would put these essays on the calibration
ladder under an unvalidated scale.
"""

from __future__ import annotations

import json
import re

from ._common import clean

BASE = "https://essaysthatworked.com"
PAGES = ["personal-statement-examples", "common-app-essay-examples", "college-essay-examples", "why-this-college",
         "why-this-major", "usc-supplemental-essays", "ucla-essay-examples", "uc-berkeley-essay-examples",
         "mit-essay-examples", "brown-university", "carnegie-mellon-university", "columbia-university",
         "duke-university", "johns-hopkins-university", "northwestern-university", "princeton-university",
         "stanford-university", "unc-chapel-hill", "university-of-michigan"]
TYPES = {"personal_statement": "personal"}


def _text(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return "".join(_text(c) for c in node.get("children", []))
    if isinstance(node, list):
        return "".join(_text(c) for c in node)
    return ""


def _paragraphs(node) -> list[str]:
    """Top-level block children of the essay's Markdoc tree, one string per paragraph."""
    if isinstance(node, dict) and node.get("name") == "article":
        return [_text(c) for c in node.get("children", [])]
    if isinstance(node, dict):
        return [_text(node)]
    return [_text(node)]


def _essays(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "essays" and isinstance(v, list):
                yield from (e for e in v if isinstance(e, dict) and e.get("html"))
            else:
                yield from _essays(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _essays(v)


def scrape(fetch, limit=None):
    pages, done, n = list(PAGES), set(), 0
    while pages:
        page = pages.pop(0)
        if page in done:
            continue
        done.add(page)
        if limit is not None and n >= limit:
            break
        try:
            html = fetch(f"{BASE}/{page}")
        except (RuntimeError, PermissionError):
            continue
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            continue
        n += 1
        for e in _essays(json.loads(m.group(1))):
            schools = [s for s in e.get("schools") or [] if isinstance(s, dict)]
            for s in schools:  # school pages carry more essays
                if s.get("page") and s["page"] not in done:
                    pages.append(s["page"])
            text = clean("\n\n".join(_paragraphs(e["html"])))
            yield {
                "source": "essaysthatworked", "url": f"{BASE}/{e.get('page') or page}",
                "tier": "admitted" if schools else "example", "title": e.get("title", ""),
                "school": schools[0].get("preferredName", "") if schools else "",
                "essay_type": TYPES.get(e.get("type", ""), "supplement"), "prompt": e.get("prompt") or "",
                "text": text,
            }
