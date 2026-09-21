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


@pytest.fixture
def repo_with_remote(tmp_path: Path) -> Path:
    """A repo with a real (local, bare) origin and upstream tracking set up.

    Lets tests exercise the real `git rev-list @{upstream}..HEAD` check
    without touching any actual network remote -- the "origin" here is just
    another directory under tmp_path.
    """
    work = tmp_path / "work"
    work.mkdir()
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True
    )
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "content").mkdir()
    (work / "content" / "a.md").write_text("original\n")
    _git(work, "add", "content/a.md")
    _git(work, "commit", "-qm", "init")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "main")
    return work


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


def test_publish_retries_unpushed_commit_after_failed_push(
    repo_with_remote: Path, monkeypatch
):
    # A failed push must not make the *next* publish() lie: the earlier
    # commit is still sitting there unpushed, so retrying must push and
    # publish it rather than reporting "nothing to publish".
    repo = repo_with_remote
    (repo / "content" / "a.md").write_text("edited\n")

    def boom(_repo):
        raise subprocess.CalledProcessError(1, ["git", "push"], stderr="rejected")

    monkeypatch.setattr("editor.publish.push", boom)
    monkeypatch.setattr("editor.publish.publish_site", lambda _repo: None)

    first = publish(repo, ["content/a.md"], "edit a")
    assert first.committed is True
    assert first.pushed is False

    # Retry: nothing new to *commit* (the edit was already committed above),
    # but the commit is still unpushed.
    monkeypatch.setattr("editor.publish.push", lambda _repo: None)

    second = publish(repo, ["content/a.md"], "edit a")

    assert second.sha == first.sha
    assert second.pushed is True
    assert second.published is True
    assert second.message != "nothing to publish"
    # This call didn't create a commit -- it picked up one that already
    # existed -- so `committed` must say so, even though the publish as a
    # whole succeeded.
    assert second.committed is False


def test_publish_reports_nothing_to_publish_when_truly_clean(repo_with_remote: Path):
    # Nothing changed and the fixture already pushed the initial commit:
    # there is genuinely nothing outstanding.
    result = publish(repo_with_remote, ["content/a.md"], "no-op")

    assert result.message == "nothing to publish"
    assert result.committed is False
    assert result.pushed is False
    assert result.published is False


def test_publish_reports_nothing_to_publish_with_no_remote_configured(repo: Path):
    # No edits, and no remote at all (the plain `repo` fixture). The
    # unpushed-commit check must degrade gracefully rather than erroring.
    result = publish(repo, ["content/a.md"], "no-op")

    assert result.message == "nothing to publish"
    assert result.committed is False


def test_publish_reports_failed_commit(repo: Path):
    # A pathspec that matches nothing makes `git add` fail; that must come
    # back as a PublishResult, not an uncaught CalledProcessError -- the
    # HTTP endpoint calling this can't turn an exception into a clean 4xx.
    result = publish(repo, ["content/does-not-exist.md"], "ghost")

    assert result.committed is False
    assert result.sha is None
    assert result.pushed is False
    assert result.published is False
    assert "commit" in result.message.lower()


def test_commit_stages_dash_prefixed_filename_literally(repo: Path):
    # A filename that looks like a flag must be treated as a literal path,
    # not parsed as an option -- `git add --` already guarantees this, this
    # proves it.
    (repo / "-f.md").write_text("dash file\n")
    (repo / "unrelated.txt").write_text("work in progress\n")

    sha = commit_paths(repo, ["-f.md"], "add dash file")

    assert sha
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert files == ["-f.md"]
    assert "unrelated.txt" in _git(repo, "status", "--porcelain")


def test_commit_stages_filename_with_spaces_literally(repo: Path):
    (repo / "content" / "my post file.md").write_text("spaced\n")
    (repo / "unrelated.txt").write_text("work in progress\n")

    sha = commit_paths(repo, ["content/my post file.md"], "add spaced file")

    assert sha
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert files == ["content/my post file.md"]
    assert "unrelated.txt" in _git(repo, "status", "--porcelain")


def test_commit_stages_literal_asterisk_filename(repo: Path):
    # A sibling file that WOULD be matched if "*" were treated as a glob
    # pattern -- it must be left alone; only the literal path is staged.
    (repo / "content" / "star*.md").write_text("literal star\n")
    (repo / "content" / "star2.md").write_text("decoy\n")
    (repo / "unrelated.txt").write_text("work in progress\n")

    sha = commit_paths(repo, ["content/star*.md"], "add literal star")

    assert sha
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert files == ["content/star*.md"]
    status = _git(repo, "status", "--porcelain")
    assert "unrelated.txt" in status
    assert "star2.md" in status  # still untracked, not swept into the commit
