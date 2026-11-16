# Editor: draft Preview

Date: 2026-11-15. Approved by Peter.

## Why

The editor shows blocks, not the page. Peter wants to see a post, drafts
included, exactly as cloudy.nyc would render it before he publishes.

## Design

- A **Preview** button in the editor bar, beside Publish. Tapping it flushes
  the open editor (`flushPendingEdit`), opens a new tab synchronously (so the
  popup isn't blocked), asks the server to build, then points the tab at the
  post's preview URL. A failed build shows its message in the tab and in the
  status line.
- `POST /api/posts/{slug}/preview` (auth-gated by the existing middleware)
  runs a Zola build of the working tree **with drafts** into a gitignored
  editor-owned dir (`editor/.preview/site`), never `public/`, using the same
  container and config handling as `scripts/build-site.sh` (factor the
  docker invocation into a helper both use, or call a small
  `scripts/build-preview.sh`). `--base-url {EDITOR_BASE_URL}/preview`.
  Serialized with a lock; returns `{url: "/preview/blog/<slug>/"}`.
  A post renamed via aliases still resolves (primary slug).
- `GET /preview/{path:path}` serves files from that dir (index.html for a
  directory), `Cache-Control: no-store`, `X-Robots-Tag: noindex`. Not on the
  public path list, so it requires sign-in like every other route
  (the route-coverage auth test must include it).
- Nothing touches `public/`, the live `web` container, git, or Cloudflare.

## Non-goals

Live auto-refresh, an in-editor preview panel, per-device frames.

## Testing

- pytest: the preview route 401s signed out; the build call is mocked to
  assert `--drafts`, the output dir and base URL; serving resolves
  `blog/<slug>/` to its index.html and refuses `..` traversal.
- One real build of `spruce-the-litter-cleaning-tracker` through the
  running app's code path (in a scratch uvicorn like the verify scripts),
  fetch the preview page, check it contains the post title and the
  `cleanup-13` image, and screenshot it.
