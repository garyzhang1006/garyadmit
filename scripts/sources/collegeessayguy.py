"""College Essay Guy: personal statement and supplemental essay examples from its blog.

The live site answers scrapers with a Cloudflare challenge, so pages are read from
their Wayback Machine copies. The list of example pages comes from the Wayback CDX
index. Essays sit either in a <blockquote> or as plain paragraphs under an
"... Essay Example" heading, followed by the site's commentary.
"""

from __future__ import annotations

import re

from ._common import paras_text, soup, words

CDX = ("https://web.archive.org/cdx/search/cdx?url=collegeessayguy.com/blog/*&collapse=urlkey"
       "&fl=original&filter=statuscode:200&from=2023")
LIVE = "https://www.collegeessayguy.com/blog/"
WAYBACK = "https://web.archive.org/web/2026id_/" + LIVE

# Slugs of pages that publish whole college essays. Law school, grad school, UCAS,
# scholarship, and transfer pages are left out because they are other genres.
KEEP = re.compile(r"^(personal-statement-examples|college-essay-examples|common-app-essay-examples|"
                  r"extracurricular-activity-essay-examples|uc-essay-examples-personal-insight-questions|"
                  r"coalition-application-essay-prompts-examples|questbridge-essay-examples|community-essay|"
                  r"overcoming-challenges-essay|challenges-college-essay|"
                  r"identity-diversity-contribute-essays-roles-and-identities|.+-supplemental-essays?|"
                  r"how-to-write-why-us.*|why-us.*|dos-and-donts-why-us-statement)$")
# Always tried even if the CDX listing fails.
SEED = ["personal-statement-examples", "college-essay-examples", "common-app-essay-examples",
        "extracurricular-activity-essay-examples", "uc-essay-examples-personal-insight-questions",
        "community-essay", "overcoming-challenges-essay"]

EXAMPLE_HEAD = re.compile(r"example\s*(#\s*\d+|:)|essay example|example essay|^\s*the\s.+\sexample", re.I)
NOT_EXAMPLE = re.compile(r"^\s*(how|what|why|where|when|tips|more|want|in-depth|analysis)\b", re.I)
COMMENTARY = re.compile(r"^\s*(tips|analysis|what i love|why (this|it) works|here'?s why|notes?\b|commentary|"
                        r"takeaways?|ethan'?s|what makes|what this essay|key takeaways)", re.I)
PREFACE = re.compile(r"written for|prompt|essay (was )?written|word count|this essay|by .{0,40}(admitted|accepted)",
                     re.I)
MIN_WORDS = 100


def _slugs(fetch) -> list[str]:
    out = list(SEED)
    try:
        for line in fetch(CDX).splitlines():
            m = re.match(r"https?://(?:www\.)?collegeessayguy\.com/blog/([^/?#]+)/?$", line.strip(), re.I)
            if m and KEEP.match(m.group(1).lower()) and m.group(1).lower() not in out:
                out.append(m.group(1).lower())
    except (RuntimeError, PermissionError):
        pass
    return out


def _heading_text(h) -> str:
    return re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip()


def _title(h) -> str:
    t = _heading_text(h)
    t = re.sub(r"^.*?example\s*#\s*\d+\s*:?\s*", "", t, flags=re.I) or t
    return t.strip(" :“”\"")


def _from_blockquotes(s):
    for bq in s.find_all("blockquote"):
        ps = [p for p in bq.find_all("p") if p.get_text(strip=True)] or [bq]
        text = paras_text(ps)
        if words(text) < MIN_WORDS:
            continue
        h = bq.find_previous(["h2", "h3", "h4"])
        yield _title(h) if h else "", text


def _from_headings(s):
    for h in s.find_all(["h2", "h3", "h4"]):
        t = _heading_text(h)
        if not EXAMPLE_HEAD.search(t) or NOT_EXAMPLE.match(t):
            continue
        paras = []
        for el in h.find_all_next(True):
            if el.name in ("h1", "h2", "h3", "h4", "blockquote"):
                break  # a blockquote means the essay is quoted and the blockquote pass has it
            if el.name != "p" or el.find_parent("li") or el.find_parent("blockquote"):
                continue
            pt = el.get_text(" ", strip=True)
            if not pt:
                continue
            if COMMENTARY.match(pt):
                break
            if not paras and len(pt.split()) < 30 and PREFACE.search(pt):
                continue
            paras.append(el)
        text = paras_text(paras)
        if words(text) >= MIN_WORDS:
            yield _title(h), text


def scrape(fetch, limit=None):
    n = 0
    for slug in _slugs(fetch):
        if limit is not None and n >= limit:
            break
        try:
            s = soup(fetch(WAYBACK + slug))
        except (RuntimeError, PermissionError):
            continue
        n += 1
        supp = bool(re.search(r"supplement|why-us|community|extracurricular|uc-essay|identity|coalition|questbridge",
                              slug))
        seen = set()
        for title, text in [*_from_blockquotes(s), *_from_headings(s)]:
            if text[:200] in seen:
                continue
            seen.add(text[:200])
            yield {
                "source": "collegeessayguy", "url": LIVE + slug, "tier": "example", "title": title,
                "essay_type": "supplement" if supp or words(text) < 400 else "personal", "text": text,
            }
