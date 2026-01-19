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

### Template System
- `templates/base.html` - Base layout (includes all CSS, nav, footer, cloud animations)
- `templates/index.html` - Homepage
- `templates/section.html` - Blog listing
- `templates/page.html` - Individual blog post
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
- "test, add, commit" means: run tests, if passing then git add and commit
