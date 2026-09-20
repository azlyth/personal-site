# Blog editor — design

**Date:** 2026-09-20
**Status:** approved, phase 1 in progress

A LAN-only editor for this site: edit posts in place from a tablet, upload
photos, and change the nav, footer and homepage — with git as the source of
truth. The server commits and publishes on your behalf.

## Goal

Peter writes and edits from a tablet, which has no filesystem access to the Pi.
Today every change to this site — a post, a job title, an email address —
requires a terminal. This makes the site self-servable without giving up the
thing that makes it durable: **the content lives in git, in this repo, in plain
markdown and TOML.** The editor is a convenience layer over that, never a
replacement for it.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Exposure | **LAN/tailnet only** (`edit.cloudy.nyc`, grey-cloud A) | The service can commit to the repo, push to GitHub and write to S3. None of that should be reachable from the internet. Removes the need for magic-link auth entirely. |
| Save model | Autosave drafts to the working tree; explicit **Publish** commits | Keeps git history readable — one commit per editing session, not one per keystroke batch. |
| Edit surface | **Block-level in place** | Feels like editing the live post, but never converts HTML back to markdown. |
| Images | Upload one or many; 2+ become an `.img-row` | Matches the convention already established in `guerilla-gardening.md`. |
| Deploy | nginx serves a **bind-mounted `public/`**; publish runs `zola build` | Publish-to-live in ~2s instead of a 60–90s image rebuild. Also removes the rebuild from ordinary template work. |
| Editor URL | `edit.cloudy.nyc` **mirror** of the site | The public build ships zero editor code, so no misconfiguration can expose the editing UI. |
| Editor location | `editor/` inside this repo | Matches `lab-backend/`, which is already an in-repo service. A single commit can change a template and the editor that edits it. |
| Runtime | Python/FastAPI, **native systemd**, not Docker | Running as `peter` grants exactly the privileges needed — repo write access and the existing SSH key for push — with no credential plumbing or mounts. |

## Architecture

```
tablet → edit.cloudy.nyc (grey-A, LAN only)
           → Caddy → 127.0.0.1:8804  blog-editor.service (FastAPI, User=peter)
                ├── reads/writes  content/blog/*.md        (posts)
                ├── reads/writes  data/*.toml              (nav, footer, homepage)
                ├── images        → EXIF strip + resize → S3 (img.cloudy.nyc)
                └── Publish       → git commit + push → zola build → public/
                                                              ↑
                       cloudy.nyc → Caddy → nginx (:8802) ────┘  bind-mounted
```

Pushing to `main` also triggers the GitHub Actions workflow, so publishing
updates **peter.direct as well as cloudy.nyc**.

### Components

- **`editor/app.py`** — FastAPI app. Routes for listing/loading/saving posts,
  block edits, image upload, data-file edits, and publish.
- **`editor/blocks.py`** — the markdown block index and splice logic. The
  riskiest code in the project; tested hardest.
- **`editor/frontmatter.py`** — TOML frontmatter read/write via `tomlkit`
  (preserves formatting of fields it doesn't touch).
- **`editor/images.py`** — the pipeline already proven in
  `scripts/upload-image.py`: EXIF strip, resize to 1600px, JPEG re-encode, S3
  put with a far-future `Cache-Control`.
- **`editor/publish.py`** — git add/commit/push and the build-and-swap.
- **`editor/web/`** — the editor front end, served by the app: vanilla JS, no
  build step, matching the dependency-free style of the rest of the site.
  Reuses the site's own CSS so the editing view looks like the real post.

**Invoking Zola.** The publish step shells out to `zola build`. If a native
`zola` binary is present on the Pi it is used directly; otherwise the build
runs in a throwaway container (`docker run --rm -v <repo>:/project`), which is
how the existing `Dockerfile` already gets Zola. Resolved at implementation;
either way it is one function in `publish.py`.

## Data model

Two kinds of editable things, so one set of UI primitives covers everything.

### Documents (posts)

`content/blog/<slug>.md` — TOML frontmatter plus a markdown body.

- Frontmatter fields the editor owns: `title`, `date`, `draft`.
- Slug is the filename; changing it is a `git mv` and **warns that existing
  links will break**.
- Body is edited block by block (below).

### Structured data (nav, footer, homepage)

Zola's `load_data()` reads TOML from `data/`. Each file is owned wholesale by
the editor, which is why these are dedicated files rather than
`config.toml [extra]` — `config.toml` has hand-written comments worth keeping,
and the editor rewrites these files entirely.

```toml
# data/nav.toml
[[items]]
label = "Home"
path  = "/"

# data/footer.toml
[[items]]
label = "Email"
url   = "mailto:peter@common37.org"
icon  = "email"

# data/home.toml
[[sections]]
heading = "I'm working as:"
  [[sections.items]]
  title       = "Staff Site Reliability Engineer @ Zocdoc"
  link        = "https://www.zocdoc.com"
  description = "Leading site reliability and infrastructure initiatives…"
```

Each requires a template migration replacing hardcoded markup with a loop.
These migrations must render byte-comparable output to what's there today —
verified by diffing the built `public/` before and after.

## Block editing

**Never reconstruct markdown from HTML.** Instead, map rendered blocks back to
source ranges.

1. Parse the body with `markdown-it-py`. Every top-level token carries
   `token.map` — a `[start_line, end_line)` range into the source.
2. Assign each top-level token an index; render each independently and wrap it:
   `<div data-block="3">…</div>`.
3. Editing block 3 fetches **its raw markdown**, not its HTML.
4. Saving splices the new text into exactly those source lines and rewrites the
   file. Bytes outside the edited range are untouched by construction.

Blocks are top-level nodes only: paragraph, heading, list, blockquote, fenced
code, HTML block, horizontal rule.

**Blocks with a dedicated editor instead of a textarea:**

- **Title** — renders as the H1 but writes to frontmatter.
- **Images and `.img-row`s** — a thumbnail strip with add / remove / reorder,
  not a raw `<div class="img-row">` textarea. Editing HTML by thumb is exactly
  what this project exists to avoid.

**Structural edits** — a `+` between blocks inserts one; each block has a
delete control. Both are line splices.

**Concurrency guard.** The editor hashes the file on load and sends the hash to
the client. A save whose hash no longer matches is refused with "reload — this
changed on disk," rather than silently clobbering an edit made from a terminal
or pulled from GitHub.

**Preview fidelity (accepted limitation).** The editor renders with
`markdown-it-py`; the site renders with Zola's Rust renderer. For the
constructs in use they agree, but they are not the same engine — the editor
preview is very close, not byte-identical. The publish step runs the real Zola
build, which is authoritative.

## Images

- Multipart upload; camera roll works via a plain file input.
- Pipeline reused from `scripts/upload-image.py`: EXIF strip (removes GPS),
  cap the longest edge at 1600px, JPEG re-encode, S3 put with
  `public, max-age=31536000, immutable`.
- Key: `<post-slug>/<alt-slug>-<hash8>.jpg`. Descriptive like the hand-made
  ones, collision-proof, and safe to cache immutably — re-uploading the same
  bytes dedupes to the same key.
- Alt text is prompted for, optional, and doubles as the filename hint.
- One image inserts as a centered standalone; two or more insert as an
  `.img-row`.
- **Orphans accepted:** removing an image from a post leaves the S3 object.
  Storage is pennies and older commits still reference it.

## Publish

1. **`git add` only the specific paths touched** — never `git add -A`. This
   repo routinely has unrelated work in flight; sweeping it into an editor
   commit would be a silent, damaging bug. Enforced by test.
2. Commit, message derived from the post title and editable.
3. Push to `origin main`. Failure leaves the commit intact locally and says so
   plainly rather than reporting success.
4. `zola build` into a temp directory, then **atomically swap** it into `public/`.

Step 4 is deliberate: `zola build` wipes its output directory first, so
building straight into what nginx serves means a failed build leaves a
half-empty site. That is precisely the failure that hit `meetup.astoria.app`,
where a wiped `dist/` during rebuild got 404s pinned in Cloudflare's cache.
Build-then-swap means a failed build leaves the last good site standing.

## Security model

The service runs as `peter` with repo write access, a git push credential and
S3 write credentials. The only thing keeping that private is the network
boundary, so that boundary is defended in four places:

1. Binds `127.0.0.1:8804` — never `0.0.0.0`.
2. `edit.cloudy.nyc` is a **grey-cloud A record** via Caddy's `dynamic_dns`
   (`cloudy.nyc edit`), resolving to a private IP.
3. **No `cloudflared` ingress entry, ever.** Called out in the Caddyfile block
   and in `http-routing/CLAUDE.md`.
4. **Startup assertion:** the service refuses to start if its own hostname
   appears in `http-routing/cloudflared/config.yml`. A cheap guard that turns a
   catastrophic misconfiguration into a failed boot.

S3 credentials come from the existing gitignored `.aws.env`.

## Testing

TDD throughout. The splice logic is where a bug quietly destroys writing, so it
carries the most tests.

- **`blocks.py`** — round-trip property: re-saving a block with its own content
  leaves the file **byte-identical**. Editing block N changes only block N's
  lines. Covers every block type, including HTML blocks and posts that end
  without a trailing newline.
- **`frontmatter.py`** — editing `title` leaves other fields and formatting
  untouched.
- **`publish.py`** — against a temp git repo: unrelated dirty files are **never**
  staged; a failed push leaves the commit; a failed build leaves the previous
  `public/` intact.
- **`images.py`** — EXIF is gone after processing; the same bytes produce the
  same key.
- **Template migrations** — built output diffed before/after to prove the
  nav/footer/homepage render identically.

## Risks

| Risk | Mitigation |
|---|---|
| Editor exposed publicly | Four independent guards above, incl. a startup assertion |
| Unrelated work swept into a commit | Explicit path-scoped `git add`, enforced by test |
| Failed build wipes the live site | Build to temp, atomic swap |
| Concurrent edit clobbers a change | File hash guard, refuses stale saves |
| Editor preview drifts from real render | Publish uses the real Zola build |
| Slug change breaks inbound links | Explicit warning before rename |

## Phases

Each phase ends with something usable.

- **Phase 1 — foundation + posts.** The service, `edit.cloudy.nyc`, the deploy
  change (bind-mount + build-and-swap), the publish pipeline, block editing,
  image upload, and `date`/`draft`/`slug`. On its own this means writing and
  publishing from the tablet.
- **Phase 2 — nav + footer.** The schema-driven data editor, used twice, plus
  two small template migrations.
- **Phase 3 — homepage sections.** Nested schema and the largest migration, so
  it goes last.

## Out of scope

- The timeline and lab pages stay code-edited.
- No image library/reuse browser — photos are rarely reused across posts.
- No multi-user anything: one editor, one person, no accounts.
