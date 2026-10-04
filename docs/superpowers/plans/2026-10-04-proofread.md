# AI Proofread Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ✨ Proofread button in the blog editor that gets spelling/grammar/punctuation-only suggestions from the local `claude` CLI and lets Peter step through them inline, accepting or rejecting each.

**Architecture:** A pure module `editor/proofread.py` owns the prompt, response parsing, the guardrails, mark rendering and applying one fix. `editor/app.py` gains two session-authed routes that use it (`/proofread` per batch of ≤5 blocks, `/proofread/apply` per accepted fix, through `_write_body` so Undo works). `editor/web/editor.js` drives batches with a progress bar, shows server-rendered marks, and a bottom review bar.

**Tech Stack:** Python 3 / FastAPI / markdown-it-py / pytest; vanilla JS + CSS; headless Chromium over CDP for the UI check.

**Spec:** `docs/superpowers/specs/2026-10-04-proofread-design.md`

## Global Constraints

- Work in a git worktree of `/home/peter/projects/personal/personal-site`, never the live checkout (blog-editor.service serves `editor/web/` from disk). Never restart services, run `make dev`/`make stop`/publish, or `pkill -f`.
- Editor tests: from `editor/`, `/home/peter/projects/personal/personal-site/editor/.venv/bin/python -m pytest -q tests/...` (baseline 625 passed).
- Commits: simple present tense, NO `Co-Authored-By` footer (repo CLAUDE.md). Don't push.
- `claude_bin` default is the absolute path `/home/peter/.local/bin/claude` (env `EDITOR_CLAUDE_BIN`); optional `EDITOR_PROOFREAD_MODEL` → `--model`. Timeout 120 s per batch. Batches of up to 5 blocks.
- Prose kinds: `paragraph`, `heading`, `list`, `blockquote`, `pair`.
- Suggestion kinds: `spelling`, `grammar`, `punctuation`.
- Guardrails: `before` occurs exactly once in the block source; `before != after`; no newline in either; `before` ≤ 80 chars; word-level edit distance ≤ 3; neither `before` nor `after` contains any of `` [ ] ( ) * _ ` # < > | `` (stricter than "doesn't alter", deliberately); `before`'s span doesn't intersect an inline code span, URL, link destination or HTML tag; non-overlapping within a block.
- No editing blocks during review; nothing in the post changes until Accept.
- User-facing copy: short declarative sentences, no emoji except the ✨ on the button.
- 44px touch targets; no hover-only controls.

## Review Focus

1. **Claude's `before` doesn't match the source exactly** (smart quotes, trimmed spaces) → the suggestion is silently dropped, never a crash or a wrong replacement. Pinned in Task 1 (`test_drops_before_not_in_source`).
2. **The same typo appears twice in one block** and Claude gives just the word → dropped as ambiguous. Pinned in Task 1 (`test_drops_ambiguous_before`).
3. **Accepting two suggestions in the same block one after the other** → the second applies to the updated source using the new block hash. Pinned in Task 2 (`test_two_accepts_in_one_block`).
4. **Claude hangs or errors on one batch** → that batch reports an error, nothing is written, other batches unaffected. Pinned in Task 2 (`test_timeout_reports_error`).
5. **A typo inside link text vs. inside a URL** → the link-text fix survives, the URL one is dropped. Pinned in Task 1 (`test_link_text_ok_url_dropped`).

---

### Task 1: `editor/proofread.py` — prompt, parsing, guardrails, marks, apply

**Files:**
- Create: `editor/proofread.py`
- Modify: `editor/config.py` (add `claude_bin()` and `proofread_model()` after `import_token()`)
- Test: `editor/tests/test_proofread.py`

**Interfaces:**
- Produces:
  - `PROSE_KINDS: frozenset[str]`
  - `block_hash(source: str) -> str` (sha256 hex of the source)
  - `build_prompt(blocks: list[Block]) -> str`
  - `run_claude(prompt: str, timeout_s: int = 120) -> str` (raises `subprocess.TimeoutExpired` / `CalledProcessError` / `OSError`)
  - `parse_response(raw: str) -> list` (raises `ValueError` when no JSON array)
  - `validate(index: int, source: str, items: list) -> list[dict]` → `[{"id": f"{index}-{n}", "before", "after", "kind"}]` sorted by position in the source
  - `review_html(source: str, suggestions: list[dict]) -> str`
  - `apply_one(source: str, before: str, after: str) -> str` (raises `ValueError` with a readable message)
  - `config.claude_bin() -> str`, `config.proofread_model() -> str`

- [ ] **Step 1: Write the failing tests** — `editor/tests/test_proofread.py`:

```python
import pytest

from editor import config, proofread
from editor.blocks import parse_blocks


def ok(before, after, kind="spelling", block=0):
    return {"block": block, "before": before, "after": after, "kind": kind}


def test_claude_bin_default_is_absolute(monkeypatch):
    monkeypatch.delenv("EDITOR_CLAUDE_BIN", raising=False)
    assert config.claude_bin() == "/home/peter/.local/bin/claude"


def test_clean_suggestion_survives_with_id():
    out = proofread.validate(3, "I will recieve it.", [ok("recieve", "receive", block=3)])
    assert out == [{"id": "3-0", "before": "recieve", "after": "receive", "kind": "spelling"}]


def test_drops_before_not_in_source():
    assert proofread.validate(0, "It’s fine.", [ok("It's", "It is")]) == []


def test_drops_ambiguous_before():
    assert proofread.validate(0, "teh cat and teh dog", [ok("teh", "the")]) == []
    out = proofread.validate(0, "teh cat and teh dog", [ok("teh cat", "the cat")])
    assert [s["before"] for s in out] == ["teh cat"]


@pytest.mark.parametrize("item", [
    ok("same", "same"),
    ok("a\nb", "a b"),
    ok("x" * 81, "y" * 81),
    ok("one two three four five", "five four three two one", kind="grammar"),
    ok("bold", "**bold**"),
    ok("word", "word", kind="style"),
    {"block": 0, "before": 5, "after": "x", "kind": "spelling"},
])
def test_guardrails_drop(item):
    source = "same a b bold word one two three four five " + "x" * 81
    assert proofread.validate(0, source, [item]) == []


def test_link_text_ok_url_dropped():
    source = "See [the documantation](https://exmaple.com/docs) now."
    out = proofread.validate(0, source, [
        ok("documantation", "documentation"),
        ok("exmaple", "example"),
    ])
    assert [s["before"] for s in out] == ["documantation"]


def test_code_and_html_spans_protected():
    source = 'Run `teh tool` and <span class="teh">ok</span> teh end.'
    out = proofread.validate(0, source, [ok("teh end", "the end")])
    assert [s["before"] for s in out] == ["teh end"]
    assert proofread.validate(0, "Run `teh tool` ok", [ok("teh tool", "the tool")]) == []


def test_overlapping_later_dropped_and_sorted_by_position():
    source = "Thier house is is big."
    out = proofread.validate(0, source, [
        ok("is is", "is", kind="grammar"),
        ok("house is", "house's", kind="grammar"),
        ok("Thier", "Their"),
    ])
    # sorted by position: "house is" (at 6) wins, "is is" (at 12) overlaps it
    assert [s["before"] for s in out] == ["Thier", "house is"]
    assert [s["id"] for s in out] == ["0-0", "0-1"]


def test_parse_response_handles_fence_and_prose():
    raw = 'Here you go:\n```json\n[{"block": 1, "before": "a", "after": "b", "kind": "spelling"}]\n```'
    assert proofread.parse_response(raw)[0]["block"] == 1
    assert proofread.parse_response("[]") == []
    with pytest.raises(ValueError):
        proofread.parse_response("no json here")


def test_review_html_marks_in_place():
    source = "I will recieve *it* soon."
    sugg = proofread.validate(0, source, [ok("recieve", "receive")])
    html = proofread.review_html(source, sugg)
    assert '<del class="pr-old" data-sid="0-0">recieve</del>' in html
    assert '<ins class="pr-new" data-sid="0-0">receive</ins>' in html
    assert "<em>it</em>" in html and html.startswith("<p>")


def test_review_html_escapes():
    source = "a & b recieve"
    sugg = proofread.validate(0, source, [ok("recieve", "receive")])
    assert "a &amp; b" in proofread.review_html(source, sugg)


def test_apply_one_replaces_exactly_once_and_rechecks():
    assert proofread.apply_one("I recieve it.", "recieve", "receive") == "I receive it."
    with pytest.raises(ValueError):
        proofread.apply_one("teh and teh", "teh", "the")
    with pytest.raises(ValueError):
        proofread.apply_one("I receive it.", "recieve", "receive")


def test_build_prompt_lists_blocks_by_index():
    blocks = parse_blocks("Para one.\n\n## Head\n\nPara two.\n")
    prompt = proofread.build_prompt(blocks)
    assert '<block index="0">\nPara one.\n</block>' in prompt
    assert '<block index="2">' in prompt
    assert "only" in prompt.lower() and "json" in prompt.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd editor && /home/peter/projects/personal/personal-site/editor/.venv/bin/python -m pytest -q tests/test_proofread.py`
Expected: collection error `ModuleNotFoundError: No module named 'editor.proofread'`.

- [ ] **Step 3: Implement**

`editor/config.py`, after `import_token()`:

```python
def claude_bin() -> str:
    """The claude CLI the proofreader runs. Absolute by default: the systemd
    unit's PATH has no ~/.local/bin, which is how recipes' prod parser broke
    on 2026-09-13. Read live so tests can override it."""
    return os.environ.get("EDITOR_CLAUDE_BIN", "/home/peter/.local/bin/claude")


def proofread_model() -> str:
    """Optional --model for the proofreader; empty means the CLI default."""
    return os.environ.get("EDITOR_PROOFREAD_MODEL", "").strip()
```

`editor/proofread.py`:

```python
"""AI proofreading: spelling, grammar and punctuation only.

Claude proposes; this module disposes. Every suggestion is checked against
the block's exact source before Peter sees it, and again when he accepts it,
so a rewording can't arrive dressed as a fix and a fix can't land on text
that has moved. Pure apart from run_claude.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess

from editor import config
from editor.blocks import _md

PROSE_KINDS = frozenset({"paragraph", "heading", "list", "blockquote", "pair"})
KINDS = frozenset({"spelling", "grammar", "punctuation"})
MAX_BEFORE = 80
MAX_WORD_EDITS = 3
_MARKUP = set("[]()*_`#<>|")
_PROTECTED = re.compile(
    r"`[^`\n]*`"            # inline code
    r"|https?://[^\s)>\]]+"  # bare or linked URLs
    r"|\]\([^)\n]*\)"        # link destinations
    r"|<[^>\n]+>"            # HTML tags
)

PROMPT = """You are a proofreader for a personal blog. Fix ONLY real spelling, grammar and punctuation mistakes.

Do not rephrase, reword, restyle or tighten anything. Keep the author's wording, voice, sentence fragments, informal phrasing, names and capitalization choices. Do not touch markdown syntax, links, URLs, HTML or code. If a sentence is correct, leave it alone. Return nothing rather than something doubtful.

Return ONLY a JSON array and no other text:
[{"block": <block index>, "before": "<exact text from that block>", "after": "<corrected text>", "kind": "spelling" | "grammar" | "punctuation"}]
"before" must be copied character for character from the block, and be the shortest span (usually one word, at most a few) that appears exactly once in that block. Return [] if there are no mistakes.

"""


def block_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_prompt(blocks) -> str:
    parts = [f'<block index="{b.index}">\n{b.source}\n</block>' for b in blocks]
    return PROMPT + "\n\n".join(parts) + "\n"


def run_claude(prompt: str, timeout_s: int = 120) -> str:
    cmd = [config.claude_bin(), "-p", prompt]
    model = config.proofread_model()
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=True)
    return proc.stdout


def parse_response(raw: str) -> list:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    text = fenced.group(1) if fenced else raw
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        raise ValueError("no JSON array in the response")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("response is not a list")
    return data


def _word_edits(a: str, b: str) -> int:
    x, y = a.split(), b.split()
    prev = list(range(len(y) + 1))
    for i, xi in enumerate(x, 1):
        cur = [i]
        for j, yj in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (xi != yj)))
        prev = cur
    return prev[-1]


def _problem(source: str, before, after, kind="spelling") -> str | None:
    """Why this fix can't be offered, or None if it can."""
    if not isinstance(before, str) or not isinstance(after, str) or kind not in KINDS:
        return "malformed suggestion"
    if not before or before == after:
        return "no change"
    if "\n" in before or "\n" in after or len(before) > MAX_BEFORE:
        return "too long"
    if source.count(before) != 1:
        return "this text is no longer in the paragraph exactly once"
    if _word_edits(before, after) > MAX_WORD_EDITS:
        return "changes too many words"
    if _MARKUP & set(before + after):
        return "touches markdown"
    start = source.index(before)
    end = start + len(before)
    for m in _PROTECTED.finditer(source):
        if m.start() < end and start < m.end():
            return "inside a link, code or HTML"
    return None


def validate(index: int, source: str, items: list) -> list[dict]:
    kept = []
    for item in items:
        if not isinstance(item, dict):
            continue
        before, after, kind = item.get("before"), item.get("after"), item.get("kind")
        if _problem(source, before, after, kind) is None:
            kept.append((source.index(before), before, after, kind))
    kept.sort(key=lambda k: k[0])
    out, last_end = [], -1
    for start, before, after, kind in kept:
        if start < last_end:
            continue  # overlaps an earlier fix
        out.append({"before": before, "after": after, "kind": kind})
        last_end = start + len(before)
    for n, s in enumerate(out):
        s["id"] = f"{index}-{n}"
    return [{"id": s["id"], "before": s["before"], "after": s["after"], "kind": s["kind"]} for s in out]


def review_html(source: str, suggestions: list[dict]) -> str:
    marked = source
    placed = sorted(suggestions, key=lambda s: source.index(s["before"]), reverse=True)
    for n, s in enumerate(placed):
        at = marked.index(s["before"])
        marked = marked[:at] + f"{n}" + marked[at + len(s["before"]):]
    out = _md.render(marked)
    for n, s in enumerate(placed):
        sid = html.escape(s["id"], quote=True)
        out = out.replace(
            f"{n}",
            f'<del class="pr-old" data-sid="{sid}">{html.escape(s["before"])}</del>'
            f'<ins class="pr-new" data-sid="{sid}">{html.escape(s["after"])}</ins>',
        )
    return out


def apply_one(source: str, before: str, after: str) -> str:
    problem = _problem(source, before, after)
    if problem:
        raise ValueError(problem)
    return source.replace(before, after, 1)
```

Note: `_problem` defaults `kind` to `"spelling"` so `apply_one` re-checks guardrails 1–5 without needing the kind.

- [ ] **Step 4: Run to verify pass**

Run: `.../python -m pytest -q tests/test_proofread.py` → all pass. Then the full suite → 625 + new, all pass.

- [ ] **Step 5: Commit**

```bash
git add editor/proofread.py editor/config.py editor/tests/test_proofread.py
git commit -m "Add the proofreader's prompt, guardrails and mark rendering"
```

---

### Task 2: Routes — `/proofread` and `/proofread/apply`

**Files:**
- Modify: `editor/app.py` (imports; new models + two routes after the import route)
- Test: `editor/tests/test_api_proofread.py`

**Interfaces:**
- Consumes: everything Task 1 produces; `parse_blocks`, `replace_block`, `_read_post`, `_write_body`, `get_post` in app.py.
- Produces:
  - `POST /api/posts/{slug}/proofread` body `{"indices": [int] (≤5)}` → `{"blocks": [{"index", "block_hash", "suggestions": [...], "review_html"}], "errors": [{"indices": [int], "message": str}]}`. Only requested prose blocks are sent to Claude; non-prose or out-of-range indices are ignored. Blocks with no surviving suggestions are returned with `suggestions: []`.
  - `POST /api/posts/{slug}/proofread/apply` body `{"index", "block_hash", "before", "after", "hash"}` → the normal post payload plus `"block_hash"` (the block's new hash). 409 on a stale post hash, a changed block, or a failed re-check (detail is readable).

- [ ] **Step 1: Write the failing tests** — `editor/tests/test_api_proofread.py`:

```python
import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import config, proofread
from editor.app import app

client = TestClient(app)
SLUG = "proofread-fixture"
BODY = (
    "I will recieve teh letter tomorow.\n\n"
    "## A heading\n\n"
    "![a photo](https://img.cloudy.nyc/x.jpg)\n\n"
    "Second paragrpah here.\n"
)


@pytest.fixture(autouse=True)
def post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(f'+++\ntitle = "Proofread fixture"\ndate = 2026-10-04\ndraft = true\n+++\n\n{BODY}')
    yield path
    path.unlink(missing_ok=True)


def fake(monkeypatch, items=None, exc=None):
    calls = []

    def run(prompt, timeout_s=120):
        calls.append(prompt)
        if exc:
            raise exc
        import json
        return json.dumps(items or [])

    monkeypatch.setattr(proofread, "run_claude", run)
    return calls


def current():
    return client.get(f"/api/posts/{SLUG}").json()


def test_returns_marked_suggestions(monkeypatch):
    calls = fake(monkeypatch, [
        {"block": 0, "before": "recieve", "after": "receive", "kind": "spelling"},
        {"block": 0, "before": "tomorow", "after": "tomorrow", "kind": "spelling"},
        {"block": 0, "before": "I will recieve teh letter", "after": "The letter arrives", "kind": "grammar"},
    ])
    res = client.post(f"/api/posts/{SLUG}/proofread", json={"indices": [0, 1, 2]})
    assert res.status_code == 200
    data = res.json()
    assert data["errors"] == []
    b0 = next(b for b in data["blocks"] if b["index"] == 0)
    assert [s["after"] for s in b0["suggestions"]] == ["receive", "tomorrow"]
    assert 'class="pr-old"' in b0["review_html"]
    assert b0["block_hash"] == proofread.block_hash("I will recieve teh letter tomorow.")
    assert '<block index="2">' not in calls[0]  # the image block is not prose


def test_rejects_more_than_five_indices(monkeypatch):
    fake(monkeypatch)
    assert client.post(f"/api/posts/{SLUG}/proofread", json={"indices": [0, 1, 2, 3, 4, 5]}).status_code == 422


def test_timeout_reports_error(monkeypatch):
    fake(monkeypatch, exc=subprocess.TimeoutExpired(cmd="claude", timeout=120))
    data = client.post(f"/api/posts/{SLUG}/proofread", json={"indices": [0, 3]}).json()
    assert data["blocks"] == []
    assert data["errors"][0]["indices"] == [0, 3]


def test_malformed_json_reports_error(monkeypatch):
    monkeypatch.setattr(proofread, "run_claude", lambda prompt, timeout_s=120: "sorry, no")
    data = client.post(f"/api/posts/{SLUG}/proofread", json={"indices": [0]}).json()
    assert data["errors"] and data["blocks"] == []


def apply(before, after, block_hash=None, index=0, post_hash=None):
    p = current()
    src = p["blocks"][index]["source"]
    return client.post(f"/api/posts/{SLUG}/proofread/apply", json={
        "index": index, "before": before, "after": after,
        "block_hash": block_hash or proofread.block_hash(src),
        "hash": post_hash or p["hash"],
    })


def test_apply_writes_one_fix_and_returns_new_block_hash():
    res = apply("recieve", "receive")
    assert res.status_code == 200
    data = res.json()
    assert data["blocks"][0]["source"] == "I will receive teh letter tomorow."
    assert data["block_hash"] == proofread.block_hash("I will receive teh letter tomorow.")


def test_two_accepts_in_one_block():
    first = apply("recieve", "receive").json()
    res = client.post(f"/api/posts/{SLUG}/proofread/apply", json={
        "index": 0, "before": "tomorow", "after": "tomorrow",
        "block_hash": first["block_hash"], "hash": first["hash"],
    })
    assert res.status_code == 200
    assert res.json()["blocks"][0]["source"] == "I will receive teh letter tomorrow."


def test_apply_refuses_changed_block():
    stale = proofread.block_hash("something else")
    assert apply("recieve", "receive", block_hash=stale).status_code == 409


def test_apply_refuses_stale_post_hash():
    assert apply("recieve", "receive", post_hash="0" * 64).status_code == 409


def test_apply_rechecks_guardrails():
    assert apply("I will recieve teh letter", "Letters come").status_code == 409


def test_apply_is_undoable():
    apply("recieve", "receive")
    assert client.post(f"/api/posts/{SLUG}/undo", json={"hash": current()["hash"]}).status_code == 200
    assert current()["blocks"][0]["source"] == "I will recieve teh letter tomorow."
```

(Check the undo route's request body in app.py — `PostRestore` — and adjust the undo call's JSON to match if it differs.)

- [ ] **Step 2: Run to verify failure**

Run: `.../python -m pytest -q tests/test_api_proofread.py` → 404s / failures.

- [ ] **Step 3: Implement** — in `editor/app.py` add `import logging`/`import subprocess` if missing, `from editor import proofread`, ensure `replace_block` and `parse_blocks` are imported, then after the import route:

```python
log = logging.getLogger("editor.proofread")


class ProofreadRequest(BaseModel):
    indices: list[int] = Field(max_length=5)


@app.post("/api/posts/{slug}/proofread")
def proofread_post(slug: str, req: ProofreadRequest):
    """Spelling/grammar suggestions for up to five prose blocks.

    One claude call per request; the client batches and shows progress.
    A failure is reported for this batch only and writes nothing."""
    _, _, _, body = _read_post(slug)
    blocks = parse_blocks(body)
    wanted = [
        blocks[i] for i in dict.fromkeys(req.indices)
        if 0 <= i < len(blocks) and blocks[i].kind in proofread.PROSE_KINDS
    ]
    if not wanted:
        return {"blocks": [], "errors": []}
    try:
        items = proofread.parse_response(proofread.run_claude(proofread.build_prompt(wanted)))
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, ValueError) as exc:
        log.warning("proofread failed for %s %s: %s", slug, [b.index for b in wanted], exc)
        return {"blocks": [], "errors": [{
            "indices": [b.index for b in wanted],
            "message": "The proofreader didn't answer for these paragraphs.",
        }]}
    out = []
    for b in wanted:
        mine = [it for it in items if isinstance(it, dict) and it.get("block") == b.index]
        suggestions = proofread.validate(b.index, b.source, mine)
        dropped = len(mine) - len(suggestions)
        if dropped:
            log.info("proofread dropped %d suggestion(s) in %s block %d", dropped, slug, b.index)
        out.append({
            "index": b.index,
            "block_hash": proofread.block_hash(b.source),
            "suggestions": suggestions,
            "review_html": proofread.review_html(b.source, suggestions) if suggestions else b.html,
        })
    return {"blocks": out, "errors": []}


class ProofreadApply(BaseModel):
    index: int
    block_hash: str
    before: str
    after: str
    hash: str


@app.post("/api/posts/{slug}/proofread/apply")
def proofread_apply(slug: str, req: ProofreadApply):
    """Apply one accepted fix. Re-checks it against the block as it is now."""
    def transform(body):
        blocks = parse_blocks(body)
        if not 0 <= req.index < len(blocks):
            raise IndexError(req.index)
        source = blocks[req.index].source
        if proofread.block_hash(source) != req.block_hash:
            raise HTTPException(status_code=409, detail="This paragraph changed since it was proofread.")
        try:
            new_source = proofread.apply_one(source, req.before, req.after)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"Can't apply this fix: {exc}.")
        return replace_block(body, req.index, new_source)

    post = _write_body(slug, req.hash, transform)
    post["block_hash"] = proofread.block_hash(post["blocks"][req.index]["source"])
    return post
```

(`_write_body` raises before snapshotting when the transform raises, so a refused fix writes nothing and leaves no Undo entry.)

- [ ] **Step 4: Run** the new file, `tests/test_auth.py` (the route walk must cover both new routes with a 401), then the full suite.

- [ ] **Step 5: Commit**

```bash
git add editor/app.py editor/tests/test_api_proofread.py
git commit -m "Add the proofread and apply routes"
```

---

### Task 3: Editor UI — button, progress, inline review, bottom bar

**Files:**
- Modify: `editor/web/index.html` (button + progress container in the top bar)
- Modify: `editor/web/editor.js` (proofread section; hooks in `renderBlocks`, the block click handler, and Undo/Discard/picker/+New/Publish)
- Modify: `editor/web/editor.css`
- Create: `scripts/verify-proofread.py` (headless-Chromium check with a fake claude)
- Modify: `CLAUDE.md` (short "Proofread" section)

**Interfaces:**
- Consumes: the two routes from Task 2; existing `state`, `els`, `setStatus`, `renderBlocks`, `applyPost`, `flushPendingEdit` in editor.js. Check `flushPendingEdit`'s return value semantics before using it as a gate.

- [ ] **Step 1: Markup** — in `index.html`, between `#status` and `#undo`:

```html
<button id="proofread" class="bar-action" title="Check spelling and grammar">✨ Proofread</button>
<span id="proof-progress" class="proof-progress" hidden>
  <span class="proof-track"><span class="proof-fill"></span></span>
  <span class="proof-text"></span>
  <button id="proof-cancel" class="bar-action">Cancel</button>
</span>
```

and before `</body>` (outside `.page`):

```html
<div id="review-bar" class="review-bar" hidden></div>
```

Add `proofread`, `proofProgress`, `proofCancel`, `reviewBar` to `els`.

- [ ] **Step 2: Proofread section in editor.js** (append near the other top-bar actions):

```js
// --- Proofread ---------------------------------------------------------------
// The server (editor/proofread.py) owns the prompt, the guardrails and the
// red/green marks; this only batches, shows progress and steps through
// what comes back. Nothing is written until Accept.
const PROSE_KINDS = new Set(['paragraph', 'heading', 'list', 'blockquote', 'pair']);
const PROOF_BATCH = 5;
state.review = null; // {blocks: Map(index -> {block_hash, review_html}), items: [], current: 0}
let proofRun = null;

function showProofProgress(done, total) {
  els.proofread.hidden = true;
  els.proofProgress.hidden = false;
  els.proofProgress.querySelector('.proof-fill').style.width = `${total ? (100 * done) / total : 0}%`;
  els.proofProgress.querySelector('.proof-text').textContent = `Proofreading ${done} of ${total} paragraphs`;
}

function hideProofProgress() {
  els.proofProgress.hidden = true;
  els.proofread.hidden = false;
}

function rangeText(indices) {
  const first = Math.min(...indices) + 1;
  const last = Math.max(...indices) + 1;
  return first === last ? `paragraph ${first}` : `paragraphs ${first}–${last}`;
}

async function startProofread() {
  if (proofRun || state.review) return;
  if ((await flushPendingEdit()) === false) return;
  const targets = state.blocks.filter((b) => PROSE_KINDS.has(b.kind)).map((b) => b.index);
  if (!targets.length) { setStatus('Nothing to proofread.'); return; }
  proofRun = { cancelled: false };
  state.review = { blocks: new Map(), items: [], current: 0 };
  const failed = [];
  showProofProgress(0, targets.length);
  for (let i = 0; i < targets.length && !proofRun.cancelled; i += PROOF_BATCH) {
    const batch = targets.slice(i, i + PROOF_BATCH);
    try {
      const res = await fetch(`/api/posts/${state.slug}/proofread`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ indices: batch }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      for (const b of data.blocks) {
        if (!b.suggestions.length) continue;
        state.review.blocks.set(b.index, { block_hash: b.block_hash, review_html: b.review_html });
        for (const s of b.suggestions) state.review.items.push({ ...s, index: b.index });
      }
      for (const e of data.errors) failed.push(...e.indices);
    } catch (err) {
      failed.push(...batch);
    }
    showProofProgress(Math.min(i + PROOF_BATCH, targets.length), targets.length);
    state.review.items.sort((a, b) => a.index - b.index); // stable: server order within a block
    renderBlocks();
    renderReviewBar();
  }
  proofRun = null;
  hideProofProgress();
  if (!state.review.items.length) {
    closeReview();
    setStatus(failed.length ? `Couldn't check ${rangeText(failed)}.` : 'No spelling or grammar issues found.');
    return;
  }
  setStatus(failed.length ? `Couldn't check ${rangeText(failed)}.` : '');
}

function currentItem() {
  return state.review && state.review.items[state.review.current];
}

function renderReviewBar() {
  const bar = els.reviewBar;
  if (!state.review || !state.review.items.length) { bar.hidden = true; bar.innerHTML = ''; return; }
  const { items, current } = state.review;
  const item = items[current];
  bar.hidden = false;
  bar.innerHTML = '';
  const mk = (label, cls, fn, title) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = label;
    if (title) b.title = title;
    b.addEventListener('click', fn);
    return b;
  };
  const count = document.createElement('span');
  count.className = 'review-count';
  count.textContent = `${current + 1} of ${items.length}`;
  const kind = document.createElement('span');
  kind.className = 'review-kind';
  kind.textContent = item.kind;
  bar.append(
    mk('↑', 'review-nav', () => step(-1), 'Previous suggestion'),
    mk('↓', 'review-nav', () => step(1), 'Next suggestion'),
    count, kind,
    mk('Accept', 'review-accept', () => accept(item)),
    mk('Reject', 'review-reject', () => reject(item)),
    mk('Accept all', 'review-all', acceptAll),
    mk('Close', 'review-close', () => { closeReview(); setStatus(''); }),
  );
  focusCurrent();
}

function focusCurrent() {
  document.querySelectorAll('.pr-current').forEach((n) => n.classList.remove('pr-current'));
  const item = currentItem();
  if (!item) return;
  const marks = document.querySelectorAll(`[data-sid="${CSS.escape(item.id)}"]`);
  marks.forEach((n) => n.classList.add('pr-current'));
  if (marks[0]) marks[0].scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function step(delta) {
  const r = state.review;
  r.current = (r.current + delta + r.items.length) % r.items.length;
  renderReviewBar();
}

// Accepting keeps the new text; rejecting keeps the old.
function resolveMark(htmlText, sid, keepNew) {
  const t = document.createElement('template');
  t.innerHTML = htmlText;
  const sel = (tag) => t.content.querySelector(`${tag}[data-sid="${CSS.escape(sid)}"]`);
  const drop = sel(keepNew ? 'del' : 'ins');
  const keep = sel(keepNew ? 'ins' : 'del');
  if (drop) drop.remove();
  if (keep) keep.replaceWith(document.createTextNode(keep.textContent));
  return t.innerHTML;
}

function removeItem(item, keepNew) {
  const r = state.review;
  const at = r.items.indexOf(item);
  if (at !== -1) r.items.splice(at, 1);
  const blk = r.blocks.get(item.index);
  if (blk) {
    blk.review_html = resolveMark(blk.review_html, item.id, keepNew);
    if (!r.items.some((i) => i.index === item.index)) r.blocks.delete(item.index);
  }
  if (r.current >= r.items.length) r.current = 0;
  if (!r.items.length) {
    closeReview();
    setStatus('All suggestions reviewed.');
    return;
  }
  renderBlocks();
  renderReviewBar();
}

async function accept(item) {
  const blk = state.review.blocks.get(item.index);
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/proofread/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        index: item.index, block_hash: blk.block_hash,
        before: item.before, after: item.after, hash: state.hash,
      }),
    });
  } catch (err) {
    setStatus('Network error. Nothing was changed.');
    return false;
  }
  if (!res.ok) {
    let detail = 'That fix no longer fits its paragraph. Skipped.';
    try { detail = (await res.json()).detail || detail; } catch (e) { /* keep default */ }
    setStatus(detail);
    removeItem(item, false);
    return true;
  }
  const data = await res.json();
  blk.block_hash = data.block_hash;
  state.hash = data.hash;
  state.blocks = data.blocks;
  state.canUndo = data.can_undo;
  removeItem(item, true);
  return true;
}

function reject(item) {
  removeItem(item, false);
}

async function acceptAll() {
  while (state.review && state.review.items.length) {
    const ok = await accept(state.review.items[0]);
    if (!ok) return;
  }
}

function closeReview() {
  if (proofRun) proofRun.cancelled = true;
  state.review = null;
  renderReviewBar();
  renderBlocks();
}

els.proofread.addEventListener('click', startProofread);
els.proofCancel.addEventListener('click', () => { if (proofRun) proofRun.cancelled = true; });
```

Integration (check exact names in editor.js; adapt, keep behavior):
- `renderBlocks()`: where a block's content is set from `block.html`, use `state.review && state.review.blocks.has(block.index) ? state.review.blocks.get(block.index).review_html : block.html`. Keep the Undo button's enabled state updated from `state.canUndo` the way `applyPost` does (call the same helper rather than `applyPost` itself if `applyPost` resets things the review needs).
- The block click handler: at its top, `if (state.review || proofRun) { setStatus('Close proofreading to edit.'); return; }`.
- Undo, Discard, post picker change, + New and Publish: call `closeReview()` first when `state.review || proofRun`.
- `els.proofread.disabled` when no prose blocks exist (update in `renderBlocks`).

- [ ] **Step 3: CSS** (editor.css):

```css
.proof-progress { display: inline-flex; align-items: center; gap: 8px; }
.proof-progress[hidden] { display: none; }
.proof-track { width: 120px; height: 6px; border-radius: 3px; background: #e5e7eb; overflow: hidden; }
.proof-fill { display: block; height: 100%; width: 0; background: #2563eb; transition: width 0.3s ease; }
.proof-text { font-size: 0.85rem; color: #555; white-space: nowrap; }
del.pr-old { color: #b42318; background: #fde8e7; text-decoration: line-through; }
ins.pr-new { color: #067647; background: #e3f6ec; text-decoration: underline; }
.pr-current { outline: 2px solid #2563eb; outline-offset: 2px; border-radius: 2px; }
.review-bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 20; display: flex;
  flex-wrap: wrap; align-items: center; justify-content: center; gap: 8px; padding: 10px 12px;
  background: #fff; border-top: 1px solid #d0d5dd; box-shadow: 0 -2px 8px rgba(0,0,0,0.06); }
.review-bar[hidden] { display: none; }
.review-bar button { min-height: 44px; min-width: 44px; padding: 0 14px; border-radius: 8px;
  border: 1px solid #d0d5dd; background: #fff; font-size: 1rem; }
.review-bar .review-accept { background: #067647; border-color: #067647; color: #fff; }
.review-bar .review-reject { color: #b42318; border-color: #f4b4ae; }
.review-count { font-variant-numeric: tabular-nums; min-width: 5.5em; text-align: center; }
.review-kind { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: #667085; }
body:has(.review-bar:not([hidden])) #blocks { padding-bottom: 120px; }
```

- [ ] **Step 4: Headless check** — `scripts/verify-proofread.py`, built on the same CDP harness pattern as `scripts/verify-edit-tap.py` (temporary uvicorn of the worktree app on a free port, throwaway `EDITOR_AUTH_DB` under ~/.cache, `EDITOR_COOKIE_SECURE=false`, a session minted like tests/conftest.py, a scratch post created and deleted, processes killed by PID). Point `EDITOR_CLAUDE_BIN` at this fake, written to a temp file and made executable:

```python
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, re, sys, time
prompt = sys.argv[sys.argv.index("-p") + 1]
time.sleep(0.6)
out = []
for idx, body in re.findall(r'<block index="(\d+)">\n(.*?)\n</block>', prompt, re.S):
    for wrong, right in (("recieve", "receive"), ("teh", "the"), ("tomorow", "tomorrow")):
        if body.count(wrong) == 1:
            out.append({"block": int(idx), "before": wrong, "after": right, "kind": "spelling"})
print(json.dumps(out))
'''
```

Scratch post: 7 paragraphs (so two batches), with typos spread across paragraphs 1, 2 and 6 and one paragraph with no typos. Assert, at 1024×1366 and 820×1180:
1. Tapping ✨ shows `#proof-progress`; its text reaches "Proofreading 7 of 7 paragraphs"; the bar's fill width grows between batches.
2. `del.pr-old` / `ins.pr-new` pairs render; the review bar shows "1 of N"; ↓ moves to 2 and the current mark is in the viewport above the bar; ↑ wraps from 1 to N.
3. Tapping a block during review doesn't open an editor and shows "Close proofreading to edit."
4. Accept → the post's source on the server (GET the post) has the fix; count drops; Undo is enabled.
5. Reject → source unchanged for that span, mark gone.
6. Accept all → every remaining fix is in the source; review bar hides; status "All suggestions reviewed."
7. Close mid-review → bar hides, normal rendering, no source change.
8. Fake claude that exits non-zero for one batch → status "Couldn't check paragraphs …" and the other batch's suggestions still show.
9. Every review-bar button is ≥ 44px tall.
Save screenshots of the review state to `~/.cache/proofread-1024.png` and `~/.cache/proofread-820.png`; Read them and fix layout if needed.

Run it: `python3 scripts/verify-proofread.py` (system python3 has websocket-client). Then the full pytest suite.

- [ ] **Step 5: CLAUDE.md** — add a short "Proofread (added 2026-10-04)" section: claude CLI at an absolute path (why), the two routes, the guardrails living in `editor/proofread.py` and being re-checked on apply, review mode locking blocks, and the verify script.

- [ ] **Step 6: Commit**

```bash
git add editor/web/index.html editor/web/editor.js editor/web/editor.css scripts/verify-proofread.py CLAUDE.md
git commit -m "Add the Proofread button, progress and inline review to the editor"
```

---

### Task 4: Deploy and a real run (controller)

- [ ] Fast-forward local `main`, run the full suite, `make editor-restart`, smoke-check `/` and that `POST /api/posts/x/proofread` is 401 signed out.
- [ ] Real Claude: run `proofread.run_claude(proofread.build_prompt(...))` + `validate` against Peter's Spruce draft's prose blocks from the live checkout (read-only; no apply), report suggestion counts and every surviving before → after, and confirm none rewords. Time a batch to sanity-check the 120 s timeout.
- [ ] Screenshot the real review state on that draft via a throwaway session (mint, use, delete) and show Peter.
- [ ] Remove the worktree and branch; ask Peter before pushing.
