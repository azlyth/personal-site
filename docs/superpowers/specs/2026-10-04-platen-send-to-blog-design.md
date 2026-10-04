# Send to blog: Platen → blog editor drafts

Date: 2026-10-04. Approved in conversation the same day.

## Goal

A "Send to blog" button in Platen (write.ubbe.nyc) that turns the open doc
into a **new draft post** in the blog editor (edit.cloudy.nyc), already split
into the editor's blocks — a heading block per heading, a paragraph block per
paragraph — so it can be finished there. Only Peter sees or can use it.

Not goals: syncing edits back and forth, publishing from Platen, images.

## Decisions

- **Every send creates a new draft.** Re-sending the same doc never
  overwrites anything; it gets the next free slug (`-2`, `-3`, ...), the same
  collision rule the editor's New post uses.
- **Always a draft.** `draft = true` is set by the editor, not requested by
  the caller. The 2026-10-04 draft gate (`scripts/check-drafts.py`) keeps it
  off cloudy.nyc until Peter un-drafts it in the editor.
- **The editor owns conversion.** It already owns slugs, frontmatter and the
  block model, so the text→post conversion lives there and is tested against
  `blocks.py`. Platen sends raw text.
- **Server to server over loopback**, authenticated by a shared secret.
  Rejected: Platen writing `content/blog/*.md` directly (duplicates the
  editor's slug/frontmatter rules in Go), and a browser hand-off to the
  editor (cross-origin cookies, URL length limits).

## Conversion rules (editor, pure function)

Input: the Platen doc's text and its name (the fallback title).
Output: `(title, body_markdown)`.

1. Normalize `\r\n` to `\n`, strip leading and trailing whitespace on each
   line. (Four spaces of indent is a code block in CommonMark; Platen has no
   code blocks, so an indented line must still post as a paragraph.)
2. **Title.** If the first non-blank line is `# <text>`, `<text>` is the
   title and that line is removed from the body. Otherwise the title is the
   doc name with a trailing `.md` removed.
3. **Splitting.** Every non-blank line becomes its own block: lines are
   joined with exactly one blank line between them. So a single line break
   is a paragraph break, and runs of blank lines collapse to one. (Platen's
   own docs separate paragraphs with blank lines today; this rule also makes
   single-break text safe from merging into one block.)
4. **Headings.** `##`–`######` lines pass through. A `# ` line in the body
   becomes `## `: the post title is the page's only h1.
5. **Inline markup** (`**strong**`, `*em*`/`_em_`, `` `code` ``) passes
   through unchanged; both apps use the same syntax.
6. An empty body (after removing the title) is rejected with 400. Nothing is
   written.

## Blog editor changes (`personal-site/editor`)

- `editor/importer.py`: the conversion above, no I/O.
- `POST /api/import`, JSON `{"text": str, "name": str}` →
  `201 {"slug", "edit_url"}` where `edit_url` is
  `{config.BASE_URL}/edit/{slug}`.
  - Creates the post through the same code path as `POST /api/posts`
    (slug rule, collision suffix, tomlkit frontmatter `title`/`date`/`draft`),
    refactored into a shared helper so the two can't drift. The body is the
    converted markdown instead of `Start writing.`
  - Does not commit. Like any new post, it is committed by the next Publish.
- **Auth.** `/api/import` is exempt from the session-cookie middleware and
  instead requires header `X-Import-Token`, compared with
  `hmac.compare_digest` against `EDITOR_IMPORT_TOKEN`. If the token isn't
  configured the route answers 404, so the feature is off by default. The
  token lives in a gitignored, 0600 file loaded the same way as
  `.editor-smtp.env`. `test_auth.py`'s every-route coverage test accounts for
  the route explicitly. All other routes are unchanged.
- The route is reachable through Caddy at edit.cloudy.nyc (LAN only), as well
  as loopback. The token is what protects it either way.

## Platen changes (`platen`)

- Config: `BLOG_IMPORT_URL` (default `http://127.0.0.1:8804/api/import`) and
  `BLOG_IMPORT_TOKEN`, from a new gitignored `.blog-import.env` loaded by
  `platen.service` (`EnvironmentFile=-`, so a missing file just disables the
  feature).
- `POST /api/docs/{name}/send-to-blog`: only for the owner account (the
  existing `-owner` flag, default ptr.vldz@gmail.com) **and** only when the
  token is configured; anyone else gets 404. Reads the doc from the store,
  POSTs `{text, name}` to the editor with a 10-second timeout, and returns
  the editor's `{slug, edit_url}`. Editor errors come back as 502 with the
  editor's message.
- `GET /api/me` gains `can_send_to_blog: bool`.
- UI (`web/chrome.js`, `web/app.js`, `web/api.js`): a full-width
  "Send to blog" button on its own row under Share / Fullscreen, rendered
  only when `can_send_to_blog`. On tap: flush autosave (as delete does),
  call the endpoint, then show "Draft created" plus an **Open in editor**
  link in its own `#blog-status` line (not `#share-status`, which clears
  itself on a timer). Failures show there too.

## Secret handling

One random token (32 bytes, hex) generated on the Pi, written to both
gitignored env files with mode 0600. Never committed, never printed in chat.
Both services restart to pick it up (`make editor-restart`,
`make svc-restart` in platen).

## Testing

- `importer.py` unit tests: title from `# `, fallback to doc name, single
  and double line breaks, collapsed blank runs, body `#` demoted to `##`,
  inline markup untouched, empty body rejected. Each converted fixture is
  run through `blocks.py` and asserted to yield the expected sequence of
  `heading`/`paragraph` blocks.
- `/api/import` tests: missing token, wrong token, unconfigured token (404),
  creates `draft = true`, second send gets `-2`, the created file passes
  `scripts/check-drafts.py`, and New post still behaves as before.
- Platen Go tests with an `httptest` fake editor: owner gets slug/edit_url,
  non-owner 404, token unset 404, editor failure → 502, `/api/me` flag.
  Browser test: button present for the owner only.
- End to end: send Peter's real Spruce doc, confirm the new draft's blocks
  match its headings and paragraphs, screenshot it in the editor. This
  leaves a real `spruce-the-litter-cleaning-tracker-2` draft, which is the
  intended result. The empty hand-made draft is left for Peter to delete.
