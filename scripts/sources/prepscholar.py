"""PrepScholar: two annotated essays by admitted students and two drafts presented as bad essays."""

from __future__ import annotations

import re

from ._common import paras_text, soup

PAGES = [
    ("https://blog.prepscholar.com/college-essay-examples-that-worked-expert-analysis", r"^Example \d", "admitted"),
    ("https://blog.prepscholar.com/bad-college-essays", r"^Essay #\d", "weak"),
]
SCHOOL = re.compile(r"(Johns Hopkins|Tufts|Harvard|Yale|Stanford|Princeton|MIT|Columbia|Duke|Brown|Cornell|Penn)")


def scrape(fetch, limit=None):
    for url, pat, tier in PAGES:
        try:
            s = soup(fetch(url))
        except (RuntimeError, PermissionError):
            continue
        box = s.select_one("span#hs_cos_wrapper_post_body") or s
        heads = [h for h in box.find_all("h3") if re.match(pat, h.get_text(" ", strip=True))]
        for i, h in enumerate(heads):
            if limit is not None and i >= limit:
                break
            paras = []
            for el in h.find_all_next(["p", "div", "h2", "h3"]):
                if el.name in ("h2", "h3"):
                    break
                if el.name == "p" and el.get_text(strip=True) and not el.find_parent("p"):
                    paras.append(el)
                elif el.name == "div" and not el.find(["p", "div"]) and el.get_text(strip=True):
                    paras.append(el)  # the bad-essays page puts each essay in a bare div
            text = paras_text(paras)
            if len(text.split()) < 150:
                continue
            head = h.get_text(" ", strip=True)
            m = SCHOOL.search(head)
            yield {
                "source": "prepscholar", "url": url, "tier": tier, "title": head,
                "school": m.group(1) if m else "", "essay_type": "personal", "text": text,
            }
