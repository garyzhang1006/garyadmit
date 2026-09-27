"""Deterministic checks that need no model.

These run first and are handed to the reviewers as hard facts, so the model
cannot talk its way around a 780-word essay or eleven stock phrases. Every
hit carries character offsets so the UI can highlight it inline.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field, asdict

# Phrases admissions readers see constantly. Kept as regexes so inflections match.
CLICHES = [
    r"ever since I was (?:a )?(?:little|young|small|a kid|a child)",
    r"(?:for as long as|as long as) I can remember",
    r"growing up,",
    r"step(?:ped|ping)? (?:out(?:side)?|out of) (?:of )?my comfort zone",
    r"comfort zone",
    r"hard work (?:and dedication )?(?:pays|paid) off",
    r"make a (?:real |positive )?difference",
    r"(?:never|don'?t) give up",
    r"outside the box",
    r"(?:my|a) passion for",
    r"the rest is history",
    r"taught me (?:the (?:value|importance|meaning) of|that|how)",
    r"shaped (?:me into )?who I am(?: today)?",
    r"made me (?:the person )?who I am(?: today)?",
    r"(?:opened|open) my eyes",
    r"a whole new world",
    r"at the end of the day",
    r"in today'?s (?:society|world)",
    r"since the dawn of time",
    r"little did I know",
    r"I (?:have )?(?:realized|learned) that",
    r"(?:it|this) (?:was|is) (?:a|an) (?:life-changing|eye-opening|humbling) experience",
    r"(?:achieve|follow|chase) my dreams?",
    r"(?:the )?(?:importance|value) of (?:hard work|teamwork|perseverance|family)",
    r"(?:learned|learn) so much",
    r"better person",
    r"blood,? sweat,? and tears",
    r"every cloud has a silver lining",
    r"everything happens for a reason",
    r"(?:I|we) all have (?:a|our) story",
]

# Vocabulary that marks text as machine-generated or over-edited. Readers now
# screen for it, and it flattens voice even when a human wrote it.
AI_TELLS = [
    r"delv(?:e|es|ed|ing)", r"tapestr(?:y|ies)", r"testament to", r"multifaceted",
    r"intricate(?:ly)?", r"navigat(?:e|ed|ing) (?:the|my|a|through)", r"resonat(?:e|ed|es|ing)",
    r"profound(?:ly)?", r"pivotal", r"embark(?:ed|ing)?", r"(?:my|this|the) journey",
    r"foster(?:ed|ing)?", r"realm", r"beacon", r"unwavering", r"indelible",
    r"symphony of", r"kaleidoscope", r"a sense of (?:purpose|belonging|community)",
    r"I have come to (?:realize|understand|appreciate)", r"ignit(?:e|ed) (?:a|my) (?:passion|spark|fire)",
    r"(?:serves|served) as a (?:reminder|catalyst)", r"underscor(?:e|es|ed)", r"showcas(?:e|ed|ing)",
    r"vibrant", r"bustling", r"transformative", r"meticulous(?:ly)?",
]

THESAURUS = [
    r"plethora", r"myriad", r"utiliz(?:e|ed|ing)", r"commence(?:d)?", r"endeavou?r(?:s|ed)?",
    r"facilitat(?:e|ed|ing)", r"ameliorat(?:e|ed)", r"juxtaposition", r"quintessential(?:ly)?",
    r"paradigm", r"cognizant", r"erstwhile", r"perspicacious", r"loquacious", r"ubiquitous",
    r"aforementioned", r"henceforth", r"notwithstanding", r"indefatigable", r"sagacious",
]

INTENSIFIERS = r"\b(?:very|really|extremely|incredibly|truly|absolutely|totally|completely|definitely|so much)\b"
TOLD_EMOTION = (
    r"\bI (?:felt|feel|was|became|grew) (?:so |very |really |extremely |incredibly )?"
    r"(?:happy|sad|proud|nervous|anxious|excited|scared|afraid|angry|frustrated|overwhelmed|"
    r"grateful|thankful|inspired|motivated|determined|devastated|heartbroken|confident|joyful|"
    r"relieved|embarrassed|lonely|hopeless|elated|ecstatic)\b"
)
PASSIVE = r"\b(?:am|is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(?:\w+ed|built|done|given|made|shown|taken|taught|told|written|known|seen|found|chosen|driven|broken)\b"
RESUME_WORDS = (
    r"\b(?:president|vice[- ]president|captain|founder|founded|award(?:s|ed)?|won|gpa|"
    r"valedictorian|salutatorian|varsity|national merit|honor roll|ap scholar|"
    r"first place|state champion(?:ship)?|olympiad|finalist|semifinalist)\b"
)
MORAL_ENDING = r"\b(?:taught me|I learned|I realized|I now know|I understand now|made me realize|I discovered that)\b"


@dataclass
class Hit:
    rule: str
    severity: str  # "major" | "minor" | "info"
    message: str
    spans: list[tuple[int, int]] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


def _find(pattern: str, text: str, flags=re.IGNORECASE) -> list[re.Match]:
    return list(re.finditer(pattern, text, flags))


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z\"'(\[])", text.strip())
    return [p for p in parts if re.search(r"[A-Za-z]", p)]


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’-]+", text))


def _syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups)
    if word.endswith("e") and n > 1 and not word.endswith(("le", "ee")):
        n -= 1
    return max(1, n)


def _pattern_hits(text: str, patterns: list[str]) -> list[re.Match]:
    hits: list[re.Match] = []
    for p in patterns:
        hits.extend(_find(r"\b" + p + r"\b", text))
    hits.sort(key=lambda m: m.start())
    # Drop overlaps so "comfort zone" is not double-counted inside a longer match.
    kept: list[re.Match] = []
    for m in hits:
        if kept and m.start() < kept[-1].end():
            continue
        kept.append(m)
    return kept


def lint(text: str, word_limit: int | None = 650, word_min: int | None = None) -> dict:
    text = text.replace("\r\n", "\n")
    hits: list[Hit] = []
    wc = word_count(text)
    sents = _sentences(text)
    paras = [p for p in re.split(r"\n\s*\n|\n(?=\s*\S)", text) if p.strip()]
    sent_lens = [word_count(s) for s in sents] or [0]

    if word_limit and wc > word_limit:
        hits.append(Hit("over_limit", "major",
                        f"{wc} words, {wc - word_limit} over the {word_limit}-word limit. The application portal will not accept it."))
    elif word_limit and wc < 0.6 * word_limit and word_limit >= 250:
        hits.append(Hit("underused_space", "minor",
                        f"{wc} words out of {word_limit}. Using under 60% of the space usually means the story is underdeveloped."))
    if word_min and wc < word_min:
        hits.append(Hit("under_min", "major", f"{wc} words, below the {word_min}-word minimum."))

    first = sents[0] if sents else ""
    if re.match(r"^\s*[\"“]", text.strip()) and re.search(r"[\"”]\s*(?:-|—|–)\s*[A-Z]", text[:400]):
        hits.append(Hit("quote_opener", "major", "Opens with a famous quotation. Readers skip these; the first line should be yours.", [(0, len(first))]))
    if re.search(r"\b(?:dictionary|merriam|webster|oxford english)\b.*\bdefine", first, re.I) or re.search(r"\bis defined as\b", first, re.I):
        hits.append(Hit("definition_opener", "major", "Opens with a dictionary definition, one of the most cited cliché openers.", [(0, len(first))]))
    if first.strip().endswith("?"):
        hits.append(Hit("question_opener", "minor", "Opens with a rhetorical question, which usually reads as a stalling device.", [(0, len(first))]))
    if re.match(r"^\s*(?:imagine|picture this|have you ever)\b", first, re.I):
        hits.append(Hit("imagine_opener", "minor", "Opens by addressing the reader (\"Imagine...\"), a stock hook.", [(0, len(first))]))

    for rule, patterns, sev, label in [
        ("cliche", CLICHES, "major", "stock phrase"),
        ("ai_tell", AI_TELLS, "major", "AI-sounding or over-edited word"),
        ("thesaurus", THESAURUS, "minor", "thesaurus word"),
    ]:
        ms = _pattern_hits(text, patterns)
        if ms:
            sev_eff = sev if len(ms) >= 2 or sev == "minor" else "minor"
            hits.append(Hit(rule, sev_eff, f"{len(ms)} {label}{'s' if len(ms) != 1 else ''}.",
                            [(m.start(), m.end()) for m in ms], sorted({m.group(0).lower() for m in ms})[:12]))

    ms = _find(INTENSIFIERS, text)
    if len(ms) >= 4:
        hits.append(Hit("intensifiers", "minor", f"{len(ms)} intensifiers (very, really, truly...). They weaken rather than strengthen.",
                        [(m.start(), m.end()) for m in ms], sorted({m.group(0).lower() for m in ms})))
    ms = _find(TOLD_EMOTION, text)
    if len(ms) >= 2:
        hits.append(Hit("told_emotion", "major" if len(ms) >= 4 else "minor",
                        f"{len(ms)} places name an emotion (\"I felt proud\") instead of showing it.",
                        [(m.start(), m.end()) for m in ms], [m.group(0) for m in ms][:8]))
    ms = _find(PASSIVE, text)
    if sents and len(ms) / max(1, len(sents)) > 0.2:
        hits.append(Hit("passive", "minor", f"{len(ms)} passive constructions across {len(sents)} sentences.",
                        [(m.start(), m.end()) for m in ms], [m.group(0) for m in ms][:8]))
    ms = _find(RESUME_WORDS, text)
    if len(ms) >= 4:
        hits.append(Hit("resume_in_prose", "major",
                        f"{len(ms)} titles/awards ({', '.join(sorted({m.group(0).lower() for m in ms})[:6])}). The activities list already covers these; the essay should not.",
                        [(m.start(), m.end()) for m in ms]))

    em = text.count("—") + len(re.findall(r"(?<=\w) -- (?=\w)", text))
    if wc and em / wc * 100 > 1.0:
        hits.append(Hit("em_dash", "minor", f"{em} em dashes ({em / wc * 100:.1f} per 100 words), a common marker of AI-polished prose."))

    if len(sents) >= 8:
        starts = [re.findall(r"[A-Za-z']+", s)[:1] for s in sents]
        i_starts = sum(1 for s in starts if s and s[0].lower() == "i")
        if i_starts / len(sents) > 0.4:
            hits.append(Hit("i_starts", "minor", f"{i_starts} of {len(sents)} sentences start with \"I\"; the rhythm gets monotonous."))
        sd = statistics.pstdev(sent_lens)
        if sd < 4.5:
            hits.append(Hit("flat_rhythm", "minor", f"Sentence lengths barely vary (std dev {sd:.1f} words). Mix short and long sentences."))
    long_sents = [s for s in sents if word_count(s) > 45]
    if long_sents:
        spans = []
        for s in long_sents:
            i = text.find(s[:60])
            if i >= 0:
                spans.append((i, i + len(s)))
        hits.append(Hit("long_sentence", "minor", f"{len(long_sents)} sentence(s) over 45 words.", spans))

    if paras:
        last = paras[-1]
        ms = _find(MORAL_ENDING, last)
        if ms:
            off = text.rfind(last)
            hits.append(Hit("moral_ending", "minor",
                            "The last paragraph states the lesson outright (\"I learned...\"). A tied-bow moral is the most common way strong essays go flat.",
                            [(off + m.start(), off + m.end()) for m in ms]))
    if len(paras) == 1 and wc > 250:
        hits.append(Hit("one_paragraph", "minor", "The whole essay is one paragraph."))

    words = re.findall(r"[A-Za-z]+", text)
    syl = sum(_syllables(w) for w in words)
    fk = 0.39 * (len(words) / max(1, len(sents))) + 11.8 * (syl / max(1, len(words))) - 15.59 if words else 0.0

    sev_rank = {"major": 0, "minor": 1, "info": 2}
    hits.sort(key=lambda h: sev_rank[h.severity])
    return {
        "word_count": wc,
        "word_limit": word_limit,
        "sentences": len(sents),
        "paragraphs": len(paras),
        "avg_sentence_words": round(statistics.mean(sent_lens), 1),
        "sentence_length_sd": round(statistics.pstdev(sent_lens), 1),
        "reading_grade": round(fk, 1),
        "hits": [asdict(h) for h in hits],
    }


def summarize_for_prompt(report: dict) -> str:
    lines = [
        f"Word count: {report['word_count']}" + (f" (limit {report['word_limit']})" if report.get("word_limit") else ""),
        f"Sentences: {report['sentences']}, paragraphs: {report['paragraphs']}, "
        f"avg sentence {report['avg_sentence_words']} words (sd {report['sentence_length_sd']})",
    ]
    for h in report["hits"]:
        ex = f" Examples: {', '.join(h['examples'][:6])}." if h.get("examples") else ""
        lines.append(f"- [{h['severity']}] {h['message']}{ex}")
    if not report["hits"]:
        lines.append("- No mechanical red flags found.")
    return "\n".join(lines)
