# Platen "Send to blog" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Platen button, visible only to the owner, that turns the open doc into a new `draft = true` post in the blog editor, split into heading and paragraph blocks.

**Architecture:** The blog editor (`~/projects/personal/personal-site/editor`, FastAPI) gains a pure converter (`importer.py`) and a `POST /api/import` route authenticated by a shared-secret header instead of the session cookie. Platen (`~/projects/personal/platen`, Go stdlib + vanilla JS) gains an owner-only `POST /api/docs/{name}/send-to-blog` that reads the doc and POSTs it to the editor over loopback, plus a panel button.

**Tech Stack:** Python 3 / FastAPI / markdown-it-py / pytest (editor); Go stdlib / `net/http/httptest` (platen server); vanilla ES modules + headless-Chromium CDP harness (platen UI).

**Spec:** `personal-site/docs/superpowers/specs/2026-10-04-platen-send-to-blog-design.md`

**Two repos.** Tasks 1–2 commit in `~/projects/personal/personal-site`; Tasks 3–4 commit in `~/projects/personal/platen`; Task 5 touches both. Do not push either repo.

## Global Constraints

- Every send creates a NEW post; never overwrite. Slug collisions get `-2`, `-3`, ... (the existing `POST /api/posts` rule).
- The editor always writes `draft = true`; the caller cannot choose.
- Token header name: `X-Import-Token`. Editor env key `EDITOR_IMPORT_TOKEN` in gitignored `personal-site/.editor-import.env`. Platen env keys `BLOG_IMPORT_TOKEN` and `BLOG_IMPORT_URL` (default `http://127.0.0.1:8804/api/import`) in gitignored `platen/.blog-import.env`. Both files mode 0600. The token is never committed, echoed, or printed in chat.
- Editor: token unset → `/api/import` answers 404; missing/wrong token → 401. Comparison via `hmac.compare_digest`.
- Platen: send-to-blog allowed only when the signed-in user's email equals the normalized `-owner` flag (default `ptr.vldz@gmail.com`) AND the token is set; otherwise 404. Upstream timeout 10 s. Upstream failure → 502 with a readable message.
- `edit_url` = `{config.BASE_URL}/edit/{slug}` (`BASE_URL` default `https://edit.cloudy.nyc`).
- User-facing copy: short declarative sentences, no emoji (Peter's voice).
- NEVER stop a process with `pkill -f`; kill by PID. In personal-site, never run `make stop`/`make dev` (see its CLAUDE.md: both take prod down).
- Editor tests run from `personal-site/editor`: `.venv/bin/python -m pytest -q tests`. Platen tests: `make test` (Go + node) and `make test-browser`.

## Review Focus

1. **Indented lines.** A Platen line starting with 4+ spaces or a tab would become a CommonMark code block in the blog. Expected: it posts as an ordinary paragraph. Pinned in Task 1 (`test_leading_indent_does_not_make_a_code_block`).
2. **Unsaved typing at the moment of the tap.** Expected: the last keystrokes are in the draft. Pinned in Task 4's browser test (types, then immediately sends, then asserts the fake editor received the text).
3. **A doc that is only a title** (or blank). Expected: refused with a readable message, nothing written. Pinned in Task 1 (`EmptyImport`) and Task 2 (400, no file) and Task 3 (502 carries the editor's message).
4. **A title with no slug characters** (e.g. `# ...` or emoji only). Expected: 400 "title has no usable characters", no file. Pinned in Task 2 (`test_import_title_without_slug_characters_is_400`).
5. **Editor down or slow.** Expected: Platen answers 502 "the blog editor is not answering" within ~10 s, the button re-enables. Pinned in Task 3 (`TestSendToBlogEditorDown`).

---

### Task 1: Editor — the converter (`importer.py`)

**Files:**
- Create: `personal-site/editor/importer.py`
- Test: `personal-site/editor/tests/test_importer.py`

**Interfaces:**
- Produces: `importer.convert(text: str, name: str) -> tuple[str, str]` returning `(title, body)` where `body` is markdown ending in exactly one `\n`, blocks separated by exactly one blank line. Raises `importer.EmptyImport` (subclass of `ValueError`) when nothing remains after the title.

- [ ] **Step 1: Write the failing tests**

`personal-site/editor/tests/test_importer.py`:

```python
"""importer.convert: Platen text -> (title, block-split markdown body).

Every fixture's body is also run through blocks.parse_blocks, the editor's
own block model, so these prove the post really arrives as separate heading
and paragraph blocks -- not just that the string looks right.
"""
import pytest

from editor.blocks import parse_blocks
from editor.importer import EmptyImport, convert


def kinds(body: str) -> list[str]:
    return [b.kind for b in parse_blocks(body)]


def test_first_h1_is_the_title_and_leaves_the_body():
    title, body = convert("# Spruce, the tracker\n\n## tldr\n\nIt cleans.\n", "2026-09-15 2252")
    assert title == "Spruce, the tracker"
    assert body == "## tldr\n\nIt cleans.\n"
    assert kinds(body) == ["heading", "paragraph"]


def test_no_h1_falls_back_to_the_doc_name():
    title, body = convert("Just a paragraph.\n", "2026-09-15 2252.md")
    assert title == "2026-09-15 2252"
    assert body == "Just a paragraph.\n"


def test_h1_not_on_the_first_line_is_demoted_not_taken_as_title():
    title, body = convert("Intro.\n\n# Later\n\nMore.\n", "doc")
    assert title == "doc"
    assert body == "Intro.\n\n## Later\n\nMore.\n"
    assert kinds(body) == ["paragraph", "heading", "paragraph"]


def test_leading_blank_lines_before_the_title_are_ignored():
    title, _ = convert("\n\n# Title\n\nBody.\n", "doc")
    assert title == "Title"


def test_single_line_breaks_become_separate_paragraphs():
    _, body = convert("# T\n\nOne.\nTwo.\nThree.\n", "doc")
    assert body == "One.\n\nTwo.\n\nThree.\n"
    assert kinds(body) == ["paragraph", "paragraph", "paragraph"]


def test_runs_of_blank_lines_collapse_to_one():
    _, body = convert("# T\n\n\n\nOne.\n\n\n\n\nTwo.\n\n\n", "doc")
    assert body == "One.\n\nTwo.\n"


def test_crlf_and_trailing_spaces_are_normalized():
    _, body = convert("# T\r\n\r\nOne.   \r\nTwo.\t\r\n", "doc")
    assert body == "One.\n\nTwo.\n"


def test_leading_indent_does_not_make_a_code_block():
    _, body = convert("# T\n\n    Indented four.\n\tTabbed.\n", "doc")
    assert body == "Indented four.\n\nTabbed.\n"
    assert kinds(body) == ["paragraph", "paragraph"]


def test_lower_headings_pass_through():
    _, body = convert("# T\n\n## Two\n\n### Three\n\nText.\n", "doc")
    assert body == "## Two\n\n### Three\n\nText.\n"
    assert kinds(body) == ["heading", "heading", "paragraph"]


def test_heading_directly_followed_by_text_splits():
    _, body = convert("# T\n\n## Head\nText right under it.\n", "doc")
    assert kinds(body) == ["heading", "paragraph"]


def test_inline_markup_is_untouched():
    _, body = convert("# T\n\nSome **bold**, *em*, _em_ and `code`.\n", "doc")
    assert body == "Some **bold**, *em*, _em_ and `code`.\n"


def test_hash_without_space_is_not_a_heading():
    _, body = convert("# T\n\n#hashtag stays text.\n", "doc")
    assert body == "#hashtag stays text.\n"


def test_title_only_is_rejected():
    with pytest.raises(EmptyImport):
        convert("# Only a title\n\n\n", "doc")


def test_blank_doc_is_rejected():
    with pytest.raises(EmptyImport):
        convert("  \n\n", "doc")


def test_peters_real_doc_shape():
    text = (
        "# Spruce, the litter cleaning tracker\n\n## tldr\n\nA short summary.\n\n"
        "## NYC means garbage for many\n\nFirst para.\n\nSecond para.\n"
    )
    title, body = convert(text, "2026-09-15 2252")
    assert title == "Spruce, the litter cleaning tracker"
    assert kinds(body) == ["heading", "paragraph", "heading", "paragraph", "paragraph"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/projects/personal/personal-site/editor && .venv/bin/python -m pytest -q tests/test_importer.py`
Expected: collection error, `ModuleNotFoundError: No module named 'editor.importer'`.

- [ ] **Step 3: Implement**

`personal-site/editor/importer.py`:

```python
"""Turn a Platen document into a blog post: a title and a block-split body.

Pure: no I/O. app.py's import_post does the writing.

Platen text is plain markdown-ish prose: `#` headings and paragraphs, with
inline **strong**, *em* and `code` (the only things its renderer knows).
The blog editor treats each top-level markdown block as one editable block,
so the job here is to make every heading and every paragraph its own block:

- The first non-blank line, if it is `# Title`, becomes the post title. The
  title is the page's h1, so it leaves the body. Otherwise the doc's name is
  the title.
- Every non-blank line becomes its own block, separated by one blank line.
  A single line break would otherwise be a soft break that merges lines into
  one paragraph -- the "one giant block" this exists to prevent.
- Leading whitespace is dropped: four spaces of indent is a code block in
  CommonMark, and Platen has no code blocks.
- A `# ` heading later in the body becomes `## `: one h1 per page.
"""
from __future__ import annotations

import re

_H1 = re.compile(r"^#[ \t]+(.+)$")
_BODY_H1 = re.compile(r"^#(?=[ \t])")


class EmptyImport(ValueError):
    """Nothing is left to post once the title is taken out."""


def convert(text: str, name: str) -> tuple[str, str]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.strip() for line in raw if line.strip()]

    title = ""
    if lines:
        match = _H1.match(lines[0])
        if match:
            title = match.group(1).strip()
            lines = lines[1:]
    if not title:
        title = re.sub(r"\.md$", "", name.strip())

    if not lines:
        raise EmptyImport("The document has nothing to post after its title.")

    body = [_BODY_H1.sub("##", line) for line in lines]
    return title, "\n\n".join(body) + "\n"
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest -q tests/test_importer.py`
Expected: `15 passed`.

- [ ] **Step 5: Commit**

```bash
cd ~/projects/personal/personal-site
git add editor/importer.py editor/tests/test_importer.py
git commit -m "editor: convert Platen text into a block-split post body

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Editor — `POST /api/import` with token auth

**Files:**
- Modify: `personal-site/editor/app.py` (`create_post`, ~line 178–213; add `import_post` right after it; imports at top)
- Modify: `personal-site/editor/config.py` (add `import_token()` after `load_smtp_env`)
- Modify: `personal-site/editor/auth/middleware.py`
- Modify: `personal-site/editor/tests/test_auth.py` (coverage walk + allowlist test, ~line 203–233)
- Modify: `personal-site/.gitignore` (add `/.editor-import.env` next to `/.editor-smtp.env`)
- Modify: `personal-site/CLAUDE.md` (editor auth section; also fix the stale "NOT deployed as of 2026-09-24" line near 1183 — auth IS deployed)
- Test: `personal-site/editor/tests/test_api_import.py`

**Interfaces:**
- Consumes: `importer.convert`, `importer.EmptyImport` (Task 1).
- Produces: `POST /api/import`, request JSON `{"text": str, "name": str}`, header `X-Import-Token`; responses `201 {"slug": str, "edit_url": str}`, `400 {"detail": str}`, `401`, `404` (token unset). Task 3's Go client reads `slug`, `edit_url`, and on error a string `detail`.

- [ ] **Step 1: Write the failing tests**

`personal-site/editor/tests/test_api_import.py`:

```python
"""POST /api/import: Platen's send-to-blog lands here.

Auth is a shared secret header, not the session cookie, so these use a
cookie-less client throughout. Like test_api_new_post.py, posts are written
into the real content/blog and removed after each test.
"""
import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app
from editor.blocks import parse_blocks
from editor.frontmatter import read_meta, split_post

anon = TestClient(app)
client = TestClient(app)  # signed in by conftest; used once, below
TOKEN = "test-import-token"
CREATED: list[str] = []


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(config, "import_token", lambda: TOKEN)
    yield
    for slug in CREATED:
        (config.BLOG_DIR / f"{slug}.md").unlink(missing_ok=True)
    CREATED.clear()


def send(text, name="doc", token=TOKEN):
    headers = {"X-Import-Token": token} if token is not None else {}
    res = anon.post("/api/import", json={"text": text, "name": name}, headers=headers)
    if res.status_code == 201:
        CREATED.append(res.json()["slug"])
    return res


def read(slug):
    fm, body = split_post((config.BLOG_DIR / f"{slug}.md").read_text())
    return read_meta(fm), body


def test_creates_a_draft_split_into_blocks():
    res = send("# Import Fixture Post\n\n## Section\n\nOne.\nTwo.\n")
    assert res.status_code == 201
    out = res.json()
    assert out["slug"] == "import-fixture-post"
    assert out["edit_url"] == f"{config.BASE_URL}/edit/import-fixture-post"
    meta, body = read(out["slug"])
    assert meta["title"] == "Import Fixture Post"
    assert meta["draft"] is True
    assert [b.kind for b in parse_blocks(body)] == ["heading", "paragraph", "paragraph"]


def test_second_send_makes_a_new_post():
    first = send("# Import Fixture Twice\n\nA.\n").json()["slug"]
    second = send("# Import Fixture Twice\n\nB.\n").json()["slug"]
    assert (first, second) == ("import-fixture-twice", "import-fixture-twice-2")
    assert "A." in read(first)[1] and "B." in read(second)[1]


def test_missing_token_is_401():
    assert send("# Import Fixture X\n\nA.\n", token=None).status_code == 401


def test_wrong_token_is_401():
    assert send("# Import Fixture X\n\nA.\n", token="nope").status_code == 401


def test_unconfigured_token_turns_the_route_off(monkeypatch):
    monkeypatch.setattr(config, "import_token", lambda: "")
    assert send("# Import Fixture X\n\nA.\n", token="").status_code == 404


def test_title_only_is_400_and_writes_nothing():
    before = set(config.BLOG_DIR.glob("*.md"))
    res = send("# Import Fixture Empty\n")
    assert res.status_code == 400
    assert "nothing to post" in res.json()["detail"]
    assert set(config.BLOG_DIR.glob("*.md")) == before


def test_import_title_without_slug_characters_is_400():
    before = set(config.BLOG_DIR.glob("*.md"))
    res = send("# ...\n\nBody.\n")
    assert res.status_code == 400
    assert set(config.BLOG_DIR.glob("*.md")) == before


def test_created_post_passes_the_draft_gate():
    send("# Import Fixture Gate\n\nBody.\n")
    result = subprocess.run(
        ["python3", str(config.REPO / "scripts" / "check-drafts.py"),
         str(config.REPO / "content"), "/nonexistent"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_a_session_cookie_alone_does_not_authorize_import():
    """The route ignores the session: a signed-in browser still needs the token.
    `client` (that exact name) gets a session from conftest's autouse fixture."""
    res = client.post("/api/import", json={"text": "# Import Fixture X\n\nA.\n", "name": "x"})
    assert res.status_code == 401
```

In `tests/test_auth.py`, change the walk and the allowlist test:

```python
from editor.auth.middleware import PUBLIC_EXACT, PUBLIC_PREFIXES, TOKEN_AUTH_EXACT, is_public
```

(adjust the existing import line to add `TOKEN_AUTH_EXACT`), and inside `test_every_route_requires_auth_unless_explicitly_public` replace

```python
        if is_public(route.path):
            continue
```

with

```python
        if is_public(route.path) or route.path in TOKEN_AUTH_EXACT:
            continue
```

Add after `test_public_allowlist_is_short_and_explicit`'s existing asserts:

```python
    # Routes that skip the session check because they authenticate with a
    # shared secret instead. Each is a deliberate decision; see app.py.
    assert TOKEN_AUTH_EXACT == frozenset({"/api/import"})


def test_token_auth_routes_refuse_an_anonymous_caller(monkeypatch):
    from editor import config
    monkeypatch.setattr(config, "import_token", lambda: "configured")
    anon = _fresh()
    for path in TOKEN_AUTH_EXACT:
        assert anon.post(path, json={"text": "# A\n\nB", "name": "x"}).status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_api_import.py tests/test_auth.py`
Expected: FAIL — `ImportError: cannot import name 'TOKEN_AUTH_EXACT'` and 401s from the import tests (route doesn't exist / middleware blocks).

- [ ] **Step 3: Implement**

`config.py`, after `load_smtp_env`:

```python
def import_token() -> str:
    """The shared secret Platen sends as X-Import-Token (see app.py's
    import_post). Read live, not at import, so tests can monkeypatch it.
    The env var wins over the gitignored .editor-import.env. Empty means
    the import route is switched off."""
    return (
        os.environ.get("EDITOR_IMPORT_TOKEN")
        or _read_env_file(".editor-import.env").get("EDITOR_IMPORT_TOKEN", "")
    ).strip()
```

`auth/middleware.py`: add below `PUBLIC_PREFIXES`:

```python
# Exact paths that skip the session check because the route authenticates
# itself with a shared secret instead (app.py's import_post: Platen's
# server-to-server send-to-blog). Not "public": the route refuses any
# caller without the token, and is off entirely when none is configured.
TOKEN_AUTH_EXACT = frozenset({"/api/import"})
```

and in `dispatch` change the condition to:

```python
        if (
            email is None
            and not is_public(request.url.path)
            and request.url.path not in TOKEN_AUTH_EXACT
        ):
```

Also add one sentence to the module docstring: "`/api/import` is the one route that authenticates with a shared secret instead of a session (TOKEN_AUTH_EXACT)."

`app.py`: add `import hmac` to the stdlib imports, `from fastapi import Header` to the fastapi import line (merge with what's there), `from pydantic import Field` if not already imported, and `from editor import importer` beside the other `editor` imports. Replace `create_post` with a shared helper plus the two routes:

```python
def _create_draft(title: str, body: str) -> str:
    """Write a new draft post and return its slug. Shared by New post and
    Platen's import so the slug, collision and frontmatter rules can't
    drift apart."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="title has no usable characters")

    # De-duplicate rather than overwrite: losing an existing post to a title
    # collision would be silent data loss.
    candidate, n = slug, 2
    while (config.BLOG_DIR / f"{candidate}.md").exists():
        candidate = f"{slug}-{n}"
        n += 1

    # Build the frontmatter with tomlkit rather than f-string interpolation
    # -- a title containing a double quote (or a backslash) would otherwise
    # produce invalid TOML that read_meta can't parse back. Same class of
    # bug as the alt-text escaping elsewhere in this project.
    doc = tomlkit.document()
    doc["title"] = title
    doc["date"] = datetime.date.today()
    doc["draft"] = True
    frontmatter = tomlkit.dumps(doc)

    # Blank-line-before-body style, matching every current post (see
    # test_frontmatter.py) and join_post's separator handling.
    _atomic_write_text(config.BLOG_DIR / f"{candidate}.md", join_post(frontmatter, "\n" + body))
    return candidate


@app.post("/api/posts")
def create_post(new: NewPost):
    return get_post(_create_draft(new.title, "Start writing.\n"))


class ImportDoc(BaseModel):
    text: str = Field(max_length=1_000_000)
    name: str = Field(default="", max_length=500)


@app.post("/api/import", status_code=201)
def import_post(doc: ImportDoc, x_import_token: str | None = Header(default=None)):
    """Platen's "Send to blog": a new draft from a Platen doc, every time.

    Authenticated by X-Import-Token, not the session cookie (see
    auth/middleware.py's TOKEN_AUTH_EXACT). With no token configured the
    route doesn't exist as far as a caller can tell. Always a draft, so the
    draft gate keeps it off cloudy.nyc until it's un-drafted here.
    """
    expected = config.import_token()
    if not expected:
        raise HTTPException(status_code=404, detail="Not Found")
    if not x_import_token or not hmac.compare_digest(
        x_import_token.encode(), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="bad import token")
    try:
        title, body = importer.convert(doc.text, doc.name)
    except importer.EmptyImport as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    slug = _create_draft(title, body)
    return {"slug": slug, "edit_url": f"{config.BASE_URL}/edit/{slug}"}
```

`.gitignore`: add `/.editor-import.env` on the line after `/.editor-smtp.env`.

`CLAUDE.md`: in the editor auth section add a short paragraph: "**One route skips the session: `POST /api/import`** (added 2026-10-04), Platen's send-to-blog. It authenticates with `X-Import-Token` against `EDITOR_IMPORT_TOKEN` in the gitignored `.editor-import.env` (0600), and answers 404 when that's unset. It always creates a new `draft = true` post via `_create_draft`, the same helper New post uses; the text→blocks rules are in `editor/importer.py`. `TOKEN_AUTH_EXACT` in `auth/middleware.py` lists it and `test_auth.py` pins the list." Also update the stale "NOT deployed" line to say auth has been live since 2026-09-24.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest -q tests/test_api_import.py tests/test_auth.py tests/test_api_new_post.py`
Expected: all pass. Then the full suite: `.venv/bin/python -m pytest -q tests` — expected all pass (≈567).

- [ ] **Step 5: Commit**

```bash
cd ~/projects/personal/personal-site
git add editor/app.py editor/config.py editor/auth/middleware.py editor/tests/test_api_import.py editor/tests/test_auth.py .gitignore CLAUDE.md
git commit -m "editor: POST /api/import creates a draft from a Platen doc

Authenticated by a shared-secret header instead of the session, off
when no token is configured. New post and import share _create_draft.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Platen server — owner-only send-to-blog

**Files:**
- Create: `platen/blog.go`
- Modify: `platen/server.go` (`Config`, `Server`, `NewServer`, `Handler` route list, `handleMe`)
- Modify: `platen/main.go` (pass `Owner`, `BlogImportURL`, `BlogImportToken`)
- Modify: `platen/systemd/platen.service` (add `EnvironmentFile=-/home/peter/projects/personal/platen/.blog-import.env` under the existing EnvironmentFile line, with a one-line comment)
- Modify: `platen/.gitignore` (add `.blog-import.env`)
- Test: `platen/blog_test.go`

**Interfaces:**
- Consumes: editor `POST /api/import` (Task 2): JSON `{"text","name"}`, header `X-Import-Token`; `201 {"slug","edit_url"}`; errors carry `{"detail": str}`.
- Produces: `POST /api/docs/{name}/send-to-blog` → `201 {"slug": str, "edit_url": str}`; `404 {"error"}` when not allowed or doc missing; `502 {"error": str}` on upstream failure. `GET /api/me` → `{"id","email","can_send_to_blog": bool}`. Task 4 consumes both.

- [ ] **Step 1: Write the failing tests**

`platen/blog_test.go`:

```go
package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeEditor stands in for the blog editor's /api/import.
type fakeEditor struct {
	mu     sync.Mutex
	calls  int
	token  string
	body   map[string]string
	status int
	reply  string
}

func (f *fakeEditor) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	f.token = r.Header.Get("X-Import-Token")
	b, _ := io.ReadAll(r.Body)
	json.Unmarshal(b, &f.body)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(f.status)
	io.WriteString(w, f.reply)
}

const owner = "owner@example.com"

// blogEnv is newEnv with the blog wiring set.
func blogEnv(t *testing.T, editorURL, token string) *testEnv {
	t.Helper()
	e := newEnv(t, "http://platen.test")
	e.srv = NewServer(Config{
		DocsRoot: e.docsRoot, Auth: e.auth, Mailer: e.mail,
		BaseURL: "http://platen.test", Pages: stubPages{},
		Now:             func() time.Time { return e.clock },
		Owner:           owner,
		BlogImportURL:   editorURL,
		BlogImportToken: token,
	})
	e.h = e.srv.Handler()
	return e
}

func newDoc(t *testing.T, e *testEnv, sid, text string) string {
	t.Helper()
	w := e.req("POST", "/api/docs", `{"title":"Draft doc"}`, sid)
	if w.Code != 201 {
		t.Fatalf("create: %d %s", w.Code, w.Body.String())
	}
	var c struct{ Name string }
	json.Unmarshal(w.Body.Bytes(), &c)
	body, _ := json.Marshal(map[string]string{"text": text})
	if w := e.req("PUT", "/api/docs/"+c.Name, string(body), sid); w.Code != 204 {
		t.Fatalf("write: %d", w.Code)
	}
	return c.Name
}

func send(e *testEnv, sid, name string) *httptest.ResponseRecorder {
	return e.req("POST", "/api/docs/"+strings.ReplaceAll(name, " ", "%20")+"/send-to-blog", "", sid)
}

func TestSendToBlogOwner(t *testing.T) {
	fake := &fakeEditor{status: 201, reply: `{"slug":"hello","edit_url":"https://edit.cloudy.nyc/edit/hello"}`}
	ed := httptest.NewServer(fake)
	defer ed.Close()
	e := blogEnv(t, ed.URL, "s3cret")
	sid := e.signIn(owner)
	name := newDoc(t, e, sid, "# Hello\n\nWorld.\n")

	w := send(e, sid, name)
	if w.Code != 201 {
		t.Fatalf("send: %d %s", w.Code, w.Body.String())
	}
	var got map[string]string
	json.Unmarshal(w.Body.Bytes(), &got)
	if got["slug"] != "hello" || got["edit_url"] != "https://edit.cloudy.nyc/edit/hello" {
		t.Fatalf("reply = %v", got)
	}
	if fake.token != "s3cret" || fake.body["text"] != "# Hello\n\nWorld.\n" || fake.body["name"] != name {
		t.Fatalf("editor saw token=%q body=%v", fake.token, fake.body)
	}
}

func TestSendToBlogNonOwnerIs404(t *testing.T) {
	fake := &fakeEditor{status: 201, reply: `{}`}
	ed := httptest.NewServer(fake)
	defer ed.Close()
	e := blogEnv(t, ed.URL, "s3cret")
	sid := e.signIn("someone@example.com")
	name := newDoc(t, e, sid, "# Hi\n\nThere.\n")
	if w := send(e, sid, name); w.Code != 404 {
		t.Fatalf("non-owner: %d", w.Code)
	}
	if fake.calls != 0 {
		t.Fatal("editor was called for a non-owner")
	}
}

func TestSendToBlogOffWithoutToken(t *testing.T) {
	fake := &fakeEditor{status: 201, reply: `{}`}
	ed := httptest.NewServer(fake)
	defer ed.Close()
	e := blogEnv(t, ed.URL, "")
	sid := e.signIn(owner)
	name := newDoc(t, e, sid, "# Hi\n\nThere.\n")
	if w := send(e, sid, name); w.Code != 404 {
		t.Fatalf("no token: %d", w.Code)
	}
}

func TestSendToBlogSignedOutIs401(t *testing.T) {
	e := blogEnv(t, "http://127.0.0.1:1", "s3cret")
	if w := send(e, "", "x"); w.Code != 401 {
		t.Fatalf("signed out: %d", w.Code)
	}
}

func TestSendToBlogMissingDocIs404(t *testing.T) {
	fake := &fakeEditor{status: 201, reply: `{}`}
	ed := httptest.NewServer(fake)
	defer ed.Close()
	e := blogEnv(t, ed.URL, "s3cret")
	sid := e.signIn(owner)
	if w := send(e, sid, "nope"); w.Code != 404 {
		t.Fatalf("missing doc: %d", w.Code)
	}
}

func TestSendToBlogEditorRefusal(t *testing.T) {
	fake := &fakeEditor{status: 400, reply: `{"detail":"The document has nothing to post after its title."}`}
	ed := httptest.NewServer(fake)
	defer ed.Close()
	e := blogEnv(t, ed.URL, "s3cret")
	sid := e.signIn(owner)
	name := newDoc(t, e, sid, "# Only a title\n")
	w := send(e, sid, name)
	if w.Code != 502 || !strings.Contains(w.Body.String(), "nothing to post") {
		t.Fatalf("refusal: %d %s", w.Code, w.Body.String())
	}
}

func TestSendToBlogEditorDown(t *testing.T) {
	ed := httptest.NewServer(http.NotFoundHandler())
	url := ed.URL
	ed.Close() // nothing listening now
	e := blogEnv(t, url, "s3cret")
	sid := e.signIn(owner)
	name := newDoc(t, e, sid, "# Hi\n\nThere.\n")
	w := send(e, sid, name)
	if w.Code != 502 || !strings.Contains(w.Body.String(), "not answering") {
		t.Fatalf("down: %d %s", w.Code, w.Body.String())
	}
}

func TestMeReportsCanSendToBlog(t *testing.T) {
	e := blogEnv(t, "http://127.0.0.1:1", "s3cret")
	for email, want := range map[string]bool{owner: true, "someone@example.com": false} {
		w := e.req("GET", "/api/me", "", e.signIn(email))
		var me struct {
			CanSendToBlog bool `json:"can_send_to_blog"`
		}
		json.Unmarshal(w.Body.Bytes(), &me)
		if me.CanSendToBlog != want {
			t.Fatalf("%s: can_send_to_blog = %v", email, me.CanSendToBlog)
		}
	}
}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/projects/personal/platen && go test ./... 2>&1 | tail -5`
Expected: build failure — `unknown field Owner in struct literal of type Config`.

- [ ] **Step 3: Implement**

`server.go` — add to `Config`:

```go
	Owner           string // the one account that may send docs to the blog
	BlogImportURL   string // the blog editor's /api/import; see blog.go
	BlogImportToken string // shared secret for it; empty switches the feature off
```

add to `Server`:

```go
	owner      string
	blogURL    string
	blogToken  string
	blogClient *http.Client
```

and in `NewServer`'s literal:

```go
		owner:      normalizeEmail(c.Owner),
		blogURL:    c.BlogImportURL,
		blogToken:  c.BlogImportToken,
		blogClient: &http.Client{Timeout: 10 * time.Second},
```

In `Handler`, after the `DELETE /api/docs/{name}` line:

```go
	mux.HandleFunc("POST /api/docs/{name}/send-to-blog", s.withUser(s.handleSendToBlog))
```

Replace `handleMe`:

```go
func (s *Server) handleMe(w http.ResponseWriter, r *http.Request, u *User) {
	writeJSON(w, 200, map[string]any{
		"id": u.ID, "email": u.Email, "can_send_to_blog": s.canSendToBlog(u),
	})
}
```

`blog.go`:

```go
package main

// Send to blog: the owner's one-tap path from a Platen doc to a draft post
// in the blog editor (personal-site/editor, edit.cloudy.nyc). Platen sends
// the raw text; the editor owns everything about posts -- the title rule,
// splitting into heading/paragraph blocks, slugs, and always draft = true.
// Every send makes a new draft; nothing is ever overwritten.
//
// The editor is on this Pi, reached over loopback, and authenticates this
// call with a shared secret (X-Import-Token) instead of a session. The
// secret comes from the gitignored .blog-import.env (platen.service);
// without it the route answers 404 to everyone, as does any account but
// the -owner one.

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"path/filepath"
)

type blogDraft struct {
	Slug    string `json:"slug"`
	EditURL string `json:"edit_url"`
}

func (s *Server) canSendToBlog(u *User) bool {
	return s.blogToken != "" && s.owner != "" && u.Email == s.owner
}

func (s *Server) handleSendToBlog(w http.ResponseWriter, r *http.Request, u *User) {
	if !s.canSendToBlog(u) {
		writeJSON(w, 404, map[string]string{"error": "not found"})
		return
	}
	store, err := NewStore(filepath.Join(s.docsRoot, u.ID))
	if err != nil {
		s.fail(w, err)
		return
	}
	name := r.PathValue("name")
	text, err := store.Read(name)
	if err != nil {
		s.fail(w, err)
		return
	}
	draft, err := s.postToBlog(r, name, text)
	if err != nil {
		log.Printf("platen: send to blog: %v", err)
		writeJSON(w, 502, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, 201, draft)
}

func (s *Server) postToBlog(r *http.Request, name, text string) (blogDraft, error) {
	payload, err := json.Marshal(map[string]string{"name": name, "text": text})
	if err != nil {
		return blogDraft{}, err
	}
	req, err := http.NewRequestWithContext(r.Context(), "POST", s.blogURL, bytes.NewReader(payload))
	if err != nil {
		return blogDraft{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Import-Token", s.blogToken)

	resp, err := s.blogClient.Do(req)
	if err != nil {
		return blogDraft{}, errors.New("the blog editor is not answering")
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))

	if resp.StatusCode != 201 {
		var e struct {
			Detail any `json:"detail"`
		}
		if json.Unmarshal(body, &e) == nil {
			if msg, ok := e.Detail.(string); ok && msg != "" {
				return blogDraft{}, fmt.Errorf("the blog editor refused it: %s", msg)
			}
		}
		return blogDraft{}, fmt.Errorf("the blog editor answered %d", resp.StatusCode)
	}
	var d blogDraft
	if err := json.Unmarshal(body, &d); err != nil || d.Slug == "" || d.EditURL == "" {
		return blogDraft{}, errors.New("the blog editor sent back something unexpected")
	}
	return d, nil
}
```

`main.go` — before building the server:

```go
	blogURL := os.Getenv("BLOG_IMPORT_URL")
	if blogURL == "" {
		blogURL = "http://127.0.0.1:8804/api/import"
	}
```

and add to the `Config{...}` literal:

```go
			Owner:           *owner,
			BlogImportURL:   blogURL,
			BlogImportToken: os.Getenv("BLOG_IMPORT_TOKEN"),
```

Also update the `-owner` flag's help string to `"the owner account: receives pre-auth top-level documents, and is the only one that can send to the blog"`, and append `, send-to-blog=%v` with `os.Getenv("BLOG_IMPORT_TOKEN") != ""` to the startup log line (a bool, never the token).

`systemd/platen.service`, under the existing `EnvironmentFile=-...aws.env` line:

```
# BLOG_IMPORT_TOKEN (and optionally BLOG_IMPORT_URL) for Send to blog
# (blog.go). Missing file = the feature is off.
EnvironmentFile=-/home/peter/projects/personal/platen/.blog-import.env
```

`.gitignore`: add `.blog-import.env`.

- [ ] **Step 4: Run to verify pass**

Run: `go vet ./... && go test ./... 2>&1 | tail -3`
Expected: `ok` for the package, all prior tests still pass.

- [ ] **Step 5: Commit**

```bash
cd ~/projects/personal/platen
git add blog.go blog_test.go server.go main.go systemd/platen.service .gitignore
git commit -m "server: owner-only send-to-blog, posting the doc to the blog editor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Platen UI — the button

**Files:**
- Modify: `platen/web/api.js` (add `sendToBlog` after `deleteDoc`)
- Modify: `platen/web/app.js` (import `sendToBlog`; two entries in `chromeHandlers()`)
- Modify: `platen/web/chrome.js` (button + status line; `panel.append(...)` near line 121)
- Modify: `platen/web/app.css` (after the `#share-status:empty` rule, ~line 385)
- Modify: `platen/tests/browser/test_editor.py` (`PlatenServer.__init__` gains `extra_args=(), extra_env=None`)
- Create: `platen/tests/browser/test_send_to_blog.py`
- Modify: `platen/CLAUDE.md` (a short "Send to blog" section)

**Interfaces:**
- Consumes: `POST /api/docs/{name}/send-to-blog`, `GET /api/me`'s `can_send_to_blog` (Task 3).
- Produces: `#send-to-blog` button and `#blog-status` line in `#panel`, present only for the owner.

Deliberate deviation from the spec: the result goes in its own `#blog-status` line, not `#share-status`, because `#share-status` clears itself on a timer and the **Open in editor** link must stay put.

- [ ] **Step 1: Write the failing browser test**

First check how the harness's `Browser` is constructed and how `make test-browser` invokes tests (`grep -n 'test-browser' -A3 Makefile`; `grep -n 'class Browser' -A15 tests/browser/cdp.py`). Each `Browser()` must get its own profile so two sign-ins don't share cookies; if it doesn't, give it one the same way the harness does elsewhere.

In `tests/browser/test_editor.py`, change `PlatenServer.__init__`'s signature and the env/argv lines:

```python
    def __init__(self, binary, port, docs, data, cwd=REPO, extra_args=(), extra_env=None):
        ...
        env = dict(os.environ, BASE_URL=f"http://127.0.0.1:{port}")
        env.update(extra_env or {})
        ...
        self.proc = subprocess.Popen(
            [binary, "-addr", f"127.0.0.1:{port}", "-docs", docs, "-data", data, *extra_args],
            ...
```

`tests/browser/test_send_to_blog.py`:

```python
"""Send to blog, in a real browser: only the owner sees the button, and a
tap sends what was just typed (autosave flushed first) and shows a link."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_editor import BINARY, REPO, Browser, PlatenServer, _free_port  # noqa: E402

OWNER = "owner@example.com"


class FakeEditor(http.server.BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeEditor.received.append((self.headers.get("X-Import-Token"), body))
        out = json.dumps({"slug": "hello", "edit_url": "http://editor.test/edit/hello"}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


class SendToBlogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["go", "build", "-o", BINARY, "."], cwd=REPO, check=True)
        cls.editor = http.server.HTTPServer(("127.0.0.1", 0), FakeEditor)
        threading.Thread(target=cls.editor.serve_forever, daemon=True).start()
        editor_url = f"http://127.0.0.1:{cls.editor.server_port}/api/import"
        cls.platen = PlatenServer(
            BINARY, _free_port(), tempfile.mkdtemp(prefix="platen-docs-"),
            tempfile.mkdtemp(prefix="platen-data-"),
            extra_args=("-owner", OWNER),
            extra_env={"BLOG_IMPORT_TOKEN": "tok", "BLOG_IMPORT_URL": editor_url},
        )

    @classmethod
    def tearDownClass(cls):
        cls.platen.stop()
        cls.editor.shutdown()

    def open_panel(self, b):
        b.eval("document.querySelector('#menu-dot').click(), true")
        b.wait_for("document.querySelector('#panel') && "
                   "getComputedStyle(document.querySelector('#panel')).display !== 'none'")

    def test_owner_sends_what_was_just_typed(self):
        b = Browser()
        try:
            self.platen.sign_in(b, OWNER)
            b.eval("document.querySelector('#input').focus(), true")
            b.type("# Hello\n\nJust typed.")
            self.open_panel(b)  # immediately: the autosave debounce has not fired
            b.wait_for("!!document.querySelector('#send-to-blog')")
            b.eval("document.querySelector('#send-to-blog').click(), true")
            b.wait_for("!!document.querySelector('#blog-status a')", timeout=15)
            href = b.eval("document.querySelector('#blog-status a').href")
            self.assertEqual(href, "http://editor.test/edit/hello")
            token, body = FakeEditor.received[-1]
            self.assertEqual(token, "tok")
            self.assertIn("Just typed.", body["text"])
        finally:
            b.close()

    def test_other_accounts_have_no_button(self):
        b = Browser()
        try:
            self.platen.sign_in(b, "someone@example.com")
            self.open_panel(b)
            self.assertFalse(b.eval("!!document.querySelector('#send-to-blog')"))
        finally:
            b.close()


if __name__ == "__main__":
    unittest.main()
```

If `b.type` doesn't handle `\n` as Enter, use whatever the harness's existing tests use for newlines (grep `test_editor.py` for `\\n` in `b.type` calls) or set `#input`'s value and dispatch `input`, as `setUp` does.

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/projects/personal/platen && python3 tests/browser/test_send_to_blog.py -v`
Expected: `test_owner_sends_what_was_just_typed` FAILS (timeout waiting for `#send-to-blog`); `test_other_accounts_have_no_button` passes.

- [ ] **Step 3: Implement**

`web/api.js`, after `deleteDoc`:

```js
// Owner only (blog.go): a new draft post in the blog editor from this doc.
// Resolves to {slug, edit_url}. Errors carry the server's message.
export async function sendToBlog(name) {
  return request(`/api/docs/${encodeURIComponent(name)}/send-to-blog`, { method: 'POST' });
}
```

`web/app.js`: add `sendToBlog` to the import list from `./api.js`. In `chromeHandlers()`, after `onShare`:

```js
    // Save first, so the draft has every keystroke -- the same wait
    // handleDeleteDoc does before its request goes out.
    onSendToBlog: async () => {
      await autosave.flush();
      await autosave.settled(docName);
      return sendToBlog(docName);
    },
    canSendToBlog: () => Boolean(me && me.can_send_to_blog),
```

`web/chrome.js`, after the `shareStatus`/`showShareStatus` block:

```js
  // Send to blog: the owner's only (the server decides, via /api/me). Its
  // own full-width row under Share / Fullscreen rather than a third flex
  // item in `actions` (see the note on #share-status above). Its status
  // line doesn't clear itself the way #share-status does: it holds the
  // Open in editor link.
  const blogBtn = document.createElement('button');
  blogBtn.id = 'send-to-blog';
  blogBtn.type = 'button';
  blogBtn.textContent = 'Send to blog';
  const blogStatus = document.createElement('div');
  blogStatus.id = 'blog-status';
  const canSendToBlog = Boolean(handlers.canSendToBlog && handlers.canSendToBlog());

  blogBtn.addEventListener('click', async () => {
    blogBtn.disabled = true;
    blogStatus.textContent = 'Sending.';
    try {
      const draft = await handlers.onSendToBlog();
      blogStatus.textContent = 'Draft created. ';
      const link = document.createElement('a');
      link.href = draft.edit_url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = 'Open in editor';
      blogStatus.append(link);
    } catch (err) {
      blogStatus.textContent = `Not sent. ${err.message}`;
    } finally {
      blogBtn.disabled = false;
    }
  });
```

and change the `panel.append(...)` line to:

```js
  panel.append(docList, newBtn, actions, shareStatus,
    ...(canSendToBlog ? [blogBtn, blogStatus] : []),
    toggles, scopeControl, wordcount, account);
```

`web/app.css`, after `#share-status:empty { ... }`:

```css
/* Send to blog (owner only): its own full-width row, bordered like Share
   and Fullscreen so it reads as a button. ID+ID to beat `#panel button`. */
#panel #send-to-blog {
  display: block;
  width: 100%;
  text-align: center;
  padding: 6px 0;
  margin: 0 0 12px;
  border: 1px solid color-mix(in srgb, var(--ink) 25%, transparent);
  border-radius: 4px;
}
#blog-status {
  margin: 0 0 12px;
  opacity: 0.7;
}
#blog-status:empty {
  margin: 0;
}
#blog-status a {
  color: inherit;
}
```

`CLAUDE.md`: add a "Send to blog" section: owner-only (the `-owner` flag), button in the panel, `blog.go` posts the doc to the blog editor's `POST /api/import` over loopback with `X-Import-Token` from the gitignored `.blog-import.env` (0600, `BLOG_IMPORT_TOKEN`, optional `BLOG_IMPORT_URL`), feature off without it; every send is a new draft; the editor owns the text→blocks rules (`personal-site/editor/importer.py`).

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/browser/test_send_to_blog.py -v && make test && make test-browser`
Expected: both new tests pass; Go, node, and existing browser suites pass.

Then screenshot the open panel as the owner to check the layout (headless Chromium per the global CLAUDE.md, via the test harness or a one-off script using the same `PlatenServer`/`Browser`), `Read` the PNG, and adjust spacing if the new row looks off against Share / Fullscreen. Light and dark theme both.

- [ ] **Step 5: Commit**

```bash
git add web/api.js web/app.js web/chrome.js web/app.css tests/browser/test_editor.py tests/browser/test_send_to_blog.py CLAUDE.md
git commit -m "ui: Send to blog button for the owner, with an Open in editor link

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Deploy and verify end to end

**Files:**
- Create (gitignored, 0600, never committed or printed): `personal-site/.editor-import.env`, `platen/.blog-import.env`
- Modify: memory files `~/.claude/projects/-home-peter-projects-personal/memory/platen-project.md` and `personal-site-project.md` (one line each)

- [ ] **Step 1: Generate and install the secret without printing it**

```bash
umask 077
TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
printf 'EDITOR_IMPORT_TOKEN=%s\n' "$TOKEN" > ~/projects/personal/personal-site/.editor-import.env
printf 'BLOG_IMPORT_TOKEN=%s\n' "$TOKEN" > ~/projects/personal/platen/.blog-import.env
unset TOKEN
stat -c '%a %n' ~/projects/personal/personal-site/.editor-import.env ~/projects/personal/platen/.blog-import.env
cd ~/projects/personal/personal-site && git check-ignore .editor-import.env
cd ~/projects/personal/platen && git check-ignore .blog-import.env
```

Expected: both files `600`; both `check-ignore` lines print the filename.

- [ ] **Step 2: Install the updated unit and restart both services**

Check how platen installs its unit (`grep -n 'install' -A4 Makefile`); use that target, or `sudo cp systemd/platen.service /etc/systemd/system/ && sudo systemctl daemon-reload`. Then:

```bash
cd ~/projects/personal/personal-site && make editor-restart
cd ~/projects/personal/platen && make svc-restart
sudo journalctl -u platen -n 5 --no-pager | grep 'send-to-blog=true'
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8804/api/import \
  -H 'Content-Type: application/json' -d '{"text":"# x\n\ny","name":"x"}'
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8804/api/import \
  -H 'Content-Type: application/json' -H 'X-Import-Token: wrong' -d '{"text":"# x\n\ny","name":"x"}'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8801/
```

Expected: platen log shows `send-to-blog=true`; both import curls `401`; platen `200`.

- [ ] **Step 3: Real end to end with Peter's Spruce doc**

Run a temporary Platen instance (the freshly built binary) on a free port with a temp docs/data dir, `-owner e2e@example.com`, `BLOG_IMPORT_URL` default (the REAL editor), and `BLOG_IMPORT_TOKEN` read from `platen/.blog-import.env` into the process env (not echoed). Drive it with the browser harness: sign in as `e2e@example.com`, write the contents of `platen/documents/a626278c859351467d79561a/2026-09-15 2252.md` into the doc (set `#input`'s value + dispatch `input`), open the panel, click **Send to blog**, wait for `#blog-status a`. Stop the temp instance by PID.

Expected: a new file `personal-site/content/blog/spruce-the-litter-cleaning-tracker-2.md`.

Verify it:

```bash
cd ~/projects/personal/personal-site/editor && .venv/bin/python - <<'PY'
from editor import config
from editor.blocks import parse_blocks
from editor.frontmatter import read_meta, split_post
fm, body = split_post((config.BLOG_DIR / "spruce-the-litter-cleaning-tracker-2.md").read_text())
print(read_meta(fm))
print([b.kind for b in parse_blocks(body)])
PY
python3 ../scripts/check-drafts.py ../content /nonexistent && echo gate-ok
```

Expected: title "Spruce, the litter cleaning tracker", `draft: True`; kinds are `heading` for each of the doc's `##` lines and `paragraph` for each paragraph, in order (compare with the source); `gate-ok`.

- [ ] **Step 4: Screenshot the draft in the real editor**

Mint a short-lived editor session in the real auth DB with `editor.auth.store.create_session` (email `ptr.vldz@gmail.com`, expiry now + 10 minutes, id from `editor.auth.security.new_session_id()`), set it as the `editor_session` cookie for `127.0.0.1` over CDP (see the headless-chromium-cdp-harness memory), load `http://127.0.0.1:8804/edit/spruce-the-litter-cleaning-tracker-2` at a tablet viewport, screenshot, then `store.delete_session` it. Read the PNG: it must show separate heading and paragraph blocks. Kill Chromium by PID and remove its profile dir (headless-chromium-process-leak memory).

- [ ] **Step 5: Final checks and memory**

Run both full suites once more (`editor: .venv/bin/python -m pytest -q tests`; `platen: make test`). Confirm `git status` in both repos shows no env files and only the expected new draft in personal-site (`content/blog/spruce-the-litter-cleaning-tracker-2.md`, left uncommitted for Peter, like any new draft). Update the two memory files with one line each: platen has an owner-only Send to blog (2026-10-04) via the editor's token-authed `/api/import`; the editor has its first non-session route. Commit nothing else; do not push.
