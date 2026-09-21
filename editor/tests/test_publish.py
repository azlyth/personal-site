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
