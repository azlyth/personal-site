# Blog Editor Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LAN-only editor at `edit.cloudy.nyc` that edits this site's blog posts in place from a tablet — text, title, date, draft, slug, and photos — and publishes by committing to git and rebuilding the live site.

**Architecture:** A FastAPI service (`editor/`, native systemd, runs as `peter`) reads and writes `content/blog/*.md` in this repo. Post bodies are edited block by block by splicing markdown **source line ranges** — rendered HTML is never converted back to markdown. Publish does a path-scoped `git add`, commits, pushes, then runs `zola build` into a temp directory and atomically swaps it into the bind-mounted `public/` that nginx serves.

**Tech Stack:** Python 3.13 + FastAPI + uvicorn, `markdown-it-py` (source maps), `tomlkit` (frontmatter), `Pillow` (EXIF strip/resize), `boto3` (S3), vanilla JS front end (no build step), Docker for Zola only.

**Spec:** `docs/superpowers/specs/2026-09-20-blog-editor-design.md`

## Global Constraints

- **Never `git add -A` / `git add .`** — publish stages only explicitly named paths. This repo routinely has unrelated work in flight.
- **Bind to `127.0.0.1:8804` only** — never `0.0.0.0`.
- **`edit.cloudy.nyc` must never appear in `http-routing/cloudflared/config.yml`.** The service asserts this at startup and refuses to boot otherwise.
- **`zola build` must never write directly into the live `public/`** — build to a temp dir, then swap. A failed build must leave the last good site standing.
- Zola is **not** installed natively on the Pi. All Zola invocations run in the `personal-site-zola` image built in Task 1.
- Site base URL for local builds is `https://cloudy.nyc` (GitHub Actions builds `peter.direct` separately; do not change that workflow).
- Python deps live in `editor/.venv` (gitignored), matching spruce's `.venv` pattern.
- All new Python files get tests; TDD order is enforced by the task steps.

---

### Task 1: Serve the site from a live directory

Replaces the baked-image deploy with nginx serving a bind-mounted `public/`, and adds the Zola image that every later build uses. After this task, `make build-site` regenerates the live site in ~2s with no Docker image rebuild.

**Files:**
- Create: `editor/zola.Dockerfile`
- Create: `scripts/build-site.sh`
- Modify: `compose.yaml`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/build-site.sh` — builds the site into `public/` atomically. Exit 0 on success, non-zero with stderr on failure. Task 4's `publish.py` shells out to this exact script.

- [ ] **Step 1: Add the Zola image definition**

Create `editor/zola.Dockerfile`:

```dockerfile
# Zola is not installed natively on the Pi; every site build runs in here.
FROM alpine:3.20
RUN apk add --no-cache zola
WORKDIR /project
```

- [ ] **Step 2: Build the image**

Run: `docker build -f editor/zola.Dockerfile -t personal-site-zola editor/`
Expected: image `personal-site-zola` built.

Verify Zola runs: `docker run --rm personal-site-zola zola --version`
Expected: prints a version like `zola 0.19.x`.

- [ ] **Step 3: Write the build script**

Create `scripts/build-site.sh`:

```bash
#!/usr/bin/env bash
# Build the site into public/ atomically.
#
# zola build wipes its output directory first, so building straight into what
# nginx serves means a failed build leaves a half-empty site -- the exact
# failure that pinned 404s in Cloudflare's cache for meetup.astoria.app.
# Build into a scratch dir, then swap only on success.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-https://cloudy.nyc}"
TMP_REL=".build-tmp"
TMP_ABS="$REPO/$TMP_REL"

rm -rf "$TMP_ABS"

docker run --rm \
  -v "$REPO:/project" \
  -w /project \
  personal-site-zola \
  zola build --base-url "$BASE_URL" --output-dir "/project/$TMP_REL" --force

# Swap: move the old aside, promote the new, then discard the old.
if [ -d "$REPO/public" ]; then
  rm -rf "$REPO/public.old"
  mv "$REPO/public" "$REPO/public.old"
fi
mv "$TMP_ABS" "$REPO/public"
rm -rf "$REPO/public.old"

echo "built $REPO/public"
```

Make it executable: `chmod +x scripts/build-site.sh`

- [ ] **Step 4: Ignore the scratch dirs**

Modify `.gitignore` — add after the existing `/public` line:

```
/.build-tmp
/public.old
/editor/.venv
```

- [ ] **Step 5: Serve the directory instead of a baked image**

Modify `compose.yaml` — replace the `web` service with:

```yaml
  web:
    image: nginx:alpine
    ports:
      - "127.0.0.1:8802:80"
    volumes:
      - ./public:/usr/share/nginx/html:ro
    restart: unless-stopped
```

The `build:` key and `NODE_ENV` are removed: nginx now serves whatever
`scripts/build-site.sh` last produced, so the site no longer lives inside the
image. Leave the `redis` and `lab-backend` services untouched.

- [ ] **Step 6: Add a make target**

Modify `Makefile` — add to `.PHONY` and add the target:

```makefile
build-site:
	./scripts/build-site.sh
```

- [ ] **Step 7: Build and bring it up**

Run:
```bash
make build-site
docker compose up -d --force-recreate web
```
Expected: `built .../public`, and `web` recreated.

- [ ] **Step 8: Verify the site still serves**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8802/`
Expected: `200`

Run: `curl -s http://127.0.0.1:8802/blog/guerilla-gardening/ | grep -c img-row`
Expected: a non-zero count (the post still renders with its image rows).

- [ ] **Step 9: Verify a failed build leaves the site standing**

Temporarily break the config: `cp config.toml /tmp/config.toml.bak && echo 'base_url = [[[' >> config.toml`

Run: `./scripts/build-site.sh; echo "exit=$?"`
Expected: non-zero exit, error text from Zola.

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8802/`
Expected: still `200` — the previous build survived.

Restore: `cp /tmp/config.toml.bak config.toml && ./scripts/build-site.sh`

- [ ] **Step 10: Commit**

```bash
git add editor/zola.Dockerfile scripts/build-site.sh compose.yaml Makefile .gitignore
git commit -m "Serve the site from a live directory instead of a baked image"
```

---

### Task 2: Markdown block index and splice

The riskiest code in the project: a bug here silently destroys writing. Pure logic, no web, tested hardest.

**Files:**
- Create: `editor/blocks.py`
- Create: `editor/tests/test_blocks.py`
- Create: `editor/requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Block` dataclass with fields `index: int`, `kind: str`, `source: str`, `start_line: int`, `end_line: int`, `html: str`
  - `parse_blocks(body: str) -> list[Block]`
  - `replace_block(body: str, index: int, new_source: str) -> str`
  - `insert_block(body: str, index: int, new_source: str) -> str` (inserts *before* `index`; `index == len(blocks)` appends)
  - `delete_block(body: str, index: int) -> str`
  - `kind` is one of: `paragraph`, `heading`, `list`, `blockquote`, `code`, `html`, `hr`, `image`, `img_row`

- [ ] **Step 1: Declare dependencies**

Create `editor/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
markdown-it-py==3.0.0
tomlkit==0.13.2
Pillow==11.1.0
boto3==1.35.92
python-multipart==0.0.20
pytest==8.3.4
httpx==0.28.1
```

Create the venv and install:
```bash
python3 -m venv editor/.venv
editor/.venv/bin/pip install -r editor/requirements.txt
```

- [ ] **Step 2: Write the failing tests**

Create `editor/tests/test_blocks.py`:

```python
import pytest

from editor.blocks import (
    Block,
    parse_blocks,
    replace_block,
    insert_block,
    delete_block,
)

SIMPLE = "First para.\n\n## A heading\n\nSecond para.\n"

IMAGES = (
    "Intro.\n"
    "\n"
    "![alt text](https://img.cloudy.nyc/p/one.jpg)\n"
    "\n"
    '<div class="img-row">\n'
    '<img src="https://img.cloudy.nyc/p/two.jpg" alt="two">\n'
    '<img src="https://img.cloudy.nyc/p/three.jpg" alt="three">\n'
    "</div>\n"
    "\n"
    "Outro.\n"
)


def test_parse_splits_top_level_blocks():
    blocks = parse_blocks(SIMPLE)
    assert [b.kind for b in blocks] == ["paragraph", "heading", "paragraph"]
    assert [b.index for b in blocks] == [0, 1, 2]


def test_parse_captures_raw_source_not_html():
    blocks = parse_blocks(SIMPLE)
    assert blocks[1].source == "## A heading"
    assert "<h2" in blocks[1].html


def test_parse_classifies_image_and_img_row():
    blocks = parse_blocks(IMAGES)
    kinds = [b.kind for b in blocks]
    assert kinds == ["paragraph", "image", "img_row", "paragraph"]


def test_replace_with_identical_source_is_byte_identical():
    # The load-bearing property: a no-op edit must not perturb the file.
    for body in (SIMPLE, IMAGES):
        for block in parse_blocks(body):
            assert replace_block(body, block.index, block.source) == body


def test_replace_changes_only_the_target_block():
    out = replace_block(SIMPLE, 0, "Rewritten.")
    assert out == "Rewritten.\n\n## A heading\n\nSecond para.\n"


def test_replace_accepts_multiline_replacement():
    out = replace_block(SIMPLE, 0, "Line one.\nLine two.")
    assert out == "Line one.\nLine two.\n\n## A heading\n\nSecond para.\n"
    assert [b.kind for b in parse_blocks(out)] == ["paragraph", "heading", "paragraph"]


def test_insert_before_index():
    out = insert_block(SIMPLE, 1, "Inserted.")
    assert out == "First para.\n\nInserted.\n\n## A heading\n\nSecond para.\n"


def test_insert_at_end_appends():
    out = insert_block(SIMPLE, 3, "Appended.")
    assert out == "First para.\n\n## A heading\n\nSecond para.\n\nAppended.\n"


def test_delete_removes_block_and_its_separator():
    out = delete_block(SIMPLE, 1)
    assert out == "First para.\n\nSecond para.\n"


def test_body_without_trailing_newline_round_trips():
    body = "Only para."
    blocks = parse_blocks(body)
    assert replace_block(body, 0, blocks[0].source) == body


def test_index_out_of_range_raises():
    with pytest.raises(IndexError):
        replace_block(SIMPLE, 99, "nope")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_blocks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'editor.blocks'`

- [ ] **Step 4: Implement `blocks.py`**

Create `editor/blocks.py`:

```python
"""Index a markdown body into editable blocks and splice edits back in.

The editor never converts rendered HTML back to markdown. Instead every
top-level markdown token carries a source line range (markdown-it-py's
`token.map`), so an edit is a line splice into the original text: the bytes
outside the edited range are untouched by construction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark").enable("table")

# Tokens markdown-it emits for a top-level node, mapped to our `kind`.
_KIND_BY_TOKEN = {
    "paragraph_open": "paragraph",
    "heading_open": "heading",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "blockquote_open": "blockquote",
    "fence": "code",
    "code_block": "code",
    "html_block": "html",
    "hr": "hr",
}

_IMG_ROW_RE = re.compile(r'<div\s+class="img-row"', re.I)
_ONLY_IMAGE_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")


@dataclass
class Block:
    index: int
    kind: str
    source: str
    start_line: int  # 0-based, inclusive
    end_line: int    # 0-based, exclusive
    html: str


def _lines(body: str) -> list[str]:
    return body.split("\n")


def _refine_kind(kind: str, source: str) -> str:
    """Promote the two shapes that get a dedicated editor UI."""
    stripped = source.strip()
    if kind == "html" and _IMG_ROW_RE.search(stripped):
        return "img_row"
    if kind == "paragraph" and _ONLY_IMAGE_RE.match(stripped):
        return "image"
    return kind


def parse_blocks(body: str) -> list[Block]:
    """Split a markdown body into top-level blocks with source ranges."""
    lines = _lines(body)
    tokens = _md.parse(body)

    blocks: list[Block] = []
    depth = 0
    for token in tokens:
        # Only consider tokens at nesting depth 0 -- a paragraph inside a list
        # item is part of that list's block, not a block of its own.
        if depth == 0 and token.type in _KIND_BY_TOKEN and token.map:
            start, end = token.map
            source = "\n".join(lines[start:end]).rstrip()
            kind = _refine_kind(_KIND_BY_TOKEN[token.type], source)
            blocks.append(
                Block(
                    index=len(blocks),
                    kind=kind,
                    source=source,
                    start_line=start,
                    end_line=end,
                    html=_md.render(source),
                )
            )
        depth += token.nesting

    return blocks


def _splice(body: str, start: int, end: int, replacement: list[str]) -> str:
    lines = _lines(body)
    return "\n".join(lines[:start] + replacement + lines[end:])


def _require(blocks: list[Block], index: int) -> Block:
    if index < 0 or index >= len(blocks):
        raise IndexError(f"no block at index {index}")
    return blocks[index]


def replace_block(body: str, index: int, new_source: str) -> str:
    """Replace block `index`'s source lines with `new_source`."""
    block = _require(parse_blocks(body), index)
    return _splice(body, block.start_line, block.end_line, new_source.split("\n"))


def insert_block(body: str, index: int, new_source: str) -> str:
    """Insert a new block before `index`. `index == len(blocks)` appends."""
    blocks = parse_blocks(body)
    new_lines = new_source.split("\n")

    if index >= len(blocks):
        trailing = "" if body.endswith("\n") else "\n"
        return body + trailing + "\n" + new_source + "\n"

    block = _require(blocks, index)
    return _splice(body, block.start_line, block.start_line, new_lines + [""])


def delete_block(body: str, index: int) -> str:
    """Remove block `index` along with the blank line that separated it."""
    blocks = parse_blocks(body)
    block = _require(blocks, index)

    end = block.end_line
    lines = _lines(body)
    # Absorb one trailing blank separator so deleting doesn't leave a gap.
    if end < len(lines) and lines[end].strip() == "":
        end += 1

    return _splice(body, block.start_line, end, [])
```

Create an empty `editor/__init__.py` and `editor/tests/__init__.py` so the package imports.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_blocks.py -v`
Expected: all PASS.

- [ ] **Step 6: Verify against the real post**

Run:
```bash
editor/.venv/bin/python -c "
from editor.frontmatter import split_post
" 2>/dev/null || true
editor/.venv/bin/python - <<'PY'
from pathlib import Path
from editor.blocks import parse_blocks, replace_block

raw = Path("content/blog/guerilla-gardening.md").read_text()
body = raw.split("+++", 2)[2].lstrip("\n")
blocks = parse_blocks(body)
print("blocks:", len(blocks))
print("kinds:", sorted({b.kind for b in blocks}))
for b in blocks:
    assert replace_block(body, b.index, b.source) == body, f"block {b.index} not byte-stable"
print("all blocks round-trip byte-identically")
PY
```
Expected: prints a block count, includes `img_row` and `image` in kinds, and
`all blocks round-trip byte-identically`.

- [ ] **Step 7: Commit**

```bash
git add editor/blocks.py editor/tests/test_blocks.py editor/requirements.txt editor/__init__.py editor/tests/__init__.py .gitignore
git commit -m "Add markdown block index and splice for the editor"
```

---

### Task 3: Frontmatter read and write

**Files:**
- Create: `editor/frontmatter.py`
- Create: `editor/tests/test_frontmatter.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `split_post(text: str) -> tuple[str, str]` — returns `(frontmatter_toml, body)`; raises `ValueError` if the `+++` delimiters are missing
  - `join_post(frontmatter_toml: str, body: str) -> str`
  - `read_meta(frontmatter_toml: str) -> dict` — plain dict of values
  - `set_meta(frontmatter_toml: str, key: str, value) -> str` — returns new frontmatter TOML, preserving the formatting and ordering of untouched fields

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_frontmatter.py`:

```python
import datetime

import pytest

from editor.frontmatter import split_post, join_post, read_meta, set_meta

POST = (
    "+++\n"
    'title = "Guerrilla Gardening"\n'
    "date = 2026-09-20\n"
    "draft = false\n"
    "+++\n"
    "\n"
    "Body starts here.\n"
)


def test_split_separates_frontmatter_and_body():
    fm, body = split_post(POST)
    assert 'title = "Guerrilla Gardening"' in fm
    assert body == "Body starts here.\n"


def test_join_is_the_inverse_of_split():
    fm, body = split_post(POST)
    assert join_post(fm, body) == POST


def test_read_meta_returns_values():
    fm, _ = split_post(POST)
    meta = read_meta(fm)
    assert meta["title"] == "Guerrilla Gardening"
    assert meta["draft"] is False
    assert meta["date"] == datetime.date(2026, 9, 20)


def test_set_meta_changes_only_the_target_field():
    fm, _ = split_post(POST)
    out = set_meta(fm, "title", "A New Title")
    assert 'title = "A New Title"' in out
    assert "date = 2026-09-20" in out
    assert "draft = false" in out


def test_set_meta_preserves_field_order():
    fm, _ = split_post(POST)
    out = set_meta(fm, "draft", True)
    assert out.index("title") < out.index("date") < out.index("draft")


def test_missing_delimiters_raises():
    with pytest.raises(ValueError):
        split_post("no frontmatter here\n")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_frontmatter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'editor.frontmatter'`

- [ ] **Step 3: Implement `frontmatter.py`**

Create `editor/frontmatter.py`:

```python
"""Read and write the TOML frontmatter Zola puts between +++ delimiters.

Uses tomlkit rather than tomllib so that editing one field leaves the
formatting, ordering and comments of every other field untouched.
"""
from __future__ import annotations

import tomlkit

DELIM = "+++"


def split_post(text: str) -> tuple[str, str]:
    """Split a post file into (frontmatter_toml, body)."""
    if not text.startswith(DELIM):
        raise ValueError("post does not start with +++ frontmatter")

    rest = text[len(DELIM):]
    end = rest.find(f"\n{DELIM}")
    if end == -1:
        raise ValueError("unterminated +++ frontmatter")

    frontmatter = rest[:end].lstrip("\n")
    body = rest[end + len(DELIM) + 1:].lstrip("\n")
    return frontmatter, body


def join_post(frontmatter_toml: str, body: str) -> str:
    fm = frontmatter_toml.rstrip("\n")
    return f"{DELIM}\n{fm}\n{DELIM}\n\n{body}"


def read_meta(frontmatter_toml: str) -> dict:
    return tomlkit.parse(frontmatter_toml).unwrap()


def set_meta(frontmatter_toml: str, key: str, value) -> str:
    doc = tomlkit.parse(frontmatter_toml)
    doc[key] = value
    return tomlkit.dumps(doc)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_frontmatter.py -v`
Expected: all PASS.

- [ ] **Step 5: Verify against every real post**

Run:
```bash
editor/.venv/bin/python - <<'PY'
from pathlib import Path
from editor.frontmatter import split_post, join_post

for path in sorted(Path("content/blog").glob("*.md")):
    if path.name == "_index.md":
        continue
    raw = path.read_text()
    fm, body = split_post(raw)
    assert join_post(fm, body) == raw, f"{path} did not round-trip"
    print("ok", path.name)
PY
```
Expected: `ok` for every post.

- [ ] **Step 6: Commit**

```bash
git add editor/frontmatter.py editor/tests/test_frontmatter.py
git commit -m "Add frontmatter read/write for the editor"
```

---

### Task 4: Publish pipeline

> **AMENDED 2026-09-20.** cloudy.nyc is now served by Cloudflare directly from
> an S3 website bucket, not by this Pi. Building locally therefore publishes
> nothing the public can see. `scripts/publish-site.sh` (already written and
> working) builds, syncs to S3 with per-type cache headers, and purges
> Cloudflare. This task wraps git around that script rather than calling
> `build-site.sh`.

**Files:**
- Create: `editor/publish.py`
- Create: `editor/tests/test_publish.py`

**Interfaces:**
- Consumes: `scripts/publish-site.sh`.
- Produces:
  - `PublishResult` dataclass: `committed: bool`, `sha: str | None`, `pushed: bool`, `published: bool`, `message: str`
  - `commit_paths(repo: Path, paths: list[str], message: str) -> str | None` — stages exactly `paths`, commits, returns sha, or `None` if nothing changed
  - `push(repo: Path) -> None` — raises `subprocess.CalledProcessError` on failure
  - `publish_site(repo: Path) -> None` — runs `scripts/publish-site.sh`; raises on failure
  - `publish(repo: Path, paths: list[str], message: str) -> PublishResult`

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_publish.py`:

```python
import subprocess
from pathlib import Path

import pytest

from editor.publish import commit_paths, publish


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "a.md").write_text("original\n")
    _git(tmp_path, "add", "content/a.md")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_commit_stages_only_named_paths(repo: Path):
    # The critical guarantee: unrelated dirty work is never swept in.
    (repo / "content" / "a.md").write_text("edited\n")
    (repo / "unrelated.txt").write_text("work in progress\n")

    sha = commit_paths(repo, ["content/a.md"], "edit a")

    assert sha
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["content/a.md"]
    assert "unrelated.txt" in _git(repo, "status", "--porcelain")


def test_commit_returns_none_when_nothing_changed(repo: Path):
    assert commit_paths(repo, ["content/a.md"], "no-op") is None


def test_untracked_named_file_is_committed(repo: Path):
    (repo / "content" / "new.md").write_text("new post\n")
    sha = commit_paths(repo, ["content/new.md"], "add new")
    assert sha
    assert "content/new.md" in _git(repo, "show", "--name-only", "--format=", "HEAD")


def test_publish_reports_failed_push_without_claiming_success(repo: Path, monkeypatch):
    (repo / "content" / "a.md").write_text("edited\n")

    def boom(_repo):
        raise subprocess.CalledProcessError(1, ["git", "push"], stderr="no remote")

    monkeypatch.setattr("editor.publish.push", boom)
    monkeypatch.setattr("editor.publish.publish_site", lambda _repo: None)

    result = publish(repo, ["content/a.md"], "edit a")

    assert result.committed is True
    assert result.pushed is False
    assert result.published is False
    assert "push" in result.message.lower()


def test_publish_reports_failed_site_publish(repo: Path, monkeypatch):
    (repo / "content" / "a.md").write_text("edited\n")

    monkeypatch.setattr("editor.publish.push", lambda _repo: None)

    def boom(_repo):
        raise subprocess.CalledProcessError(1, ["publish"], stderr="s3 sync failed")

    monkeypatch.setattr("editor.publish.publish_site", boom)

    result = publish(repo, ["content/a.md"], "edit a")

    assert result.pushed is True
    assert result.published is False
    assert "s3" in result.message.lower() or "publish" in result.message.lower()


def test_publish_happy_path(repo: Path, monkeypatch):
    (repo / "content" / "a.md").write_text("edited\n")
    monkeypatch.setattr("editor.publish.push", lambda _repo: None)
    monkeypatch.setattr("editor.publish.publish_site", lambda _repo: None)

    result = publish(repo, ["content/a.md"], "edit a")

    assert (result.committed, result.pushed, result.published) == (True, True, True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_publish.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'editor.publish'`

- [ ] **Step 3: Implement `publish.py`**

Create `editor/publish.py`:

```python
"""Commit, push, and publish the site.

Two rules are load-bearing here:

1. Only explicitly named paths are staged. This repo routinely has unrelated
   work in flight, and an editor that ran `git add -A` would quietly sweep it
   into a commit.
2. Publishing goes through scripts/publish-site.sh, which builds, syncs to S3
   and purges Cloudflare. cloudy.nyc is served by Cloudflare straight from S3,
   so a local build alone changes nothing the public can see -- and because
   pages live at stable URLs, skipping the purge would leave the old post up.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PublishResult:
    committed: bool
    sha: str | None
    pushed: bool
    published: bool
    message: str


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_paths(repo: Path, paths: list[str], message: str) -> str | None:
    """Stage exactly `paths` and commit. Returns the sha, or None if no change."""
    if not paths:
        return None

    # `git add --` with explicit paths: never -A, never .
    _git(repo, "add", "--", *paths)

    staged = _git(repo, "diff", "--cached", "--name-only")
    if not staged:
        return None

    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def push(repo: Path) -> None:
    _git(repo, "push", "origin", "HEAD")


def publish_site(repo: Path) -> None:
    subprocess.run(
        [str(repo / "scripts" / "publish-site.sh")],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def publish(repo: Path, paths: list[str], message: str) -> PublishResult:
    sha = commit_paths(repo, paths, message)
    if sha is None:
        return PublishResult(False, None, False, False, "nothing to publish")

    try:
        push(repo)
    except subprocess.CalledProcessError as exc:
        return PublishResult(
            True, sha, False, False,
            f"committed {sha[:8]} but push failed: {exc.stderr or exc}",
        )

    try:
        publish_site(repo)
    except subprocess.CalledProcessError as exc:
        return PublishResult(
            True, sha, True, False,
            f"pushed {sha[:8]} but publishing to S3 failed "
            f"(the live site still shows the previous version): {exc.stderr or exc}",
        )

    return PublishResult(True, sha, True, True, f"published {sha[:8]}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_publish.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add editor/publish.py editor/tests/test_publish.py
git commit -m "Add publish pipeline with path-scoped commits"
```

---

### Task 5: Image processing and S3 upload

**Files:**
- Create: `editor/images.py`
- Create: `editor/tests/test_images.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `process_image(data: bytes, max_edge: int = 1600, quality: int = 85) -> bytes` — EXIF-stripped, resized JPEG bytes
  - `image_key(post_slug: str, alt_text: str, data: bytes) -> str` — e.g. `guerilla-gardening/brick-border-a1b2c3d4.jpg`
  - `markdown_for(urls: list[str], alts: list[str]) -> str` — one URL renders a standalone `![]()`; two or more render an `.img-row` div
  - `upload(data: bytes, key: str, bucket: str, client) -> str` — puts the object with the immutable `Cache-Control` and returns `https://img.cloudy.nyc/<key>`

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_images.py`:

```python
import io

from PIL import Image

from editor.images import process_image, image_key, markdown_for, upload


def _jpeg_with_exif(size=(2400, 1800)) -> bytes:
    img = Image.new("RGB", size, (120, 140, 90))
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"   # Make
    exif[0x8825] = {}             # GPSInfo slot
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_process_strips_exif():
    out = process_image(_jpeg_with_exif())
    assert dict(Image.open(io.BytesIO(out)).getexif()) == {}


def test_process_caps_longest_edge():
    out = process_image(_jpeg_with_exif((2400, 1800)), max_edge=1600)
    assert max(Image.open(io.BytesIO(out)).size) == 1600


def test_process_leaves_small_images_alone():
    small = _jpeg_with_exif((400, 300))
    out = process_image(small, max_edge=1600)
    assert Image.open(io.BytesIO(out)).size == (400, 300)


def test_key_is_descriptive_and_content_addressed():
    data = _jpeg_with_exif()
    key = image_key("guerilla-gardening", "Brick Border!", data)
    assert key.startswith("guerilla-gardening/brick-border-")
    assert key.endswith(".jpg")


def test_same_bytes_produce_the_same_key():
    data = _jpeg_with_exif()
    assert image_key("p", "a", data) == image_key("p", "a", data)


def test_key_without_alt_text_still_works():
    key = image_key("p", "", _jpeg_with_exif())
    assert key.startswith("p/")
    assert key.endswith(".jpg")


def test_single_image_renders_standalone():
    out = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a cat"])
    assert out == "![a cat](https://img.cloudy.nyc/p/a.jpg)"


def test_multiple_images_render_as_img_row():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["a", "b"],
    )
    assert out.startswith('<div class="img-row">')
    assert out.rstrip().endswith("</div>")
    assert out.count("<img ") == 2


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_upload_sets_immutable_cache_headers():
    client = FakeS3()
    url = upload(b"bytes", "p/a.jpg", "img.cloudy.nyc", client)

    call = client.calls[0]
    assert call["Bucket"] == "img.cloudy.nyc"
    assert call["Key"] == "p/a.jpg"
    assert call["ContentType"] == "image/jpeg"
    assert call["CacheControl"] == "public, max-age=31536000, immutable"
    assert url == "https://img.cloudy.nyc/p/a.jpg"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_images.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'editor.images'`

- [ ] **Step 3: Implement `images.py`**

Create `editor/images.py`:

```python
"""Prepare uploaded photos and put them in S3.

Same pipeline as scripts/upload-image.py: re-encoding is what strips EXIF (and
with it, the GPS coordinates a phone camera attaches), and content-addressed
keys make the far-future Cache-Control safe -- different bytes always get a
different URL.
"""
from __future__ import annotations

import hashlib
import io
import re

from PIL import Image, ImageOps

IMAGE_HOST = "img.cloudy.nyc"
CACHE_CONTROL = "public, max-age=31536000, immutable"


def process_image(data: bytes, max_edge: int = 1600, quality: int = 85) -> bytes:
    img = Image.open(io.BytesIO(data))
    # Apply the orientation tag before dropping EXIF, or phone photos rotate.
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    width, height = img.size
    longest = max(width, height)
    if longest > max_edge:
        scale = max_edge / longest
        img = img.resize((round(width * scale), round(height * scale)), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40]


def image_key(post_slug: str, alt_text: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:8]
    stem = _slugify(alt_text)
    name = f"{stem}-{digest}" if stem else digest
    return f"{post_slug}/{name}.jpg"


def markdown_for(urls: list[str], alts: list[str]) -> str:
    """One image is a standalone; several become an .img-row."""
    if len(urls) == 1:
        return f"![{alts[0]}]({urls[0]})"

    lines = ['<div class="img-row">']
    lines += [f'<img src="{url}" alt="{alt}">' for url, alt in zip(urls, alts)]
    lines.append("</div>")
    return "\n".join(lines)


def upload(data: bytes, key: str, bucket: str, client) -> str:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType="image/jpeg",
        CacheControl=CACHE_CONTROL,
    )
    return f"https://{IMAGE_HOST}/{key}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_images.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add editor/images.py editor/tests/test_images.py
git commit -m "Add image processing and S3 upload for the editor"
```

---

### Task 6: Service skeleton, exposure guard, and host wiring

After this task the editor answers at `https://edit.cloudy.nyc` from the LAN with a post list, and refuses to boot if it is ever routed publicly.

**Files:**
- Create: `editor/config.py`
- Create: `editor/guard.py`
- Create: `editor/app.py`
- Create: `editor/tests/test_guard.py`
- Create: `systemd/blog-editor.service`
- Modify: `Makefile`
- Modify: `../http-routing/Caddyfile`
- Modify: `../http-routing/CLAUDE.md`

**Interfaces:**
- Consumes: `frontmatter.split_post`, `frontmatter.read_meta` (Task 3).
- Produces:
  - `config.REPO: Path`, `config.HOSTNAME: str`, `config.PORT: int`, `config.load_aws_env() -> dict`
  - `guard.assert_not_publicly_routed(hostname: str, cloudflared_config: Path) -> None` — raises `RuntimeError` if the hostname appears as a tunnel ingress entry
  - `GET /api/posts -> [{slug, title, date, draft}]`
  - `GET /healthz -> {"ok": true}`

- [ ] **Step 1: Write the failing guard tests**

Create `editor/tests/test_guard.py`:

```python
import pytest

from editor.guard import assert_not_publicly_routed

EXPOSED = """
ingress:
  - hostname: cloudy.nyc
    service: https://192.168.1.185:443
  - hostname: edit.cloudy.nyc
    service: https://192.168.1.185:443
  - service: http_status:404
"""

SAFE = """
ingress:
  - hostname: cloudy.nyc
    service: https://192.168.1.185:443
  - service: http_status:404
"""


def test_raises_when_hostname_is_tunnelled(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(EXPOSED)
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_passes_when_hostname_is_absent(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAFE)
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_passes_when_config_is_missing(tmp_path):
    # A missing tunnel config means no tunnel, which is safe.
    assert_not_publicly_routed("edit.cloudy.nyc", tmp_path / "nope.yml")


def test_substring_hostname_does_not_false_positive(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("ingress:\n  - hostname: noedit.cloudy.nyc\n")
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'editor.guard'`

- [ ] **Step 3: Implement config and guard**

Create `editor/config.py`:

```python
"""Paths and settings for the editor service."""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTTP_ROUTING = REPO.parent / "http-routing"
CLOUDFLARED_CONFIG = HTTP_ROUTING / "cloudflared" / "config.yml"

HOSTNAME = os.environ.get("EDITOR_HOSTNAME", "edit.cloudy.nyc")
PORT = int(os.environ.get("EDITOR_PORT", "8804"))
BLOG_DIR = REPO / "content" / "blog"


def load_aws_env() -> dict:
    """Read the gitignored .aws.env written by personal-cloud-infra."""
    env: dict[str, str] = {}
    path = REPO / ".aws.env"
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env
```

Create `editor/guard.py`:

```python
"""Refuse to run if this service has been exposed to the internet.

The editor can commit to the repo, push to GitHub and write to S3. The only
thing keeping that private is the network boundary, so a misconfiguration that
routes it through the tunnel should fail loudly at boot rather than quietly
becoming a public write endpoint.
"""
from __future__ import annotations

import re
from pathlib import Path


def assert_not_publicly_routed(hostname: str, cloudflared_config: Path) -> None:
    if not cloudflared_config.exists():
        return

    pattern = re.compile(
        rf"^\s*-?\s*hostname:\s*{re.escape(hostname)}\s*$", re.MULTILINE
    )
    if pattern.search(cloudflared_config.read_text()):
        raise RuntimeError(
            f"{hostname} is publicly routed via {cloudflared_config}. "
            "The editor can write to git and S3 and must stay LAN-only. "
            "Remove the tunnel ingress entry before starting this service."
        )
```

- [ ] **Step 4: Run the guard tests to verify they pass**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_guard.py -v`
Expected: all PASS.

- [ ] **Step 5: Implement the app skeleton**

Create `editor/app.py`:

```python
"""The blog editor service. LAN-only; see editor/guard.py."""
from __future__ import annotations

from fastapi import FastAPI

from editor import config
from editor.frontmatter import read_meta, split_post
from editor.guard import assert_not_publicly_routed

assert_not_publicly_routed(config.HOSTNAME, config.CLOUDFLARED_CONFIG)

app = FastAPI(title="blog editor")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/posts")
def list_posts():
    posts = []
    for path in sorted(config.BLOG_DIR.glob("*.md")):
        if path.name == "_index.md":
            continue
        frontmatter, _ = split_post(path.read_text())
        meta = read_meta(frontmatter)
        posts.append(
            {
                "slug": path.stem,
                "title": meta.get("title", path.stem),
                "date": str(meta.get("date", "")),
                "draft": bool(meta.get("draft", False)),
            }
        )
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts
```

- [ ] **Step 6: Run it and verify locally**

Run: `editor/.venv/bin/uvicorn editor.app:app --host 127.0.0.1 --port 8804 &`

Then: `curl -s http://127.0.0.1:8804/healthz` → expect `{"ok":true}`
Then: `curl -s http://127.0.0.1:8804/api/posts | head -c 200` → expect JSON including `guerilla-gardening`.

Stop it: `fuser -k 8804/tcp`

- [ ] **Step 7: Verify the guard actually fires**

Run:
```bash
EDITOR_HOSTNAME=cloudy.nyc editor/.venv/bin/python -c "import editor.app" 2>&1 | tail -3
```
Expected: `RuntimeError: cloudy.nyc is publicly routed ...` — because `cloudy.nyc`
*is* in the tunnel config, proving the assertion works against the real file.

- [ ] **Step 8: Add the systemd unit**

Create `systemd/blog-editor.service`:

```ini
[Unit]
Description=blog-editor — LAN-only editor for cloudy.nyc (FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=peter
WorkingDirectory=/home/peter/projects/personal/personal-site
ExecStart=/home/peter/projects/personal/personal-site/editor/.venv/bin/uvicorn \
    editor.app:app --host 127.0.0.1 --port 8804
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Add to `Makefile`:

```makefile
EDITOR_SERVICE := blog-editor.service

editor-install:
	sudo cp systemd/$(EDITOR_SERVICE) /etc/systemd/system/$(EDITOR_SERVICE)
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(EDITOR_SERVICE)

editor-restart:
	sudo systemctl restart $(EDITOR_SERVICE)

editor-logs:
	journalctl -u $(EDITOR_SERVICE) -f
```

Add `editor-install editor-restart editor-logs` to `.PHONY`.

Run: `make editor-install`
Then: `systemctl is-active blog-editor` → expect `active`

- [ ] **Step 9: Wire the LAN-only host**

Modify `../http-routing/Caddyfile` — add `cloudy.nyc edit` to the `dynamic_dns`
`domains` block so the grey-cloud A record is managed:

```
	dynamic_dns {
		provider cloudflare {env.CLOUDFLARE_API_TOKEN}
		domains {
			ubbe.nyc cloud pi.tortoise home status uptime traffic mayor chat depot write
			cloudy.nyc edit
		}
```

Then add the site block at the end of the file:

```
# --- edit.cloudy.nyc: LAN-ONLY blog editor -----------------------------------
# ⚠ This host must NEVER get a cloudflared ingress entry. The service behind it
# commits to the personal-site repo, pushes to GitHub and writes to S3 — the
# network boundary is the only thing making that safe. It is a grey-cloud A
# record via dynamic_dns above, and blog-editor.service asserts at startup that
# this hostname is absent from cloudflared/config.yml, refusing to boot if not.
edit.cloudy.nyc {
	bind {$ROUTER_BIND_IP}
	reverse_proxy 127.0.0.1:8804
}
```

- [ ] **Step 10: Validate and reload Caddy**

Run: `cd ../http-routing && make validate-caddy 2>&1 | tail -2`
Expected: `Valid configuration`

Run: `make reload-caddy`

Wait for the cert, then verify from the LAN:
Run: `curl -s --resolve edit.cloudy.nyc:443:192.168.1.185 https://edit.cloudy.nyc/healthz`
Expected: `{"ok":true}`

- [ ] **Step 11: Confirm it is NOT publicly reachable**

Run: `curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 https://edit.cloudy.nyc/healthz`
Expected: a failure or a Cloudflare error page — **not** `{"ok":true}`. The host
has no tunnel ingress, so the public internet cannot reach it.

- [ ] **Step 12: Document the host**

Modify `../http-routing/CLAUDE.md` — add to the Routes table:

```
| `edit.cloudy.nyc` | `127.0.0.1:8804` (blog-editor — LAN-ONLY, **never tunnel this**) | LAN-only (grey-A) |
```

- [ ] **Step 13: Commit**

```bash
git add editor/config.py editor/guard.py editor/app.py editor/tests/test_guard.py systemd/blog-editor.service Makefile
git commit -m "Add the LAN-only editor service and route edit.cloudy.nyc to it"
cd ../http-routing
git add Caddyfile CLAUDE.md
git commit -m "route: edit.cloudy.nyc -> blog-editor (LAN-only, never tunnelled)"
cd ../personal-site
```

---

### Task 7: Post read API and the editor page

Renders a post as editable blocks in the editor UI, styled like the real site. Read-only at this stage.

**Files:**
- Modify: `editor/app.py`
- Create: `editor/web/index.html`
- Create: `editor/web/editor.js`
- Create: `editor/web/editor.css`
- Create: `editor/tests/test_api_posts.py`

**Interfaces:**
- Consumes: `blocks.parse_blocks` (Task 2), `frontmatter` (Task 3), `config` (Task 6).
- Produces:
  - `GET /api/posts/{slug}` → `{slug, meta: {title, date, draft}, hash: str, blocks: [{index, kind, source, html}]}`
  - `hash` is the sha256 of the post file at read time; every write echoes it back for the staleness check.
  - `GET /` and `GET /edit/{slug}` serve the editor page.

- [ ] **Step 1: Write the failing API test**

Create `editor/tests/test_api_posts.py`:

```python
from fastapi.testclient import TestClient

from editor.app import app

client = TestClient(app)


def test_list_posts_includes_the_gardening_post():
    slugs = [p["slug"] for p in client.get("/api/posts").json()]
    assert "guerilla-gardening" in slugs


def test_get_post_returns_blocks_and_hash():
    data = client.get("/api/posts/guerilla-gardening").json()

    assert data["meta"]["title"] == "Guerrilla Gardening"
    assert len(data["hash"]) == 64
    assert len(data["blocks"]) > 5

    first = data["blocks"][0]
    assert first["index"] == 0
    assert first["kind"] == "paragraph"
    assert "<p>" in first["html"]


def test_get_post_marks_image_rows():
    data = client.get("/api/posts/guerilla-gardening").json()
    kinds = {b["kind"] for b in data["blocks"]}
    assert "img_row" in kinds
    assert "image" in kinds


def test_unknown_post_404s():
    assert client.get("/api/posts/does-not-exist").status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_api_posts.py -v`
Expected: FAIL — `/api/posts/{slug}` returns 404 for the gardening post (route not defined).

- [ ] **Step 3: Add the read API**

Modify `editor/app.py` — add imports and routes:

```python
import hashlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from editor.blocks import parse_blocks


def _post_path(slug: str):
    path = config.BLOG_DIR / f"{slug}.md"
    if not path.exists() or path.name == "_index.md":
        raise HTTPException(status_code=404, detail=f"no post {slug!r}")
    return path


def _read_post(slug: str):
    path = _post_path(slug)
    raw = path.read_text()
    frontmatter, body = split_post(raw)
    return path, raw, frontmatter, body


@app.get("/api/posts/{slug}")
def get_post(slug: str):
    _, raw, frontmatter, body = _read_post(slug)
    meta = read_meta(frontmatter)
    return {
        "slug": slug,
        "meta": {
            "title": meta.get("title", slug),
            "date": str(meta.get("date", "")),
            "draft": bool(meta.get("draft", False)),
        },
        "hash": hashlib.sha256(raw.encode()).hexdigest(),
        "blocks": [
            {"index": b.index, "kind": b.kind, "source": b.source, "html": b.html}
            for b in parse_blocks(body)
        ],
    }
```

And at the bottom of the file, serve the front end:

```python
WEB = Path(__file__).resolve().parent / "web"


@app.get("/")
@app.get("/edit/{slug}")
def editor_page(slug: str | None = None):
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
```

Add `from pathlib import Path` to the imports.

- [ ] **Step 4: Run to verify it passes**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_api_posts.py -v`
Expected: all PASS.

- [ ] **Step 5: Build the editor page**

Create `editor/web/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Editing — Peter's blog</title>
<link rel="stylesheet" href="/static/editor.css">
</head>
<body>
  <header class="bar">
    <select id="post-picker"></select>
    <span id="status" class="status"></span>
    <button id="publish" class="publish">Publish</button>
  </header>
  <main class="container">
    <h1 id="post-title" class="title" data-field="title"></h1>
    <div id="post-meta" class="post-meta"></div>
    <div id="blocks"></div>
  </main>
  <script src="/static/editor.js"></script>
</body>
</html>
```

Create `editor/web/editor.css`:

```css
/* Mirrors the site's reading column so editing looks like the real post. */
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.6;
    color: #333;
    margin: 0;
    padding: 0 0 6rem;
}

.container { max-width: 800px; margin: 0 auto; padding: 1rem; }

.bar {
    position: sticky; top: 0; z-index: 10;
    display: flex; gap: 0.75rem; align-items: center;
    padding: 0.75rem 1rem;
    background: #f8f9fa; border-bottom: 1px solid #e9ecef;
}

.bar select { flex: 1; padding: 0.5rem; font-size: 1rem; }
.status { font-size: 0.85rem; color: #666; min-width: 6rem; text-align: right; }

.publish {
    padding: 0.5rem 1rem; font-size: 1rem;
    border: 1px solid #0066cc; border-radius: 6px;
    background: #0066cc; color: #fff; cursor: pointer;
}
.publish:disabled { opacity: 0.5; cursor: default; }

.title { font-size: 1.6rem; font-weight: 600; }
.post-meta { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }

.block {
    position: relative;
    border: 1px solid transparent; border-radius: 6px;
    padding: 0.25rem 0.5rem; margin: 0.25rem -0.5rem;
    cursor: text;
}
.block:hover { border-color: #d5e6f7; background: #fbfdff; }
.block.editing { border-color: #0066cc; background: #fff; cursor: default; }

.block textarea {
    width: 100%; box-sizing: border-box;
    font: inherit; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.95rem; line-height: 1.5;
    border: none; outline: none; resize: vertical; background: transparent;
}

.block img { max-width: 100%; height: auto; border-radius: 6px; display: block; margin: 1rem auto; }
.img-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.75rem; margin: 1rem 0; }
.img-row img { margin: 0; width: 100%; height: 100%; object-fit: cover; }
```

Create `editor/web/editor.js`:

```js
// Editor front end. Blocks render as HTML; tapping one swaps in its raw
// markdown, so the source is always what gets edited and saved.
const state = { slug: null, hash: null, blocks: [] };

const els = {
  picker: document.getElementById('post-picker'),
  title: document.getElementById('post-title'),
  meta: document.getElementById('post-meta'),
  blocks: document.getElementById('blocks'),
  status: document.getElementById('status'),
  publish: document.getElementById('publish'),
};

function setStatus(text) {
  els.status.textContent = text;
}

async function loadPostList() {
  const posts = await (await fetch('/api/posts')).json();
  els.picker.innerHTML = posts
    .map((p) => `<option value="${p.slug}">${p.title}${p.draft ? ' (draft)' : ''}</option>`)
    .join('');
  return posts;
}

async function loadPost(slug) {
  const data = await (await fetch(`/api/posts/${slug}`)).json();
  state.slug = data.slug;
  state.hash = data.hash;
  state.blocks = data.blocks;

  els.title.textContent = data.meta.title;
  els.meta.textContent = data.meta.date + (data.meta.draft ? ' · draft' : '');
  renderBlocks();
  setStatus('');
}

function renderBlocks() {
  els.blocks.innerHTML = '';
  state.blocks.forEach((block) => {
    const el = document.createElement('div');
    el.className = 'block';
    el.dataset.index = block.index;
    el.innerHTML = block.html;
    el.addEventListener('click', () => startEditing(el, block));
    els.blocks.appendChild(el);
  });
}

function startEditing(el, block) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing');
  el.innerHTML = '';

  const textarea = document.createElement('textarea');
  textarea.value = block.source;
  textarea.rows = Math.max(2, block.source.split('\n').length + 1);
  el.appendChild(textarea);
  textarea.focus();

  textarea.addEventListener('blur', async () => {
    el.classList.remove('editing');
    if (textarea.value === block.source) {
      el.innerHTML = block.html;
      return;
    }
    await saveBlock(block.index, textarea.value);
  });
}

async function saveBlock(index, source) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, hash: state.hash }),
  });

  if (res.status === 409) {
    setStatus('changed on disk — reload');
    return;
  }

  const data = await res.json();
  state.hash = data.hash;
  state.blocks = data.blocks;
  renderBlocks();
  setStatus('saved');
}

els.picker.addEventListener('change', () => loadPost(els.picker.value));

(async function main() {
  const posts = await loadPostList();
  const fromPath = location.pathname.startsWith('/edit/')
    ? location.pathname.slice('/edit/'.length)
    : null;
  const slug = fromPath || (posts[0] && posts[0].slug);
  if (slug) {
    els.picker.value = slug;
    await loadPost(slug);
  }
})();
```

- [ ] **Step 6: Verify the page renders the post**

Run: `make editor-restart`
Then open `https://edit.cloudy.nyc/` from a LAN browser (or screenshot it headless).
Expected: the gardening post renders with its images, hovering a paragraph
highlights it. Saving is not wired yet — that's Task 8.

- [ ] **Step 7: Commit**

```bash
git add editor/app.py editor/web editor/tests/test_api_posts.py
git commit -m "Render posts as editable blocks in the editor"
```

---

### Task 8: Block write API

Closes the loop on text editing: tapping a paragraph, changing it, and blurring persists it to the working tree.

**Files:**
- Modify: `editor/app.py`
- Create: `editor/tests/test_api_blocks.py`

**Interfaces:**
- Consumes: `blocks.replace_block`, `insert_block`, `delete_block` (Task 2).
- Produces:
  - `PUT /api/posts/{slug}/blocks/{index}` body `{source, hash}` → same shape as `GET /api/posts/{slug}`; **409** if `hash` is stale
  - `POST /api/posts/{slug}/blocks` body `{index, source, hash}` → inserts before `index`
  - `DELETE /api/posts/{slug}/blocks/{index}` body `{hash}`

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_api_blocks.py`:

```python
import shutil

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "editor-test-post"

POST = """+++
title = "Editor Test Post"
date = 2026-01-01
draft = true
+++

First para.

## A heading

Second para.
"""


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST)
    yield path
    path.unlink(missing_ok=True)


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


def test_edit_block_persists_to_disk(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Rewritten.", "hash": data["hash"]},
    )
    assert res.status_code == 200
    assert "Rewritten." in temp_post.read_text()
    assert "## A heading" in temp_post.read_text()


def test_edit_returns_fresh_hash_and_blocks(temp_post):
    data = _get()
    out = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Rewritten.", "hash": data["hash"]},
    ).json()
    assert out["hash"] != data["hash"]
    assert out["blocks"][0]["source"] == "Rewritten."


def test_stale_hash_is_refused(temp_post):
    data = _get()
    temp_post.write_text(POST.replace("First para.", "Changed elsewhere."))

    res = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Mine.", "hash": data["hash"]},
    )

    assert res.status_code == 409
    assert "Changed elsewhere." in temp_post.read_text()


def test_insert_block(temp_post):
    data = _get()
    out = client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": "Inserted.", "hash": data["hash"]},
    ).json()
    assert out["blocks"][1]["source"] == "Inserted."
    assert len(out["blocks"]) == len(data["blocks"]) + 1


def test_delete_block(temp_post):
    data = _get()
    out = client.request(
        "DELETE",
        f"/api/posts/{SLUG}/blocks/1",
        json={"hash": data["hash"]},
    ).json()
    assert len(out["blocks"]) == len(data["blocks"]) - 1
    assert "## A heading" not in temp_post.read_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_api_blocks.py -v`
Expected: FAIL — 405/404, the write routes don't exist.

- [ ] **Step 3: Implement the write routes**

Modify `editor/app.py` — add:

```python
from pydantic import BaseModel

from editor.blocks import delete_block, insert_block, replace_block
from editor.frontmatter import join_post


class BlockEdit(BaseModel):
    source: str
    hash: str


class BlockInsert(BaseModel):
    index: int
    source: str
    hash: str


class BlockDelete(BaseModel):
    hash: str


def _write_body(slug: str, expected_hash: str, transform):
    """Rewrite a post's body, refusing if the file changed since it was read."""
    path, raw, frontmatter, body = _read_post(slug)

    actual = hashlib.sha256(raw.encode()).hexdigest()
    if actual != expected_hash:
        raise HTTPException(
            status_code=409,
            detail="post changed on disk since it was loaded; reload before saving",
        )

    path.write_text(join_post(frontmatter, transform(body)))
    return get_post(slug)


@app.put("/api/posts/{slug}/blocks/{index}")
def edit_block(slug: str, index: int, edit: BlockEdit):
    return _write_body(slug, edit.hash, lambda body: replace_block(body, index, edit.source))


@app.post("/api/posts/{slug}/blocks")
def add_block(slug: str, edit: BlockInsert):
    return _write_body(slug, edit.hash, lambda body: insert_block(body, edit.index, edit.source))


@app.delete("/api/posts/{slug}/blocks/{index}")
def remove_block(slug: str, index: int, edit: BlockDelete):
    return _write_body(slug, edit.hash, lambda body: delete_block(body, index))
```

- [ ] **Step 4: Run to verify it passes**

Run: `editor/.venv/bin/python -m pytest editor/tests/ -v`
Expected: all PASS (the whole suite).

- [ ] **Step 5: Add insert/delete affordances to the front end**

Modify `editor/web/editor.js` — in `renderBlocks()`, after appending each block
element, add the controls:

```js
function blockControls(block) {
  const bar = document.createElement('div');
  bar.className = 'block-controls';

  const add = document.createElement('button');
  add.textContent = '+';
  add.title = 'Insert a paragraph here';
  add.addEventListener('click', (e) => {
    e.stopPropagation();
    insertBlock(block.index);
  });

  const del = document.createElement('button');
  del.textContent = '×';
  del.title = 'Delete this block';
  del.addEventListener('click', (e) => {
    e.stopPropagation();
    if (confirm('Delete this block?')) removeBlock(block.index);
  });

  bar.append(add, del);
  return bar;
}

async function insertBlock(index) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ index, source: 'New paragraph.', hash: state.hash }),
  });
  await applyWrite(res);
}

async function removeBlock(index) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hash: state.hash }),
  });
  await applyWrite(res);
}

async function applyWrite(res) {
  if (res.status === 409) {
    setStatus('changed on disk — reload');
    return;
  }
  const data = await res.json();
  state.hash = data.hash;
  state.blocks = data.blocks;
  renderBlocks();
  setStatus('saved');
}
```

Call `el.appendChild(blockControls(block))` inside the `forEach` in
`renderBlocks()`, just before `els.blocks.appendChild(el)`.

Then replace `saveBlock` entirely so it shares `applyWrite`:

```js
async function saveBlock(index, source) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, hash: state.hash }),
  });
  await applyWrite(res);
}
```

Add to `editor/web/editor.css`:

```css
.block-controls {
    position: absolute; top: 0.25rem; right: 0.25rem;
    display: none; gap: 0.25rem;
}
.block:hover .block-controls { display: flex; }
.block-controls button {
    width: 28px; height: 28px; line-height: 1;
    border: 1px solid #ddd; border-radius: 6px;
    background: #fff; cursor: pointer; font-size: 1rem;
}
```

- [ ] **Step 6: Verify end to end in the browser**

Run: `make editor-restart`, open `https://edit.cloudy.nyc/`, tap a paragraph,
change it, tap away. Expect "saved".

Confirm it hit the working tree: `git diff --stat content/blog/`
Expected: the edited post shows as modified.

Then revert the test edit: `git checkout content/blog/<slug>.md`

- [ ] **Step 7: Commit**

```bash
git add editor/app.py editor/web editor/tests/test_api_blocks.py
git commit -m "Add block editing, insert and delete to the editor"
```

---

### Task 9: Frontmatter editing (title, date, draft, slug)

**Files:**
- Modify: `editor/app.py`
- Modify: `editor/web/editor.js`
- Create: `editor/tests/test_api_meta.py`

**Interfaces:**
- Consumes: `frontmatter.set_meta` (Task 3), `publish.commit_paths` (Task 4, for the rename).
- Produces:
  - `PUT /api/posts/{slug}/meta` body `{title?, date?, draft?, hash}` → same shape as `GET /api/posts/{slug}`
  - `POST /api/posts/{slug}/rename` body `{new_slug, hash}` → `{slug, warning}`; uses `git mv` so history follows the file

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_api_meta.py`:

```python
import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "meta-test-post"

POST = """+++
title = "Meta Test"
date = 2026-01-01
draft = true
+++

Body.
"""


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST)
    yield path
    path.unlink(missing_ok=True)
    (config.BLOG_DIR / "renamed-post.md").unlink(missing_ok=True)


def test_set_title(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta",
        json={"title": "A Better Title", "hash": data["hash"]},
    ).json()

    assert out["meta"]["title"] == "A Better Title"
    assert 'title = "A Better Title"' in temp_post.read_text()
    assert "date = 2026-01-01" in temp_post.read_text()


def test_set_draft_false(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta", json={"draft": False, "hash": data["hash"]}
    ).json()
    assert out["meta"]["draft"] is False


def test_set_date(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta", json={"date": "2026-02-02", "hash": data["hash"]}
    ).json()
    assert out["meta"]["date"] == "2026-02-02"


def test_stale_hash_refused(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    temp_post.write_text(POST.replace("Body.", "Changed."))
    res = client.put(
        f"/api/posts/{SLUG}/meta", json={"title": "Nope", "hash": data["hash"]}
    )
    assert res.status_code == 409


def test_rename_moves_the_file_and_warns(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.post(
        f"/api/posts/{SLUG}/rename",
        json={"new_slug": "renamed-post", "hash": data["hash"]},
    ).json()

    assert out["slug"] == "renamed-post"
    assert "link" in out["warning"].lower()
    assert (config.BLOG_DIR / "renamed-post.md").exists()
    assert not temp_post.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_api_meta.py -v`
Expected: FAIL — routes not defined.

- [ ] **Step 3: Implement the meta routes**

Modify `editor/app.py`:

```python
import subprocess

from editor.frontmatter import set_meta


class MetaEdit(BaseModel):
    hash: str
    title: str | None = None
    date: str | None = None
    draft: bool | None = None


class Rename(BaseModel):
    new_slug: str
    hash: str


@app.put("/api/posts/{slug}/meta")
def edit_meta(slug: str, edit: MetaEdit):
    path, raw, frontmatter, body = _read_post(slug)

    if hashlib.sha256(raw.encode()).hexdigest() != edit.hash:
        raise HTTPException(
            status_code=409,
            detail="post changed on disk since it was loaded; reload before saving",
        )

    updates = edit.model_dump(exclude={"hash"}, exclude_none=True)
    for key, value in updates.items():
        if key == "date":
            value = datetime.date.fromisoformat(value)
        frontmatter = set_meta(frontmatter, key, value)

    path.write_text(join_post(frontmatter, body))
    return get_post(slug)


@app.post("/api/posts/{slug}/rename")
def rename_post(slug: str, rename: Rename):
    path, raw, _, _ = _read_post(slug)

    if hashlib.sha256(raw.encode()).hexdigest() != rename.hash:
        raise HTTPException(status_code=409, detail="post changed on disk; reload")

    new_slug = re.sub(r"[^a-z0-9-]+", "-", rename.new_slug.lower()).strip("-")
    if not new_slug:
        raise HTTPException(status_code=400, detail="slug is empty after sanitising")

    target = config.BLOG_DIR / f"{new_slug}.md"
    if target.exists():
        raise HTTPException(status_code=409, detail=f"{new_slug} already exists")

    # git mv keeps the file's history attached to the new name.
    subprocess.run(
        ["git", "mv", str(path.relative_to(config.REPO)), str(target.relative_to(config.REPO))],
        cwd=config.REPO, check=True, capture_output=True, text=True,
    )

    return {
        "slug": new_slug,
        "warning": f"/blog/{slug}/ will 404 — any existing links to it will break.",
    }
```

Add `import datetime` and `import re` to the imports.

- [ ] **Step 4: Run to verify it passes**

Run: `editor/.venv/bin/python -m pytest editor/tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Wire the title and meta UI**

Modify `editor/web/editor.js` — make the title editable and add a meta row:

```js
function startEditingTitle() {
  if (els.title.dataset.editing) return;
  els.title.dataset.editing = '1';

  const input = document.createElement('input');
  input.type = 'text';
  input.value = els.title.textContent;
  input.className = 'title-input';
  els.title.textContent = '';
  els.title.appendChild(input);
  input.focus();

  input.addEventListener('blur', async () => {
    delete els.title.dataset.editing;
    await saveMeta({ title: input.value });
  });
}

async function saveMeta(fields) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/meta`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fields, hash: state.hash }),
  });

  if (res.status === 409) {
    setStatus('changed on disk — reload');
    return;
  }

  const data = await res.json();
  state.hash = data.hash;
  els.title.textContent = data.meta.title;
  renderMeta(data.meta);
  setStatus('saved');
}

function renderMeta(meta) {
  els.meta.innerHTML = '';

  const date = document.createElement('input');
  date.type = 'date';
  date.value = meta.date;
  date.addEventListener('change', () => saveMeta({ date: date.value }));

  const draftLabel = document.createElement('label');
  const draft = document.createElement('input');
  draft.type = 'checkbox';
  draft.checked = meta.draft;
  draft.addEventListener('change', () => saveMeta({ draft: draft.checked }));
  draftLabel.append(draft, document.createTextNode(' draft'));

  els.meta.append(date, draftLabel);
}
```

Call `els.title.addEventListener('click', startEditingTitle)` in `main()`, and
replace the `els.meta.textContent = ...` line in `loadPost` with
`renderMeta(data.meta)`.

Add to `editor/web/editor.css`:

```css
.title-input { font: inherit; width: 100%; border: none; outline: none; }
.post-meta { display: flex; gap: 1rem; align-items: center; }
.post-meta input[type="date"] { font: inherit; font-size: 0.9rem; }
```

- [ ] **Step 6: Verify in the browser**

Run: `make editor-restart`, open the editor, change a title and toggle draft.
Expected: "saved", and `git diff content/blog/` shows the frontmatter change.
Revert afterwards with `git checkout content/blog/`.

- [ ] **Step 7: Commit**

```bash
git add editor/app.py editor/web editor/tests/test_api_meta.py
git commit -m "Add title, date, draft and slug editing"
```

---

### Task 10: Image upload

**Files:**
- Modify: `editor/app.py`
- Modify: `editor/web/editor.js`
- Modify: `editor/web/editor.css`
- Create: `editor/tests/test_api_images.py`

**Interfaces:**
- Consumes: `images.*` (Task 5), `blocks.insert_block` (Task 2).
- Produces:
  - `POST /api/posts/{slug}/images` — multipart: `files` (1..n), `alts` (JSON array of strings), `index` (block position), `hash` → same shape as `GET /api/posts/{slug}`
  - `app.state.s3` — the boto3 client, overridable in tests

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_api_images.py`:

```python
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "image-test-post"

POST = """+++
title = "Image Test"
date = 2026-01-01
draft = true
+++

Intro.

Outro.
"""


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST)
    app.state.s3 = FakeS3()
    yield path
    path.unlink(missing_ok=True)


def _png(size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def test_single_upload_inserts_standalone_image(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["a cat"]', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 200
    text = temp_post.read_text()
    assert "![a cat](https://img.cloudy.nyc/" in text
    assert app.state.s3.calls[0]["CacheControl"] == "public, max-age=31536000, immutable"


def test_multiple_uploads_insert_an_img_row(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    client.post(
        f"/api/posts/{SLUG}/images",
        files=[
            ("files", ("a.png", _png((800, 600)), "image/png")),
            ("files", ("b.png", _png((640, 480)), "image/png")),
        ],
        data={"alts": '["a", "b"]', "index": "1", "hash": data["hash"]},
    )

    text = temp_post.read_text()
    assert '<div class="img-row">' in text
    assert text.count("<img ") == 2
    assert len(app.state.s3.calls) == 2


def test_uploaded_bytes_are_reencoded_as_jpeg(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]', "index": "1", "hash": data["hash"]},
    )

    body = app.state.s3.calls[0]["Body"]
    assert Image.open(io.BytesIO(body)).format == "JPEG"


def test_stale_hash_refused(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    temp_post.write_text(POST.replace("Intro.", "Changed."))

    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 409
    assert not app.state.s3.calls
```

- [ ] **Step 2: Run to verify it fails**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_api_images.py -v`
Expected: FAIL — route not defined.

- [ ] **Step 3: Implement the upload route**

Modify `editor/app.py`:

```python
import json

import boto3
from fastapi import File, Form, UploadFile

from editor.images import image_key, markdown_for, process_image, upload


def _s3():
    """Lazily build the client so tests can inject a fake before first use."""
    if not hasattr(app.state, "s3") or app.state.s3 is None:
        env = config.load_aws_env()
        app.state.s3 = boto3.client(
            "s3",
            aws_access_key_id=env.get("PERSONAL_SITE_IMAGES_ACCESS_KEY_ID"),
            aws_secret_access_key=env.get("PERSONAL_SITE_IMAGES_SECRET_ACCESS_KEY"),
            region_name=env.get("AWS_REGION", "us-east-1"),
        )
    return app.state.s3


@app.post("/api/posts/{slug}/images")
async def add_images(
    slug: str,
    index: int = Form(...),
    hash: str = Form(...),
    alts: str = Form("[]"),
    files: list[UploadFile] = File(...),
):
    _, raw, _, _ = _read_post(slug)
    if hashlib.sha256(raw.encode()).hexdigest() != hash:
        raise HTTPException(
            status_code=409,
            detail="post changed on disk since it was loaded; reload before saving",
        )

    alt_list = json.loads(alts)
    bucket = config.load_aws_env().get("PERSONAL_SITE_IMAGES_BUCKET", "img.cloudy.nyc")

    urls, used_alts = [], []
    for position, upload_file in enumerate(files):
        alt = alt_list[position] if position < len(alt_list) else ""
        processed = process_image(await upload_file.read())
        key = image_key(slug, alt, processed)
        urls.append(upload(processed, key, bucket, _s3()))
        used_alts.append(alt)

    snippet = markdown_for(urls, used_alts)
    return _write_body(slug, hash, lambda body: insert_block(body, index, snippet))
```

- [ ] **Step 4: Run to verify it passes**

Run: `editor/.venv/bin/python -m pytest editor/tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Add the upload UI**

Modify `editor/web/editor.js` — extend `blockControls` with a photo button:

```js
  const photo = document.createElement('button');
  photo.textContent = '🖼';
  photo.title = 'Add photos here';
  photo.addEventListener('click', (e) => {
    e.stopPropagation();
    pickImages(block.index);
  });
  bar.append(add, photo, del);
```

And add:

```js
function pickImages(index) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.multiple = true;

  input.addEventListener('change', async () => {
    if (!input.files.length) return;

    const alts = [];
    for (const file of input.files) {
      alts.push(prompt(`Alt text for ${file.name} (describes the photo):`, '') || '');
    }

    const form = new FormData();
    for (const file of input.files) form.append('files', file);
    form.append('alts', JSON.stringify(alts));
    form.append('index', index);
    form.append('hash', state.hash);

    setStatus(`uploading ${input.files.length} photo(s)…`);
    await applyWrite(await fetch(`/api/posts/${state.slug}/images`, {
      method: 'POST',
      body: form,
    }));
  });

  input.click();
}
```

- [ ] **Step 6: Verify a real upload from the tablet**

Open the editor on the tablet, tap 🖼 on a block, pick two photos from the
camera roll, give alt text.
Expected: an `.img-row` appears with both photos, served from `img.cloudy.nyc`.

Confirm they landed in S3:
```bash
source .aws.env
AWS_ACCESS_KEY_ID=$PERSONAL_SITE_IMAGES_ACCESS_KEY_ID \
AWS_SECRET_ACCESS_KEY=$PERSONAL_SITE_IMAGES_SECRET_ACCESS_KEY \
aws s3 ls "s3://$PERSONAL_SITE_IMAGES_BUCKET/<slug>/"
```

Revert the test edit afterwards: `git checkout content/blog/`

- [ ] **Step 7: Commit**

```bash
git add editor/app.py editor/web editor/tests/test_api_images.py
git commit -m "Add photo upload from the editor"
```

---

### Task 11: Publish from the editor

The last link: a Publish button that commits, pushes, and rebuilds the live site.

**Files:**
- Modify: `editor/app.py`
- Modify: `editor/web/editor.js`
- Create: `editor/tests/test_api_publish.py`

> **AMENDED 2026-09-20.** `PublishResult.built` is now `published`, and
> publishing runs `scripts/publish-site.sh` (build + S3 sync + Cloudflare
> purge) rather than a local-only build. `_dirty_paths` must also handle
> staged renames — see the ruling below.

**Interfaces:**
- Consumes: `publish.publish` (Task 4).
- Produces:
  - `GET /api/status` → `{dirty: [paths], clean: bool}` — only ever reports paths under `content/blog/`
  - `POST /api/publish` body `{message?}` → `{committed, sha, pushed, built, message}`

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_api_publish.py`:

```python
from fastapi.testclient import TestClient

from editor.app import app

client = TestClient(app)


def test_status_only_reports_blog_paths(monkeypatch):
    monkeypatch.setattr(
        "editor.app._dirty_paths",
        lambda: ["content/blog/a.md", "templates/base.html", "editor/app.py"],
    )
    data = client.get("/api/status").json()
    assert data["dirty"] == ["content/blog/a.md"]
    assert data["clean"] is False


def test_publish_passes_only_blog_paths_to_git(monkeypatch):
    seen = {}

    def fake_publish(repo, paths, message):
        seen["paths"] = paths
        seen["message"] = message
        from editor.publish import PublishResult
        return PublishResult(True, "abc12345", True, True, "published abc12345")

    monkeypatch.setattr(
        "editor.app._dirty_paths",
        lambda: ["content/blog/a.md", "templates/base.html"],
    )
    monkeypatch.setattr("editor.app.publish", fake_publish)

    out = client.post("/api/publish", json={"message": "Update a post"}).json()

    assert seen["paths"] == ["content/blog/a.md"]
    assert out["sha"] == "abc12345"
    assert out["published"] is True


def test_publish_with_nothing_to_do(monkeypatch):
    monkeypatch.setattr("editor.app._dirty_paths", lambda: [])
    out = client.post("/api/publish", json={}).json()
    assert out["committed"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_api_publish.py -v`
Expected: FAIL — routes not defined.

- [ ] **Step 3: Implement the publish routes**

Modify `editor/app.py`:

```python
from editor.publish import publish

BLOG_PREFIX = "content/blog/"


class PublishRequest(BaseModel):
    message: str | None = None


def _dirty_paths() -> list[str]:
    """Paths git reports as dirty.

    Renames matter: `git mv` (the slug-change route) makes git report
    `R  old.md -> new.md` on ONE line. Handing that whole string to `git add`
    as a single path fails, so both sides are split out -- the pre-image needs
    staging for the deletion, the new path for the addition.
    """
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=config.REPO, check=True, capture_output=True, text=True,
    ).stdout

    paths: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        entry = line[3:].strip()
        paths.extend(part.strip() for part in entry.split(" -> "))
    return paths


def _blog_paths() -> list[str]:
    return [p for p in _dirty_paths() if p.startswith(BLOG_PREFIX)]


@app.get("/api/status")
def status():
    dirty = _blog_paths()
    return {"dirty": dirty, "clean": not dirty}


@app.post("/api/publish")
def do_publish(request: PublishRequest):
    paths = _blog_paths()
    if not paths:
        return {"committed": False, "sha": None, "pushed": False,
                "published": False, "message": "nothing to publish"}

    message = request.message or f"Update {len(paths)} post(s) from the editor"
    result = publish(config.REPO, paths, message)
    return result.__dict__
```

- [ ] **Step 4: Run to verify it passes**

Run: `editor/.venv/bin/python -m pytest editor/tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Wire the Publish button**

Modify `editor/web/editor.js`:

```js
async function refreshStatus() {
  const data = await (await fetch('/api/status')).json();
  els.publish.disabled = data.clean;
  els.publish.textContent = data.clean
    ? 'Published'
    : `Publish (${data.dirty.length})`;
}

els.publish.addEventListener('click', async () => {
  const message = prompt('Commit message:', `Update ${state.slug}`);
  if (message === null) return;

  els.publish.disabled = true;
  setStatus('publishing…');

  const res = await fetch('/api/publish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();

  setStatus(data.message);
  await refreshStatus();
});
```

Call `refreshStatus()` at the end of `applyWrite`, `saveMeta`, and `main()`.

- [ ] **Step 6: Publish a real edit end to end**

From the tablet: make a small edit to a post, hit Publish.

Expected:
- status shows `published <sha>`
- `git log --oneline -1` in the repo shows the commit
- `git status --porcelain content/blog/` is empty
- `curl -s https://cloudy.nyc/blog/<slug>/ | grep "<your edit>"` finds the change
- the GitHub Actions run for peter.direct is triggered:
  `gh run list --limit 1`

- [ ] **Step 7: Verify an unrelated dirty file was not swept in**

Run:
```bash
echo "scratch" > /tmp/scratch-check.txt && cp /tmp/scratch-check.txt ./scratch-check.txt
# make an edit in the editor, publish, then:
git show --name-only --format= HEAD
```
Expected: only `content/blog/...` paths listed — `scratch-check.txt` untouched
and still dirty in `git status`.

Clean up: `rm scratch-check.txt`

- [ ] **Step 8: Document the editor**

Modify `CLAUDE.md` — add under Deployment:

```markdown
- **Editing from a tablet:** `edit.cloudy.nyc` (LAN-only) runs `blog-editor.service`
  from `editor/`. It edits `content/blog/*.md` in the working tree, uploads photos
  to S3, and on Publish commits only `content/blog/` paths, pushes, and rebuilds
  the live site via `scripts/build-site.sh`. Design:
  `docs/superpowers/specs/2026-09-20-blog-editor-design.md`.
  ⚠ The service refuses to start if `edit.cloudy.nyc` is ever added to the
  cloudflared tunnel config — it must stay LAN-only.
```

- [ ] **Step 9: Commit**

```bash
git add editor/app.py editor/web editor/tests/test_api_publish.py CLAUDE.md
git commit -m "Add publish from the editor"
```

---

---

### Task 12: Create a new post

> **ADDED 2026-09-20.** Brainstorming agreed Phase 1 covers "edit AND create",
> but the original plan only covered editing. Without this, starting a post
> still needs a terminal, which undercuts a tablet-first editor.

**Files:**
- Modify: `editor/app.py`
- Modify: `editor/web/editor.js`
- Create: `editor/tests/test_api_new_post.py`

**Interfaces:**
- Consumes: `frontmatter.join_post` (Task 3), `config.BLOG_DIR` (Task 6).
- Produces:
  - `POST /api/posts` body `{title}` → `{slug, ...}` (same shape as `GET /api/posts/{slug}`)
  - Slug is derived from the title, sanitised to `[a-z0-9-]`, de-duplicated with a numeric suffix.
  - New posts are created with `draft = true` and today's date.

- [ ] **Step 1: Write the failing tests**

Create `editor/tests/test_api_new_post.py`:

```python
import datetime

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
CREATED: list = []


@pytest.fixture(autouse=True)
def cleanup():
    yield
    for slug in CREATED:
        (config.BLOG_DIR / f"{slug}.md").unlink(missing_ok=True)
    CREATED.clear()


def _create(title: str):
    res = client.post("/api/posts", json={"title": title})
    if res.status_code == 200:
        CREATED.append(res.json()["slug"])
    return res


def test_creates_a_post_with_a_slug_from_the_title():
    out = _create("A Brand New Post!").json()
    assert out["slug"] == "a-brand-new-post"
    assert (config.BLOG_DIR / "a-brand-new-post.md").exists()


def test_new_post_is_a_draft_dated_today():
    out = _create("Draft Check").json()
    assert out["meta"]["draft"] is True
    assert out["meta"]["date"] == datetime.date.today().isoformat()


def test_new_post_has_an_editable_starter_block():
    out = _create("Starter Block").json()
    assert len(out["blocks"]) >= 1


def test_duplicate_titles_get_distinct_slugs():
    first = _create("Same Title").json()["slug"]
    second = _create("Same Title").json()["slug"]
    assert first != second
    assert second.startswith(first)


def test_title_that_sanitises_to_nothing_is_rejected():
    assert client.post("/api/posts", json={"title": "!!!"}).status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `editor/.venv/bin/python -m pytest editor/tests/test_api_new_post.py -v`
Expected: FAIL — the route does not exist (405/404).

- [ ] **Step 3: Implement the route**

Modify `editor/app.py`:

```python
class NewPost(BaseModel):
    title: str


@app.post("/api/posts")
def create_post(new: NewPost):
    slug = re.sub(r"[^a-z0-9]+", "-", new.title.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="title has no usable characters")

    # De-duplicate rather than overwrite: losing an existing post to a title
    # collision would be silent data loss.
    candidate, n = slug, 2
    while (config.BLOG_DIR / f"{candidate}.md").exists():
        candidate = f"{slug}-{n}"
        n += 1

    frontmatter = (
        f'title = "{new.title}"\n'
        f"date = {datetime.date.today().isoformat()}\n"
        "draft = true\n"
    )
    body = "Start writing.\n"
    (config.BLOG_DIR / f"{candidate}.md").write_text(join_post(frontmatter, body))
    return get_post(candidate)
```

- [ ] **Step 4: Run to verify it passes**

Run: `editor/.venv/bin/python -m pytest editor/tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Add the "New post" button**

Modify `editor/web/editor.js` — add next to the post picker in the header:

```js
async function newPost() {
  const title = prompt('Title for the new post:');
  if (!title) return;

  setStatus('creating…');
  const res = await fetch('/api/posts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });

  if (!res.ok) {
    setStatus((await res.json()).detail || 'could not create');
    return;
  }

  const data = await res.json();
  await loadPostList();
  els.picker.value = data.slug;
  await loadPost(data.slug);
  setStatus('created (draft)');
}
```

Add a button to `editor/web/index.html`'s `.bar`, before the status span:

```html
<button id="new-post" class="publish" title="Start a new post">+ New</button>
```

and wire it in `main()`: `document.getElementById('new-post').addEventListener('click', newPost);`

- [ ] **Step 6: Verify in the browser**

`make editor-restart`, open the editor, click "+ New", give a title. Expect the
new draft to load with its starter block, and `git status` to show the new file
under `content/blog/`. Delete the test post afterwards.

- [ ] **Step 7: Commit**

```bash
git add editor/app.py editor/web editor/tests/test_api_new_post.py
git commit -m "Add new-post creation to the editor"
```

## Phase 1 done when

- Editing a paragraph from the tablet changes the post and shows "saved".
- Uploading two photos produces an `.img-row` served from `img.cloudy.nyc`.
- Title, date and draft are editable; renaming warns about broken links.
- Publish commits **only** `content/blog/` paths, pushes, syncs to S3 and
  purges Cloudflare; cloudy.nyc shows the change within a few seconds.
- "+ New" creates a draft post you can immediately write into.
- `edit.cloudy.nyc` answers on the LAN and is unreachable publicly.
- `editor/.venv/bin/python -m pytest editor/tests/ -v` is green.

Phases 2 (nav + footer) and 3 (homepage sections) get their own plans.
