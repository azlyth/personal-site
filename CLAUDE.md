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

### Deployment
- GitHub Pages via `.github/workflows/deploy.yml`
- Zola v0.20.0 builds to `public/` directory
- Lab backend deployed separately (see `render.yaml` for Render.com config)

## Git Workflow
- Use simple present tense commit messages (e.g., "Add dark mode toggle")
- Do not include Claude Code footer in commits
- Wait for user to verify fixes before staging/committing
- Only commit when explicitly told to do so
- "test, add, commit" means: run tests, if passing then git add and commit
