"""Hamilton College "College Essays that Worked" (current class plus archive pages)."""

from __future__ import annotations

import re

from ._common import paras_text, soup

INDEX = "https://www.hamilton.edu/admission/apply/college-essays-that-worked"
FOOTER = re.compile(r"^These essays (are|were) (in addition to|part of)", re.I)


def _pages(fetch) -> list[str]:
    s = soup(fetch(INDEX))
    pages = [INDEX]
    for a in s.find_all("a", href=True):
        href = str(a.get("href") or "")
        if re.search(r"/college-essays-that-worked/\d{4}-essays-that-worked$", href):
            url = href if href.startswith("http") else "https://www.hamilton.edu" + href
            if url not in pages:
                pages.append(url)
    return pages


def scrape(fetch, limit=None):
    n = 0
    for page in _pages(fetch):
        try:
            main = soup(fetch(page)).find("main")
        except (RuntimeError, PermissionError):
            continue
        if not main:
            continue
        for h in main.find_all("h3"):
            if limit is not None and n >= limit:
                return
            paras = []
            for el in h.find_all_next(["p", "h2", "h3"]):
                if el.name in ("h2", "h3"):
                    break
                t = el.get_text(" ", strip=True)
                if t and not FOOTER.match(t):
                    paras.append(el)
            text = paras_text(paras)
            if len(text.split()) < 150:
                continue
            head = h.get_text(" ", strip=True)
            m = re.search(r"[’'](\d\d)\b", head)
            n += 1
            yield {
                "source": "hamilton", "url": page, "tier": "exemplar", "school": "Hamilton",
                "year": f"20{m.group(1)}" if m else "", "essay_type": "personal",
                "title": head, "text": text,
            }
