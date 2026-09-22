# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
make dev          # Start development server (Zola + lab backend) - ports 1111 & 3001
make prod         # Build and serve production with nginx on port 8080
make check        # Validate site structure
make logs         # View container logs
make stop         # ⚠ STOPS PRODUCTION TOO - see below
make clean        # Clean up containers and images
make open-local   # Open http://localhost:1111
make open-gh      # Open https://peter.direct
```

⚠ **Stopping the dev server takes the live site down. Both ways.** This caused
two outages on 2026-09-21.

- `make stop` runs `docker compose down` on the **prod** compose first, then
  the dev one. Since the Pi became the origin, removing `web` is an outage.
- `docker compose -f compose.dev.yaml down` is **also unsafe** — both compose
  files resolve to the same project name (`personal-site`), so `down` on the
  dev file also removes the shared `redis` and `lab-backend`. It leaves `web`
  alone, so `cloudy.nyc` keeps answering 200 and looks fine while
  `lab.cloudy.nyc` 502s.

**Safe dev teardown is one container:** `docker rm -f personal-site-zola-1`.
Then `sudo systemctl restart personal-site` and check **`lab.cloudy.nyc`, not
just the apex**. A hand-run `docker compose down` also leaves systemd
reporting the unit `active` while the containers are gone, so the restart is
what re-syncs it.

`make dev` passes `HOST_UID`/`HOST_GID` so the dev container writes `public/`
as you. Without it the dev server ran as root, and any file only it had
produced (a newly added static asset) was left root-owned — which then failed
the next publish, because the promote rsync runs as you and can't `chgrp` a
destination it doesn't own.

Lab backend (standalone):
```bash
cd lab-backend && npm start   # Run backend on port 3001
cd lab-backend && npm test    # Unit + Redis-backed integration tests (needs Docker)
```

After changing lab backend or template code, redeploy the Pi with
`./scripts/build-site.sh` (static site) and `docker compose up -d --build
lab-backend` (socket server); `make deploy-restart` does both plus nginx.

## Architecture

### Static Site (Zola)
- **Framework**: Zola (Rust-based static site generator)
- **Base URL**: https://peter.direct
- **Templates**: Tera templating engine with block inheritance
- **Styling**: All CSS inline in `templates/base.html` (no external stylesheets)

### Content Structure
- `content/blog/*.md` - Blog posts with TOML frontmatter (`+++` delimiters)
- `content/lab/*.md` - Lab experiments, each references a template via `template = "experiment-*.html"`

### Lab Experiments (WebSocket)
The `/lab` section contains real-time collaborative experiments using Socket.IO:

- **Backend**: `lab-backend/server.js` - Express + Socket.IO server with Redis persistence (fallback to in-memory)
- **Session pattern**: Global sessions (`GLOBAL_GO_SESSION`, `GLOBAL_DRAWING_SESSION`) for persistence across reloads
- **UI pattern**: Desktop shows QR code + preview, mobile shows controller (use `?mobile=true` to test)

**The drawing canvas does not read-modify-write per packet** (fixed 2026-09-20).
Pointer events arrive faster than a Redis round trip, so the old handler — load
the stroke array, push one stroke, save it back, all with `await`s — let two
packets load the same version and each save over the other. Every stroke in a
batch but the last was dropped, which is why fast straight lines came back
broken. Now:

- `lab-backend/drawing-store.js` holds the canvas in memory as the source of
  truth: loaded from Redis once, mutated **synchronously** (nothing can
  interleave mid-update), written back on a 250ms coalescing timer that loops
  while the session is dirty. Strokes are capped at 20k per session, and
  SIGTERM/SIGINT flush before Redis disconnects.
- The client (`templates/experiment-drawing.html`) queues points and flushes
  once per animation frame as `drawing-data { segments: [...] }`, also flushing
  on pointer-up and on colour change. A single `{fromX, ...}` segment is still
  accepted so older open tabs keep working.
- The server broadcasts **only the new strokes** (`drawing-append`), not the
  whole canvas on every packet; clients draw them incrementally instead of
  clearing and repainting everything.
- Tests: `cd lab-backend && npm test` (needs Docker for the Redis-backed
  integration test). `scripts/verify-lab-drawing.py` drives real Chromium over
  CDP against the deployed page and checks a fast drag stores every point.

Current experiments:
1. `experiment.html` - Shared counter (increment/decrement)
2. `experiment-go.html` - Collaborative 9x9 Go board
3. `experiment-drawing.html` - Real-time drawing canvas

### Timeline Page (`/timeline`)
The timeline page (`templates/timeline.html`) displays work history, projects, talks, and education using a Gantt-style layout.

**Template Structure:**
- `templates/timeline.html` - Contains HTML structure, JavaScript for interactivity, and `panelContent` data
- `templates/base.html` - Contains all CSS (`.gantt-*` classes, `.info-panel` styles, mobile media queries)

**Layout (Desktop):**
- 6-column CSS grid: Education | Employment | Timeline Center | Projects | Civic | Talks
- Grid definition: `grid-template-columns: auto auto 200px auto auto auto`
- Timeline height: `550px`
- Center column has black spine line with year markers (2025, 2020, 2015, 2010, 2005)
- Colored bars positioned absolutely within bar columns

**Card/Bar Data Attributes:**
- `data-id` - Unique identifier linking cards to bars (e.g., "botm", "shipyard", "nycmesh")
- `data-cat` - Category for coloring: "employment", "education", "civic", "projects", "talks"
- `data-connects-card` - For talks, links to the related card (e.g., DevOpsDays talks connect to Shipyard)

**Color Scheme:**
- Employment: Blue (`#4a90e2`)
- Civic: Green (`#2ecc71`)
- Projects: Orange (`#f39c12`)
- Education: Purple (`#9b59b6`)
- Talks: Red (`#e74c3c`)

**Info Panel System:**
- Fixed-position panel appears on hover, shows detailed info about each item
- `pointer-events: auto` when `.visible` class is added (allows hovering over panel)
- Click on card/bar to "pin" the panel open (toggle with same item, or click elsewhere to close)
- Panel positioning: left side of viewport for left-column items, right side for right-column items
- Vertical position clamped to keep panel visible (450px buffer from bottom for tall panels)

**Info Panel Content (`panelContent` object in timeline.html):**
```javascript
'item-id': {
    title: 'Display Title',
    subtitle: 'Role • Date Range',
    description: '<div class="info-panel-site">...</div><ul><li>Bullet points</li></ul><p class="info-panel-link">...</p>'
}
```

**Embedded Content in Panels:**
- **Site previews**: `<div class="info-panel-site"><iframe src="URL" loading="lazy"></iframe></div>`
  - Iframes render at 300% size and scale to 33% for zoomed-out desktop preview
- **YouTube embeds**: `<div class="info-panel-video"><iframe src="https://www.youtube.com/embed/VIDEO_ID" ...></iframe></div>`
- **Links**: `<p class="info-panel-link"><a href="URL" target="_blank"><i class="fa-brands fa-github"></i>View on GitHub →</a></p>`

**Project Subtitles:**
- Open Source projects (Lowkey, Turtle, Snorlax, React Native SSH): "Open Source • YEAR"
- Personal projects: "Personal Project • YEAR"

**Connector Lines (SVG):**
- `drawConnectors()` function draws lines from cards to their corresponding bars
- Talks with `data-connects-card` draw dashed lines to related cards
- Lines and dots get `.highlight` class on hover

**Hover Highlighting:**
- `.gantt-timeline.has-hover` dims all items to 25% opacity
- `.highlight` class restores full opacity on hovered item chain
- Chains include: card → bar → connector lines → connected talks

**Mobile Layout (≤700px):**
- 3-column grid: Left (Education+Employment) | Center (Timeline) | Right (Projects+Civic+Talks)
- Timeline height: `1100px`
- Connector lines hidden
- Info panel hidden (`display: none`)
- Project card positions overridden with `!important` for proper spacing:
  ```css
  .gantt-projects .gantt-card[data-id="dontdie"] { top: 1% !important; }
  .gantt-projects .gantt-card[data-id="lowkey"] { top: 5% !important; }
  /* etc. */
  ```

**Important Constraints:**
- Cards and bars both have `cursor: pointer` for click affordance
- Items in the same column should not overlap vertically
- Mobile overrides use `!important` to ensure proper positioning

### Template System
- `templates/base.html` - Base layout (includes all CSS, nav, footer, cloud animations)
- `templates/index.html` - Homepage
- `templates/section.html` - Blog listing
- `templates/page.html` - Individual blog post
- `templates/timeline.html` - Timeline page with work history
- `templates/lab.html` - Lab index (embeds all experiments inline)
- `templates/experiment-*.html` - Individual experiment pages
- `templates/404.html` - Not-found page (see below)

**The site is called "Peter @ WWW" and every `<title>` says so** (settled
2026-09-21). `base.html` defines the default; every other template overrides
`{% block title %}` as `<page name> - Peter @ WWW`. Half the templates used to
end in `- Peter Valdez`, which is the *author*, not the site. `config.toml`'s
root `title` is the same string because the feed template reads it; `author`
stays `Peter Valdez`.

**`404.html` exists because Zola's built-in fallback is a two-line page** with
no nav, no CSS and a bare `404 Not Found` title. Adding it forced one change in
`base.html`: the nav's active-link checks are `{% if current_path is defined
and … %}`, because **Zola renders `404.html` without `current_path` in the
context** and an unguarded `current_path == "/"` hard-fails the whole build.
Any new `base.html` use of a page-scoped variable needs the same guard.

### Typography (added 2026-09-21)

Everything used to be the system font stack at every size, which is what made
the site read as untouched. Two families now, set as `--font-text` and
`--font-display` on `:root` in `templates/base.html`:

- **Sentient** (serif, Fontshare) — `h1`–`h4` and post titles.
- **Switzer** (grotesque, Fontshare) — running text, nav, UI, meta.
- Code keeps the existing `Monaco/Menlo/Ubuntu Mono` stack.

⚠ **Each family needs its own `<link>`. The Fontshare API honours only the
first `f[]` parameter and silently drops the rest** — the obvious combined
`?f[]=sentient…&f[]=switzer…` URL returns Sentient alone. The failure is quiet:
text still renders in the fallback stack with *synthesised* weights, so it
looks like a styling bug (the nav rendering too heavy) rather than a font that
never loaded. Check `document.fonts` before believing a weight problem.

**One type scale for the whole site**: `h1` 2rem, `h2` 1.5, `h3` 1.25, `h4`
1.0625, all weight 500. `h1`/`h2` were previously 1.6/1.5rem — near enough to
read as the same level.

Changing font metrics is **not** cosmetic here: `/timeline` positions its cards
absolutely with hand-tuned percentages, so re-check that page (desktop *and*
mobile) for card overlap after any type change.

### Responsive layout (reworked 2026-09-20)

Two layouts here "break out" of the 700px `.container`, and both used to do it
with hand-computed `calc()` math that only landed centered at one specific
viewport width. Both now use the same correct idiom — **an outer element bled
to `100vw` via `margin-left: calc(50% - 50vw)`, and an inner element that caps
its width and `margin: 0 auto`s inside it**. One element can't do both jobs:
mixing a container-relative `margin-left` with an own-width-relative
`translateX` (the old approach) only cancels out at a single width, and visibly
drifts off-center everywhere else.

- **`/blog` (`section.html`)** is a plain index — **no JavaScript at all**, and
  no longer a single-page app (reworked 2026-09-21). It used to inline every
  post and switch between them client-side, which cost 184KB of HTML
  referencing 7MB of media on a page where you read one post; posts are real
  pages now and the index is 70KB. The list is **continuous, not grouped by
  year**: posting here is irregular, so year blocks carved the page into
  lopsided chunks and made the quiet years read as holes. The year marks the
  margin only where it changes (`set_global shown_year` in the Tera loop).
  Rows align on `align-items: baseline` at the grid level with the padding on
  the row rather than the link, which is what puts the year marker and date on
  the title's baseline.
- **The index rows sit in weather** (added 2026-09-21) — the page was
  deliberately bare (no rules, no cards, spacing doing all the work) and read
  as unfinished. Each row now carries a soft cloud and a fading horizon
  hairline instead of a rule. It is the site's own motif: the same triple-puff
  shape the home page's `VoxelCloudSystem` draws, at a tenth of the opacity,
  in the same `rgba(116,196,231,…)` sky blue. Three properties are
  load-bearing, each because its absence looked wrong on screen:
  - **The cloud spills `-1.5rem` past its row vertically.** Sized to its own
    row it becomes a band, and ten bands is a striped table — the first
    attempt looked exactly like the card stack it was meant to avoid.
    Overflowing means no cloud shares an edge with the row behind it.
  - **The lobes are centred in the top quarter of that box** — the air *above*
    the title, not behind it. Centred on the row they landed square on the
    words and read as blue highlighter.
  - **Every gradient stop ends in `rgba(116,196,231,0)`, never `transparent`.**
    Engines interpolate `transparent` through transparent *black* and leave a
    grey fringe across the fade.
  Per-row variation rides on custom properties the pseudo-element composes
  (`--cx` position, `--ps` scale, `--puff` opacity) rather than on `::before`
  rules directly — that is what lets a row's scatter and the hover drift
  coexist instead of overwriting each other, and the `:hover` block must stay
  *after* the `nth-child` scatter since both are specificity (0,2,1).
  **`--ps` only ever scales down**: a transform grows the pseudo-element's
  scrollable overflow area and that box already reaches exactly the viewport
  edge on a phone (`inset: … -1rem`, body padding `1rem`), so scaling any
  cloud up buys a horizontal scrollbar. The ambient drift animates
  `translate`, not `transform`, so it does not clobber the scatter, and it is
  gated behind `prefers-reduced-motion: no-preference`.
- **The index is two columns** (changed 2026-09-21) — the title, and one date
  cell carrying the day and the year together (`Sep 20 2026`, the year a shade
  lighter). The year used to sit in its own left-hand gutter, which made every
  row a three-part grid for one piece of metadata; the row is a plain block
  now. The gap before the year is **a real space in the markup** plus a small
  margin, not margin alone: spacing it visually while `textContent` still read
  `Sep 202026` handed that string to screen readers and to anyone copying the
  line.
- **A pair of gulls crosses the list** every 38s, visible for about a third of
  that, flying behind the rows and behind their clouds. Both of its
  load-bearing details are non-obvious:
  - **A `translate` percentage resolves against the element's own box**, not
    its container. Animating the 17px bird to `104%` moved it 17px and read as
    a twitch. The bird therefore rides a **full-width runner**
    (`.archive-bird`) with the graphic hung off `::before`/`::after`, so `104%`
    is an actual crossing.
  - **The runner must be clipped, and not by `.archive-sky`.** Translated past
    100% it extends the page's scrollable area and hands a phone a horizontal
    scrollbar; clipping on `.archive-sky` instead would cut the rows' clouds,
    which spill 1rem sideways on purpose. Hence the dedicated
    `.archive-flightpath` layer with `overflow: hidden`.
  The path and the wing beat are separate animations on separate elements
  because they need separate timings — on one element the `animation`
  shorthand's second declaration just replaces the first. The pair shares one
  runner so they fly a single path, and flap on slightly different beats
  because synchronised wings look mechanical.
- **The titles carry a rest-state underline, and that is an accessibility fix
  rather than a style** (added 2026-09-21). They previously sat at `#1a1a1a`
  with `text-decoration: none` and signalled nothing until `:hover` turned
  them blue — which on a touch screen is no signal at all. The underline uses
  the gulls' own ink held at 62% (`rgba(94,135,152,0.62)`) rather than a link
  blue, so the affordance belongs to the page's palette; at full strength the
  nine underlines plus nine row rules read as ruled paper, which is why the
  row rule came down to 0.22 at the same time. It is a real
  `text-decoration`, not a faded gradient matching the row separators: the
  faded version is prettier and measurably less obviously a link.
  `:active` (the only feedback a tap gets) and a `:focus-visible` ring were
  both missing entirely and now exist.
- ⚠ **The row's padding lives on `.archive-link`, not on `.archive-row`.**
  That is a touch target, not a style choice: with the padding on the row the
  anchor measured **700x26**, so a finger had to find a 26px strip while the
  airy padding above and below it did nothing — well under the 44px minimum.
  On the link, the anchor fills the whole 700x60 row. Baseline alignment is
  unaffected because both columns live inside that flex box. Don't move it
  back.
- ⚠ **The nav's `marquee` animation is the one thing on these pages that
  ignores `prefers-reduced-motion`.** Everything the blog index adds stops
  under `reduce` (the bird settles at opacity 0 rather than freezing
  mid-flight); the scrolling site title does not, on any page.
- **`.bleed` opts any block out of the reading column and across the whole
  viewport** (added 2026-09-21; first use is the localmart three.js
  visualization). It is the same two-layer idiom `lab.html` documents —
  `width: 100vw` plus `margin-inline: calc(50% - 50vw)` on the outer element,
  and an optional `.bleed-inner` that re-caps and centres inside that strip.
  One element cannot do both jobs; see the `lab.html` comment for the version
  that drifted off-centre.
- ⚠ **`body { overflow-x: clip }` is what makes `.bleed` safe, and it is load
  bearing.** `html` sets `scrollbar-gutter: stable`, so the gutter is always
  reserved and `100vw` is wider than the client width by exactly the
  scrollbar — without the clip, every page with a bleed gets a horizontal
  scrollbar for those last ~15px. It must be `clip` and not `hidden`:
  `hidden` would make `body` a scroll container and break `position: sticky`
  and scroll anchoring on the vertical axis.
- **The localmart visualization is full-bleed** and sizes itself from
  `container.offsetWidth/offsetHeight` (camera aspect *and*
  `renderer.setSize`), with a `resize` listener, so the bleed needed no JS
  change. Its height is `min(64vh, 760px)` with a `380px` floor rather than a
  fixed `600px`, because at a fixed height a full-bleed box letterboxes on a
  wide screen — and since the camera takes its aspect from the box, a wider
  box just fans the field of view out flat. Its control panel is pinned with
  `right: max(20px, calc(50% - 440px))`, which parks it at the *post column's*
  right edge on a wide screen instead of flinging it to the far side of a 27"
  monitor. ⚠ **The scene itself does not grow with the viewport** — camera
  distance is fixed, so past roughly 1600px the extra width becomes empty
  sky. Fixing that means scaling camera distance with aspect in the post's
  own JS.
- ⚠ **Testing this page headless needs software WebGL.** With plain
  `--disable-gpu` the renderer throws `Error creating WebGL context` and the
  canvas silently stays at its default `300x150` while CSS stretches it to
  fill — which looks exactly like a sizing bug in the page. Add
  `--enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader`.
- **Post pages (`page.html`) read at `min(900px, 94vw)`**, not the site's 700px
  default — that is the width the `.img-row`/`.video-row` size presets were
  tuned against. `.container.post-container > nav:not(.post-nav)` is deliberate:
  the prev/next block is itself a `<nav>` and belongs at the post's full width,
  not the site nav's 700px.
- **Prev/next on posts is written but inert.** Zola hands this template no
  `page.earlier`/`page.later` (nor `lighter`/`heavier`) for these pages, so the
  block is wrapped in `{% if page.later or page.earlier %}` — unguarded it
  rendered as a bare rule and empty space under every post. Left in place
  because the markup is right; it starts working if the neighbours ever resolve.
- **`/blog/#<slug>` hash links no longer resolve** — they were how the SPA
  selected a post. Deliberately not shimmed.
- **`/` (`index.html`)** widens to `min(1080px, 92vw)` at ≥1000px and flows its
  sections into two columns via **`column-count`, not a grid** — the browser
  balances them, so adding a section later doesn't need the split re-hardcoded.
  `.home-intro` is a `flow-root`: without it the floated photo escapes the
  intro and the multi-column box shrinks sideways to avoid the float instead of
  using the full width. The "Author of" list links **live sites, not repos**,
  and only things that are actually publicly reachable — check
  `http-routing/cloudflared/config.yml` for that, not a curl from the Pi, since
  LAN-only hosts answer 200 from here and would be dead links for visitors.
- **`/lab` (`lab.html`)** uses the same bleed pattern for the experiments grid.
  The Go board and drawing canvas size up on `(min-width: 700px)` via JS, not
  CSS: both compute geometry from a pixel size (the board's `boardSize`, the
  canvas's `width`/`height` **attributes**), and pointer/touch coordinates come
  from `getBoundingClientRect()`. Scaling the canvas with CSS instead would
  leave the drawing buffer at the old resolution and put every stroke off from
  the finger.

### Deployment
- GitHub Pages via `.github/workflows/deploy.yml` — builds with
  `--base-url https://peter.direct`, the original/primary deployment.
- Zola v0.20.0 builds to `public/` directory
- Lab backend deployed separately on Render.com (`render.yaml`) for the GitHub
  Pages deployment.
- **Self-hosted on the Pi (berryfive) at `cloudy.nyc`**, added 2026-09-20 —
  same repo, a second deployment via `compose.yaml` (nginx serving a Zola
  build with `--base-url https://cloudy.nyc`, plus `lab-backend` + `redis`),
  fronted by `http-routing`/Caddy per that project's usual flow. `make
  deploy-up` / `make deploy-restart` / `make install` (boot systemd unit,
  `systemd/personal-site.service`). Ports: `web` on loopback `:8802`,
  `lab-backend` on loopback `:8803` (container-internal port stays 3001 —
  ig-parser already owns `:3001` on the Pi, so only the host-side mapping
  changed), `redis` has no host port at all. `lab.cloudy.nyc` is a separate
  Caddy/tunnel host for the Socket.IO backend (`getBackendUrl()` in
  `templates/lab.html` + the three `experiment-*.html` files, and CORS in
  `lab-backend/server.js`, both special-case `cloudy.nyc`/`www.cloudy.nyc`
  hostnames — same pattern as the existing `peter.direct` case, don't remove
  it when touching that logic). `www.cloudy.nyc` 301s to the apex. Full routing
  details: `~/projects/personal/http-routing/CLAUDE.md`.
- **The Pi is the origin, Cloudflare is the cache** (settled 2026-09-21). Pages
  are served by the `web` container and held at the Cloudflare edge for **30
  days**, so the Pi sees almost no real traffic and a cached site keeps serving
  while this machine is off. **`make publish-site` = build + purge**, and the
  purge is the part that publishes: the build only updates the origin, which
  nobody reads directly. `scripts/publish-site.sh` exits non-zero if the purge
  fails, so a "published" message always means readers actually see the change.
  ⚠ **The `web` container being up is now the whole site, not a convenience.**
  It used to be a local preview while S3 served the public, so a stopped
  container was invisible; it is now an outage. Uptime Kuma monitors 41-43 watch
  the apex, images and lab backend.
  For one day (2026-09-20 → 09-21) this was inverted — Cloudflare read the pages
  straight out of an S3 website bucket and the Pi was out of the path entirely.
  That bucket (`personal-cloud-infra modules/personal-site-pages`) still exists
  but is **no longer written to, so its contents are stale**; don't treat it as a
  live rollback without re-syncing `public/` first.
- **`web` runs a custom nginx conf, `nginx/site.conf`** (added 2026-09-21),
  bind-mounted over `conf.d/default.conf`. It is the stock `nginx:alpine`
  server block plus `error_page 404 /404.html` — without that, a missing path
  gets nginx's own plain page and the site's 404 template is unreachable
  (GitHub Pages picks up `404.html` on its own; nginx does not). There is
  deliberately **no `internal;`** on the `/404.html` location, so the page is
  also directly fetchable with a 200, matching Pages. ⚠ It is a **single-file
  bind mount**: editing it and reloading serves the stale inode, so changes
  need `docker compose up -d --force-recreate web` (same trap as
  `http-routing`'s Caddyfile).
- **Blog post images live in S3, not this repo** (added 2026-09-20, first post:
  `guerilla-gardening.md`) — public-read bucket (`personal-cloud-infra`
  `modules/personal-site-images`), served at `img.cloudy.nyc` and edge-cached
  by Cloudflare, so real traffic never touches the Pi (only a cache miss does).
  To add images to a post: `make upload-image SLUG=<post-slug> NAME=<name>
  FILE=<path>` (strips EXIF, resizes to 1600px longest edge, re-encodes JPEG,
  uploads with a far-future `Cache-Control`, prints the `https://img.cloudy.nyc/...`
  URL to paste into the post as a normal `![alt](url)`). Needs `.aws.env`
  (gitignored) — `make sync-personal-site-images` in `personal-cloud-infra`
  writes it. `templates/base.html`'s `.container img` rule makes embedded
  images responsive (didn't exist before this post; no prior post had images).
  **The S3 key is content-hashed** (`editor/images.py::image_key`,
  `editor/videos.py::video_key`) — `scripts/upload-image.py` and
  `scripts/upload-video.py` import those same functions rather than building
  their own `<slug>/<name>.ext` key (fixed 2026-09-21; the original CLI
  scripts didn't hash, which is dangerous specifically *because* the
  Cache-Control is `immutable`: re-uploading a corrected file under the same
  `NAME` reused the URL, and immutable tells every cache to never even
  re-check it). `editor/tests/test_images.py` and `test_videos.py` each have
  a `test_cli_upload_path_shares_the_content_addressed_key` guarding this,
  same pattern as `test_both_upload_paths_share_one_encoder_definition` in
  `test_video_encoding.py`. **All seven `guerilla-gardening` clips were
  rekeyed** (2026-09-22, by copying each object's existing bytes to its
  `video_key` under the same bucket, repointing the post, publishing, then
  deleting the old unhashed key — no re-encode, so the bytes and their SDR
  tags are byte-identical to before). `flowers-in-trunk.jpg` is the one asset
  still on the old unhashed scheme; the two images uploaded through the
  tablet editor before this fix already carry a hash suffix.
  **Several photos in a row in the source material (e.g. a litter-patrol
  sequence, before/after pairs) render as a row, not stacked** — wrap them in
  `<div class="img-row">...</div>` with raw `<img src="..." alt="...">` tags
  (not markdown `![]()` — avoids ambiguity in how the markdown parser wraps
  consecutive image lines in `<p>`s). `.img-row` and `.video-row` are **flex,
  not grid** (changed 2026-09-21): a row of three wrapping to two-plus-one left
  the leftover in grid column 1 with dead space beside it, and grid has no way
  to centre a partial last row. Items are capped at `calc(50% - 0.375rem)` so
  that leftover keeps its siblings' size rather than growing to fill its line —
  50% is the tightest cap that still allows two side by side. **A row holding a
  single item opts out of the cap** (`:only-child`); those rows are sizing
  wrappers, not rows, and must still fill the width their size class allows.
  See `guerilla-gardening.md` for two worked examples. A **standalone** image
  (not in an `.img-row`) is centered (`.container img { margin: 1.5rem auto }`)
  rather than flush-left, since most photos render narrower than the 700px
  content column.
- **Stripping location/device metadata on upload is load-bearing privacy
  protection, not incidental.** `editor/images.py::process_image`'s PIL
  re-encode drops EXIF (and with it GPS) by construction — Pillow never
  carries EXIF forward unless you pass `exif=` explicitly. **Video needs the
  explicit equivalent**: `editor/videos.py::process_video` and
  `scripts/upload-video.py::process` both pass `-map_metadata -1` to ffmpeg.
  Without it, ffmpeg preserves container/global metadata across a re-encode
  by default — a real 2026-09-20 incident published the owner's home GPS
  coordinates (`TAG:location`/`location-eng`) and phone model
  (`TAG:com.android.model`/`manufacturer`) on 14 live clips at
  `img.cloudy.nyc` before this was caught and fixed. Verified empirically
  with `ffprobe` on real phone clips (`format_tags` vs `stream_tags`) that
  these tags live at the container level only, so `-map_metadata -1` alone
  is sufficient — no per-stream `-map_metadata:s:v -1` needed, but don't
  assume that holds for a future source format without re-checking with
  `ffprobe`. **Any new media type added to this pipeline (audio? a GIF
  path?) needs the same audit before its first upload**, not after a leak:
  re-encode-only is not automatically metadata-stripping — check what the
  encoder actually drops with `ffprobe -show_entries format_tags:stream_tags`
  on a real source file, don't assume.
- **Video encode settings live in `editor/ffmpeg_args.py` — one definition for
  both upload paths** (`editor/videos.py` and `scripts/upload-video.py`; a test
  asserts the CLI doesn't re-hardcode flags). Three things in there are
  load-bearing, all added 2026-09-21 after the guerilla-gardening clips played
  at a few frames per second on a phone and looked brighter than the page:
  - **HDR sources must be tone-mapped, not just bit-depth-reduced.** Phone video
    is HLG/BT.2020 (`color_transfer=arib-std-b67`). `-pix_fmt yuv420p` drops it
    to 8 bit but carries the HDR *tags* through, so the file is SDR-ish data
    still labelled HDR and an HDR phone screen renders it through the HDR path.
    The zscale/tonemap chain converts it and the colour flags re-tag it BT.709.
    It is applied **only when the source is HDR** — that curve would crush an
    already-SDR clip.
  - **`is_hdr()` parses `-of default=nw=1`, not `csv=p=0`, on purpose.** Real
    handheld clips carry display-matrix (rotation) side data, which pads CSV
    output with a trailing field so the value reads `"arib-std-b67,"` and never
    matches. Synthetic test clips have no rotation and hid this — the test suite
    now builds a rotated clip specifically to keep it caught.
  - **`-g`/`-keyint_min` are not a size tweak.** Clips previously had exactly one
    keyframe, and `templates/base.html`'s loop-sync corrects drift by assigning
    `currentTime`, which is a seek — every correction re-decoded from frame 0.
    That fed back into more drift. The sync code now nudges `playbackRate`
    instead and only seeks as a rate-limited last resort, but both halves matter:
    don't restore a long GOP, and don't reintroduce per-frame seeking.
- **Editing from a tablet:** `edit.cloudy.nyc` (LAN-only) runs `blog-editor.service`
  from `editor/`. It edits `content/blog/*.md` in the working tree, uploads photos
  to S3, and on Publish commits only `content/blog/` paths, pushes, and rebuilds
  the live site via `scripts/publish-site.sh` (build + Cloudflare purge). Design: `docs/superpowers/specs/2026-09-20-blog-editor-design.md`.
  ⚠ The service refuses to start if `edit.cloudy.nyc` is ever added to the
  cloudflared tunnel config — it must stay LAN-only.

### How the editor edits (the rules that keep it from eating posts)

`editor/` is a FastAPI service; `docs/superpowers/specs/2026-09-20-blog-editor-design.md`
is the design. Three properties are load-bearing — each exists because its
absence caused a real bug here.

- **Every edit is a line splice into the markdown source.** `editor/blocks.py`
  indexes a post body into top-level blocks carrying their source line ranges;
  editing replaces those lines. The editor NEVER reconstructs markdown from
  rendered HTML, so bytes outside the edited range are untouched by
  construction. `move_block` and the merge route are splice-out + splice-in on
  the same primitives — don't add an edit path that re-serialises the document.
- **Structured editors are offered only when parsing is provably lossless.**
  `images.parse_images` / `videos.parse_videos` regenerate markup from what
  they parsed and compare it **byte-for-byte** against the original block
  source, returning `None` on any mismatch; the API then omits `images`/
  `videos` and the client falls back to a raw textarea. Gate the UI on that
  key being present, never on `block.kind`. An early version matched only one
  exact `<img>` shape, silently dropped tags it didn't recognise, and
  regenerated the block without them — deleting photos from a live post. A
  merge refuses if EITHER side parses lossily, for the same reason.
- **Post writes go through `_write_body` → `_atomic_write_text`.** That gives
  the staleness hash check (409 rather than clobbering an edit made from a
  terminal), a temp-file + `os.replace` write (a crash can't truncate a post),
  and **preservation of the file mode** — an earlier atomic-write fix dropped
  posts to 0600 via `mkstemp`, which breaks the containerised Zola build since
  it runs as a different UID.

Block kinds and their editors: `image` (standalone markdown), `img_row` and
`video` (side-by-side grids) get thumbnail strips with add/remove/reorder,
alt text, and Small/Medium/Full size presets; everything else gets a markdown
textarea. Any block can be moved (pick it up, tap a gap) or merged with an
adjacent same-family block. A media row adjacent to a paragraph or list gets
a different pair control instead -- "put the row beside this text", which
floats it (see below).

- **"Split out" is how a clip escapes its row.** `move_block` moves blocks, not
  clips, so a clip sharing a `video` row had no way to reach a distant part of
  the post. `POST .../blocks/{index}/videos/split` lifts one clip into a row of
  its own directly below (inheriting the source row's size), which the ordinary
  block move can then place anywhere. Three things are load-bearing:
  - **It takes the row's whole clip list, not just the split index.** The row
    editor keeps a local working copy and only commits on Done, so reordering
    and *then* splitting has to arrive as one request or the reorder is lost.
  - **Both halves run in one `_write_body` transform** (`replace_block` then
    `insert_block` at `index + 1` — `replace_block` doesn't change the block
    count, so that's still the gap just below). As two requests the second
    could 409 and strand the post half-split.
  - **A row of fewer than two clips is a 400, not a no-op.** It is already its
    own row, and letting it through would hit the "empty clip list deletes the
    block" rule and silently delete it instead of splitting it.
  The button sits on its own full-width line under each thumbnail rather than
  beside the ←/→/× row: a fourth button across a 140px thumb falls under the
  44px touch target the other controls are sized to. Unlike them it commits
  immediately, because it changes the block list and the local `clips` array
  can't represent a clip that now lives in a different block.

- **`editor.js`/`editor.css` are served at content-hashed paths, same
  `stem-<8 hex sha256>.ext` shape `editor/images.py::image_key` uses for S3
  keys — one hashing convention rather than two.** `editor_page`
  (`editor/app.py`) rewrites `/static/editor.js` to `/static/editor-<hash>.js`
  when it serves `index.html`; `RevalidatedStaticFiles.get_response` resolves
  a hashed request back to the real file and answers with
  `public, max-age=31536000, immutable`. This exists because `StaticFiles`
  sends an ETag/Last-Modified but no `Cache-Control`, and with none a browser
  falls back to *heuristic* freshness (commonly 10% of the file's age since
  Last-Modified) — a long-unchanged `editor.js` earns a multi-hour window, so
  a just-shipped feature looks "cached" and missing on the tablet, and
  **that window can't be revoked after the fact**: a later `no-cache` header
  only governs responses served from then on, it can't reach a copy the
  browser is already holding. The hashed path sidesteps the whole problem —
  the page names a URL the browser has never seen, so there's nothing stale
  to reuse. A plain unhashed request (`/static/editor.js` — a tab still on an
  old page) still resolves, but only with `no-cache`, so it costs one 304 per
  load instead of serving silently stale for hours. The hash in a hashed
  request is **not** verified against the current file's hash before
  serving — unlike S3, only one copy of `editor.js` exists on disk, so a
  stale hash has no older version to look up; it just gets today's file,
  which is correct since that tab was headed for the current editor either
  way. `editor_page` itself answers `no-cache` for the same bootstrap
  reason: a heuristically cached shell would keep naming the OLD hashes
  forever.

- **"Beside text" is a float, not a two-column block.** Putting a vertical
  clip next to a paragraph is a third class on the row (`<div class="video-row
  size-medium beside-right">`) plus `float: right` -- deliberately NOT a new
  block kind holding both. A merged wrapper would have to contain markdown
  inside HTML, which CommonMark doesn't parse, so keeping links and emphasis
  alive means the wrapper spans several top-level tokens -- and `blocks.py`'s
  whole model is one top-level token per block. The float buys the same
  layout with no change to that model, at the cost of the text wrapping back
  to full width under the row once it runs past it (which is usually what you
  want anyway).
  - **`side` is orthogonal to `size`**, not three more presets: a row is
    "medium, floated right". `none` writes no class at all, so every row
    published before this existed stays byte-identical -- the same discipline
    that keeps `size-full` implicit.
  - **A full-width row can't float and is refused at the boundary**
    (`markdown_for` raises): a row capped at 100% leaves the text no column,
    so the pair would silently render as a plain stack. Both the one-tap
    action and the editor's side buttons therefore narrow a full-width row to
    **medium** when you float it, and picking Full drops the side. That
    constraint lives in exactly one place on each side of the wire
    (`markdown_for`, and `framingControls()` in editor.js) or the two row
    editors drift apart.
  - **Three supporting rules in `base.html` are load-bearing**, each fixing a
    way floats leak: `h1,h2,h3,h4 { clear: both }` (or the next section's
    title rides up beside the video -- this is also *why* `app.py` refuses to
    pair a heading with a row, and a test pins the two together);
    `.container { display: flow-root }` (or a float taller than its text
    escapes the post and overlaps the footer); and a `max-width: 700px`
    unfloat (below the reading column's own width even the 240px preset
    leaves an unreadable measure).
  - **`POST .../blocks/{index}/beside` floats AND moves in one write.** A
    float only wraps what follows it, so when the row sits below its
    paragraph the row has to be lifted above it too -- one `_write_body`
    transform, same reasoning as the clip split: as two requests the second
    could 409 and strand the post with a floated row in the wrong place.
    `index` names the UPPER block of the pair, the convention `/merge` uses,
    because the control that drives it sits in the gap between the two.
  - **The editor lets the float escape its own `.block`** (`#blocks` carries
    the `flow-root` instead). Each block is a separate div, so a float
    contained inside its own box would sit beside an empty strip and the
    paragraph would start below it -- the exact thing the feature exists to
    avoid, previewed wrong. Left to escape, the following block's line boxes
    wrap around it the way the published page does.

- **Sizing a standalone image is opt-in by design.** Markdown has nowhere to
  hang a class, so a lone photo at default size stays `![alt](url)`; choosing a
  non-default size converts it to `<div class="img-row size-small">`, and
  setting it back returns it to markdown. This is what keeps existing posts
  from being rewritten — an unsized legacy row parses as default and
  regenerates **unsized**, so an unrelated edit can't stamp `size-full` onto it.
- **The size widths are duplicated by hand** in `templates/base.html` (the
  published site) and `editor/web/editor.css` (the editor). A test asserts they
  match; without it a one-sided edit looks right while editing and wrong once
  published. If you add a size, change both.
- **Block controls live in a sibling node to the content** (`.block-content`),
  because opening an editor used to `innerHTML = ''` the whole block and take
  the controls with it. Cancel restores by calling `renderBlocks()`, not by
  patching HTML — the old patch raced the block's own click listener and
  silently reopened the editor. Control actions call `flushPendingEdit()` first:
  the `mousedown preventDefault()` that keeps the toolbar clickable also
  suppresses the blur that would have saved an open textarea, so without the
  flush a tap would discard typing with no warning.


## Git Workflow
- Use simple present tense commit messages (e.g., "Add dark mode toggle")
- Do not include Claude Code footer in commits
- Wait for user to verify fixes before staging/committing
- Only commit when explicitly told to do so
- "test, add, commit" means: run tests, if passing then git add and commit
