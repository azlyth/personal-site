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
    res = send("# Import Fixture Gate\n\nBody.\n")
    assert res.status_code == 201, res.text
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
