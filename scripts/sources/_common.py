"""Shared scraping helpers: polite fetching, text cleanup, and the record schema."""

from __future__ import annotations

import hashlib
import re
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 GaryAdmitCorpus/0.1 (personal, non-commercial essay study)")

TIERS = {"exemplar", "admitted", "example", "weak", "before", "after"}
TYPES = {"personal", "supplement"}

# AdmitReport-style letter grades mapped onto GaryAdmit's 0-100 scale. The
# mapping is an assumption; bench uses grades only for rank order.
GRADE_LEVEL = {
    "A+": 90, "A": 86, "A-": 82, "B+": 76, "B": 72, "B-": 68, "C+": 62, "C": 58, "C-": 54,
    "D+": 48, "D": 44, "D-": 40, "F": 32,
}


class Fetcher:
    """GET with a per-host delay (at least robots.txt Crawl-delay), robots.txt check, retries, and an in-memory cache."""

    def __init__(self, delay: float = 1.0, timeout: int = 30):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                               "Accept-Language": "en-US,en;q=0.9"})
        self.delay, self.timeout = delay, timeout
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._cache: dict[str, str] = {}

    def allowed(self, url: str) -> bool:
        host = urlparse(url).scheme + "://" + urlparse(url).netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(host + "/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[host] = rp
            except requests.RequestException:
                self._robots[host] = None
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(UA, url)

    def __call__(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        rp = self._robots.get(urlparse(url).scheme + "://" + host)
        # Honor a site's Crawl-delay when it asks for more than our default (Hamilton asks for 5s).
        delay = max(self.delay, float((rp.crawl_delay(UA) if rp else None) or 0))
        wait = self._last.get(host, 0) + delay - time.time()
        if wait > 0:
            time.sleep(wait)
        err = None
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=self.timeout)
                self._last[host] = time.time()
                if r.status_code == 200:
                    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
                    self._cache[url] = r.text
                    return r.text
                err = f"HTTP {r.status_code}"
                if r.status_code in (403, 404, 410, 451):
                    break
            except requests.RequestException as e:
                err = str(e)
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"GET {url} failed: {err}")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def clean(text: str) -> str:
    """Normalize whitespace, keep paragraph breaks."""
    text = text.replace("\r", "").replace(" ", " ").replace("​", "").replace("\u00ad", "")
    paras = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paras if p)


def paras_text(elems) -> str:
    out = []
    for el in elems:
        t = el.get_text(" ", strip=True) if isinstance(el, Tag) else str(el).strip()
        if t:
            out.append(t)
    return clean("\n\n".join(out))


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’-]+", text))


def make_record(*, source: str, url: str, text: str, tier: str, title: str = "", school: str = "",
                year: str | int = "", essay_type: str = "personal", prompt: str = "",
                grade: str = "", commentary: str = "") -> dict:
    text = clean(text)
    assert tier in TIERS, tier
    assert essay_type in TYPES, essay_type
    assert url.startswith("http"), url
    norm = re.sub(r"\W+", " ", text.lower()).strip()
    rid = f"{source}-{hashlib.sha1(norm[:400].encode()).hexdigest()[:10]}"
    rec = {
        "id": rid, "source": source, "url": url, "title": clean(title)[:160], "school": school,
        "year": str(year or ""), "essay_type": essay_type, "prompt": clean(prompt)[:1000],
        "tier": tier, "text": text, "words": words(text),
    }
    if grade:
        rec["grade"] = grade
    if commentary:
        rec["commentary"] = clean(commentary)[:4000]
    return rec


def heading_run(start: Tag, stop_tags=("h1", "h2", "h3"), stop_text: str | None = None, keep=("p",)) -> list[Tag]:
    """Collect elements after `start` until a stop heading or an element matching stop_text."""
    out = []
    for el in start.find_all_next(True):
        if el.name in stop_tags:
            break
        if stop_text and re.search(stop_text, el.get_text(" ", strip=True) or "", re.I):
            break
        if el.name in keep and el.get_text(strip=True):
            # Skip nested duplicates (a <p> inside another collected <p>).
            if not any(el in o.descendants for o in out[-3:]):
                out.append(el)
    return out
