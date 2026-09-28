# Make every change: one button for all the line edits, with made-up details marked

Date: 2026-09-27. Status: approved by the owner's standing /goal instruction (autonomous mode).

## What the user asked for

"Can u add a feature so that when i press a button it makes all the suggested changes. and then also add something so that if i do press that button, it adds a tab to the top bar and then i can see the changes. also make it so that u can generate quotes urself to make it more persoanlized"

Read as three requirements:

1. One button that makes every suggested change to the essay.
2. Pressing it adds a tab to the report's tab bar, where the student sees the changed essay and what changed.
3. Where a suggestion needs a detail only the student knows, GaryAdmit writes the quote or detail itself instead of leaving a bracketed question.

The suggested changes are the line edits: the cards on the Line edits tab, each tied to an exact passage. The top fixes, category notes, and problems are advice with no target passage, and the Rewrite tab already acts on those.

## Observable result

On a saved review with line edits, a "Make all N changes" button sits above the edit cards, and a matching button sits in the Feedback tab's actions. Pressing either one:

- adds a "Changes made" tab after "Line edits" and switches to it, with live progress, while the other tabs stay usable;
- one to three minutes later shows the essay with every change made, a Changes view against the original, the word count against the limit, and a list of every detail GaryAdmit made up, each saying what the student should put there instead;
- highlights each made-up detail in the essay so it cannot pass as the student's own;
- saves the result in the review's history file, so the tab is there when the review is reopened.

## Design

### Flow

```
saved review ─ edits located in the essay ─┬─ cuts and plain rewrites: applied as written, no model
                                            └─ notes and bracketed rewrites ─ editor writes the text ─ checks
                                                                   ▲                                      │
                                                                   └── one retry for unusable answers ◄───┘
   ─ splice every change into the essay ─ tidy the joins ─ invented-fact check marks anything undeclared
```

Two model calls in the common case (the editor, then the fact check), three when an answer needs the retry. A review whose edits are all cuts and plain rewrites makes only the fact-check call.

### Components

- `garyadmit/apply.py` (new) owns the pipeline: `apply_all(essay, edits, *, meta, model=None, max_rounds=2, progress=None) -> dict`, plus the pure helpers `splice` and `tidy` that the tests exercise directly.
- `garyadmit/rubric.py` gains `APPLY_SYSTEM`, `APPLY_SCHEMA` and `apply_prompt()`, next to the other prompts. `fence()` also neutralizes the new `draft` and `edit` tag names.
- `garyadmit/server.py`: `POST /api/apply`, a job like `/api/revise`. Body `{review_id}` loads the saved review and writes the result back under `"applied"`, replacing any earlier one, inside the same lock as the other write-backs. Body `{essay, edits, prompt, essay_type, word_limit, school}` runs without saving. The module docstring loses its stale Google Fonts sentence.
- `garyadmit/web/index.html`: the buttons, the conditional tab, its panel, and the job wiring.
- `README.md` and `docs/PRODUCT.md`: the new feature and the one place GaryAdmit makes things up on purpose.

### Which edits change the essay

Every saved edit has `original`, `kind` (cut, rewrite, comment), `problem`, `suggestion`, and the offsets `start` and `end` into the saved essay. In the 15 saved reviews all 281 offsets match their passage and none overlap. Each edit is located again before use: offsets that still match are kept, a mismatch falls back to `scoring.locate`, a passage that cannot be found is reported as not made, and an edit overlapping an earlier one is dropped. Saved reviews now carry a `partial` flag on every edit, true when the line editor's quote only partly matched the essay; a partial edit is reported as not made, since making it would leave the rest of the quote behind. For older reviews without the flag, an edit of six or more words whose passage stops mid-sentence is treated as partial when it is a cut, or when it is a rewrite whose suggestion ends a sentence. The server fills that flag in when it serves an older review, so the page counts the same edits the pipeline makes.

- A cut replaces its passage with nothing.
- A rewrite without square brackets goes in exactly as written. In the saved data these are clean replacement text (96 of 96 checked).
- A rewrite with brackets (85 of 181 saved rewrites) and every note with advice go to the editor, because their suggestions mix replacement text with instructions ("[name the singer or piece if you know it]", "Keep this line. After it, add the next scene: [...]"). Pasting those in would put instructions and questions into the essay.
- A note with empty advice changes nothing.

### The editor call

The editor sees the essay with the cuts and plain rewrites already made, joined by the same splice and tidy as the finished essay so its seams match what the student will read, and each open passage wrapped in `<edit id="N">...</edit>`, then a list of the open edits with their problem and instruction, the essay context, and a word budget: the limit minus the current count. For each id it returns `text`, the exact replacement for the marked passage, and `made_up`, a list of `{text, stands_for}` naming every detail it wrote that the essay does not state, copied exactly from its text, with what the student should put there instead.

The prompt tells it to carry out each instruction, to fill every bracket with a specific, ordinary, plausible detail consistent with the essay and with its other inventions, to keep the student's voice, to join the words before and after the passage, to stay within the budget, and to use no brackets, em dashes, stock AI words, or closing lesson.

Answers with ids that were not asked for are ignored. An answer is unusable when its id is missing, when its text still contains a square bracket the essay does not have, or when its text is empty, unless the instruction asks for the whole passage to be cut. Unusable ids get one retry that names the reason for each. An edit still unusable after the retry, or one whose retry call failed, is reported as not made, and its passage stays as the student wrote it. Em dashes in the editor's text become commas before splicing, and a `made_up` item that is not in its text is dropped.

### Splicing and tidying

Replacements are spliced into the essay by offset. Outside a passage, only the punctuation and capitalization at its joins can change: a cut sentence opener takes its comma with it, a cut that removes a sentence's end keeps the end mark, and a replacement that now starts a sentence is capitalized unless its first word has an inner capital. Each made-up detail's position is tracked through the splice. The tidy pass then repairs spacing next to the changes: it collapses runs of spaces, removes spaces before closing punctuation and at line ends, turns ", ." into "." and ",," into ",", and collapses three or more line breaks into a paragraph break, adjusting every tracked span as characters go.

### Marking what was made up

Every copy of a declared detail that the original essay does not contain, in any letter case, is marked, including one a retry or another edit reused without declaring it again. Then `revise.fidelity(essay, draft)` checks the whole new essay against the original, which catches details the editor did not declare and any facts the line editor's own rewrites added, since those were never fact-checked. Each flagged passage is marked with the checker's reason, by these rules:

- A span the declared marks already cover is dropped.
- A span that only partly covers declared marks absorbs them into one mark, whose `stands_for` joins theirs, so no undeclared word sits outside a mark.
- A quote that drifts at its end, so only its head is found, is extended to the end of the last change in its sentence. If the extended text is all in the original essay, the span is dropped.

If the check fails to run, the result keeps the declared marks and says the check did not run.

### Result

Saved as `applied` in the history file:

```
version, created, meta, essay, draft,
diff        diff_segments(essay, draft)
made_up     [{start, end, text, stands_for, why, edit, source: "editor" | "check"}]
edits       [{i, kind, original, status: "made" | "unchanged" | "not made", text, reason}]
counts      {made, unchanged, not_made}
checks      {word_count, over_limit, fact_check: {ran, error, voice_drift}}
usage, models {editor}
```

`i` indexes the review's `edits`, so the web page can pair each change with its card, and `original` is the passage it replaced. A made-up detail from the editor carries `stands_for`; one found by the fact check carries the checker's reason in `why`.

### The web page

- `TABS` gains `["applied", "Changes made"]` after Line edits. The tab and its panel render only when the review has `applied` or a job is running for it. Pressing a button inserts the tab and panel if missing, with a short entrance, and selects the tab.
- The buttons read "Make all N changes" (Line edits) and "Make all N line edits" (Feedback), where N counts the cuts, rewrites, and notes with advice. They are absent when that count is zero. While a job runs they read "See progress"; after a result exists, "See the changes made". Both then jump to the tab.
- A running job shows its steps in the panel, marks the tab busy, survives the student reopening the review, and ends with the same "Show me" toast as the Rewrite tab when the student is elsewhere.
- The finished panel has a heading, one status line with the counts, and, when anything was made up, a warning to replace each highlighted detail with what really happened or cut it. Below it: the essay with made-up details highlighted in amber, an Essay and Changes toggle, the word count (amber when over the limit), Copy, "Use in chat", and "Edit and re-score". Then "Check these details": each made-up detail with what it stands for, and clicking one highlights it in the essay. Then an "Edit by edit" disclosure pairing each passage with its new text or its status. Last, a note that Claude runs the check too and can miss a detail, and "Make the changes again", which replaces the result with a new one.
- Copy warns in its toast when made-up details remain. "Use in chat" makes this version the chat's working essay, so the student can type the real details there. The chat already treats details inherited from its starting essay as notes rather than failures.
- A failed first run leaves the tab with the error and a "Try again" button. A failed re-run keeps the earlier result and shows the error above it.
- The existing Essay and Changes handler is scoped to the Rewrite panel so the two toggles never act on each other.

## Rulings

Each ruling was made without the owner, under the autonomous goal. Cost if wrong follows each.

1. **Only line edits count as the suggested changes.** Top fixes and category notes have no target passage. Cost if wrong: a student expecting the top fixes applied uses the Rewrite tab, which acts on them.
2. **Notes are carried out, not skipped.** They are a fifth of all edits and mostly ask for a sentence or scene only the student can supply, which is exactly where requirement 3 applies. Cost if wrong: more new text than the student wanted; every such change is listed edit by edit and its inventions are marked.
3. **Made-up details happen only in this flow.** The Rewrite tab, the chat, and the line editor keep asking in brackets and keep their invented-fact failures. Cost if wrong: a student who wants the chat to write a quote still gets a question there; "Use in chat" is the path.
4. **No judge and no score.** The result claims only that the changes were made, never that the essay improved; "Edit and re-score" measures it. Cost if wrong: one more click to find out whether it helped.
5. **One saved result per review.** A new run replaces the old one, as a new rewrite does. Cost if wrong: the earlier made-up details are gone after a re-run.
6. **A fact check that fails to run does not discard the result.** The declared details are still marked and the panel says the check did not run. Cost if wrong: an undeclared invention could go unmarked on that run, and the panel says so.

## Testing

`tests/test_apply.py`, with the fake model:

- `splice` applies cuts and rewrites right to left and capitalizes after a cut that starts a sentence; `tidy` fixes spacing and punctuation and keeps tracked spans on the same characters.
- `apply_all` makes cuts and plain rewrites without the editor, sends bracketed rewrites and notes to it, marks declared details at the right offsets, and leaves no bracket in the draft.
- A bracketed answer is retried once and reported as not made if it fails again, with its passage left as written; a missing id gets the same retry.
- Undeclared details found by the fact check are marked with source "check"; a declared detail not in its text is dropped; em dashes become commas.
- A fact check that raises still returns the result with the error recorded; a review with no usable edits raises a plain error; a stale offset is found again or reported.
- The server job writes `applied` into the history file under the lock, runs without a review id when given the essay and edits, and refuses unknown review ids and cross-site posts.

The web page is checked in the in-app browser with `fetch` mocked: the buttons, the tab appearing and selected, progress, reopening mid-run, the finished panel in both themes at 1280px and 375px, the Essay and Changes toggle, the detail list, Copy, "Use in chat", errors, and keyboard use of the new tab.

## Out of scope

A CLI command, choosing which edits to make, marking made-up details inside the Changes view, and letting the student confirm a made-up detail as true so later checks treat it as a fact.
