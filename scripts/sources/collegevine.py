"""CollegeVine blog essay examples. Essays sit in div.callout, apart from the commentary."""

from __future__ import annotations

import re

from ._common import soup

PAGES = [
    ("https://blog.collegevine.com/college-essay-examples", "example", None),
    ("https://blog.collegevine.com/common-app-essay-examples/", "example", "personal"),
    ("https://blog.collegevine.com/why-this-college-essay-examples", "example", "supplement"),
    ("https://blog.collegevine.com/ivy-league-essay-examples", "example", None),
    ("https://blog.collegevine.com/college-essays-that-need-improvement", "weak", None),
]
SCHOOLS = ["UPenn", "Penn", "Harvard", "Yale", "Princeton", "Columbia", "Brown", "Dartmouth", "Cornell",
           "Northwestern", "NYU", "Boston University", "Tufts", "Georgia Tech", "UW Madison", "MIT",
           "Stanford", "Duke", "UChicago", "Johns Hopkins", "Rice", "Vanderbilt"]


def _label(callout) -> str:
    h = callout.find_previous(["h2", "h3"])
    return h.get_text(" ", strip=True) if h else ""


def scrape(fetch, limit=None):
    for i, (url, tier, forced_type) in enumerate(PAGES):
        if limit is not None and i >= limit:
            break
        try:
            s = soup(fetch(url))
        except (RuntimeError, PermissionError):
            continue
        for c in s.select("div.callout"):
            ps = [p.get_text(" ", strip=True) for p in c.find_all("p")]
            ps = [p for p in ps if p]
            if not ps:
                continue
            prompt = ""
            if re.match(r"^prompt\b", ps[0], re.I):
                if len(ps) == 1:
                    continue  # a prompt header callout, not an essay
                prompt = re.sub(r"^prompt[^:]*:\s*", "", ps[0], flags=re.I)
                ps = ps[1:]
            text = "\n\n".join(ps)
            if len(text.split()) < 60:
                continue
            label = _label(c)
            school = next((sch for sch in SCHOOLS if re.search(rf"\b{re.escape(sch)}\b", label)), "")
            if school == "Penn":
                school = "UPenn"
            if forced_type:
                etype = forced_type
            else:
                long_personal = len(text.split()) >= 450 and not school
                etype = "personal" if long_personal else "supplement"
            yield {
                "source": "collegevine", "url": url, "tier": tier, "school": school,
                "essay_type": etype, "title": label, "prompt": prompt, "text": text,
            }
