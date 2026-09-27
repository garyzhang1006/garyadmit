"""StudyNotes essays by admitted students, mirrored as .txt files in haze/college_essay_analysis."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from ._common import clean, words

API = "https://api.github.com/repos/haze/college_essay_analysis/contents/essays?ref=master"
RAW = "https://raw.githubusercontent.com/haze/college_essay_analysis/master/essays/{name}"
FOOTER = re.compile(r"(StudyNotes|AP study guides|Follow @StudyNotesApp|Enlist the expert help)", re.I)
SCHOOLS = {
    "stanford": "Stanford", "harvard": "Harvard", "yale": "Yale", "penn": "UPenn", "upenn": "UPenn",
    "duke": "Duke", "cornell": "Cornell", "caltech": "Caltech", "uc": "University of California",
    "princeton": "Princeton", "columbia": "Columbia", "brown": "Brown", "dartmouth": "Dartmouth",
    "mit": "MIT", "chicago": "UChicago", "uchicago": "UChicago", "northwestern": "Northwestern",
    "georgetown": "Georgetown", "rice": "Rice", "vanderbilt": "Vanderbilt", "tufts": "Tufts",
    "notre": "Notre Dame", "berkeley": "UC Berkeley", "ucla": "UCLA", "nyu": "NYU", "usc": "USC",
}
# Files open with the prompt only sometimes; otherwise the first paragraph is essay text.
PROMPT_CUE = re.compile(r"(^|[.?!]\s+)(Describe|Tell us|Tell me|Please|Discuss|Explain|Reflect|Share|Choose|Imagine|"
                        r"Write|Evaluate|Elaborate|Briefly|Consider|Recount|Identify|Pick|Select|Using)\b")


def _is_prompt(para: str) -> bool:
    n = words(para)
    if n > 100:
        return False
    return (para.rstrip().endswith("?") or bool(PROMPT_CUE.search(para))
            or bool(re.search(r"please share|share your story|if this sounds like you", para, re.I))
            or bool(re.search(r"\(\s*\d+[^)]{0,20}words?\s*\)|word limit", para, re.I)))


def scrape(fetch, limit=None):
    try:
        entries = json.loads(fetch(API))
    except (RuntimeError, PermissionError, json.JSONDecodeError):
        return
    files = sorted(e["name"] for e in entries if e.get("name", "").endswith(".txt"))
    for i, name in enumerate(files):
        if limit is not None and i >= limit:
            break
        try:
            raw = fetch(RAW.format(name=quote(name)))
        except (RuntimeError, PermissionError):
            continue
        lines = raw.replace("\r", "").split("\n")
        cut = next((j for j, ln in enumerate(lines) if FOOTER.search(ln)), len(lines))
        # Paragraphs are hard-wrapped at ~80 columns; rejoin their lines.
        paras = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", "\n".join(lines[:cut])) if p.strip()]
        # A trailing famous quote with attribution precedes the footer on many files.
        # It is either quoted with a dash or bare, like "Who seeks shall find. Sophocles".
        while paras and (re.match(r'^["“].{0,300}["”]\s*[-—–]\s*\S', paras[-1], re.S)
                         or (words(paras[-1]) <= 40 and not re.search(r"[.!?\"”’')]$", paras[-1]))):
            paras.pop()
        if len(paras) < 2:
            continue
        # A prompt ending in "(N words)" is sometimes run into the first essay paragraph.
        m = re.match(r"^(.{10,400}?\(\s*\d+[^)]{0,20}words?\s*\))\s*(\S.+)$", paras[0], re.S)
        if m:
            paras[:1] = [m.group(1), m.group(2)]
        prompt, essay = (paras[0], paras[1:]) if _is_prompt(paras[0]) else ("", paras)
        if not prompt and PROMPT_CUE.match(essay[0]):
            continue  # prompt fused with the essay in one paragraph; no clean split
        stem = re.sub(r"^\d+\s+", "", name[:-4])
        key = stem.split("-")[0].lower()
        is_personal = "common" in stem.lower() or "personal" in stem.lower()
        # Some supplement files hold two answers back to back; they would pollute retrieval.
        if not is_personal and (words("\n\n".join(essay)) > 800 or sum(map(_is_prompt, essay)) > 0):
            continue
        yield {
            "source": "studynotes", "url": RAW.format(name=quote(name)), "tier": "admitted",
            "school": "" if is_personal else SCHOOLS.get(key, key.title()),
            "essay_type": "personal" if is_personal else "supplement",
            "title": stem.replace("-", " "), "prompt": prompt, "text": clean("\n\n".join(essay)),
        }
