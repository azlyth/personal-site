# Proofread: sentence-level fixes on Sonnet

Date: 2026-11-15. Builds on `2026-10-04-proofread-design.md`.

## Why

Proofread catches typos but can't fix the mistakes that actually show up in
drafts: a sentence left half-edited ("I'm sharing it with to share it for
people to track their cleaning too, and we and if enough of us do...") or
punctuation like `--` used as a dash. The two-word cap that keeps it from
rewording also stops it from repairing a broken sentence.

## Goals

- Proofread can fix a broken sentence, even when that takes more than two
  words.
- It still changes as few words as possible. A fix keeps Peter's wording and
  voice, and a typo fix still touches one word.
- The review shows only what changed, so a small fix inside a long sentence
  still looks small.
- It runs on Sonnet.

## Non-goals

- No background checking. It stays the ✨ Proofread button (Peter's call).
- No style or tightening suggestions on sentences that are already correct.

## Anti-goals

- Proofread turning into a rewriter: suggestions that restate a correct
  sentence in other words.
- A fix that lands on links, code, HTML or markup.

## Approaches

- **A. Keep the review screen; mark only the changed words (picked).** A
  suggestion may span a whole sentence, but the review marks only the words
  that differ inside it. The bottom bar shows the kind plus a short reason
  instead of the clipped `before → after`. Reuses the apply route, Undo and
  the stale-text 409s.
- B. A before/after card per suggestion. Clearer for big rewrites, but a new
  component and an extra tap per fix.
- C. A side panel listing every suggestion. Most work, and it splits
  attention between the panel and the text.

Peter picked A.

## Design

**Model.** `config.proofread_model()` defaults to `sonnet` when
`EDITOR_PROOFREAD_MODEL` is unset (still overridable).

**Prompt.** Same contract, three changes:
- Fix spelling, grammar and punctuation, including broken sentences
  (missing, doubled or leftover words) and `--` used as a dash.
- Prefer the smallest span and the fewest changed words; span a whole
  sentence only when the sentence itself is broken. Never restate a correct
  sentence.
- Each suggestion adds `"reason"`: two to four plain words ("Typo",
  "Missing words", "Double hyphen"). Kinds stay spelling / grammar /
  punctuation.

**Guardrails (`proofread.validate`).**
- `spelling` keeps today's rules exactly: one word, `difflib` ratio >= 0.6.
- `grammar` / `punctuation`: the two-word cap is replaced by
  - `before` must stay inside one sentence (no sentence-ending `.`/`?`/`!`
    followed by more text) and within one block, up to 300 characters
    (was 80);
  - at most `max(2, words_in_before // 2)` NEW words may come in (words of
    `after` that replace or add to `before`); removing stray words is free
    (my call: repairing a half-edited sentence is mostly deleting leftovers,
    while restating a correct sentence brings in mostly new words). `after`
    may not be empty.
- Unchanged: exactly-once match, word boundaries, protected spans
  (code, URLs, link targets, HTML, image alt, `www.`), no block-type change,
  and the same re-check plus block hash on apply.
- `reason` is required, trimmed to 40 characters, plain text (escaped).

**Review marks.** `review_html` runs a word-level diff between `before` and
`after` and wraps only the changed runs in `<del class="pr-old">` /
`<ins class="pr-new">`, all sharing the suggestion's `data-sid`. Stepping,
scrolling and Accept treat every mark with that sid as one suggestion.
Unchanged words inside the span stay plain text.

**Bottom bar.** Shows the kind and the reason ("Grammar · Missing words")
in place of `before → after`. Buttons, order and 44px targets unchanged.

## Testing

- Unit (`editor/tests/test_proofread.py`): a multi-word grammar fix passes;
  a fix crossing a sentence end is dropped; a fix changing more than half
  the words is dropped; spelling still capped at one word; review_html marks
  only changed words; reason required and escaped; model defaults to sonnet.
- `scripts/verify-proofread.py`: the fake claude adds one sentence-level
  fix; check it renders as several marks with one sid, steps as one, the bar
  shows its reason, and Accept writes it.
- One real Sonnet call against the Spruce draft to sanity-check that it
  catches the two sentences and leaves correct ones alone.

## Left to the builder

Exact diff tokenization (whitespace and punctuation handling), how the bar
truncates a long reason on narrow screens, and test fixture wording.
