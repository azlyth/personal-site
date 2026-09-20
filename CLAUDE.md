# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
make dev          # Start development server (Zola + lab backend) - ports 1111 & 3001
make prod         # Build and serve production with nginx on port 8080
make check        # Validate site structure
make logs         # View container logs
make stop         # Stop running containers
make clean        # Clean up containers and images
make open-local   # Open http://localhost:1111
make open-gh      # Open https://peter.direct
```

Lab backend (standalone):
```bash
cd lab-backend && npm start   # Run backend on port 3001
```

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
- `templates/projects.html` - Timeline/Projects page with work history
- `templates/lab.html` - Lab index (embeds all experiments inline)
- `templates/experiment-*.html` - Individual experiment pages

### Responsive layout (reworked 2026-09-20)

Two layouts here "break out" of the 700px `.container`, and both used to do it
with hand-computed `calc()` math that only landed centered at one specific
viewport width. Both now use the same correct idiom — **an outer element bled
to `100vw` via `margin-left: calc(50% - 50vw)`, and an inner element that caps
its width and `margin: 0 auto`s inside it**. One element can't do both jobs:
mixing a container-relative `margin-left` with an own-width-relative
`translateX` (the old approach) only cancels out at a single width, and visibly
drifts off-center everywhere else.

- **`/blog` (`section.html`)** is a desktop-only SPA: sidebar post list on the
  left, full post on the right, switched client-side by slug hash. Below 768px
  `.blog-content` is hidden entirely and the sidebar becomes a plain list whose
  items navigate to the real `/blog/<slug>/` permalinks (`page.html`). The
  two-column layout is a **CSS grid** (`260px minmax(0, 1fr)`) with a
  `position: sticky` sidebar — it was `position: fixed` plus `calc()` offsets
  hardcoded to a 900px container, so the post column could never grow past
  630px no matter the screen. Container now scales to `min(1400px, 94vw)`,
  post column caps at 900px, and post body text steps up at 1000px/1300px so a
  wider column doesn't read thin. The sticky (not fixed) sidebar is also what
  lets the footer clear it without the old margin hack.
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
  **Several photos in a row in the source material (e.g. a litter-patrol
  sequence, before/after pairs) render as a row, not stacked** — wrap them in
  `<div class="img-row">...</div>` with raw `<img src="..." alt="...">` tags
  (not markdown `![]()` — avoids ambiguity in how the markdown parser wraps
  consecutive image lines in `<p>`s). `.img-row` is a CSS grid
  (`repeat(auto-fit, minmax(140px, 1fr))` in `templates/base.html`) that lays
  images out side by side and wraps gracefully on narrow screens. See
  `guerilla-gardening.md` for two worked examples. A **standalone** image
  (not in an `.img-row`) is centered (`.container img { margin: 1.5rem auto }`)
  rather than flush-left, since most photos render narrower than the 700px
  content column.

## Git Workflow
- Use simple present tense commit messages (e.g., "Add dark mode toggle")
- Do not include Claude Code footer in commits
- Wait for user to verify fixes before staging/committing
- Only commit when explicitly told to do so
- "test, add, commit" means: run tests, if passing then git add and commit
