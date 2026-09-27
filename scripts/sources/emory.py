"""Emory admission blog "Strong Personal Statements" series: applicant essays with admission staff feedback.

2021 and later posts come from the live WordPress REST API. The 2016-2019 posts
were taken down, so they come from their Internet Archive snapshots (raw id_ form).
Essay and feedback paragraphs are both indented (padding-left); the "Feedback
from Admission Staff" heading is what separates them.
"""

from __future__ import annotations

import json
import re

from ._common import paras_text, soup

API = ("https://blog.emoryadmission.com/wp-json/wp/v2/posts?search=personal%20statement&per_page=100"
       "&_fields=link,date,title,content")
CDX = ("https://web.archive.org/cdx/search/cdx?url=blog.emoryadmission.com/20*&output=json&collapse=urlkey"
       "&filter=statuscode:200&fl=original,timestamp&limit=5000")
ARCHIVED_POST = re.compile(r"^https?://blog\.emoryadmission\.com(?::80)?/(201[6-9])/\d\d/strong-personal-statements[^/?]*/$")
FEEDBACK = re.compile(r"^feedback from admission", re.I)


def _indented(el) -> bool:
    return "padding-left" in (el.get("style") or "")


def split_post(container) -> list[dict]:
    """Walk a post body and cut it into {prompt, essay, feedback} blocks."""
    els = [e for e in container.find_all(["p", "h4", "h5"]) if e.get_text(strip=True)]
    blocks, cur, mode = [], {"prompt": "", "essay": [], "feedback": []}, "pre"

    def flush():
        nonlocal cur
        if cur["essay"]:
            blocks.append(cur)
        cur = {"prompt": "", "essay": [], "feedback": []}

    for i, el in enumerate(els):
        t = el.get_text(" ", strip=True)
        if FEEDBACK.match(t):
            mode = "feedback"
            continue
        nxt = els[i + 1] if i + 1 < len(els) else None
        starts_block = el.name in ("h4", "h5") or (
            not _indented(el) and mode != "essay" and nxt is not None and _indented(nxt)
            and not re.match(r"as we read applications", t, re.I))
        if starts_block:
            flush()
            cur["prompt"] = re.sub(r"^personal statement question:\s*", "", t, flags=re.I)
            mode = "pre"
            continue
        if _indented(el):
            if mode == "feedback":
                cur["feedback"].append(el)
            else:
                mode = "essay"
                cur["essay"].append(el)
    flush()
    return blocks


COMMON_APP = re.compile(r"^(Some students have|The lessons we take|Reflect on|Describe a|Discuss an|Share an essay|"
                        r"Tell a story|Please describe)")


def _records(container, url: str, year: str, title: str):
    for b in split_post(container):
        prompt, essay_title = b["prompt"], title
        if re.match(r"this is (one|part)", prompt, re.I):
            prompt = ""
        elif prompt and len(prompt.split()) <= 8 and not prompt.endswith("?"):
            prompt, essay_title = "", prompt  # a heading that is the essay's own title
        first = b["essay"][0].get_text(" ", strip=True)
        if not prompt and COMMON_APP.match(first) and len(first.split()) < 90 and len(b["essay"]) > 1:
            prompt, b["essay"] = first, b["essay"][1:]
        yield {
            "source": "emory", "url": url, "tier": "exemplar", "school": "Emory", "year": year,
            "essay_type": "personal", "title": essay_title, "prompt": prompt,
            "text": paras_text(b["essay"]), "commentary": paras_text(b["feedback"]),
        }


def scrape(fetch, limit=None):
    n = 0
    try:
        items = json.loads(fetch(API))
    except (RuntimeError, PermissionError, json.JSONDecodeError):
        items = []
    for it in items:
        title = soup(it["title"]["rendered"]).get_text(" ", strip=True)
        for r in _records(soup(it["content"]["rendered"]), it["link"], it["date"][:4], title):
            if limit is not None and n >= limit:
                return
            n += 1
            yield r
    try:
        rows = json.loads(fetch(CDX))[1:]
    except (RuntimeError, PermissionError, json.JSONDecodeError):
        return
    posts = {}
    for original, ts in rows:
        m = ARCHIVED_POST.match(original)
        if m:
            key = re.sub(r"^https?://([^/]+?)(:80)?/", "", original)
            posts.setdefault(key, (ts, original, m.group(1)))
    for key, (ts, original, year) in sorted(posts.items()):
        try:
            page = soup(fetch(f"https://web.archive.org/web/{ts}id_/{original}"))
        except (RuntimeError, PermissionError):
            continue
        body = page.select_one("div.single-blog-content") or page.select_one("div.entry-content")
        if body is None:
            continue
        # Archived themes put the blog name in <h1>, so title comes from the slug.
        title = key.rstrip("/").split("/")[-1].replace("-", " ").capitalize()
        live_url = "https://blog.emoryadmission.com/" + key
        for r in _records(body, f"https://web.archive.org/web/{ts}/{live_url}", year, title):
            if limit is not None and n >= limit:
                return
            n += 1
            yield r
