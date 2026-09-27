"""The Harvard Crimson's sponsored "Successful Harvard Application Essays" series (admitted students)."""

from __future__ import annotations

import re

from ._common import paras_text, soup

PAGE = "https://www.thecrimson.com/topic/sponsored-successful-harvard-essays-{year}/"
START = re.compile(r"^(ESSAY|Successful Harvard Essay)\b", re.I)
STOP = re.compile(r"^(REVIEW|_{3,}|Professional Review)", re.I)


def scrape(fetch, limit=None):
    pages = 0
    for year in range(2018, 2031):
        if limit is not None and pages >= limit:
            break
        url = PAGE.format(year=year)
        try:
            s = soup(fetch(url))
        except (RuntimeError, PermissionError):
            continue
        pages += 1
        for h in s.find_all(class_="md:text-6xl"):
            body = h.find_next(class_="essay-body")
            if body is None:
                continue
            started, title, paras = False, "", []
            for el in body.find_all(["p", "h2"]):
                t = el.get_text(" ", strip=True)
                if not started:
                    if START.match(t):
                        started = True
                        # 2021+ headings read "Successful Harvard Essay: <title>".
                        title = t.split(":", 1)[1].strip() if ":" in t else ""
                    continue
                if STOP.match(t):
                    break
                if el.name != "p" or not t or el.find_parent("blockquote"):
                    continue
                if not title and not paras and len(t.split()) <= 10 and not t.endswith((".", "?", "!", "”", '"')):
                    title = t  # a short first line is the essay's title
                    continue
                paras.append(el)
            if not paras:
                continue
            name = re.sub(r"['’]s Essay$", "", h.get_text(" ", strip=True))
            yield {
                "source": "harvard_crimson", "url": url, "tier": "admitted", "school": "Harvard",
                "year": year, "essay_type": "personal", "title": title or f"{name}'s essay",
                "text": paras_text(paras),
            }
