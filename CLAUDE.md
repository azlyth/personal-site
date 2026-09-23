# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
make dev          # Start development server (Zola + lab backend) - ports 1111 & 3001
make prod         # Build and serve production with nginx on port 8080
make check        # Validate site structure (zola check + check-fit)
make check-fit    # Pages meant to be one screenful still fit one (FIT_URL=... to retarget)
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

⚠ **`make dev` takes the lab backend down with it** (2026-09-22).
`compose.dev.yaml` publishes lab-backend on `3001:3001`, and **ig-parser**, a
native systemd service, already owns `127.0.0.1:3001` — so compose removes the
running prod container, fails to bind its replacement, and leaves
`lab.cloudy.nyc` dead while `cloudy.nyc` keeps answering 200. Start only the
service you actually want:

```bash
docker compose -f compose.dev.yaml up -d zola   # dev server on :1111, nothing else touched
docker rm -f personal-site-zola-1               # and that is the whole teardown
```

If `make dev` has already done it, restore prod with `docker compose -f
compose.yaml up -d lab-backend` and verify with `curl -s -o /dev/null -w '%{http_code}'
http://127.0.0.1:8803/games` — the backend answers **404 at `/`** even when healthy,
so the apex tells you nothing.

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
- `content/lab/_index.md` - the games page; there are no per-game content files (see The Lab below)

### The Lab (`/lab`)

`/lab` is **one page holding six games** — chess, checkers, Connect Four,
tic-tac-toe, Go and the finger-painting canvas — behind a menu of tiles.
Picking a tile sets `location.hash` (`/lab/#chess`), so a game is a link you
can send someone and the back button walks out to the menu. Rebuilt
2026-09-21; before that the page rendered three experiments live side by side
and each also had its own `/lab/experiment-N` page.

Every game is **one global board shared by everyone on the internet**. There
are no rooms and no accounts. That is the point, and it is what the Go board
and the canvas already did.

**Adding a game is two files.** Nothing else should need to change:

1. `lab-backend/games/<id>.js` — the rules, as pure functions. `initialState()`
   and `applyMove(state, move)` returning `{state}` or `{error}`, no sockets,
   no Redis, no clock, and **no mutation of the state it is handed**. Register
   it in `games/index.js`, which documents the contract in full. Being pure is
   the only reason a chess engine is testable here at all. It also declares
   `seats` — and **each seat id must be exactly a value `state.turn` takes**,
   since that comparison is the whole of side enforcement.
2. `templates/games/<id>.html` — the renderer. A `<section class="game-panel"
   data-game="<id>" hidden>`, scoped CSS, and a `LabGames.register(...)` call.
   Then one `{% include %}` line in `lab.html`.

**Chess delegates to `chess.js`** (1.4.0, BSD-2, zero deps). Castling, en
passant, promotion, check, checkmate, stalemate, threefold and the fifty-move
rule are all its job. Note 1.4.0's `move()` **throws** on an illegal move
rather than returning null, and it throws on a promoting move with no
`promotion` field — `games/chess.js` passes `promotion: 'q'` unconditionally,
which chess.js ignores on non-promoting moves. Do not hand-roll any of this.

**Sides are shared, not claimed** (added 2026-09-22). The picker in the shared
chrome binds YOU to White; it does not reserve White from anyone else, and
several people can be on a side at once. That choice is deliberate and it is
what makes the feature small: no ownership, no release-on-disconnect, no idle
takeover timer, and nobody can squat a seat on a public board. **"Both" is the
default**, so playing both sides by yourself — how the boards worked before —
is unchanged. The choice is per game, kept in `localStorage` under
`lab-seat-<id>`, sent with `game-join` and again on `game-seat`. Enforcement is
one comparison in `game-move`: bound, and it isn't your turn, so no. Chess and
checkers rotate to face your side; a renderer asks `LabGames.seatFor(id)` and
the shell re-renders when it changes.

⚠ **A flipped board must not flip what a click means.** Both renderers keep the
square's identity on the element (`data-square`, `data-row`/`data-col`, set once
at build time) and reorder elements for display. Deriving the coordinate from a
DOM index a second time is how this breaks.

**Undo is shared too** (added 2026-09-22). `game-store.js` keeps up to
`MAX_HISTORY` (20) previous positions per board; anyone on the board can step
it back, the same way anyone can reset it. **A reset pushes onto that stack**,
so "somebody just wiped the game I was playing" is recoverable — that is the
case the feature is actually for. `game-state` carries `canUndo` so the button
can disable itself. The canvas has its own Undo next to Clear, removing one
press-to-lift stroke: the client stamps a `gesture` id on every packet of a
stroke and `drawing-store.undoLastGesture` drops the trailing run sharing the
newest id. Only a TRAILING run, because two people draw at once and undo is
last-in-first-out. Removing strokes can't be an append, so the server answers
`drawing-undone` with a full repaint.

⚠ **The persisted shape went v1 → v2 to carry history, and the loader ADOPTS a
v1 board** rather than discarding it. The version guard's natural behaviour is
to throw away what it doesn't recognise, which would have wiped every game in
progress on deploy. Only a genuinely unreadable version resets.

⚠ **The framework `<script>` must come before the `{% include %}`s in
`lab.html`.** Partials call `LabGames.register()` as they parse, so with the
framework below them every one of the six throws `LabGames is not defined` and
the page renders a menu whose tiles open empty panels. Cost an hour.

**Client contract** (`window.LabGames`, documented at length in `lab.html`):
the shell owns routing, the socket, the title, the whose-turn line, the player
count, the reset button and the error line. A renderer owns its board and
nothing else, gets `render(state)` on every update, and must paint **from the
state alone** — a state can arrive that this browser did not cause, so a
shadow copy of the board will drift. Non-turn-based games (the canvas)
register `turnBased: false` and get `onOpen()`/`onClose()` instead of
join/move/reset.

**Backend** (`lab-backend/server.js`, ~370 lines, down from 777):

- A handful of generic socket events cover every turn-based game: `game-join`,
  `game-move`, `game-reset`, `game-undo`, `game-seat`, `game-list`, answered by
  `game-state`, `game-error`, `game-seats` and `game-catalog`. One Socket.IO
  room per game id; the room size IS the player count. `game-counts` broadcasts
  to everyone on any join or leave, because the menu shows a live count on
  every tile. Every board update is shaped by one `stateFor()` helper, so a new
  field can't reach some clients and not others depending on which handler
  sent it.
- `lab-backend/game-store.js` holds boards in memory, loads from Redis once at
  boot and writes back on a coalescing timer — the same discipline
  `drawing-store.js` documents below, for the same reason. **`applyMove` is
  synchronous on purpose**: nothing may interleave between reading the current
  board and installing the next one.
- Persisted under `game:<id>` with **no TTL** (a half-played game should still
  be there tomorrow) and a `STATE_VERSION`; a board stored under an older
  version is discarded rather than fed to a rule module that has moved on.
- `GET /games` returns every board's full state — the fastest way to check
  what the server actually thinks is on the board.

**What was removed in the rebuild:** the shared counter (experiment #1) and
its `create-session`/`increment`/`decrement` handlers, the `sessions` and
`goSessions` maps, `updateGlobalCounter`, and the whole `session:`/`go:`/
`global:counter` half of `persistence.js`. Also `templates/experiment*.html`
and `content/lab/experiment-*.md` — which means **the QR-code
phone-as-controller pairing is gone**. It only ever existed on those two
pages, and keeping them meant maintaining Go and the canvas twice.

**The drawing canvas does not read-modify-write per packet** (fixed
2026-09-20). Pointer events arrive faster than a Redis round trip, so the old
handler — load the stroke array, push one stroke, save it back, all with
`await`s — let two packets load the same version and each save over the other.
Every stroke in a batch but the last was dropped, which is why fast straight
lines came back broken. Now:

- `lab-backend/drawing-store.js` holds the canvas in memory as the source of
  truth: loaded from Redis once, mutated **synchronously**, written back on a
  250ms coalescing timer that loops while the session is dirty. Strokes are
  capped at 20k, and SIGTERM/SIGINT flush before Redis disconnects.
- The client (`templates/games/drawing.html`) queues points and flushes once
  per animation frame as `drawing-data { segments: [...] }`, also flushing on
  pointer-up and on colour change. A single `{fromX, ...}` segment is still
  accepted so older open tabs keep working.
- The server broadcasts **only the new strokes** (`drawing-append`), not the
  whole canvas on every packet.
- The canvas keeps its own socket events, unchanged by the rebuild.

⚠ **The canvas's drawing buffer is a fixed 900x900 and must stay a constant.**
Stroke coordinates are shared between everybody's browsers, so display scaling
is **CSS only** and pointer coordinates convert back through
`canvas.width / rect.width`. Before the rebuild the buffer was 220x280 on a
phone and 300x380 on a desktop — two people on different screens genuinely saw
each other's strokes in different places. `LINE_WIDTH` is 9 rather than 3
because 1% of the buffer is what the old 3px pen felt like on the old canvas.
The 247 strokes already stored were in the old space and would have rendered
squashed into a corner, so the canvas was **cleared** at the rebuild rather
than rescaled (Peter's call, 2026-09-21). If a future change moves the buffer
again, note that the canvas is held in memory by `drawing-store.js`: editing
the Redis key under a running `lab-backend` just gets overwritten on its next
flush, so stop the backend first.

**Verifying the lab:**

- `cd lab-backend && npm test` — 94 tests. Rule modules are unit-tested
  per-game; the drawing store has a Redis-backed integration test that needs
  Docker and **binds port 6399**, so nothing else may be holding it.
- `scripts/verify-lab-drawing.py` drives real Chromium over CDP against the
  deployed page and checks a fast drag stores every point.
- For UI work, a page-level CDP harness beats the one-shot `--screenshot`
  flag: the page holds a websocket open, so `--virtual-time-budget` never
  settles and the flag just hangs.
- ⚠ **A row with an author `display` needs `[hidden] { display: none }` of its
  own.** The `hidden` attribute only sets `display: none` in the UA stylesheet,
  so `.game-seats { display: flex }` beat it and the side picker followed you
  onto the painting canvas, which has no sides. The DOM said `hidden === true`
  the whole time; only a screenshot caught it. `.game-panel[hidden]` already
  existed for the same reason.
- ⚠ **Chess state is rebuilt from the FEN on every move**, so `chess.history()`
  knows only the move it was just handed. The move list has to be carried
  forward explicitly (`past.concat(...)` in `buildState`). Reading it directly
  left the list permanently one move long, which every single-move test passed
  happily.
- `templates/lab.html`'s `backendUrl()` accepts a `?backend=<url>` override
  **only when the page is served from localhost**, which is how a dev page
  gets pointed at a throwaway backend instead of playing on the live boards.
  Deliberately localhost-gated: on the public site that parameter would let a
  link hand your browser to somebody else's socket server.

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
- `templates/lab.html` - The games page: menu, client framework, game includes
- `templates/games/*.html` - One board renderer per game
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

### Link previews and the feed (added 2026-09-22)

A post is usually **read as a card before it is read as a page** — pasted into
Reddit, sent in iMessage, listed in a feed reader. Before this the site had
**no `og:`/`twitter:`/`description` tags at all**, so a crawler found a
`<title>` and nothing else and rendered a blank card; and Zola's built-in feed
template put the **whole rendered post** in `<description>`, `.pair` wrappers
and `<img>` tags included, which is the "summary" every aggregator showed.

**`templates/macros/preview.html` derives the two values, and both `base.html`
and `templates/rss.xml` import it.** One definition on purpose: the failure
mode of writing it twice is the card and the feed slowly disagreeing about
what a post is, and neither is visible from the site itself.

- **`description(page)`** — a frontmatter `description` if present, else the
  text **between the first `<p>` and its `</p>`**. Between, not "everything up
  to the first `</p>`": splice-audio opens with a heading, and the leading
  slice glued "The goal" onto the front of the sentence. Truncated at 200
  characters **on a word boundary**, with `config.description` as the last
  resort for a post that renders no paragraph at all.
- **`image(page)`** — `extra.preview_image` if pinned (the editor's star),
  else the **last `<img src="` in the post**, else `/og-card.jpg`. Last rather
  than first because a post here builds towards its closing photo. A relative
  src goes through `get_url`; a `<source src="">` inside a `<video>`
  deliberately does not match, since a crawler can't fetch a video frame.

**`static/og-card.jpg` is the fallback, and `scripts/build-og-card.py` cuts
it** from `static/home.jpg` (added 2026-09-23). It is **1200x630**, which is
what Facebook, Slack, iMessage and X all crop `summary_large_image` to — a
square source gets centre-cropped by each of them slightly differently, so
the framing is decided in that script rather than by whoever renders the
card. The crop is measured, not centred (`CROP_TOP = 660`): centred clips the
cat's ears against the top edge. Re-run the script after changing home.jpg.
It is the og:image for **every page but Guerrilla Gardening** — home, /blog,
/lab, /timeline, 404 and all eight text-only posts — so a broken one is a
broken card across the whole site, which is why a test asserts its
dimensions.

⚠ **`hooks.md` carried a dead `<img src="/content/images/2016/11/demo.gif">`**
— a leftover from the old Ghost blog; the file has never been in this repo and
404s. It had been an invisible broken image on the live page since 2016, and
it only surfaced because this feature dutifully picked it as that post's
preview. Removed 2026-09-23. No site-relative image references remain in
`content/blog/`; anything new goes to S3 via the upload path below.

Four things in there are load-bearing, each because its absence shipped a real
bug in the first pass:

- ⚠ **The macros emit raw text (`| safe` on every output) and the CALLER
  escapes once, with `| escape_xml | safe`.** Tera's default escaper turns `/`
  into `&#x2F;`, so `og:image` first shipped reading
  `https:&#x2F;&#x2F;img.cloudy.nyc&#x2F;…`. A conforming parser decodes it,
  but every crawler that reaches for a URL with a regex gets it wrong.
  `escape_xml` handles `& < > " '` and leaves the slashes alone.
- ⚠ **The `replace` that collapses newlines holds a REAL NEWLINE inside its
  quotes.** Tera does not process escape sequences in string literals, so the
  tidier-looking `from="\n"` matches a literal backslash-n and silently does
  nothing — a markdown-soft-wrapped paragraph then spans four lines inside a
  `content="…"` attribute.
- **Rendered HTML still holds entities, so the description decodes them** —
  `don&#x27;t` is what a quote inside a code span becomes, and a card would
  print it literally. `&amp;` is decoded LAST, or `&amp;lt;` turns into a
  real `<`.
- **`base.html` computes the values with `set_global`, not `set`.** Tera
  scopes a plain `set` to the block it appears in, so the page/section
  branches would compute values the markup underneath them can't see. The
  `{% if page is defined %}` / `{% elif section is defined %}` / else chain
  also covers `404.html`, which Zola renders with neither.

**`templates/rss.xml` overrides the built-in feed**: `<description>` is now
that same one-line summary, the full post moved to `<content:encoded>` (in
CDATA, where readers look for it), and `<media:content>`/`<media:thumbnail>`
give the list a picture. Both extra namespaces are declared on `<rss>`.
`<link rel="alternate">` in the head is new too — the footer had always linked
`rss.xml`, but a reader handed "cloudy.nyc" looks for the tag and nothing else.

**The editor pins the override with a star.** Each photo thumbnail — in the
row editor and in a pair's media column — carries a `★` overlaid on the
picture; tapping writes `extra.preview_image` through the ordinary
`PUT .../meta` route, tapping the pinned one clears it back to the default. A
chip in the post-meta row shows the pinned photo with an `×`, so an override
is visible without opening the block that holds it.

- **Overlaid rather than added to the controls row** for the reason "Split
  out" documents: that row is already three 44px buttons across a 140px
  thumb. Unpinned is a bare shadowed glyph on a transparent target, not a
  chip — a white box on every thumbnail turned a three-photo row into three
  boxes.
- **It commits immediately** and repaints the stars in place
  (`refreshPreviewPicks`) rather than calling `renderBlocks()`: pinning
  happens from inside an OPEN photo editor, and a re-render would close it
  and discard the working copy's un-saved alt text and reordering.
- **Nothing is shown when the photo isn't pinned.** The default is derived
  from the RENDERED page, and re-deriving "the last photo" in the client from
  the source blocks would be a second implementation to keep in step.
- ⚠ **`extra.preview_image` is the editor's first nested frontmatter value,
  and TOML tables are a trap for anything that appends.** Once `[extra]` is in
  the document, a naively appended `draft = true` lands INSIDE it and Zola
  sees no draft flag at all. `frontmatter.set_meta` now lifts the tables out,
  adds the new top-level key and puts them back; `set_extra`/`clear_extra`
  own the nested half, and clearing removes the table when it empties.
- `editor/tests/test_preview_tags.py` builds the real templates with Zola
  against a **copy** of the site (fixtures replacing `content/blog`), because
  `build-site.sh` and the editor's Publish both render the working tree — a
  publish racing the test would put "Preview fixture" on cloudy.nyc.

⚠ **None of this reaches a crawler until `make publish-site`.** Pages sit in
the Cloudflare edge cache for 30 days; the purge is what publishes.

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

### Scaling on large displays (added 2026-09-22)

Past ~1600px wide the page used to float in a growing white field — a 700px
reading column is 27% of a 2560px screen. The root font size now scales, and
because everything here is already sized in `rem` that is a **zoom rather than
a re-layout**: type, spacing and the column caps grow together, so **the measure
in characters never changes**. That is the reason to scale instead of widening
— a wider column at the same type size is a worse line to read.

One rule on `html` in `templates/base.html` does it:

```css
--fit-cap: calc(100vh / 63);
font-size: clamp(1rem, min(calc(0.375rem + 0.625vw), var(--fit-cap)), 1.375rem);
```

- **`rem` on the root's own `font-size` resolves against the BROWSER's default**,
  not the rule's own output — no recursion — so a reader running a 20px default
  keeps their multiplier instead of having it stomped by a px value.
- **The width term** is flat 16px to 1600px, ramps, and tops out at 22px from
  2560px. Below 1600px every width is byte-identical to before the change.
- **The height term stops the page outgrowing the window.** Scaling by width
  alone pushed the home page's footer just off the bottom of a 1440p screen.
  There is no circular dependency to solve, because scaling does not change how
  many LINES a page has, only how big they are — so **a page's height measured
  in rem is a constant** (drift measured at 1.5% across the range) and "fits the
  window" is just `root <= viewportHeight / thatConstant`, i.e. a plain `vh`
  value. No JS, no runtime measuring, no feedback loop.
- **63 is the home page's height in rem** — the tallest page that ought to fit.
  ⚠ It is a MEASUREMENT of today's content, not a constant of nature. Add a
  project to the home list and the real number climbs past it and the footer
  clips again. **`make check` runs `scripts/verify-fit.py`**, which drives
  Chromium at five window sizes and fails if any capped page can scroll.
- **Posts opt out** via `{% block html_class %}page-scrolls{% endblock %}` in
  `page.html`, which sets `--fit-cap: 100vh` — always larger than the ceiling, so
  `min()` ignores it. A post is ~370 rem tall and can never fit a window, so
  capping it would shrink the one page you are here to read for nothing. The
  accepted cost: a post renders a step larger than the home page, so **the chrome
  band is not the same width on both** — a deliberate exception to the "one width
  everywhere" rule below. `/lab/#<game>` is likewise uncapped in practice: an open
  board is 64–68 rem, so that page can still scroll a little.
- ⚠ **The caps that had to become `rem` each carry a "scales" note** —
  `.container`, `.post-container`, `.home-container`, the chrome band, `.archive`,
  `.bleed-inner`, the gantt (including its fixed height), the image/video/pair
  size presets, the home portrait, the marquee, the lab board and tile grid. A px
  value left among them does not look like a style nit; it pins that element at
  laptop size while the text around it grows past it. **The marquee's 20px track
  heights were the sharp edge** — left in px they clip 22px text.
  Hairlines, radii, shadows and optical nudges stay px on purpose.
- ⚠ **CSS COMMENTS DO NOT NEST, and that silently disabled this whole feature
  once.** The explanatory comment above the rule contained a literal
  `/* scales */`; its inner close-marker ended the comment early, the remaining
  prose parsed as a declaration, and it swallowed the `font-size` under it. No
  console error — the rule simply vanished and every measurement read as a no-op.
  Don't write a nested comment in there.
- ⚠ **`documentElement.scrollHeight` is clamped UP to the viewport height**, so
  the obvious "is the page taller than the window" comparison passes for every
  page at every size. The first version of `verify-fit.py` shipped exactly that
  and proved nothing. The honest test is to scroll to the bottom and read
  `window.scrollY` — which is also the complaint stated literally. The script
  keeps a CANARY (a long post, which must report an overflow) so a future break
  in that measurement fails loudly instead of turning every check green.

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
- **The index is one sky, and the list lives inside it** (reworked
  2026-09-21, replacing the per-row clouds below). `.archive-sky` bleeds to
  the full viewport while `ul.archive` re-caps itself at the reading
  measure; the clouds are **two parallax layers** on `.archive-sky`'s
  `::before` (near: fewer, larger, each with a deeper-blue underside) and
  `::after` (far: smaller, fainter, drifting the other way), on durations
  that are deliberately not multiples of each other so they never fall back
  into step. A faint vertical wash runs from this year at the top toward
  2016 at the bottom, feathered to transparent at both ends because a hard
  line where a gradient stops reads as a panel rather than weather. The
  seven-year silence between 2017 and 2025 now reads as open sky.
- ⚠ **`.archive-sky` sets `overflow-x: clip` and that is load-bearing.**
  The cloud layers are `inset: 0` but animated with `translate` up to 18px,
  and **`translate` contributes to scrollable overflow** — without the clip
  the page gained a real ~10px horizontal scroll at desktop widths that
  drifted in and out as the animation ran. Same class of bug as the bird
  runner, which carries its own `.archive-flightpath` clipping layer for the
  same reason: **any full-width decorative layer that is translated needs a
  clipping ancestor.**
- ⚠ **Diagnosing that class of bug: `scrollWidth > clientWidth` is not the
  tell.** `body` sets `overflow-x: clip`, which makes `body` not a scroll
  container, so `scrollWidth` reports *layout* overflow and can exceed
  `clientWidth` while nothing actually scrolls. The honest test is
  `window.scrollTo(400, 0)` followed by reading `window.scrollX` — if it
  stays 0 there is no horizontal scroll. Bisect the culprit by setting
  `display: none` on candidates and re-reading, remembering that hiding tall
  content removes the *vertical* scrollbar and grows `clientWidth` by ~15px,
  which shows up as a misleading negative.
- **The home page and the timeline were given ambient scenes, and then had
  them taken away again** (2026-09-22, three versions in an afternoon, all
  reverted at Peter's call — `git log` for `9693781` and `3661c6d` if one is
  ever wanted back). Both pages are plain white on purpose now, and the
  **blog index is the only page with a scene**. What the attempts taught,
  which applies to anything decorative added here later:
  - **Scenery behind a diagram fights the diagram.** The timeline is a
    spine, five bar colours, connector lines and cards at every height.
    Cloud between the cards read as smudges rather than sky, and a
    full-width band of grass under 2005 read as a stock illustration with
    the chart sitting on top of it. The blog index works because an archive
    list is mostly open space.
  - **Framing a page is not filling it.** Plants standing in the margins
    either side of the column read as furniture placed around the text
    rather than as a place the text sits in.
  - ⚠ **`overflow-x: clip` clips the OTHER axis too** — when one axis is
    `clip`, a `visible` axis computes to `clip`. A scene wrapper that
    clipped x to contain a sway cropped its own full-bleed children back to
    the reading column and put a hard edge under the nav. `.archive-sky`
    can clip safely only because it IS the full-bleed box and its children
    are `inset: 0`.
  - ⚠ **`overflow` does not contain an element's OWN movement**, only its
    children's. A full-width runner that translated sideways handed the home
    page 17px of real horizontal scroll at 1280px, drifting in and out as it
    moved, despite `overflow: clip` on the runner itself. **Anything that
    translates needs a clipping ANCESTOR** — which is exactly what
    `.archive-flightpath` is for the gull, and why it exists.
  - **A `--screenshot` run renders at animation time zero**, so anything
    starting at `opacity: 0` (the gull) is invisible in it. Drive CDP and
    inject `animation-delay: -6s` to see it in flight. The timeline's hover
    panel needs a real `Input.dispatchMouseEvent`, not a synthetic
    `mouseenter`.
- **Date left, title right, and the title is what hangs.** The row was
  `justify-content: space-between`, which actively pushed the pair apart —
  "Back online" left a 600px void before its date and nothing read as one
  record. `.archive-link` is now a `5.5rem minmax(0, 1fr)` grid: the pair
  stays adjacent, every title starts on the same vertical line, and a
  wrapped title gets its hanging indent for free. **Under 600px it stacks**
  (`grid-template-columns: minmax(0, 1fr)`), because a 5.5rem date gutter on
  a 380px line pushes the longer titles onto a third wrapped line.
- **The per-row clouds this replaced** (added and superseded the same day) — the page was
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
  blue, so the affordance belongs to the page's palette. It is a real
  `text-decoration` and not a faded gradient: the faded version is prettier
  and measurably less obviously a link, and this is the one element on the
  page where being understood beats being handsome.
  `:active` (the only feedback a tap gets) and a `:focus-visible` ring were
  both missing entirely and now exist.
- **There is deliberately no row separator** (removed 2026-09-21). There was
  one — a hairline faded to nothing at both ends — and it stopped earning its
  place once the titles gained the underline above and the list moved inside
  the sky: every row then carried two horizontal lines about 20px apart,
  which reads as ruled paper, and a rule that stops dead at the column edge
  inside a full-bleed scene reads as a leftover table. The underline
  separates one title from the next; the spacing and the sky do the rest.
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
  monitor. **The scene grows with the viewport** via `fitCamera()`, called from
  `init()` and `onWindowResize()`: it scales the camera's *position vector*
  (which keeps the isometric angle identical — only distance changes) by
  `max(0.85, (1.55 / aspect) ** 0.25)`, and aims `lookAt` slightly below the
  origin by `10 * (1 - k)`. Both numbers are held back from what looks best
  at any single width, because the two failure modes sit at opposite ends:
  **too much zoom runs the plate's bottom vertex off the bottom edge, and too
  much lift clips the CORPORATIONS label off the top.** The lift exists to
  spend the dead sky above the towers, which is what pays for the extra
  scale. Below the 1.55 reference aspect the multiplier is exactly 1 and the
  lift exactly 0, so phones and tablet-portrait are bit-identical to the old
  fixed camera. Past roughly 3.5:1 the frame is too short to hold the label
  and the plate at full strength, so the ultrawide case keeps its side sky
  rather than losing content — a square isometric plate cannot fill a 3.7:1
  frame, and that is geometry rather than a bug.
- ⚠ **Testing this page headless needs software WebGL.** With plain
  `--disable-gpu` the renderer throws `Error creating WebGL context` and the
  canvas silently stays at its default `300x150` while CSS stretches it to
  fill — which looks exactly like a sizing bug in the page. Add
  `--enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader`.
  ⚠ **And reap the browser properly.** `Popen.terminate()` on the parent
  kills only the root process; the renderer, network, storage and (with
  swiftshader) a 400–700MB GPU process are left orphaned on PID 1. Three
  abandoned runs took this 8GB machine down to 463MB available. Kill the root
  PID, wait, then kill any remaining chromium PIDs **by PID** — never
  `pkill -f chromium`, per the machine-wide rule about name-matched kills.
- **Post pages (`page.html`) read at `min(900px, 94vw)`**, not the site's 700px
  default — that is the width the `.img-row`/`.video-row` size presets were
  tuned against. Only the body: the nav and footer run at the site chrome width
  like every other page (below), so `:not(.post-nav)` is what keeps the
  prev/next block — itself a `<nav>` — at the post's own measure instead.
- **Prev/next on posts is live** (fixed 2026-09-22; it had been written but
  inert since it was added). The block read `page.earlier`/`page.later`, which
  **Zola dropped in 0.19** — they resolved to nothing, the `{% if %}` guard was
  permanently false, and no post ever rendered a neighbour link. The current
  names are **`page.lower`/`page.higher`, and they are positions in the sorted
  list rather than dates**: `content/blog/_index.md` sorts `date` (newest
  first), so **`lower` is the NEWER post and `higher` the older one**. If the
  block ever goes blank again, check those names against the Zola version in
  `Dockerfile.dev` before anything else.
  It renders as **one row with a side each — older left, newer right**
  (Peter's call, 2026-09-22; a stacked first version was rejected).
  Left-to-right is forward in time, which is how a timeline runs and how
  prev/next reads elsewhere, so the SIDE says which direction and the word
  says which direction in time. The pieces are the blog index's: the same
  Sentient title, the same gull-ink underline, the same sky-blue hover wash
  (leaning toward each link's own edge so the halves read as two things),
  the same meta grey for label and date.
  **Both sides are always in the markup, even when empty** — the first and
  last post have one neighbour, and the empty `div` holding its half is what
  keeps the one that exists on its own side instead of sliding to the middle.
  The chevrons are **two borders on an `<i>`, rotated 45°**, not `‹`/`›`:
  those glyphs aren't in Switzer and fall back to another face at another
  weight. **It stays two halves under 600px** — a prev/next control that
  stacks stops being one — and what gives instead is the type, since at
  ~180px a column the 1.0625rem serif wraps every title to five or six lines.
- ⚠ **`.post-nav` has to undo the bare `nav` type selector, at EVERY width.**
  `base.html` styles `nav` directly, and the prev/next block is a `<nav>`: the
  desktop rule brings `display: flex`, `justify-content`, `align-items` and
  bottom spacing, and **the mobile rule adds `flex-direction: column` and a
  `gap`**. `.post-nav` therefore writes all of those out in full rather than
  only what looks necessary. The `flex-direction` one is the trap — leaving it
  alone stacked the two sides on a phone and *only* on a phone, so a desktop
  check said it was fine. Anything added to the `nav` rule needs an answer in
  `.post-nav`. This is the second thing it has to opt out of; `:not(.post-nav)`
  on the chrome-width rule is the first.
- ⚠ **`a:hover { text-decoration: underline }` outranks a link-level
  `text-decoration: none`** — (0,1,1) beats (0,1,0) — so any anchor here that
  wraps more than its own link text and hand-draws the underline on one child
  needs its own `:hover { text-decoration: none }`. Both `.archive-link` and
  `.post-nav-link` do; the archive had been silently underlining each row's
  DATE on hover since the row became a whole-row anchor (fixed 2026-09-22).
- **`/blog/#<slug>` hash links no longer resolve** — they were how the SPA
  selected a post. Deliberately not shimmed.
- **`/` (`index.html`)** widens to `min(1080px, 92vw)` at ≥1000px and flows its
  sections into two columns via **`column-count`, not a grid** — the browser
  balances them, so adding a section later doesn't need the split re-hardcoded.
  **Its nav and footer run that full width too** (fixed 2026-09-22) — they were
  capped back to 700px and re-centred, the way post pages did it, which left
  them inset 190px on each side of the page they belong to at 1280px wide: the
  nav links started well right of "Welcome." and the footer's rule began and
  ended in mid-air. Uncapped, the links share the heading's left edge and the
  site title lands exactly on the photo's right edge. **That width is now the
  whole site's chrome width** — see the next bullet; fixing home alone just
  moved the inconsistency to every other page.
  `.home-intro` is a `flow-root`: without it the floated photo escapes the
  intro and the multi-column box shrinks sideways to avoid the float instead of
  using the full width. **"Welcome." and the photo are level at the top of the
  page, and three separate rules are what keep them there** (fixed 2026-09-22;
  the intro used to start a photo's height down the page, under a band of
  nothing). `.home-header h1` opts out of the site-wide heading `clear` — this
  is the one heading meant to sit beside a float — and zeroes its top margin.
  The float lives on the photo's LINK (`.home-photo`), not the `<img>`: a float
  inside an inline box can't rise above that box's line box, so floating the
  image alone parked it 24px lower than the heading. And `.home-photo
  .home-image` is two classes deep on purpose, to outrank `.container img`'s
  `margin: 1.5rem auto` — inherited, that margin re-created the same 24px gap
  inside the link. The "Author of" list links **live sites, not repos**,
  and only things that are actually publicly reachable — check
  `http-routing/cloudflared/config.yml` for that, not a curl from the Pi, since
  LAN-only hosts answer 200 from here and would be dead links for visitors.
- **Two things are the same on every page, and both are enforced in
  `base.html` rather than per template** (settled 2026-09-22):
  - **The nav and footer sit at one width — `min(1080px, 92vw)` — whatever
    the page's own reading column does.** They used to inherit their
    container, so the links jumped as you moved between pages: 1080px on
    home, 700px on `/blog`, `/timeline` and `/lab`, 700px on a post inside a
    900px container. `.container > nav:not(.post-nav), .container > footer`
    pulls the band back out of the container with
    `margin-inline: calc(50% - min(540px, 46vw))` — `50%` resolves against
    the centred container, so that computes to -190px from a 700px one and
    to exactly 0 from home's, which is why home is unchanged. The `width`
    and the margins are both required; a lone `width` just overflows right.
    On the narrower pages the band is deliberately wider than the text under
    it: the nav belongs to the page, not to the column.
  - **The first line of text starts at the same y on every page** (105.6px at
    desktop sizes — nav bottom + its 2rem margin). Everything else got this
    free from its `<h1>`; the blog index did not, because `.archive-sky`
    carried `2.5rem` of top padding *and* the first row's own `1.05rem`
    touch-target padding, which put the first post title 57px below where
    every other page starts. The sky's top padding is now 0 and `.archive`
    carries `margin-top: -1.05rem` to cancel the row padding. Don't fix this
    by shrinking `.archive-link`'s padding — that padding IS the 44px touch
    target, as the bullet above warns.
  - Verify both with a DOM probe rather than by eye: inject a script that
    reports `nav.getBoundingClientRect()` and the topmost element in
    `.container` holding a non-empty text node, then read it back out of
    `chromium --headless --dump-dom` (no screenshot needed, and the numbers
    are exact).
- **`/lab` (`lab.html`)** uses the same bleed pattern for `.game-stage`, so a
  board can be wider than the 700px reading column. Boards no longer switch
  between hardcoded pixel sizes at a breakpoint the way the old Go board and
  canvas did: each scales with the viewport (SVG `viewBox`, CSS grid, or
  `aspect-ratio`) and caps around 520px, so switching games doesn't lurch.
  Pointer coordinates therefore always convert through
  `getBoundingClientRect()` rather than assuming a fixed size — see the canvas
  warning in The Lab above, which is the one place that is genuinely subtle.

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
  Caddy/tunnel host for the Socket.IO backend (`backendUrl()` in
  `templates/lab.html`, and CORS in
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
alt text, and Small/Medium/Full size presets; `pair` (a picture and a bounded
run of prose, side by side) gets that same strip plus its prose in one
markdown field; `clear` and `spacer` render as labelled dividers; everything
else gets a markdown textarea.

Each block's control bar carries `+` (paragraph), `🖼` (photos), `␣`
(spacer), `◨` (layout controls, on media rows, pairs and spacers), `⊟` (stop-wrap
marker, only where a float is still wrapping), `⇅` (move) and `×`. The
inserting ones ask above or below. Behind `◨`, a media row offers
"Text wraps: No / Left / Right" — choosing a side floats it and the text
flows around it — plus "⧉ Centre", which folds the row and the section
beside it into a `pair`; a pair offers "⤢ Unpair" instead; a spacer offers
"Space shows: Everywhere / Desktop only". A single photo or
clip can be split out of its row into one of its own, and any block can be
moved (pick it up, tap an overlaid bar) or merged with an adjacent
same-family block. The editor bar has Undo (walks back through the post's
edits), Discard (back to the last published version), and "↗ View live".

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

- **Undo is one hook, not a hook per route.** Every body write funnels
  through `_write_body`, so `history.snapshot()` sits there and covers every
  block route at once. The meta route (title/date/draft) writes by a
  different path and carries its own call -- an Undo that silently skipped
  a title edit would be a trap. `editor/history.py` keeps whole numbered
  copies of the post under a gitignored `editor/.history/<slug>/`, capped at
  25:
  - **Snapshots must not live under `content/`** -- Zola renders every `.md`
    in that tree, so one parked there becomes a ghost post on the live site.
  - **Undo deliberately does not snapshot what it replaces.** If it did, undo
    would be its own inverse: the first tap records the current text and the
    second restores it, ping-ponging between two versions instead of walking
    backwards. A test pins this.
  - **`can_undo` rides on every post payload**, not just the initial load,
    because the client re-renders from each write's own response -- otherwise
    the button stays disabled until the next full page load.
- **Discard restores from git, because Publish is what commits.** `publish.py`
  stages exactly the post's path, so "since the last publish" and "since the
  last commit" are the same line and Discard can be a plain
  `git checkout HEAD -- <post>`. Two details are load-bearing:
  - **It snapshots first**, so the one big destructive button is reachable by
    Undo. Otherwise it's the only action with no way back.
  - **The tracked-ness check is `git cat-file -e HEAD:<path>`, not
    `git ls-files`.** `ls-files` also succeeds for a merely *staged* post --
    `rename_post` stages exactly like that -- and `git checkout HEAD --` on
    one of those fails, surfacing as a 500 instead of the clear "never been
    committed" refusal. A brand-new draft is refused rather than deleted.
- **Text wrapping is a float and nothing more: the row picks a side.** A
  photo or clip sitting next to prose is a third class on the row
  (`<div class="video-row size-medium beside-right">`) plus `float: right`.
  Everything after it wraps around it and returns to full width once past
  it. **There is deliberately no way to say which blocks sit beside a row** --
  page widths are fluid, so how much text fits alongside isn't knowable when
  the post is written. An earlier version had you select a fixed set of
  blocks, gathered them into a run and fenced it with a marker; it could not
  survive a change of screen width and was removed.
  - **`side` is orthogonal to `size`**, not three more presets: a row is
    "medium, floated right". `none` writes no class at all, so every row
    published before this existed stays byte-identical -- the same discipline
    that keeps `size-full` implicit.
  - **A full-width row can't float and is refused at the boundary**
    (`markdown_for` raises): a row capped at 100% leaves the text no column,
    so the pair would silently render as a plain stack. Choosing a side
    therefore narrows a full-width row to **medium**, and choosing Full drops
    the side. That constraint lives in exactly one place on each side of the
    wire (`markdown_for`, and `framingControls()`/`setRowSide()` in
    editor.js) or the two row editors drift apart.
  - **Setting a side has no route of its own.** It is an ordinary property of
    the row, so the picker performs the same PUT the row editor does.
  - **A floated row carries `clear: both`.** Without it a second float slots
    into whatever room is left beside an earlier one, so two pictures close
    together pair up, the prose is squeezed into the gutter between them and
    headings break one word per line. Each floated row starts its own wrap
    region.
  - **In the editor it is the whole `.block` that floats, not the row inside
    it.** Letting the row escape its block left the block a full-width,
    zero-height box lying across the picture, and three things broke at once:
    hovering the photo lit up whichever paragraph's box overlapped it, that
    paragraph's absolutely-positioned controls landed on top of the photo,
    and the photo's own controls appeared at the top-right of its invisible
    block. The floated block carries the row's width (`--row-w` plus the
    block's own padding and border, so the picture still measures its
    published width), the row inside drops back to `float: none; width: 100%`,
    and the wrap picker lives inside the block so it travels with the float.
    - **It also needs `z-index: 1`.** Every `.block` is `position: relative`
      (its controls are absolutely positioned inside it), and positioned
      boxes paint above floats -- so a following paragraph, whose box still
      spans the full column even though its text wraps away from the
      picture, covered the photo and swallowed the pointer.
  - **Two rules in `base.html` are load-bearing**, each fixing a way floats
    leak: `.container { display: flow-root }` (or a float taller than its
    text escapes the post and overlaps the footer), and a `max-width: 700px`
    unfloat (below the reading column's own width even the 240px preset
    leaves an unreadable measure). Headings do **not** clear a float -- a
    section title is allowed to sit beside a photo, which is the whole point
    of letting the text flow.
  - **`.clear-beside` is the stop-wrap marker, inserted by hand.** A float
    otherwise wraps everything after it, so this is how an author ends a wrap
    early and starts a new full-width section (typically one that pairs with
    its own picture). It is an ordinary block -- added through the generic
    add-block route, deleted like any other -- and `blocks.py` promotes it to
    the `clear` kind so the editor shows a labelled divider rather than a
    mystery empty block. The control only appears where a float is actually
    still wrapping (`wrapIsActiveAt` scans back for a sided media row,
    stopping at any earlier marker), so it can't insert a block that does
    nothing.
  - **The picker is a full-width strip under the row, not an icon in
    `.block-controls`.** That bar is `display: none` until `:hover`, and the
    tablet this editor exists for has no hover -- the feature was there and
    effectively invisible.
  - **"↗ View live" opens the published post in a new tab.** The base comes
    from `config.SITE_BASE_URL`, hand-duplicated from `scripts/build-site.sh`'s
    `BASE_URL` default and pinned by a test -- **that** script is what renders
    the live site, and `config.toml`'s `base_url` (`peter.direct`) is only
    the fallback it overrides, so building a link from it would point at a
    host that doesn't answer. A draft's link is shown but muted and says so
    in its title: a draft isn't built at all, so it would 404, and "where is
    my post" is exactly the question a draft raises.
  - **Layout controls are behind a `◨` toggle in the control bar**
    (`state.wrapOpen`), not always on: a picture usually just sits there, and
    a strip under every one of them is noise when reading a post back. The
    toggle lights up while its controls are showing.
  - **A spacer (`<div class="post-spacer">`) is plain breathing room between
    sections**, with its own block kind for the same reason the stop marker
    has one: an empty div is otherwise an invisible, unexplainable block. It
    is `post-spacer`, NOT `spacer` -- `templates/lab.html` already uses that
    class for its game chrome, and base.html's styles are site-wide. The
    editor sets the height on `.block.spacer-block` rather than on an inner
    element, because a spacer renders its label instead of its own html; a
    test keeps that height in step with the published one, or the gap would
    be tuned by guesswork.
  - **A spacer can be desktop-only** (`class="post-spacer desktop-only"`,
    picked behind `◨`): on a phone the post is already one narrow column, so a
    deliberate section break reads as a scroll of blank screen. `base.html`
    collapses it to `height: 0` inside the same `max-width: 700px` query that
    unfloats rows, so "mobile" means one thing site-wide, and the rule is
    written compound (`.post-spacer.desktop-only`) because `desktop-only`
    alone would be a site-wide class that hides whatever picked it up.
    `_SPACER_RE` spells the modifier out rather than allowing any class, so
    only the two shapes the editor writes are promoted to the `spacer` kind --
    a test parses every `*SPACER_SOURCE` constant in `editor.js` back through
    it. The API reports `desktop_only` on spacer blocks the way rows report
    `size`/`side`. The editor does NOT hide the gap: it runs on a tablet,
    above the breakpoint, so the space genuinely is there -- it says so
    instead, with dashed rules and a "space · desktop only" label.
  - **`+`, `␣` and `⊟` ask above or below** rather than assuming. Both hang off a
    block, and "above" (the old behaviour) was wrong about half the time --
    an undo and a retry every other go. `insert_block` takes the block count
    itself as "append", so "below the last block" needs no special case.
  - **A text block is `display: flow-root`.** A block beside a float keeps
    the full column width -- only its LINE boxes shorten -- so a text block's
    border and hover background ran under a floated photo and vanished behind
    it. A BFC root doesn't overlap a float; it narrows to the room left,
    which is where the text ends. The cost, worth naming: one block taller
    than the picture stays narrow for its whole height instead of reclaiming
    the column part-way down, so the preview is very slightly less faithful
    than the published page for a single long paragraph.
  - **Move mode OVERLAYS; it never inserts.** It renders the real blocks --
    not its own previews -- and adds a fixed banner plus a `.move-layer` of
    absolutely positioned drop zones, so picking a block up reflows nothing
    at all (verified: page height and every block's position unchanged to the
    pixel). It used to swap the list for previews and insert N+1 button-sized
    targets, which shoved the whole post down exactly when you were trying to
    aim at it. `#blocks` is `position: relative` so the zones resolve against
    it, and each zone's `top` is a block's measured `offsetTop`, which lands
    on the right boundary with no margin arithmetic. The banner's `top` is
    measured from `.bar` rather than hard-coded, since the toolbar's height
    depends on its own contents.
  - **The zones are repositioned by a `ResizeObserver`, not just at render.**
    At first render the pictures have not loaded, and an `<img>` with no
    intrinsic size yet is zero pixels tall -- so every block below one
    measures too high and the bars end up scattered across the post instead
    of between its blocks. One observer over the blocks catches every reason
    the layout can move (pictures arriving, video metadata landing, fonts
    swapping, the window resizing) instead of a list of `load` handlers. It
    is disconnected in `renderBlocks` and `cancelMove`, since it points at
    nodes that are about to be discarded.
  - **A zone's tap area is a pseudo-element.** The bar is 8px so it reads as
    a hairline; an absolutely positioned `::after` extends the hit region
    ~12px either side, and out-of-flow boxes cost no layout.
  - **The published page and the editor fail differently here, so check
    both.** A full-width control next to a float gets pushed below it (a BFC
    root never overlaps a float); a positioned sibling paints on top of it.
    Neither shows up on the published page, which has no editor chrome --
    which is exactly how both shipped. **Verify float work in the editor
    preview, not just in a Zola build.**

- **A paired section is the one thing a float can't be: vertically centred.**
  A float lets text flow around a picture from the top down, and CSS has no
  way to centre that text against it -- centring needs both in one container.
  So `<div class="pair pair-right size-medium">` holds a `.pair-media` column
  and a `.pair-text` column, flexed and `align-items: center`.
  - **The blank lines around the prose are the mechanism, not formatting.**
    CommonMark only parses markdown inside an HTML block once a blank line
    has closed that block. Without them every link and emphasis in the
    section would render as literal text. The cost is that the wrapper spans
    several top-level tokens (opening html, the prose, closing html), which
    is the one thing `blocks.py`'s one-token-per-block model couldn't
    represent -- so `_group_pairs` folds the range back into a single `pair`
    block. **It matches on the opener's SOURCE, not its kind**: that block
    contains the media column's own row div, so `_refine_kind` has already
    called it an `img_row`.
    - An opener with no closer is left ungrouped rather than swallowing the
      rest of the post: raw fragments can be seen and repaired; a block that
      ate the post just looks like the post vanished.
  - **The media column holds an ordinary row, verbatim.** That is what makes
    pairing and unpairing lossless (the row's source moves in and out, never
    regenerated) and what lets the existing thumbnail editors drive a paired
    picture unchanged -- `_block_json` reports a pair's `images`/`videos`
    from it. The row inside must never be plain markdown, which wouldn't
    parse inside an HTML block; it can't be, because a paired row always has
    a side, a side always implies small or medium, and both write the div.
  - **`isMediaRow()` excludes pairs.** A pair reports `images` too, so
    without that it would get a wrap picker instead of Unpair, and would look
    like it started a wrap for everything after it.
  - **A section's boundary is the stop marker, the next picture, or the end
    of the post** -- exactly what the float was already wrapping. Pairing
    consumes the marker (the pair's closing div does that job now) and
    unpairing puts one back, which is what makes the round trip byte-exact.
  - **Stacked on a phone, the picture comes AFTER the text.** A picture on
    top pushes the words it belongs to off the screen -- you scroll past a
    photo to find out what it's of.
  - **The pair's narrow-screen overrides must sit AFTER the base `.pair`
    rules, not in the breakpoint block higher up the file.** They override
    declarations the base rules also set, and at equal specificity source
    order decides: placed above, `align-items: stretch` and the auto widths
    silently lost, which left a `size-medium` pair holding a 420px picture
    on a 412px screen. editor.css had exactly that bug; base.html didn't,
    because its pair rules happen to precede its breakpoint.
  - **`justify` decides how the prose sits against the picture**, in flexbox
    terms: `center` (the default, writing no class), `top` (flex-start),
    `spread` (space-between -- flush top and bottom, slack between the
    blocks) and `evenly` (space-evenly). Distributing needs the text column
    to be as tall as the picture, and **only that column may stretch**:
    stretching the pair would stretch the media column too, and
    `.img-row img` carries `height: 100%; object-fit: cover`, so the photo
    would be cropped to whatever height the prose happened to want.
  - **A pair is edited as one thing**: its picture through the usual strip,
    its prose as markdown in one textarea. That is the trade the pair makes
    in exchange for being able to centre -- the section stopped being a set
    of sibling blocks.

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
  **They are `rem` in both files** (`15rem`/`26.25rem`), which is the one
  thing about them that looks like a pointless unit choice in the editor: the
  site scales its root font size past 1600px so its caps grow with the page,
  while the editor's root stays at the browser default and 15rem renders as
  exactly the 240px it always was. The unit exists so the two files can be
  compared literally. The 2026-09-22 scaling work converted base.html and left
  editor.css in px, so `test_video_size_presets.py` was **red for a day**
  (fixed 2026-09-23). The pair's `.pair-media` widths drifted identically and
  had no test at all; they do now.
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
