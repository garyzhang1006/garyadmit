"""St. John's College "Great Essays From Past Years": essays by enrolled students, posted by admissions.

Each essay sits in an accordion. The toggle shows "NAME 'YY: first words..." and
the hidden panel holds the rest, sometimes continuing mid-sentence after "...".
"""

from __future__ import annotations

import re

from ._common import clean, soup

URL = "https://www.sjc.edu/admissions-and-aid/undergraduate/apply/essay-tips-faq"
LABEL = re.compile(r"^\s*([A-Z][A-Za-z .'-]{1,30}?)\s*[’']\s*(\d\d)\s*:\s*")


def scrape(fetch, limit=None):
    try:
        page = soup(fetch(URL))
    except (RuntimeError, PermissionError):
        return
    n = 0
    for tog in page.select(".accordion-toggle"):
        if limit is not None and n >= limit:
            break
        for icon in tog.select(".toggle-icon"):
            icon.decompose()
        head = tog.get_text(" ", strip=True)
        m = LABEL.match(head)
        panel = tog.find_next(class_="accordion-content")
        if not m or panel is None:
            continue
        paras = [p.get_text(" ", strip=True) for p in panel.find_all("p")]
        paras = [p for p in paras if p]
        if not paras:
            continue
        preview = head[m.end():].rstrip(". …").strip()
        if re.match(r"^(\.\.\.|…)", paras[0]):
            # Panel resumes mid-sentence; the toggle holds the opening words.
            paras[0] = preview + " " + re.sub(r"^(\.\.\.|…)\s*", "", paras[0])
        q = tog.find_previous("h4")
        prompt_el = q.find_next("p") if q else None
        year_m = re.search(r"(20\d\d)", q.get_text(" ", strip=True)) if q else None
        n += 1
        yield {
            "source": "st_johns", "url": URL, "tier": "admitted", "school": "St. John's College",
            "year": year_m.group(1) if year_m else f"20{m.group(2)}", "essay_type": "supplement",
            "title": f"{m.group(1).title()} '{m.group(2)}",
            "prompt": prompt_el.get_text(" ", strip=True) if prompt_el else "",
            "text": clean("\n\n".join(paras)),
        }
