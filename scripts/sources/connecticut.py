"""Connecticut College "Essays that Worked", chosen by its admission counselors."""

from __future__ import annotations

import re

from ._common import paras_text, soup

INDEX = "https://www.conncoll.edu/admission/apply/essays-that-worked/"


def scrape(fetch, limit=None):
    s = soup(fetch(INDEX))
    links = sorted({str(a.get("href") or "") for a in s.find_all("a", href=True)
                    if "/essays-that-worked/" in str(a.get("href")) and str(a.get("href")).rstrip("/").split("/")[-1] != "essays-that-worked"})
    for i, url in enumerate(links):
        if limit is not None and i >= limit:
            break
        url = url if url.startswith("http") else "https://www.conncoll.edu" + url
        try:
            p = soup(fetch(url))
        except (RuntimeError, PermissionError):
            continue
        box = p.select_one("div.all-full.centered") or p
        title_el = box.find("h3")
        if not title_el:
            continue
        essay, comments, mode = [], [], "essay"
        for el in title_el.find_all_next(["h3", "h4", "p"]):
            t = el.get_text(" ", strip=True)
            if el.name == "h3" and re.match(r"why it worked", t, re.I):
                mode = "comments"
                continue
            if el.name == "p" and re.match(r"read more essays that worked", t, re.I):
                break
            if el.name == "p" and t:
                (essay if mode == "essay" else comments).append(el)
        if mode != "comments" or not essay:
            continue
        m = re.search(r"-(\d\d)/?$", url)
        yield {
            "source": "connecticut", "url": url, "tier": "exemplar", "school": "Connecticut College",
            "year": f"20{m.group(1)}" if m else "", "essay_type": "personal",
            "title": title_el.get_text(" ", strip=True), "text": paras_text(essay), "commentary": paras_text(comments),
        }
