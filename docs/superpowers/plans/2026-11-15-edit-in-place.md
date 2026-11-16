# Edit in place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open blocks in the tablet editor without moving them, in the blog's own type, with all of an open block's controls in one slim bar fixed to the bottom of the screen.

**Architecture:** A single `#edit-bar` element (like the Proofread review bar) is filled by whichever editor is open and emptied on close. The text editor's rail and every editor's in-block button rows go away; `framingControls` renders compact toggles into the bar. The pair editor keeps its published flex layout while open. All writes still go through the existing save functions and routes; nothing server-side changes except one font-parity test.

**Tech Stack:** vanilla JS (`editor/web/editor.js`), CSS (`editor/web/editor.css`), `editor/web/index.html`, pytest, headless Chromium over CDP (`scripts/verify-*.py`, system `python3`).

**Spec:** `docs/superpowers/specs/2026-11-15-edit-in-place-design.md` (read it whole, including "Calls made after review").

## Global Constraints

- Read the repo CLAUDE.md sections "How the editor edits" and "Text editors close on Done, never on blur" before touching `editor.js`. Every guarantee there must survive: `openEditor` registry, `flushPendingEdit`, `closeEditor`, re-attach by index, localStorage drafts, tapping another block saves this one, `captureOpenText`/`restoreOpenText`.
- No server write-path changes. Same routes, same request bodies (pair alt edits use the existing `PUT .../pair` `images` field).
- Every bar button is >= 44px tall, has `aria-label` and `title`. No all-caps labels. One filled button (`Done`).
- Fonts: two Fontshare `<link>`s, one per family (Sentient, Switzer) — the combined URL silently drops the second family.
- Bump nothing by hand: `editor.js`/`editor.css` are served at content-hashed paths automatically.
- Do NOT commit; the repo commits only on Peter's word. Do not touch `content/blog/`. Never `make stop`/`make dev`/`pkill` by name; harnesses start their own scratch servers.
- Run `editor/.venv/bin/python -m pytest editor/tests -q` and the three harnesses (`python3 scripts/verify-edit-tap.py`, `verify-proofread.py`, `verify-add-photo.py`) at the end of each task that touches `editor.js`; they must stay green except checks this plan explicitly rewrites.

## Review Focus

- Tapping block B while block A is open: A saves, the bar is re-filled for B, never shows A's controls for B. Pinned in Task 3 (harness).
- Proofread started while an editor is open: editor closes (saves), the edit bar hides, the review bar shows; never both bars. Pinned in Task 2.
- The last block of a long post opened: its field sits above the bar (bottom padding), not under it. Pinned in Task 3.
- Cancel on a pair after flipping side and editing alt text: nothing is written, block renders as before. Pinned in Task 5.
- Window resize / rotation while open: bar stays at the bottom, padding re-measured, block top unchanged. Pinned in Task 3 (1366x1024 -> 1024x1366 resize mid-edit).

---

### Task 1: The blog's type in the editor

**Files:** Modify `editor/web/index.html` (head), `editor/web/editor.css` (`body`, `.block` rendered content, `.block-source`, `.pair-text-input`, `.block.editing`); Create `editor/tests/test_editor_fonts.py`.

**Interfaces:** Produces CSS custom properties `--font-text` / `--font-display` on `:root` in editor.css with the same family names as `templates/base.html`.

- [ ] **Step 1: Failing test** `test_editor_uses_the_blogs_families`: read `templates/base.html` and `editor/web/editor.css`, extract the first family name in each file's `--font-text` and `--font-display` values, assert equal; assert `index.html` has two `api.fontshare.com` links, one containing `sentient`, one `switzer`.
- [ ] **Step 2:** `editor/.venv/bin/python -m pytest editor/tests/test_editor_fonts.py -q` -> FAIL.
- [ ] **Step 3: Implement.** Copy base.html's two `<link>`s and the two variables. Rendered block prose and `.block-source` / `.pair-text-input` use `--font-text` at the rendered paragraph's font-size and line-height, `padding: 0`, `border: 0`, transparent background; heading blocks render AND edit in `--font-display` at the h1-h4 sizes base.html uses (2/1.5/1.25/1.0625rem, weight 500). Monospace remains only on the raw-markup fallback textarea (blocks without `images`/`videos` that are HTML). `.block.editing` changes border COLOUR only — same border width and padding as `.block`.
- [ ] **Step 4:** pytest file PASS; full `pytest editor/tests -q` PASS.

### Task 2: The edit bar shell

**Files:** Modify `editor/web/index.html` (add `<div id="edit-bar" hidden role="toolbar" aria-label="Block controls">` next to the review bar, update viewport meta), `editor/web/editor.js` (new section after `closeEditor`), `editor/web/editor.css`.

**Interfaces — Produces:**
- `showEditBar({ left: HTMLElement[], settings: HTMLElement[], onDone: () => void, onCancel: (() => void) | null }) -> void` — empties and fills `#edit-bar`: `left` groups (block controls), `settings` groups, then `Cancel` (only when `onCancel`) and `Done` pushed right.
- `hideEditBar() -> void` — empties, hides, removes `#blocks` bottom padding.
- `editBarReserve()` — internal: ResizeObserver on the bar sets `#blocks.style.paddingBottom` to bar height + 16px while shown.
- `segmented(choices: [value, label, ariaLabel][], current: string, onPick: (v) => void) -> { el, set(v) }` — the compact toggle group used by Tasks 4-5.

- [ ] **Step 1:** Viewport meta becomes `width=device-width, initial-scale=1, interactive-widget=resizes-content`. Add `visualViewport` `resize`/`scroll` listeners that set the bar's `bottom` to `innerHeight - (vv.height + vv.offsetTop)` (clamped >= 0).
- [ ] **Step 2:** Implement the functions above. `hideEditBar` is called from `closeEditor` paths, `startReview`, `enterMoveMode`, placing start; `showEditBar` refuses (no-op) while `state.review`, move or placing is active.
- [ ] **Step 3:** CSS: fixed bottom, full width, white, 1px top hairline, `env(safe-area-inset-bottom)` padding, `--font-text`, flex with `gap`, wraps to two rows below 700px; segmented toggles are outlined, active fills with the post ink colour (`#1a1a1a`), `Done` keeps the editor's existing blue.
- [ ] **Step 4:** Add to `scripts/verify-proofread.py`: open a paragraph, tap ✨ Proofread -> `#edit-bar` hidden and review bar shown. Run it -> PASS.

### Task 3: Text editor: rail out, bar in, block stays put

**Files:** Modify `editor/web/editor.js` (`startEditing` 1888-2006, `RAIL_ROOM`, `placeRail`, rail DOM), `editor/web/editor.css` (delete `.edit-rail*`, `.rail-side*` rules ~250-310), `scripts/verify-edit-tap.py`.

**Interfaces — Consumes:** Task 2's `showEditBar`/`hideEditBar`. The block's existing `.block-controls` node and `.insert-choice` menu are MOVED into the bar's `left` group while open and moved back on close (not rebuilt), so their handlers keep working. The insert menu renders as a popover anchored above the bar.

- [ ] **Step 1: Rewrite the harness's rail cases first.** In `verify-edit-tap.py`, replace every assertion about `.edit-rail` / `rail-side` / the 72px column / sticky row with bar equivalents (Done is in `#edit-bar`, visible, inside the viewport, does not overlap the textarea's rect). Add, at all three viewports: (a) open a paragraph and a heading: block top and next block top within 2px of pre-open, `scrollY` unchanged; (b) the textarea's computed `font-family` equals the closed block's; (c) open the LAST block: textarea bottom <= bar top; (d) open A, tap B: bar holds B's controls, A saved; (e) at 1366x1024 open a paragraph, resize to 1024x1366: bar at bottom, top of block unchanged within 2px; (f) every `#edit-bar button` >= 44px tall. Skip (a)'s next-block check for a text block beside a float (spec call 5).
- [ ] **Step 2:** `python3 scripts/verify-edit-tap.py` -> new checks FAIL.
- [ ] **Step 3: Implement.** Remove the rail; on open call `showEditBar({ left: [controls], settings: [], onDone: closeEditor, onCancel: null })` (text keeps Done-only, as today). The textarea opens at the rendered content's measured height before `fit()` runs. Opening must not call `scrollIntoView` unless the field's top would sit under the bar. `closeEditor` and every teardown path call `hideEditBar()` and return the moved nodes.
- [ ] **Step 4:** Harness PASS (all of it, all viewports); `verify-proofread.py` and `verify-add-photo.py` PASS.

### Task 4: Settings into the bar (rows, spacers, the ◨ strip)

**Files:** Modify `editor/web/editor.js` (`framingControls` 773-855, `blockControls` 1156-1283 layout button, `wrapControl`/`unpairControl`/`spacerControl` 918-1030, `startEditingImages` ~2290-2335, `startEditingVideos` ~2660-2700), `editor/web/editor.css`, `scripts/verify-edit-tap.py`.

**Interfaces — Produces:** `framingControls(size, side, options)` keeps its return shape `{ el, size, side }` but `el` is now a bar group built from Task 2's `segmented` (size: `S` `M` `Full`; side: none / `◧` / `◨`, with the existing full<->side coupling rules). Consumed by Task 5.

- [ ] **Step 1: Harness first:** a closed block's hover controls have no `◨`; opening a photo row shows size/side in `#edit-bar` and no `.framing-controls` inside the block; the row's own top stays within 2px (spec call 3); changing side then Done writes the same markup the old picker wrote (compare file text); Cancel writes nothing; opening a spacer shows `Everywhere` / `Desktop only` in the bar and Done writes the same `post-spacer desktop-only` markup as `spacerControl` did; a row offers a `Pair` button and a pair offers `Unpair`, each acting immediately via `pairBlock`/`unpairBlock` after flushing.
- [ ] **Step 2:** Run harness -> FAIL.
- [ ] **Step 3: Implement.** Drop the `◨` button and `state.wrapOpen` strips; row/video editors pass `framing.el` (+ `Pair` button when `isMediaRow`) as bar `settings` with their existing Done/Cancel handlers; spacer opening shows the two-way toggle and saves through `saveBlock` with the same source strings `spacerControl` used (`SPACER_SOURCE` constants). Keep `setRowSide` only if still referenced.
- [ ] **Step 4:** All three harnesses + pytest PASS.

### Task 5: The pair opens as a pair

**Files:** Modify `editor/web/editor.js` (`startEditingPair` 2363-2500), `editor/web/editor.css` (`.pair-edit-*`), `scripts/verify-edit-tap.py`.

**Interfaces — Consumes:** `framingControls(..., { sides: ['left','right'] })`, `segmented`, `showEditBar`, `saveBlockPair(index, text, size, side, justify, media, opts)` unchanged.

- [ ] **Step 1: Harness first:** open a pair: media column and textarea are side by side (their rects don't overlap vertically-stacked: media.left > text.right or vice versa), block top and next block top within 2px; flip side in the bar -> media swaps sides live; change prose position -> class updates live; Done with unchanged media writes byte-identical text to the old editor's output (save a copy of the file before, compare after Done with no changes = unchanged file); `Photo` opens a sheet with one alt field + star per image, editing alt then Done writes the new alt in the pair's `<img alt>`; Cancel after flipping side and editing alt leaves the file unchanged; a video pair has no `Photo` button.
- [ ] **Step 2:** Run harness -> FAIL.
- [ ] **Step 3: Implement.** Build the open pair with the published structure (`.pair.pair-<side>.size-<size>.justify-<j>` > `.pair-media` real images/clips + `.pair-text` holding the textarea), re-applying classes live from the bar toggles. The `Photo` sheet is a panel fixed above the bar (alt `<input>` per image + `previewPickButton(url)`); alt edits update the working `media` copy; the editor's `dirty()` includes media JSON vs original.
- [ ] **Step 4:** All harnesses + pytest PASS. Screenshot an open pair, an open paragraph and an open photo row at 1366x1024 and 820x1180 (harness `--shots`) and look at them.

### Task 6: Docs

**Files:** Modify `CLAUDE.md`.

- [ ] **Step 1:** Replace the rail description in "Text editors close on Done" with the edit bar; document `showEditBar`/`hideEditBar`, the reserve padding, the visualViewport positioning (and that it needs a manual tablet check), the removal of `◨`/`wrapOpen`, the pair-as-pair editor and its Photo sheet, and the stays-put rule (top edge; rows exempt below).
- [ ] **Step 2:** Final full run: pytest + three harnesses, report the pass lines.
