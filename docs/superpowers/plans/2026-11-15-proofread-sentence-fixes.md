# Proofread sentence-level fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the editor's ✨ Proofread repair broken sentences (more than two words when needed) on Sonnet, marking only the changed words and showing a short reason.

**Architecture:** All guardrail and rendering changes live in `editor/proofread.py` (pure functions, pytest-covered). The client change is small: every mark sharing a suggestion id is resolved together, and the review bar prints `kind · reason`. The browser harness gains one sentence-level fix.

**Tech Stack:** Python 3 / FastAPI / markdown-it (`_md`, commonmark), vanilla JS, pytest, headless Chromium over CDP (`scripts/verify-proofread.py`).

**Spec:** `docs/superpowers/specs/2026-11-15-proofread-sentence-fixes-design.md`

## Global Constraints

- Model default `sonnet` when `EDITOR_PROOFREAD_MODEL` is unset or blank; a set value still wins.
- `spelling` rules unchanged: `MAX_BEFORE` 80 chars, at most 2 word edits, `difflib` ratio >= 0.6.
- `grammar`/`punctuation`: `before` up to 300 chars, inside one sentence, NEW words (words of `after` in replace/insert opcodes of a word-level `difflib` match) <= `max(2, words_in_before // 2)`; deletions are free; empty `after` dropped.
- Every existing guard stays: exactly-once, word boundaries, `_MARKUP`, `_PROTECTED`, no block-type change, no newline.
- `reason`: plain string, stripped, cut to 40 chars; missing or non-string becomes `""` (builder's call recorded here: dropping an otherwise valid fix for a missing label is worse than showing the kind alone).
- Commits: simple present tense, NO Claude footer, and only when Peter says so (repo CLAUDE.md). Tasks end at "tests green", not at a commit.
- Never run `make stop`/`make dev`; the harness starts its own scratch uvicorn.

## Review Focus

- A sentence fix whose `before` contains an abbreviation like "e.g. the" reads as crossing a sentence end and is dropped. Expected: dropped, never mangled. Pinned in Task 1.
- Model returns a whole correct sentence restated. Expected: dropped by the half-the-words rule. Pinned in Task 1.
- Diff marks inside a sentence where only punctuation changed ("say -- no" -> "say, no"). Expected: marks cover just the changed tokens, Accept writes the full `after`. Pinned in Task 2.
- Rejecting a multi-mark suggestion leaves no stray `<ins>` text. Pinned in Task 3 (harness).
- A reason containing `<b>` renders as text. Pinned in Task 3 (bar uses `textContent`) and Task 1 (validate keeps it raw, client never uses innerHTML for it).

---

### Task 1: Guardrails, reason and model default

**Files:**
- Modify: `editor/proofread.py` (`PROMPT`, `_problem`, `validate`, new constants)
- Modify: `editor/config.py:96-98` (`proofread_model`)
- Test: `editor/tests/test_proofread.py`

**Interfaces:**
- Produces: `validate(...)` items now `{"id", "before", "after", "kind", "reason"}`; constants `MAX_BEFORE_SENTENCE = 300`, `MAX_REASON = 40`; `_crosses_sentence(before: str) -> bool`; `_new_words(before: str, after: str) -> int`.

- [ ] **Step 1: Write the failing tests** in `test_proofread.py`:
  - `test_model_defaults_to_sonnet(monkeypatch)`: delenv `EDITOR_PROOFREAD_MODEL` -> `config.proofread_model() == "sonnet"`; setenv `"opus"` -> `"opus"`; setenv `"  "` -> `"sonnet"`.
  - `test_grammar_can_repair_a_broken_sentence`: source `"I'm sharing it with to share it for people to track their cleaning too."`, before `"with to share it for people to track"`, after `"so people can track"`, kind grammar -> kept (2 new words: so, can). Also `"the the"` -> `"the"` kept, and an empty `after` -> `[]`.
  - `test_grammar_rewrite_of_most_words_dropped`: before `"the city is very dirty today"` -> after `"our town looks filthy now"` -> `[]`.
  - `test_fix_may_not_cross_a_sentence`: source `"It was late. we left."`, before `"late. we"`, after `"late. We"` -> `[]`; and `"e.g. the"` case -> `[]`.
  - `test_spelling_still_short`: a 3-word spelling `before` with 3 edits -> `[]`; `MAX_BEFORE` 81-char spelling -> `[]`.
  - `test_punctuation_double_hyphen`: `"they'll say -- no matter"`, before `"say -- no"`, after `"say, no"`, punctuation -> kept.
  - `test_reason_kept_trimmed_and_defaulted`: reason `"  Missing words  "` -> `"Missing words"`; 60-char reason -> len 40; missing -> `""`; `5` -> `""`; `"<b>x</b>"` kept verbatim.
  - Rename `test_grammar_limited_to_two_word_edits` to `test_grammar_new_word_cap`: `"one two three four"` -> `"uno dos tres cuatro"` dropped (4 new > max(2,2)); `"one two"` -> `"uno dos"` kept.
  - Update `test_guardrails_drop`'s `"x"*81` item to `kind="spelling"` (it is), and add a `"x"*301` grammar item.
- [ ] **Step 2: Run** `cd ~/projects/personal/personal-site && editor/.venv/bin/python -m pytest editor/tests/test_proofread.py -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement.** `proofread_model()` returns the stripped env value or `"sonnet"`. In `_problem`: length cap `MAX_BEFORE` for spelling, `MAX_BEFORE_SENTENCE` otherwise; `_word_edits` cap `MAX_WORD_EDITS` for spelling only; drop when `_crosses_sentence(before)`, defined as regex `[.!?]["')\]]?\s+\S` found in `before`. `validate` carries `reason` (str -> strip -> `[:MAX_REASON]`, else `""`) through sorting and into each output dict. Prompt: replace "shortest span (usually one word, at most a few)" with the spec's three rules (smallest span and fewest changed words; whole sentence only when the sentence itself is broken; never restate a correct sentence; `--` used as a dash is punctuation) and add `"reason": "<2-4 plain words>"` to the JSON shape.
- [ ] **Step 4: Run** the same command. Expected: all PASS (whole file).

### Task 2: Mark only the changed words

**Files:**
- Modify: `editor/proofread.py` (`review_html`, new `_diff_html`)
- Test: `editor/tests/test_proofread.py`

**Interfaces:**
- Consumes: Task 1's suggestion dicts.
- Produces: `_diff_html(before: str, after: str, sid: str) -> str` — escaped text with `<del class="pr-old" data-sid>`/`<ins class="pr-new" data-sid>` around changed runs only. `review_html` signature unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_review_html_marks_only_changed_words`: source `"I'm sharing it with to share it for people to track."`, suggestion before `"with to share it for people to track"` after `"so people can track"`. Assert `"people"` appears outside any `<del>`/`<ins>` (unchanged), `<del` count >= 1, every mark has `data-sid="0-0"`.
  - `test_review_html_punctuation_only_change`: `"say -- no"` -> `"say, no"`: the word `say` and `no` are unmarked; `--` is inside a `<del>`.
  - `test_diff_html_round_trip`: for the case above, stripping `<ins>…</ins>` and unwrapping `<del>` yields `html.escape(before)`; stripping `<del>…</del>` and unwrapping `<ins>` yields `html.escape(after)`.
  - Existing single-word tests (`test_review_html_marks_in_place`, escapes, digits, two suggestions) must still pass unchanged.
- [ ] **Step 2: Run** `pytest editor/tests/test_proofread.py -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement `_diff_html`.** Tokenize both strings with `re.findall(r"\s+|\w+|[^\w\s]", s)` (keeps whitespace as tokens so joins are exact), run `difflib.SequenceMatcher(None, a, b, autojunk=False)`, emit `html.escape` of equal runs, and for replace/delete/insert emit `<del>` of the old run then `<ins>` of the new run (omit an empty one). In `review_html`, replace the current single del+ins substitution with `_diff_html(s["before"], s["after"], sid)`.
- [ ] **Step 4: Run** the file. Expected: all PASS. Then `pytest editor/tests -q` (whole editor suite) — expected all PASS (test_api_proofread included).

### Task 3: Client resolves every mark; bar shows the reason

**Files:**
- Modify: `editor/web/editor.js` (`resolveMark` ~3230, `renderReviewBar` ~3189-3201)
- Modify: `editor/web/editor.css:1012-1013`
- Modify: `scripts/verify-proofread.py` (fake claude + checks)

**Interfaces:**
- Consumes: Task 1/2 payload (`reason`, multi-mark per `data-sid`).

- [ ] **Step 1: Extend the harness first.** Add a scratch paragraph `"I'm sharing it with to share it for people to track their cleaning too."` to the planted draft, and have `FAKE_CLAUDE` also return `{"block": <its index>, "before": "with to share it for people to track", "after": "so people can track", "kind": "grammar", "reason": "Missing words"}`; give the existing typo items `"reason": "Typo"`. Update check 2 to expect the bar text `"spelling · Typo"` (no longer `before → after`). Add checks: the sentence fix renders as >= 2 marks sharing one sid and `step` counts it once; its bar reads `"grammar · Missing words"`; Reject on it leaves no `.pr-new` for that sid and the source unchanged; Accept writes `"I'm sharing it so people can track their cleaning too."`. Update every "N of M" total the new item shifts.
- [ ] **Step 2: Run** `python3 scripts/verify-proofread.py` (system python3, ~3 min). Expected: the new/changed checks FAIL.
- [ ] **Step 3: Implement.** `resolveMark`: use `querySelectorAll` for both tags and resolve every node (drop all of one tag, unwrap all of the other). `renderReviewBar`: drop the `change` span; `kind.textContent = item.reason ? `${item.kind} · ${item.reason}` : item.kind` (textContent only). CSS: `.review-kind` loses `text-transform: uppercase` and `letter-spacing` (sentence case per spec), keeps colour/size, gains `overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0`; delete the now-unused `.review-change` rule.
- [ ] **Step 4: Run** the harness again. Expected: `N/N checks passed`. Read both `--shots` PNGs to eyeball the bar at 820px and 1024px.

### Task 4: Real Sonnet run and docs

**Files:**
- Modify: `CLAUDE.md` (the "### Proofread" section)

- [ ] **Step 1: Real call, read-only.** From `editor/`'s venv, parse `content/blog/spruce-the-litter-cleaning-tracker.md` with `editor.blocks.parse_blocks`, pick the prose blocks holding "I'm sharing it with" and "-- no matter", run `proofread.build_prompt` -> `run_claude` -> `parse_response` -> `validate` -> `review_html`. Print each kept suggestion and how many were dropped. Expected: both sentences get a kept fix; no fix on an untouched correct paragraph. Write nothing to the post. If a sentence is missed, adjust only the prompt wording and re-run (max 3 tries), then report.
- [ ] **Step 2: Update CLAUDE.md** Proofread section: model default sonnet; the per-kind caps (80/2 spelling, 300 chars + one sentence + half-the-words for grammar/punctuation); `reason`; word-level diff marks with one sid per suggestion and `resolveMark` resolving all; bar shows `kind · reason`.
- [ ] **Step 3: Restart the live editor** so Peter can use it: `make editor-restart`, then `make editor-logs` shows a clean start (no traceback).
