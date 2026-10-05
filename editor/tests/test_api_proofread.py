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
