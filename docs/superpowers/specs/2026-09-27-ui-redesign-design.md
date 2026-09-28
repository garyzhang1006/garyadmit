# Web UI redesign

Status: self-approved on 2026-09-27. The user set a `/goal` ("make the ui/ux a lot better and more smooth and less ai generated, make it more aesthetic too") and asked for no pauses, so each brainstorming gate was approved by the author and recorded here. Product context lives in `docs/PRODUCT.md`.

## What the user asked for, and what I assumed

Said: better UI and UX, smoother, less AI-generated, more aesthetic.

Assumed:

- Every feature stays: compose form, progress, the full report, the rewrite, the chat, history. Nothing is removed, only reorganized and restyled.
- The app stays one `index.html` with vanilla JS, served by the stdlib server, with no build step and no new runtime dependency.
- The chat and rewrite logic (working-essay versions, replay, localStorage, Undo, Use this version) was reviewed hard earlier today and must behave exactly as before.
- The user's Mac runs in dark mode, so dark is the primary theme, with light mode kept at the same quality.

Classification: architectural, the heavier path. The change is one file, but it restructures how every screen fits together.

## Why the current UI reads as AI-made

The design skill's detector flags 7 patterns in the current file: five colored side-stripe borders, Fraunces, and a bounce easing on the stamp. Beyond the detector, the whole look sits in the saturated "editorial-typographic" lane: Fraunces and Newsreader with uppercase letter-spaced IBM Plex Mono labels, a dotted cream paper background, a rotated rubber stamp, and hard offset shadows on red buttons. All three fonts are on the skill's reflex-reject list.

The UX problems are bigger than the styling. The report is one 11,400px scroll with about fifteen boxed panels of equal weight, three copies of the essay, and two long explanatory paragraphs before the student reaches the scores. The history list is an absolutely positioned box, errors use `alert()`, copy buttons never reset, and every view change is an instant `display` swap.

## Approaches considered

1. Reskin only: swap fonts, colors, and shadows and keep the layout. Low risk, but the 11,400px report and the duplicated essays stay, so the UX barely improves.
2. Restructure into a tabbed workspace with a compact verdict header, a history drawer, toasts, and purposeful motion, keeping all JS logic. Medium risk and the largest gain. **Picked.**
3. Rebuild as a framework app (React and Vite). Breaks the no-build architecture and multiplies the blast radius for no user-visible gain over option 2.

Pre-mortem for option 2:

- The chat or rewrite breaks because markup moved. Mitigation: keep every id and data attribute the script uses, keep the logic functions untouched, and run browser checks with mocked `fetch` for review, revise, and chat jobs, including errors and a reopened review mid-request.
- The new look still reads generic, for example an Apple Books clone or a SaaS dashboard. Mitigation: the bans list below, the skill's detector at zero hits, and screenshot review of every screen in both themes before calling it done.

## Visual system

**Typography.** One family, Times New Roman, for every text style, at the user's request after the first build (which split Literata for the student's words from the system sans for the interface). It is installed on macOS, iOS and Windows, with Tinos and Liberation Serif as metric twins on ChromeOS and Linux, so the page downloads no fonts. Hierarchy comes from size, weight, and color. No monospace font. Fixed rem scale: 14, 15, 17, 19, 22, 28px, about 1px above a sans scale because Times has a small x-height, with the essay at 20px and line-height 1.7 (1.75 on dark), and the score numeral at 72px. Line length for prose is capped near 68ch. Sentence case everywhere, including the result chips (Win, Loss, Split); nothing is set in uppercase.

**Color.** Restrained strategy in OKLCH. Neutrals carry a faint tint toward the brand hue (29). Dark theme: page L 0.17, surface L 0.205, raised L 0.245, text L 0.93, muted text L 0.74. Light theme: page is a near-white at L 0.985 (not cream), surfaces are white, text L 0.22, muted text L 0.50. Primary buttons are solid ink. One interaction accent, a blue, marks selection, focus, links, and the bracketed questions that need the student's input. The brand vermilion appears only in the wordmark. Semantic hues: red for cuts, losses, major severity, and errors; green for wins, strengths, verified, and insertions; amber for splits, minor severity, not verified, and mechanical flags; a soft highlighter tint for line-edit marks. Every text color passes 4.5:1 on its background in both themes.

**Shape and depth.** 4px spacing scale (4, 8, 12, 16, 24, 32, 48, 64). Radii of 6px on controls, 10px on panels, full pills on chips. Document surfaces (the essay, the edit cards, the chat panel) are a lighter tone with a 1px hairline, because a white surface on the near-white light page has too little edge without one; hairlines also separate list items. Shadows are limited to overlays (toasts, the phone edit sheet) and the segmented-control thumb, none wider than 8px blur; the history drawer has none and dims the page instead. No side-stripe borders, no border paired with a wide soft shadow, no texture.

## Layout and information architecture

**Header.** Sticky and opaque, 56px: the wordmark (bold Times New Roman, "Admit" in the brand vermilion), then the corpus count, a theme toggle (auto, light, dark), History, and New essay. An earlier draft carried the tagline; it was dropped because its slogan cadence read as generated, and the corpus count is the factual line.

**Compose.** The essay field is a document surface that grows with its content. A settings column holds the essay type as a segmented control, the word limit, the prompt, a school field that appears only for supplements, and fast mode as a switch. The primary button reads "Review essay" and also fires on Cmd or Ctrl plus Enter. A word counter with a thin meter turns amber near the limit and red over it. A too-short essay gets an inline message instead of `alert()`.

**Progress.** A calm panel with the step log, elapsed time against the usual one to three minutes, an indeterminate progress line, and a "Keep editing while it runs" button; a toast brings the student back when the review lands. (An earlier draft put a report skeleton under the panel. It was dropped because a skeleton promises content within seconds, and this job takes minutes; the step log is the honest indicator.)

**Report.** A verdict header, then five tabs:

- The verdict header shows the score numeral, the band title and description, the committee line, and a ruler from 0 to 100 marked with the real band thresholds from `rubric.band` (35, 50, 65, 75, 85, 93) and a marker at the score. The scoring math sits one disclosure away.
- **Feedback** (default): the AI flag if any, the top three fixes as a numbered list, the seven category scores with both readers and expandable reasons, what each reader remembers, biggest problems and what works side by side, and the mechanical checks.
- **Line edits**: the marked-up essay with the edit list in a sticky margin column, linked both ways as today.
- **Rewrite**: the "Make it a lot better" flow (the Feedback button of that name opens this tab, and the tab's own button of that name starts the job, so the README's wording holds) and its result (status, the edited essay with an Essay and Changes toggle, the bracket questions, and "Why these changes").
- **Ask for changes**: the working essay beside a sticky chat panel with thread, suggestion chips, and composer.
- **Comparisons**: a ladder of the calibration essays sorted by level with a rung for your score, each rung carrying its verdict and reasoning, then head-to-heads and more similar essays.

Tabs show counts where useful (line edits, chat turns, comparisons). A tab whose job is running shows a small spinner, and when that job finishes while the student is elsewhere, the tab gets a dot and a toast offers to open it. The tab bar sticks under the header while scrolling.

**History.** A native `<dialog>` drawer from the right with focus trapping and Escape to close, listing score, first line, date, and band.

**Toasts.** One polite live region at the bottom for copy results, finished jobs, and non-blocking errors, plus a second one inside the history drawer, because the modal drawer makes the rest of the page inert. Copy buttons reset their label after 1.6 seconds.

## Motion

Product register: 150 to 250ms on most transitions, exponential ease-out (`cubic-bezier(0.22, 1, 0.36, 1)`), no bounce. Motion only conveys state:

- View changes between compose, progress, and report fade up over 250ms with a CSS keyframe. The View Transitions API was rejected for this because its update callback runs asynchronously, and the code that follows a view switch reads the new state immediately. The theme toggle alone uses a view-transition crossfade, since nothing reads state after it.
- Tab changes slide the tab indicator and fade the incoming panel in over 180ms.
- The score counts up and the ruler marker slides to it over 700ms when a report first renders; category bars grow in with a 40ms stagger.
- Category reasons open with a `grid-template-rows` transition. Other disclosures ("Why these changes", opponents' essays, the scoring math) fade their content in over 200ms; a height transition was dropped because it animates layout.
- Chat messages rise 6px and fade in; the thread scrolls smoothly to the newest message.
- The drawer slides in over 260ms with a fading backdrop; toasts rise and fade.
- `prefers-reduced-motion: reduce` turns every movement into an instant change or a plain crossfade.

No content is hidden until an animation runs: entrance fades start at 35% opacity, so a frozen or throttled animation still shows the content.

## Interaction and accessibility

- Every control is a real `<button>` or input with hover, focus-visible, active, disabled, and loading states. Focus rings are 2px, offset 2px, in the info blue.
- Tabs follow the ARIA tabs pattern with roving tabindex and arrow keys.
- Category rows toggle from a button with `aria-expanded`; clicking inside the reasons no longer collapses them.
- Progress logs and the chat thread are polite live regions.
- Results and severities are always written as words, never color alone.
- At 900px and below the layout becomes one column, the tab bar scrolls horizontally to the screen edge and centers the chosen tab so its neighbours peek in, the line-edit list becomes a sheet pinned to the bottom, and the chat panel stacks above the working essay. Touch targets are at least 44px on small screens and coarse pointers, including toast buttons, small disclosures, form fields, and the Essay and Changes toggle. At 560px and below the document bars stop sticking and put their actions on one row under the title.
- Input edges and the unchecked switch use a `--control` token at 3:1 against their surface (WCAG 1.4.11); `--line-strong` stays for decorative rules.
- When a control that had focus is replaced or disabled, focus moves to the nearest useful place: the rewrite's progress list, then its "Your edited essay" heading or the retry button; the chat message box while a request runs; Undo after "Use this version", and the message box once Undo runs out.

## Copy

Explanatory paragraphs get shorter without losing any honesty caveat: the rewrite and chat intros keep the sentence that Claude runs the checks too and that every line should be read against what happened. Button labels are verb plus object. No em dashes.

## Findings from the critique panel

Four critics (UX flow, visual tells, interaction and accessibility, JS contract) reviewed the old file. Their findings add these requirements:

- One accent for interaction. Red stops meaning brand, action, and problem at once: primary buttons are ink, selection and focus use a blue accent, and red is kept for cuts, losses, major severity, and errors. The wordmark keeps a small vermilion "Admit" as the only brand use.
- The two readers' markers differ by shape (filled dot for the admissions officer, ring for the editor), not only by color.
- Feedback prose renders in the main text color; muted text is for metadata only. Amber text uses a darker token that passes 4.5:1.
- Each "Edit and re-score" loads the essay version its tab shows: the reviewed essay from Feedback, the rewrite from Rewrite, the working essay from Ask for changes. Compose shows a "Back to report" link while a report exists.
- A failed poll request retries with backoff before the job is treated as failed.
- When a review finishes after the student has left the progress screen, a toast offers to open it instead of replacing what they are reading. A rewrite that finishes for a different review than the one on screen says so in a toast.
- Progress lists append new steps instead of re-rendering, so nothing flickers each poll, and the pending chat message updates in place instead of rebuilding the thread.
- Errors appear where they happen: review failures on compose with a retry, history failures inside the drawer, rewrite and chat failures in their panels, and anything else as a toast.
- Compose shows a restored-draft note with a Clear action, labels both textareas, announces the limit change when the essay type switches, and shows the school field only for supplements. The note is a polite live region that also carries Undo after a draft is cleared or replaced.
- The rewrite status appears once. "Why these changes" lists how the draft was checked instead of repeating the banner.
- Line-edit cards are keyboard operable, and the mobile layout puts the chat panel before the working essay.

## JavaScript contract

Unchanged logic: `versions`, `working`, `initChat`, `saveWorking`, `savedWorking`, `sendChat` (except the DOM updates and focus rulings below), `startRevision`, `applied`, `chipsHtml`, `threadHtml`, `turnHtml`, `ratingHtml`, `revisionHtml` content, `markedEssay`, `activate`, `pollJob`, `startJob`, and the escaping helpers. Every id and data attribute the script depends on keeps its name. New code is limited to view switching, tabs, the drawer, toasts, the theme toggle, animations, the compose validation message, and the job indicators on tabs.

## Testing

- `node --check` on the extracted script and a check that every referenced function is defined.
- Browser checks on the live server with saved reviews covering: a verified rewrite with four chat turns (passed, failed, question), an unverified rewrite, a single passing chat turn, and a low score.
- Mocked `fetch` for `/api/review`, `/api/revise`, `/api/chat`, and `/api/job/<id>` to exercise progress, success, and error paths without model calls.
- Screenshots of every screen and tab in light and dark at 1280px and 390px, plus a reduced-motion pass.
- The skill's detector at zero findings, and `pytest` green.

## Rulings made during implementation

- Re-clicking the essay type that is already selected does nothing, so it no longer resets a word limit the student typed.
- `activate()` and every scripted scroll use instant scrolling under reduced motion. Tab switches scroll instantly, because smooth-scrolling through content that just changed carries no meaning.
- Each "Edit and re-score" also applies the review's settings (type, limit, prompt, school) so the new score is comparable. Undo for a replaced or cleared draft lives in the note above the editor, not in a toast: a toast times out and keyboard users struggle to reach it, and the note holds the only copy of the previous draft. It stays until the next review or replacement, a load that replaces nothing (an empty editor or the same text) keeps it, and it swaps rather than discards (Undo, then Redo), so a stray click loses nothing. It holds one earlier draft, not a history.
- Rewrites track their progress per review (`revising`), so a second click cannot start a second job, a reopened copy of the review shows the running job, and progress never paints into another review's panel (a bug in the old page).
- Chat requests are tracked per review (`chatting`), like rewrites, so a review can run one request while another review runs its own, a reopened copy shows its running request with the controls locked, and one request finishing never unlocks another. The thread is a live log, so a request appends or edits only its own two messages instead of rebuilding the thread; a copy reopened after the server saved the turn drops the placeholder instead of showing the turn twice. New steps are followed only when the student is at the bottom of the thread, and a finished reply opens at the student's message, because replies can be taller than the thread.
- While a chat request runs, the message box is read-only, not disabled, so focus can stay in it. A chip sends without touching a half-typed message, and only a failed message from the box is put back into it, including when it failed while another review was on screen (it waits for that review to reopen).
- A toast's action closes the history drawer before it changes the view, and toasts with actions move into the drawer while it is open and back out when it closes, so their buttons stay reachable.
- A "Show me" toast checks that its review is still on screen, and opening a saved review that fails to render puts the previous one back with a toast instead of leaving half a report.
- Turn buttons follow the working essay: "Show what changed" is a pressed toggle, and the button for the version already in use reads "In use" and is disabled.
- Opening the Ask for changes tab brings the working area up under the tab bar when the composer would otherwise sit below the fold.
- Quotes are indented italics with no quote marks drawn by CSS and no stripe.
- The README's chat paragraph now points to the Ask for changes tab, because the chat no longer sits below the revision.

## Out of scope

Server and Python changes, new features, a framework or build step, changes to scoring or prompts, and committing or pushing (the user has not asked).
