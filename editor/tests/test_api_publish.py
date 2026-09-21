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
