"""Johns Hopkins "Essays That Worked" (Hopkins Insider), picked and annotated by the admissions committee.

All 64 essays come from the site's public WordPress REST endpoint for the
essays-that-worked category; each has the committee's comments after it.
"""

from __future__ import annotations

import json
import re

from ._common import paras_text, soup

API = ("https://apply.jhu.edu/wp-json/wp/v2/insider_article?hi_officer_article_category=58"
       "&per_page=100&page={page}&_fields=link,date,title,content")


def scrape(fetch, limit=None):
    items, page = [], 1
    while True:
        try:
            batch = json.loads(fetch(API.format(page=page)))
        except (RuntimeError, PermissionError, json.JSONDecodeError):
            break
        if not batch:
            break
        items += batch
        if len(batch) < 100:
            break
        page += 1
    for i, it in enumerate(items):
        if limit is not None and i >= limit:
            break
        body = soup(it["content"]["rendered"])
        essay, comments, mode, byline = [], [], "essay", ""
        for el in body.find_all(["h2", "h3", "h4", "h5", "p"]):
            t = el.get_text(" ", strip=True)
            if el.name == "h2" and not byline and re.match(r"by\b", t, re.I):
                byline = t
                continue
            if el.name in ("h3", "h4") and re.match(r"admissions committee comments", t, re.I):
                mode = "comments"
                continue
            if el.name in ("h3", "h5") and mode == "comments":
                break
            if el.name == "p" and t and el.find_parent("blockquote") is None:
                (essay if mode == "essay" else comments).append(el)
        if mode != "comments" or not essay:
            continue  # unknown layout: skip rather than risk mixing in commentary
        m = re.search(r"[’'](\d\d)\b", byline)
        yield {
            "source": "jhu", "url": it["link"], "tier": "exemplar", "school": "Johns Hopkins",
            "year": f"20{m.group(1)}" if m else it["date"][:4], "essay_type": "personal",
            "title": soup(it["title"]["rendered"]).get_text(" ", strip=True),
            "text": paras_text(essay), "commentary": paras_text(comments),
        }
