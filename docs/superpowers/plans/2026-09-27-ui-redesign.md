# Web UI redesign implementation plan

**Goal:** Replace `garyadmit/web/index.html` with the tabbed, calmer design in the spec, with every feature and every chat and rewrite behavior intact.

**Architecture:** One HTML file, vanilla JS, no build. CSS is rewritten from tokens up. The markup skeleton and the render templates change; the escaping helpers, job helpers, and chat and rewrite logic keep their code paths and every id and data attribute they touch.

**Tech stack:** HTML, CSS (OKLCH tokens, keyframe entrances, one view-transition crossfade on the theme toggle), vanilla JS, Literata from Google Fonts, the system UI font.

**Spec:** `docs/superpowers/specs/2026-09-27-ui-redesign-design.md`

**Execution:** inline by the author, chosen under the user's autonomous `/goal`. The file is a single unit whose parts share one stylesheet and one script, so parallel implementers would collide; reviewers fan out at the end instead.

Ruling: steps name exact interfaces and checks instead of carrying full code, because the executor is the author working in one file and the code would otherwise be written twice. Cost if wrong: a later reader of this plan sees the intent and checks, not the code, which is in git.

## Global constraints

- No em dashes in any user-visible string. No fonts from the skill's reflex-reject list. No side-stripe borders, no border paired with a wide soft shadow, no texture backgrounds, no bounce easing.
- Every id and data attribute in the spec's JS contract keeps its name. The ids looked up at load (`#essay`, `#limit`, `#wc`, `#wl`, `#typeSeg`, `#compose`, `#progress`, `#report`, `#newBtn`, `#go`, `#histBtn`, `#errBox`, `#corpusInfo`, `#prompt`, `#school`, `#fast`, `#history`) stay static.
- Essay text keeps `white-space: pre-wrap` everywhere it renders. `#draftView` and `#chatDraft` keep class `draft`.
- `prefers-reduced-motion: reduce` gets an instant or crossfade path for every animation.

## Review focus

1. Reopening a review while a chat request runs repaints the pending message on the fresh DOM and lands the turn in the fresh copy.
2. Pressing Undo, then "Use this version", then reloading restores the same working essay from localStorage.
3. A rewrite finishing while the student sits on another tab updates the Rewrite tab, moves the chat's starting essay only if the chat has not changed anything, and shows a toast.
4. A poll request failing once mid-review does not abort the review.
5. Keyboard-only use reaches every tab, category row, line-edit card, chat control, and the history drawer, with visible focus.

## Tasks

### Task 1: tokens, base, header, compose

- CSS: OKLCH tokens for both themes (`:root`, the dark media query guarded by `:root:not([data-theme="light"])`, and `:root[data-theme="dark"]`), type and space scales, radii, motion tokens, button and field components, focus rings, reduced-motion block.
- Markup: header with wordmark, corpus count, theme toggle, History, New essay; compose with labeled essay document, type segmented control, limit, prompt, school (supplement only), fast-mode switch, "Review essay" button, counter meter, restored-draft note, "Back to report" link.
- JS: `setTheme`, inline validation replacing `alert()`, Cmd or Ctrl plus Enter to submit, limit-change announcement, school visibility.
- Check: screenshots in both themes at 1280px; typing updates the count and meter; Supplement sets 250 and shows School; a 10-word submit shows the inline message and sends no request.

### Task 2: view switching and progress

- JS: `show(id)` restarts a CSS keyframe entrance on the view (ruling: the View Transitions API runs its callback asynchronously, so it was rejected for view switches); focus moves to the view heading; the step list appends new steps only (`syncSteps`); `pollJob` retries failed requests with backoff; a finished review renders only if the progress view is still showing, otherwise a toast offers it.
- Markup: progress panel with log, elapsed time, and indeterminate line (ruling: the report skeleton was dropped because a skeleton promises content within seconds and this job takes minutes).
- Check: with mocked `fetch`, a review job shows steps appearing one by one without flicker, survives one failed poll, and lands on the report; an error returns to compose with the message.

### Task 3: report shell, verdict, tabs

- `render(r)` emits the verdict header (score, band, description, committee line, ruler, scoring math disclosure) and the tab bar and five panels. `selectTab(name)` handles clicks, arrow keys, the sliding indicator, and the panel fade. Tabs show counts and job indicators (`setTabState(name, "busy" | "done" | "")`).
- Check: every saved-review fixture renders without console errors; arrow keys move between tabs; the score counts up once.

### Task 4: Feedback tab

- AI flag notice, top three fixes, category rows with a header button (`aria-expanded`) and animated reasons, readers' first impressions, problems and strengths, mechanical checks, and actions ("Make it a lot better" jumps to Rewrite, "Edit and re-score" loads the reviewed essay).
- Check: a row opens and closes from its button only; selecting text in the reasons does not collapse them.

### Task 5: Line edits tab

- Marked essay beside a sticky edit list; cards are keyboard operable; `activate` unchanged.
- Check: clicking a mark highlights and reveals its card; Enter on a focused card scrolls the essay to its mark.

### Task 6: Rewrite tab

- `betterIntro` and `revisionHtml` restyled with shorter copy and one status line; "Why these changes" becomes a disclosure with "How it was checked"; copy buttons flash and reset; a finished rewrite sets the tab indicator and toasts.
- Check: with a verified fixture, the Essay and Changes toggle swaps the view; with an unverified fixture the reasons show once; a mocked revise job runs and an error re-shows the intro with the message.

### Task 7: Ask for changes tab

- `chatHtml` restyled into document plus sticky chat panel; `paint` updates the pending message in place; thread scrolls to the newest message when the tab opens.
- Check: with the four-turn fixture and mocked chat jobs: send, pending steps, success, failure with the message restored, Undo, "Use this version anyway", "Show what changed" toggling, chips, Enter and Shift plus Enter, and the reopen-mid-request case.

### Task 8: Comparisons tab

- Calibration ladder, head-to-heads with flat result chips, calibration details, more similar essays; opponent essays in disclosures.
- Check: fixtures with and without calibration render; links are scheme-checked.

### Task 9: history drawer, toasts, theme toggle

- `<dialog id="history">` opened with `showModal`, loading and error states, rows as buttons marked current; `toast(message, action)`; theme toggle cycling auto, light, dark and saved in localStorage.
- Check: Escape and backdrop close the drawer and return focus to History; a failed history fetch shows an inline error.

### Task 10: responsive pass and final verification

- 390px layout for every view; the skill's detector at zero findings; `node --check`; `pytest`; screenshots of every view in both themes; reduced-motion pass.
- Final adversarial review by independent reviewers (JS regression against the old file, accessibility, visual and AI tells), each finding verified before fixing.
