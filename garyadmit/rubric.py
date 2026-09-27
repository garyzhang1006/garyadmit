"""Rubric, calibration text, prompts, and JSON schemas for every model call.

The six MaxAdmit categories (hook, voice, flow, conciseness, authenticity,
uniqueness) plus insight, which admissions readers weigh most and MaxAdmit's
list leaves out.
"""

from __future__ import annotations

CATEGORIES = ["hook", "voice", "flow", "conciseness", "authenticity", "uniqueness", "insight"]

# What a reader learns about the applicant, and whether it is distinctive and
# genuine, decides essays at selective schools; sentence craft matters less.
WEIGHTS = {
    "insight": 0.20,
    "uniqueness": 0.17,
    "authenticity": 0.17,
    "voice": 0.16,
    "hook": 0.10,
    "flow": 0.10,
    "conciseness": 0.10,
}

CATEGORY_GUIDE = {
    "hook": "Do the first two or three sentences make a tired reader want to keep going, through a specific image, tension, or voice? A generic scene-setter, quote, definition, or rhetorical question is a 3-4.",
    "voice": "Does it sound like one particular 17-year-old talking, with their own diction, humor, and way of noticing things? Polished-but-anonymous prose is a 5 at best.",
    "flow": "Does the structure carry the reader, with each paragraph earning the next and transitions that feel inevitable? Is the ending earned instead of tacked on?",
    "conciseness": "Is every sentence doing work? Penalize throat-clearing, repeated points, filler, stacked adjectives, and word-count padding. Over the word limit caps this at 3.",
    "authenticity": "Does it feel true and unperformed, free of inflated stakes, borrowed wisdom, thesaurus words, or signs of AI generation or adult editing?",
    "uniqueness": "Could only this applicant have written it? Common topics (sports injury, mission trip, grandparent death, immigrant parents, winning the game, the debate round) must be told from an angle no one else would take to score above 6.",
    "insight": "What does the reader learn about how this person thinks, what they value, and how they have changed? Reflection must be specific and earned; a stated moral ('I learned perseverance') is a 3-4.",
}

ANCHORS = """Score each category from 1 to 10 using these anchors. The anchors describe where the essay would sit in the stack of essays submitted to a college that admits under 10% of applicants.
10 = best essay in a reading season. Essentially never given.
9 = top 2%. Belongs next to the essays colleges publish as "Essays That Worked".
8 = top 10%. Clearly strong; the reader would quote a line from it in committee.
7 = top 25%. Good, with real moments, but something holds it back from standing out.
6 = slightly above the median. Competent and pleasant, and the reader will not remember it tomorrow.
5 = the median applicant essay. Clear, correct, and forgettable. This is the most common score.
4 = below median. Generic, clichéd, or underdeveloped in ways a reader notices.
3 = weak. The problems dominate the reading.
1-2 = actively hurts the application."""

CALIBRATION = """Calibration rules. These outrank any instinct to encourage the writer.
- Your scores are audited against experienced admissions readers' ratings of the same essays. Inflation is the most common error and counts as a miss exactly like harshness does.
- Most essays you will ever see score 4 to 6. Do not drift toward 7 and 8 because the writing is grammatical and earnest; that is the floor, not an achievement.
- A serious, painful, or impressive topic earns nothing by itself. Grade what the writing does with it.
- Polish without a distinct person behind it is a 5 at most for voice, authenticity, and uniqueness.
- If the essay reads as AI-generated or heavily adult-edited (abstract vocabulary like tapestry, journey, testament, delve; symmetrical paragraphs; a tidy moral; no specific, odd, lived detail), score authenticity and voice at 4 or below and say so plainly.
- Never sandwich criticism between compliments. Only praise what you can quote, and never use words like compelling, powerful, vivid, beautiful, or impressive without quoting the exact line that earns them.
- Quotes must be copied exactly, character for character, from the essay. Do not paraphrase inside quote fields.
- Judge the essay in front of you. Do not reward what the applicant could write, and do not guess at an admissions decision.
- Length earns nothing. A shorter essay that says more beats a longer one that pads."""


def reviewer_system(persona: str) -> str:
    return f"""{persona}

{CALIBRATION}

{ANCHORS}

Category definitions:
""" + "\n".join(f"- {c}: {CATEGORY_GUIDE[c]}" for c in CATEGORIES) + """

Process:
1. Read the essay once the way an admissions officer does, then write what you actually remember and what you would say about this applicant in committee.
2. List every significant weakness, each tied to an exact quote.
3. List strengths only where you can quote the line that proves them. It is fine to list few or none.
4. For each category, pick the anchor that fits, give the integer score, and justify it with an exact quote.
5. Give the three changes that would raise the score the most, ordered by impact."""


PERSONA_AO = """You are a senior admissions officer at a highly selective US university, reading this essay as part of a file in the middle of reading season. You spend about four minutes on an essay. You care about one question: after reading, do I know someone specific, and do I want them on campus? You have read tens of thousands of essays and have no patience for performance, cliché, or résumé recitation."""

PERSONA_EDITOR = """You are a former Ivy League admissions reader who now trains new readers to score essays consistently. You read at the level of structure, paragraph, and sentence: what each part is doing, where the essay loses the reader, which details are specific and which are generic. New readers are told to copy your scores because they match committee outcomes, not because they are generous."""


def reviewer_prompt(essay: str, meta: dict, lint_summary: str) -> str:
    # Framed as an anonymous file from the pool: models give kinder feedback
    # when they believe the reader wrote the text (Sharma et al. 2023).
    ctx = ["An essay from this year's applicant pool, pulled for a calibration read.",
           "Essay type: personal statement" if meta.get("essay_type", "personal") == "personal" else "Essay type: supplemental essay"]
    if meta.get("prompt"):
        ctx.append(f"Prompt: {meta['prompt']}")
    if meta.get("school"):
        ctx.append(f"Target school: {meta['school']}")
    if meta.get("word_limit"):
        ctx.append(f"Word limit: {meta['word_limit']}")
    if meta.get("essay_type") == "supplement":
        ctx.append("For a supplement, also judge whether it answers the prompt directly and, for 'why us' prompts, whether the details could only apply to this school. A 'why us' essay that could be pasted into another school's application scores 4 or below on uniqueness.")
    return "\n".join(ctx) + f"""

Mechanical checks already run on the essay (these are facts, not opinions):
{lint_summary}

<essay>
{essay}
</essay>"""


_QUOTE = {"type": "string", "description": "Exact text copied from the essay"}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "first_impression": {"type": "string", "description": "What a reader remembers after one read, in 2-3 blunt sentences"},
        "committee_line": {"type": "string", "description": "The one sentence you would say about this applicant in committee"},
        "weaknesses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string"},
                    "quote": _QUOTE,
                    "why_it_matters": {"type": "string"},
                    "severity": {"type": "string", "enum": ["major", "minor"]},
                },
                "required": ["issue", "quote", "why_it_matters", "severity"],
            },
        },
        "strengths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"what": {"type": "string"}, "quote": _QUOTE},
                "required": ["what", "quote"],
            },
        },
        "scores": {
            "type": "object",
            "properties": {
                c: {
                    "type": "object",
                    "properties": {
                        "score": {"type": "integer", "minimum": 1, "maximum": 10},
                        "justification": {"type": "string"},
                        "quote": _QUOTE,
                        "to_raise": {"type": "string", "description": "The specific change that would add a point"},
                    },
                    "required": ["score", "justification", "quote", "to_raise"],
                }
                for c in CATEGORIES
            },
            "required": CATEGORIES,
        },
        "ai_suspicion": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": ["none", "low", "medium", "high"]},
                "evidence": {"type": "string"},
            },
            "required": ["level", "evidence"],
        },
        "top_fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fix": {"type": "string"}, "why": {"type": "string"}},
                "required": ["fix", "why"],
            },
        },
    },
    "required": ["first_impression", "committee_line", "weaknesses", "strengths", "scores", "ai_suspicion", "top_fixes"],
}


EDITOR_SYSTEM = """You are a line editor for college application essays, trained as an admissions reader. You give the student line-by-line edits the way a demanding human editor marks up a draft: exact phrases to cut, sentences to rewrite, and margin comments. You do not praise. You do not rewrite the essay in your own voice; rewrites keep the student's voice and facts and never invent events or details, and where a rewrite needs a detail only the student knows, write the suggestion as an instruction in brackets, e.g. [name the song your dad hummed].

Rules:
- "original" must be copied exactly, character for character, from the essay: a phrase or one sentence, never more than two sentences.
- Prioritize edits by how much they would change a reader's impression. Cuts of filler and clichés, vague abstractions that need a concrete detail, told emotions, and a moralizing ending come first; commas come last.
- Give 10 to 25 edits. Skip anything trivial."""

EDITS_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": _QUOTE,
                    "kind": {"type": "string", "enum": ["cut", "rewrite", "comment"]},
                    "problem": {"type": "string"},
                    "suggestion": {"type": "string", "description": "Replacement text for rewrite, empty for cut, advice for comment"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "severity": {"type": "string", "enum": ["major", "minor"]},
                },
                "required": ["original", "kind", "problem", "suggestion", "category", "severity"],
            },
        },
        "paragraph_notes": {
            "type": "array",
            "description": "One note per paragraph on what it does and what it should do",
            "items": {
                "type": "object",
                "properties": {"paragraph": {"type": "integer"}, "note": {"type": "string"}},
                "required": ["paragraph", "note"],
            },
        },
    },
    "required": ["edits", "paragraph_notes"],
}


def edits_prompt(essay: str, meta: dict) -> str:
    extra = f"Prompt: {meta['prompt']}\n" if meta.get("prompt") else ""
    return f"{extra}Word limit: {meta.get('word_limit') or 'none'}\n\n<essay>\n{essay}\n</essay>"


PROFILE_SYSTEM = """You index college application essays for similarity search. Describe the essay's topic, themes, and structure precisely and plainly, and produce search keywords that would match other essays about the same subject matter (concrete nouns, activities, places, relationships, identities, objects), not generic words like growth or challenge."""

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "One plain sentence: what the essay is about"},
        "topic": {"type": "string"},
        "themes": {"type": "array", "items": {"type": "string"}},
        "structure": {"type": "string", "description": "e.g. single narrative, montage, object-centered, reflective argument, why-us list"},
        "keywords": {"type": "array", "items": {"type": "string"}, "description": "12-25 concrete search terms"},
    },
    "required": ["summary", "topic", "themes", "structure", "keywords"],
}

RERANK_SYSTEM = """You match a student's college essay to the most similar published college essays. Similar means the same kind of subject matter (the same activity, relationship, identity, object, or experience) first, then a similar theme or structure. Do not pick an essay because it is good; pick it because a student writing this essay would learn the most from reading it side by side. Only choose ids from the candidate list."""

RERANK_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "why_similar": {"type": "string", "description": "One sentence naming the concrete overlap"},
                },
                "required": ["id", "why_similar"],
            },
        }
    },
    "required": ["matches"],
}

COMPARE_SYSTEM = """You are an admissions officer at a university that admits under 10% of applicants. You will read two application essays by two different students and decide which one makes the stronger case for its writer, the way you would if both were in front of you in committee.

Rules:
- Judge only the text. If you think you recognize an essay, ignore that.
- Do not prefer an essay for being longer, more polished-sounding, or about a more dramatic or impressive topic. Prefer the essay that shows you a specific person more clearly and more memorably.
- You must pick a winner. If they are close, say so through the confidence field.
- Quotes must be copied exactly from the essay they come from."""

COMPARE_SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["1", "2"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "category_winners": {
            "type": "object",
            "properties": {c: {"type": "string", "enum": ["1", "2", "tie"]} for c in CATEGORIES},
            "required": CATEGORIES,
        },
        "decisive_difference": {"type": "string", "description": "The main reason the winner wins, specific to these two essays"},
        "lesson_for_weaker": {"type": "string", "description": "One concrete thing the weaker essay's writer should take from the stronger essay"},
        "stronger_quote": {"type": "string", "description": "A line from the winning essay that shows the difference, copied exactly"},
    },
    "required": ["winner", "confidence", "category_winners", "decisive_difference", "lesson_for_weaker", "stronger_quote"],
}


def compare_prompt(essay_1: str, essay_2: str, meta: dict) -> str:
    extra = f"Both students were answering a prompt like: {meta['prompt']}\n\n" if meta.get("prompt") else ""
    return f"{extra}<essay_1>\n{essay_1}\n</essay_1>\n\n<essay_2>\n{essay_2}\n</essay_2>"


ADJUDICATE_SYSTEM = """You are the senior reader who settles disagreements between two admissions readers about a college essay. You get the essay and both readers' scores and reasons for the categories where they disagree by three or more points. Decide each category yourself from the essay, using the same anchors they used. Do not split the difference by default; side with the reading the text supports."""


def adjudicator_system() -> str:
    return f"{ADJUDICATE_SYSTEM}\n\n{CALIBRATION}\n\n{ANCHORS}\n\nCategory definitions:\n" + "\n".join(
        f"- {c}: {CATEGORY_GUIDE[c]}" for c in CATEGORIES)


def adjudicate_schema(cats: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            c: {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "reason": {"type": "string"},
                },
                "required": ["score", "reason"],
            }
            for c in cats
        },
        "required": cats,
    }


def band(score: float) -> tuple[str, str]:
    """Plain-language meaning of an overall score, tied to the anchors above."""
    if score >= 93:
        return "Best in the pile", "Would stand out even among essays colleges publish as models."
    if score >= 85:
        return "Exemplar level", "Comparable to published 'Essays That Worked'. Top few percent."
    if score >= 75:
        return "Strong", "Clearly above most applicants; competitive at highly selective schools."
    if score >= 65:
        return "Above average", "Better than the typical essay, but it will not stand out at top-20 schools yet."
    if score >= 50:
        return "Typical", "Reads like many applicants' essays. It will not hurt you, and it will not help much."
    if score >= 35:
        return "Weak", "Generic or underdeveloped in ways readers notice. Likely a drag on the application."
    return "Hurts the application", "Needs a rethink, not a polish."
