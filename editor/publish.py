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


def _has_unpushed_commits(repo: Path, pathspec: str | None = None) -> bool:
    """True if HEAD has commits the upstream (or origin/main) doesn't.

    Used so a retried publish after a failed push doesn't report "nothing to
    publish" just because there's nothing new to *commit* -- the previous
    commit is still sitting there unpushed.

    `pathspec`, when given, scopes the check to commits that touch that path
    (e.g. `"content/blog/"`). Without it, this repo's constant unrelated
    in-progress code commits would count as "unpushed work" forever, drowning
    out the one case this exists to catch: a blog commit whose push or
    publish failed. Scoping also means a later, unrelated commit stacked on
    top of a stuck blog commit can't hide it -- `rev-list` still walks the
    whole range and counts any commit in it that touched the pathspec.
    """
    for upstream in ("@{upstream}", "origin/main"):
        try:
            args = ["rev-list", f"{upstream}..HEAD", "--count"]
            if pathspec:
                args += ["--", pathspec]
            out = _git(repo, *args)
        except subprocess.CalledProcessError:
            continue
        return out not in ("", "0")
    return False


def publish(
    repo: Path, paths: list[str], message: str, pathspec: str | None = None
) -> PublishResult:
    try:
        sha = commit_paths(repo, paths, message)
    except subprocess.CalledProcessError as exc:
        return PublishResult(
            False, None, False, False,
            f"commit failed: {exc.stderr or exc}",
        )

    # Whether *this call* created a commit. Once sha is backfilled below
    # (the retry path, picking up a pre-existing unpushed commit) it stays
    # populated for push()/publish_site() to use, but `committed` must not
    # claim this invocation did something it didn't.
    did_commit = sha is not None

    if sha is None:
        if not _has_unpushed_commits(repo, pathspec):
            return PublishResult(False, None, False, False, "nothing to publish")
        # A previous publish committed but failed to push (or publish). Pick
        # up where it left off rather than reporting "nothing to publish"
        # while a commit sits unpushed and the live site is stale.
        sha = _git(repo, "rev-parse", "HEAD")

    try:
        push(repo)
    except subprocess.CalledProcessError as exc:
        return PublishResult(
            did_commit, sha, False, False,
            f"committed {sha[:8]} but push failed: {exc.stderr or exc}",
        )

    try:
        publish_site(repo)
    except subprocess.CalledProcessError as exc:
        return PublishResult(
            did_commit, sha, True, False,
            f"pushed {sha[:8]} but publishing to S3 failed "
            f"(the live site still shows the previous version): {exc.stderr or exc}",
        )

    return PublishResult(did_commit, sha, True, True, f"published {sha[:8]}")
