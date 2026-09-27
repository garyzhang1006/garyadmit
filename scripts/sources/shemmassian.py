"""Shemmassian Consulting: 14 essays, each labeled with the school that admitted the student."""

from __future__ import annotations

import re

from ._common import paras_text, soup

URL = "https://www.shemmassianconsulting.com/blog/college-essay-examples"


def _indented(p) -> bool:
    return p.get("data-indent") == "1" or "margin-left:40px" in str(p.get("style") or "").replace(" ", "")


def scrape(fetch, limit=None):
    s = soup(fetch(URL))
    heads = [h for h in s.find_all("h2") if re.search(r"College essay example #\d+", h.get_text(" ", strip=True), re.I)]
    for i, h in enumerate(heads):
        if limit is not None and i >= limit:
            break
        paras = []
        for el in h.find_all_next(True):
            if el.name in ("h2", "figure"):
                break
            if el.name == "p" and _indented(el) and el.get_text(strip=True):
                if not el.get_text(strip=True).startswith("(Suggested reading"):
                    paras.append(el)
        if len(paras) < 2:
            continue
        label = paras[0].get_text(" ", strip=True)
        m = re.search(r"(?:admitted to|worked for|accepted to|got into)\s+(?:the\s+)?(.+?)[.]?$", label, re.I)
        body = paras[1:] if m else paras
        text = paras_text(body)
        yield {
            "source": "shemmassian", "url": URL, "tier": "admitted",
            "school": m.group(1).strip() if m else "", "title": h.get_text(" ", strip=True),
            "essay_type": "supplement" if len(text.split()) < 400 else "personal", "text": text,
        }
