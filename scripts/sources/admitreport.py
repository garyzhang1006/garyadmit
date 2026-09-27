"""AdmitReport graded essay examples (A+ to F), with inline admissions-officer comments removed.

The grades are AdmitReport's own and the site does not say who wrote the
essays, so bench uses them only for rank order, never as absolute truth.
"""

from __future__ import annotations

import re

from ._common import paras_text, soup

PAGES = [
    "https://admitreport.com/blog/college-essay-examples",
    "https://admitreport.com/blog/common-app-essay-examples",
    "https://admitreport.com/blog/personal-statement-examples",
]
HEAD = re.compile(r"Example #\d+|^(Community|Diversity|Personal Challenge|Extracurricular|Why this Major|Academic Interest) Essay", re.I)
SUPP = re.compile(r"^(Community|Diversity|Personal Challenge|Extracurricular|Why this Major|Academic Interest)", re.I)
END = re.compile(r"^(Word Count:|Admissions Officer Notes|AO Notes)", re.I)
INTRO = re.compile(r"^(the (first|next|last|final)|this|our|here'?s|let'?s)\b.*\b(essay|example)\b.*\b(grade|got an?|scored|earned)\b", re.I)
GRADE = re.compile(r"^Grade:\s*([ABCDF][+-]?)", re.I)
COMMENT = re.compile(r"\(\([^)]*\)\)")
COMMENT_ML = re.compile(r"\(\(.*?\)\)", re.S)
PROMPT_LINE = re.compile(r"^(common app )?prompt\b", re.I)
COUNT_LINE = re.compile(r"^(word|world) count:", re.I)
WEAK = {"C+", "C", "C-", "D+", "D", "D-", "F"}


def scrape(fetch, limit=None):
    for pi, url in enumerate(PAGES):
        if limit is not None and pi >= limit:
            break
        try:
            s = soup(fetch(url))
        except (RuntimeError, PermissionError):
            continue
        body = s.select_one("div.blog-post__body") or s
        for h in body.find_all("h3"):
            head = h.get_text(" ", strip=True)
            if not HEAD.search(head):
                continue
            paras, grade, ended = [], "", False
            for el in h.find_all_next(["p", "h2", "h3", "h4"]):
                t = el.get_text(" ", strip=True)
                if el.name in ("h2", "h3"):
                    break
                if not ended and END.match(t):
                    ended = True
                    continue
                if ended:
                    m = GRADE.match(t)
                    if m:
                        grade = m.group(1).upper()
                        break
                    continue
                if el.name == "p" and t:
                    paras.append(COMMENT.sub("", t).strip())
            if paras and "((" not in paras[0] and INTRO.match(paras[0]):
                paras = paras[1:]
            prompt = ""
            while paras and PROMPT_LINE.match(paras[0]):
                prompt = paras.pop(0)
            paras = [p for p in paras if not COUNT_LINE.match(p)]
            if not ended or not grade or not paras:
                continue  # no grade or no clear end marker: skip rather than guess
            text = COMMENT_ML.sub("", "\n\n".join(p for p in paras if p))
            text = re.sub(r"\(\(|\)\)", "", text)
            text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
            title = re.sub(r"^.*?Example #\d+:\s*", "", head)
            yield {
                "source": "admitreport", "url": url, "tier": "weak" if grade in WEAK else "example",
                "grade": grade, "title": title, "prompt": re.sub(r"^[^:]*:\s*", "", prompt) if ":" in prompt else "",
                "essay_type": "supplement" if SUPP.match(head) else "personal", "text": paras_text([text]),
            }
