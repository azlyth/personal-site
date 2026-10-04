# Proofread: AI spelling and grammar suggestions in the blog editor

Date: 2026-10-04. Design approved in conversation the same day.

## Goal

A ✨ **Proofread** button in the blog editor (edit.cloudy.nyc) that asks
Claude for spelling, grammar and punctuation fixes only — never rephrasing —
and shows them on the post as suggestions Peter steps through and accepts or
rejects one at a time. Nothing in the post changes until he accepts.

Not goals: style advice, rewording, tone, fact checking, proofreading
anything but prose (photos, video, code, links and raw HTML are left alone),
a non-AI checker (LanguageTool was considered and set aside: more false
alarms on names, fragments and casual voice; it can be added later as an
instant first pass).

## Engine

The local `claude` CLI, the same way the recipes and split apps call it
(`subprocess.run([claude_bin, "-p", prompt], timeout=...)`).

- `claude_bin` defaults to the absolute path `/home/peter/.local/bin/claude`
  (overridable by `EDITOR_CLAUDE_BIN`): the systemd unit's PATH doesn't
  include `~/.local/bin`, which is exactly how recipes' prod parser broke on
  2026-09-13.
- Optional `EDITOR_PROOFREAD_MODEL`, passed as `--model` when set; unset
  means the CLI default.
- Timeout 120 s per batch.

## Flow

1. **Start.** Tapping ✨ Proofread flushes any open editor (the existing
   flush path), then the client collects the post's prose blocks — kinds
   `paragraph`, `heading`, `list`, `blockquote`, and `pair` (its prose) — and
   sends them to the server in batches of up to 5 blocks, one batch at a
   time.
2. **Progress.** While running, a thin progress bar and the line
   "Proofreading N of M paragraphs" show in the top bar, with **Cancel**.
   Progress counts blocks actually finished. Suggestions from finished
   batches appear immediately; Cancel stops further batches and keeps what
   has arrived.
3. **Review.** Each suggestion is shown inline in its block: the old text
   struck through in red, the new text in green right after it. A fixed bar
   at the bottom of the screen holds: `3 of 12`, **↑** / **↓** to move
   between suggestions (the current one is highlighted and scrolled into
   view), a short kind label (spelling / grammar / punctuation), **Accept**,
   **Reject**, **Accept all** and **Close**. 44px touch targets, no
   hover-only controls.
4. **Accept** applies that one fix to the block's markdown source and saves
   it (so the editor's Undo can take it back), then moves to the next
   suggestion. **Reject** drops it and moves on. **Accept all** applies every
   remaining suggestion, block by block. **Close** leaves review mode,
   discarding unreviewed suggestions. When none are left, review mode ends
   with a status line ("All suggestions reviewed").
5. **Stale blocks.** Blocks can't be edited during review, but a block can
   still change underneath it (Undo, another tab, or an earlier accepted fix
   that consumed a later suggestion's text). When an apply comes back 409 or
   fails the re-check, that suggestion is dropped with a status line and the
   rest continue.
6. **Errors.** A batch that fails or times out shows "Couldn't check
   paragraphs 5–7" in the status line; the other batches carry on. No
   suggestions at all → "No spelling or grammar issues found".

## Server

### `POST /api/posts/{slug}/proofread`

Request `{"indices": [int, ...]}` (≤ 5). For each index, the server reads the
current block source, sends those blocks to Claude with a fixed prompt, and
returns:

```json
{"blocks": [{"index": 4, "block_hash": "<sha256 of the block source>",
             "suggestions": [{"id": "4-0", "before": "recieve", "after": "receive",
                              "kind": "spelling"}],
             "review_html": "<p>… <del class=\"pr-old\" data-sid=\"4-0\">recieve</del><ins class=\"pr-new\" data-sid=\"4-0\">receive</ins> …</p>"}],
 "errors": []}
```

`review_html` is the block rendered by the editor's own markdown renderer
with every surviving suggestion marked in place, so the client shows marks
without mapping source offsets itself. Session auth like every other route.

### Prompt

Spelling, grammar and punctuation only; keep the author's wording, voice,
sentence fragments, informal phrasing, names and capitalization choices; do
not touch markdown syntax, links, URLs, HTML or code; return strict JSON —
a list of `{block, before, after, kind}` where `before` is copied exactly from
the block and is the shortest span that makes it unique within that block.

### Guardrails (server-side; a suggestion failing any is dropped and logged)

1. Its block was in the request, and `before` occurs **exactly once** in that
   block's current source.
2. `before != after`.
3. Neither `before` nor `after` contains a newline, and `before` is at most
   80 characters.
4. Word-level edit distance between `before` and `after` is at most 3.
5. The change doesn't add, remove or alter any of `` [ ] ( ) * _ ` # < > | ``,
   and `before` doesn't overlap a URL, an inline code span, a link
   destination or an HTML tag in the source.
6. `kind` is one of `spelling`, `grammar`, `punctuation`.
7. Two suggestions in the same block don't overlap (the later one is
   dropped).

Malformed JSON from Claude fails that batch (reported in `errors`), never the
whole run.

### `POST /api/posts/{slug}/proofread/apply`

Request `{"index", "block_hash", "before", "after", "hash"}` (`hash` is the
post hash, the usual staleness check). The server checks the block's current
source still hashes to `block_hash` (else 409, "this paragraph changed"),
re-checks guardrails 1–5, replaces the single occurrence, and writes through
`_write_body` (history snapshot, atomic write, Undo) with `replace_block`.
Returns the normal post payload plus the block's new `block_hash`. The
client stores that as the block's hash, so the block's remaining
suggestions apply against the updated source; each is re-checked on its own
apply (its `before` must still occur exactly once).

## Client (editor.js / editor.css)

- ✨ button in the top bar; disabled while proofreading or when no prose
  blocks exist.
- Review mode renders the post normally except that proofread blocks show
  `review_html`; blocks are not editable while reviewing (tapping one shows a
  hint to Close review first) — this keeps the block hash stable.
- `del.pr-old`: red, strikethrough; `ins.pr-new`: green, underlined; the
  current pair gets a highlight ring. Accept removes the `del` and unwraps
  the `ins`; Reject removes the `ins` and unwraps the `del`.
- Bottom bar as described in Flow; it never covers the current suggestion
  (scrolled into view above it).

## Testing

- Server unit tests with a fake `claude` (a script on PATH or a patched
  runner): each guardrail drops what it should; a clean suggestion survives
  with correct `review_html`; malformed JSON fails one batch only; apply
  replaces exactly one occurrence, refuses a changed block (409), and is
  undoable; the claude binary path default is absolute.
- Auth coverage test picks up both routes.
- Headless-Chromium check at 1024×1366 and 820×1180 with a fake claude: the
  progress bar advances, marks render, ↑/↓ move and scroll, Accept / Reject /
  Accept all / Close work, and the post source matches after accepts.
- One real-Claude run on Peter's Spruce draft, screenshotted and shown to
  him; no suggestion that rewords may survive the guardrails.
