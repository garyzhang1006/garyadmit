"""Essays That Worked Corpus (langdonholmes/essays-that-worked-corpus): older admissions-office
essays (JHU, Tufts, Hamilton, Connecticut College) and counselor-site examples, as TEI XML."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ._common import paras_text

FILES = {
    "edu.xml": "exemplar",
    "com.xml": "example",
}
RAW = "https://raw.githubusercontent.com/langdonholmes/essays-that-worked-corpus/main/{name}"
BLOB = "https://github.com/langdonholmes/essays-that-worked-corpus/blob/main/{name}"
HOSTS = {"jhu.edu": "Johns Hopkins", "tufts.edu": "Tufts", "hamilton.edu": "Hamilton", "conncoll.edu": "Connecticut College"}


def scrape(fetch, limit=None):
    n = 0
    for name, tier in FILES.items():
        try:
            xml = BeautifulSoup(fetch(RAW.format(name=name)), "xml")
        except (RuntimeError, PermissionError):
            continue
        for tei in xml.find_all("TEI"):
            ref = tei.find("ref")
            target = str(ref.get("target") or "") if ref else ""
            url = target if target.startswith("http") and "XXX" not in target else BLOB.format(name=name)
            school = next((v for k, v in HOSTS.items() if k in target), "")
            for text_el in tei.find_all("text"):
                body = text_el.find("body", recursive=False)
                if body is None:
                    continue
                if limit is not None and n >= limit:
                    return
                # Admissions commentary sits in <note> inside the body.
                ps = [q for q in body.find_all("p") if q.find_parent("note") is None]
                notes = [q for q in body.find_all("p") if q.find_parent("note") is not None]
                essay = paras_text(ps)
                if len(essay.split()) < 100:
                    continue
                title_el = text_el.find("titlePart")
                n += 1
                yield {
                    "source": "etwc", "url": url, "tier": tier if school or tier == "example" else "example",
                    "school": school, "essay_type": "personal",
                    "title": re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) if title_el else "", "text": essay,
                    "commentary": paras_text(notes),
                }
