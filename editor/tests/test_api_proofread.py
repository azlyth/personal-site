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


# --- pair blocks: prose and image share one block ---------------------------
# Same markup shape as tests/test_blocks.py's PAIR fixture, with a typo
# planted in the prose. The highest-risk kind for this feature because its
# source is markdown wrapped in raw HTML -- a suggestion or a fix landing
# anywhere but inside the prose would corrupt the wrapper or the image.

PAIR_SLUG = "proofread-pair-fixture"
PAIR = (
    '<div class="pair pair-right size-medium">\n'
    '<div class="pair-media">\n'
    '<img src="u.jpg" alt="a">\n'
    "</div>\n"
    '<div class="pair-text">\n'
    "\n"
    "This is teh garden.\n"
    "\n"
    "</div>\n"
    "</div>"
)
PAIR_BODY = f"Intro paragraph.\n\n{PAIR}\n\nOutro.\n"
PAIR_INDEX = 1  # Intro (0), pair (1), Outro (2) -- see parse_blocks in editor/blocks.py


@pytest.fixture(autouse=True)
def pair_post():
    path = config.BLOG_DIR / f"{PAIR_SLUG}.md"
    path.write_text(
        f'+++\ntitle = "Proofread pair fixture"\ndate = 2026-10-04\ndraft = true\n+++\n\n{PAIR_BODY}'
    )
    yield path
    path.unlink(missing_ok=True)


def pair_current():
    return client.get(f"/api/posts/{PAIR_SLUG}").json()


def test_proofread_pair_block_marks_only_the_prose(monkeypatch):
    fake(monkeypatch, [{"block": PAIR_INDEX, "before": "teh", "after": "the", "kind": "spelling"}])
    res = client.post(f"/api/posts/{PAIR_SLUG}/proofread", json={"indices": [PAIR_INDEX]})
    assert res.status_code == 200
    data = res.json()
    assert data["errors"] == []
    block = next(b for b in data["blocks"] if b["index"] == PAIR_INDEX)
    assert [s["after"] for s in block["suggestions"]] == ["the"]
    html_out = block["review_html"]
    # The wrapper and the image are still there -- only the prose line
    # carries the marks.
    assert 'class="pair-media"' in html_out
    assert '<img src="u.jpg"' in html_out
    assert 'class="pr-old"' in html_out and 'class="pr-new"' in html_out
    assert '<del class="pr-old"' in html_out.split('pair-text')[-1]


def test_proofread_pair_drops_suggestion_inside_the_html(monkeypatch):
    fake(monkeypatch, [
        {"block": PAIR_INDEX, "before": "teh", "after": "the", "kind": "spelling"},
        # "before" sits inside the <img> tag's src attribute -- a real fix
        # here would corrupt the markup, so it must not survive validate().
        {"block": PAIR_INDEX, "before": "u.jpg", "after": "v.jpg", "kind": "spelling"},
    ])
    res = client.post(f"/api/posts/{PAIR_SLUG}/proofread", json={"indices": [PAIR_INDEX]})
    data = res.json()
    block = next(b for b in data["blocks"] if b["index"] == PAIR_INDEX)
    assert [s["before"] for s in block["suggestions"]] == ["teh"]
    assert "v.jpg" not in block["review_html"]


def test_apply_on_pair_changes_only_the_prose():
    p = pair_current()
    before_source = p["blocks"][PAIR_INDEX]["source"]
    res = client.post(f"/api/posts/{PAIR_SLUG}/proofread/apply", json={
        "index": PAIR_INDEX, "before": "teh", "after": "the",
        "block_hash": proofread.block_hash(before_source),
        "hash": p["hash"],
    })
    assert res.status_code == 200
    data = res.json()
    after_source = data["blocks"][PAIR_INDEX]["source"]
    assert after_source != before_source
    assert data["block_hash"] == proofread.block_hash(after_source)

    # Only the typo span differs -- wrapper and media lines are byte-for-byte
    # the same before and after.
    before_lines = before_source.splitlines()
    after_lines = after_source.splitlines()
    assert len(before_lines) == len(after_lines)
    changed = [i for i, (a, b) in enumerate(zip(before_lines, after_lines)) if a != b]
    assert changed == [6]  # "This is teh garden." -> "This is the garden."
    for i in range(len(before_lines)):
        if i not in changed:
            assert before_lines[i] == after_lines[i]
    assert '<div class="pair-media">' in after_source
    assert '<img src="u.jpg" alt="a">' in after_source

    # Still one pair block with its image intact.
    from editor.blocks import parse_blocks
    from editor import pairs

    blocks = parse_blocks(f"Intro paragraph.\n\n{after_source}\n\nOutro.\n")
    assert [b.kind for b in blocks] == ["paragraph", "pair", "paragraph"]
    parsed = pairs.parse_pair(blocks[1].kind, blocks[1].source)
    assert parsed is not None
    assert "This is the garden." in parsed["text"]
    media = parse_blocks(parsed["media_source"])
    assert len(media) == 1
    assert '<img src="u.jpg" alt="a">' in media[0].source
