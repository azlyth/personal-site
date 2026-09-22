"""Per-post edit history -- the snapshots Undo walks back through.

Deliberately dumb: a directory of numbered copies of the whole post. Posts
are a few kilobytes and the depth is shallow, so there is nothing to gain
from storing diffs, and a full copy means restoring is a single write rather
than a patch application that could half-apply and leave a corrupt post.

Snapshots live OUTSIDE `content/` on purpose. Zola renders every `.md` under
that tree, so a snapshot parked there would surface as a ghost post on the
live site.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from editor import config

# Gitignored -- these are scratch copies of work in progress, not history
# worth publishing. `git` already holds the durable history (see the Discard
# route, which restores from HEAD).
HISTORY_DIR = config.REPO / "editor" / ".history"

# Deep enough to walk back through a bad run of edits, shallow enough that a
# post's history stays a handful of small files.
MAX_DEPTH = 25


def _dir_for(path: Path) -> Path:
    return HISTORY_DIR / path.stem


def _snapshots(path: Path) -> list[Path]:
    """Existing snapshots for `path`, oldest first.

    Sorted by the integer in the filename rather than lexically: `10.md`
    sorts before `9.md` as a string, which would make "the newest snapshot"
    wrong the moment a post passed ten edits.
    """
    directory = _dir_for(path)
    if not directory.is_dir():
        return []
    snaps = []
    for child in directory.glob("*.md"):
        try:
            snaps.append((int(child.stem), child))
        except ValueError:
            # Not one of ours -- leave it alone rather than guessing.
            continue
    return [child for _, child in sorted(snaps)]


def depth(path: Path) -> int:
    return len(_snapshots(path))


def can_undo(path: Path) -> bool:
    return depth(path) > 0


def snapshot(path: Path) -> None:
    """Record `path`'s current contents as the state one Undo goes back to.

    Called before every write. Copied with `shutil.copyfile` rather than a
    read-then-write so the bytes land verbatim -- no encoding round trip, no
    newline translation.
    """
    if not path.exists():
        return

    directory = _dir_for(path)
    directory.mkdir(parents=True, exist_ok=True)

    existing = _snapshots(path)
    next_n = int(existing[-1].stem) + 1 if existing else 0
    shutil.copyfile(path, directory / f"{next_n}.md")

    # Prune from the oldest end. Done after writing rather than before so a
    # crash mid-prune costs an old snapshot, never the new one.
    for stale in _snapshots(path)[:-MAX_DEPTH]:
        stale.unlink(missing_ok=True)


def undo(path: Path) -> bool:
    """Restore the newest snapshot over `path`. True if there was one.

    Deliberately does NOT snapshot what it replaces. If it did, undo would be
    its own inverse -- the first tap would record the current text and the
    second would restore it, ping-ponging between two versions instead of
    walking backwards through the edits.
    """
    snaps = _snapshots(path)
    if not snaps:
        return False

    newest = snaps[-1]
    shutil.copyfile(newest, path)
    newest.unlink()
    return True
