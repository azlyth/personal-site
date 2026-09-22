"""Per-post edit history: the snapshots Undo walks back through.

Kept deliberately dumb -- a directory of numbered copies of the whole file.
The posts are small, the depth is shallow, and a full copy means restoring
is a write rather than a patch application that could half-apply.
"""

import pytest

from editor import history


@pytest.fixture
def post(tmp_path):
    p = tmp_path / "a-post.md"
    p.write_text("version one", encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def history_root(tmp_path, monkeypatch):
    root = tmp_path / "history"
    monkeypatch.setattr(history, "HISTORY_DIR", root)
    return root


def test_no_history_for_an_untouched_post(post):
    assert history.depth(post) == 0
    assert history.can_undo(post) is False


def test_snapshot_records_the_current_contents(post):
    history.snapshot(post)
    assert history.depth(post) == 1


def test_undo_restores_the_previous_contents(post):
    history.snapshot(post)
    post.write_text("version two", encoding="utf-8")

    assert history.undo(post) is True
    assert post.read_text(encoding="utf-8") == "version one"


def test_undo_walks_back_one_step_at_a_time(post):
    history.snapshot(post)                                   # holds "one"
    post.write_text("version two", encoding="utf-8")
    history.snapshot(post)                                   # holds "two"
    post.write_text("version three", encoding="utf-8")

    history.undo(post)
    assert post.read_text(encoding="utf-8") == "version two"
    history.undo(post)
    assert post.read_text(encoding="utf-8") == "version one"


def test_undo_consumes_the_snapshot_it_used(post):
    history.snapshot(post)
    history.undo(post)
    assert history.depth(post) == 0


def test_undo_does_not_snapshot_the_state_it_replaces(post):
    """Otherwise undo would be its own inverse: the first tap would record
    the current text, and the second tap would restore it -- ping-ponging
    between two versions instead of walking backwards.
    """
    history.snapshot(post)
    post.write_text("version two", encoding="utf-8")

    history.undo(post)
    assert history.depth(post) == 0
    assert history.undo(post) is False
    assert post.read_text(encoding="utf-8") == "version one"


def test_undo_with_no_history_reports_that_and_changes_nothing(post):
    assert history.undo(post) is False
    assert post.read_text(encoding="utf-8") == "version one"


def test_history_is_capped_and_drops_the_oldest(post):
    for i in range(history.MAX_DEPTH + 5):
        post.write_text(f"version {i}", encoding="utf-8")
        history.snapshot(post)

    assert history.depth(post) == history.MAX_DEPTH
    # The newest MAX_DEPTH snapshots survived, so the first undo returns the
    # most recent one rather than something from the start of the run.
    history.undo(post)
    assert post.read_text(encoding="utf-8") == f"version {history.MAX_DEPTH + 4}"


def test_two_posts_keep_separate_histories(tmp_path):
    one = tmp_path / "one.md"
    two = tmp_path / "two.md"
    one.write_text("one a", encoding="utf-8")
    two.write_text("two a", encoding="utf-8")

    history.snapshot(one)
    one.write_text("one b", encoding="utf-8")
    two.write_text("two b", encoding="utf-8")

    assert history.depth(two) == 0
    history.undo(one)
    assert one.read_text(encoding="utf-8") == "one a"
    assert two.read_text(encoding="utf-8") == "two b"


def test_snapshots_live_outside_the_content_directory(post):
    """Zola renders every .md under content/. A snapshot parked there would
    become a ghost post on the live site.
    """
    from editor import config

    history.snapshot(post)
    for snap in history.HISTORY_DIR.rglob("*"):
        assert config.BLOG_DIR not in snap.parents


def test_a_restored_post_can_be_snapshotted_again(post):
    history.snapshot(post)
    post.write_text("version two", encoding="utf-8")
    history.undo(post)

    history.snapshot(post)
    post.write_text("version three", encoding="utf-8")
    history.undo(post)
    assert post.read_text(encoding="utf-8") == "version one"


def test_snapshot_preserves_bytes_exactly(post):
    post.write_text("trailing newline and unicode: café\n\n", encoding="utf-8")
    history.snapshot(post)
    post.write_text("clobbered", encoding="utf-8")

    history.undo(post)
    assert post.read_text(encoding="utf-8") == "trailing newline and unicode: café\n\n"
