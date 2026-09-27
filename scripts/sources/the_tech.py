"""The Tech (MIT student newspaper): MIT application essays submitted by admitted students.

Articles hold one or more Prompt/Response pairs, labeled either as their own
paragraphs/headings ("Prompt", "Response") or inline ("Prompt We know...").
"""

from __future__ import annotations

import re

from ._common import soup

TAGS = ["https://thetech.com/tags/mit-application-essays-that-worked", "https://thetech.com/tags/mit-essays-that-worked"]
SIG = re.compile(r"^[—–-]\s*[A-Z][\w.' -]+\s*[’']\d\d\s*$")
TRAILING_SIG = re.compile(r"\s*[—–-]\s*[A-ZÀ-Ý][\w.' -]+\s*[’']\d\d\s*$")
LABEL = re.compile(r"^(prompt|response)\b[:.]?\s*", re.I)


def _links(fetch) -> list[str]:
    links = []
    for t in TAGS:
        try:
            s = soup(fetch(t))
        except (RuntimeError, PermissionError):
            continue
        for a in s.find_all("a", href=True):
            m = re.match(r"^(?:https://thetech\.com)?(/\d{4}/\d\d/\d\d/[\w-]+)/?$", str(a.get("href") or ""))
            if m and "https://thetech.com" + m.group(1) not in links:
                links.append("https://thetech.com" + m.group(1))
    return links


def scrape(fetch, limit=None):
    for i, url in enumerate(_links(fetch)):
        if limit is not None and i >= limit:
            break
        try:
            art = soup(fetch(url)).select_one("article")
        except (RuntimeError, PermissionError):
            continue
        if not art:
            continue
        title_el = art.find("h1")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        pairs, prompt, body, mode, year = [], "", [], None, ""
        for el in art.find_all(["h3", "p"]):
            t = el.get_text(" ", strip=True)
            if not t:
                continue
            if SIG.match(t):
                m = re.search(r"[’'](\d\d)", t)
                year = f"20{m.group(1)}" if m else ""
                break
            lab = LABEL.match(t)
            if lab:
                rest = t[lab.end():].strip()
                if lab.group(1).lower() == "prompt":
                    if body:
                        pairs.append((prompt, body))
                    prompt, body, mode = rest, [], "prompt"
                else:
                    mode = "essay"
                    if rest:
                        body.append(rest)
                continue
            if mode == "prompt":
                prompt = (prompt + " " + t).strip()
            elif mode == "essay":
                body.append(t)
        if body:
            pairs.append((prompt, body))
        for prompt, body in pairs:
            body[-1] = TRAILING_SIG.sub("", body[-1])
            yield {
                "source": "the_tech", "url": url, "tier": "admitted", "school": "MIT", "year": year,
                "essay_type": "supplement", "prompt": prompt, "text": "\n\n".join(body), "title": title,
            }
