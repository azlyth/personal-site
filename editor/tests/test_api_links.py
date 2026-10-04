"""A post's links: its filename is the primary URL, `aliases` redirect.

Every test runs against a throwaway git repo (config.REPO/BLOG_DIR pointed
at it), so renames and staged deletions never touch the real index.
"""

import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import app as app_module
from editor import config, history
from editor.app import app
from editor.frontmatter import read_meta, split_post
from editor.publish import commit_paths

client = TestClient(app)


def post(title, *, draft=False, aliases=()):
    lines = [f'title = "{title}"', "date = 2026-01-01"]
    if draft:
        lines.append("draft = true")
    if aliases:
        quoted = ", ".join(f'"{a}"' for a in aliases)
        lines.append(f"aliases = [{quoted}]")
    return "+++\n" + "\n".join(lines) + "\n+++\n\nBody.\n"


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def site(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "content" / "blog").mkdir(parents=True)
    _git(repo, "init", "--quiet", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    monkeypatch.setattr(config, "REPO", repo)
    monkeypatch.setattr(config, "BLOG_DIR", repo / "content" / "blog")
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    return repo


def write(repo, slug, text, *, commit=False):
    path = repo / "content" / "blog" / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    if commit:
        _git(repo, "add", "--", str(path))
        _git(repo, "commit", "--quiet", "-m", f"add {slug}")
    return path


def aliases_on_disk(path):
    return read_meta(split_post(path.read_text(encoding="utf-8"))[0]).get("aliases")


def load(slug):
    res = client.get(f"/api/posts/{slug}")
    assert res.status_code == 200
    return res.json()


# --- payload ---------------------------------------------------------------

def test_payload_exposes_aliases_as_slugs(site):
    write(site, "primary", post("P", aliases=["/blog/old-one/", "/blog/old-two/"]))
    assert load("primary")["meta"]["aliases"] == ["old-one", "old-two"]


def test_payload_has_an_empty_list_without_aliases(site):
    write(site, "primary", post("P"))
    assert load("primary")["meta"]["aliases"] == []


# --- add -------------------------------------------------------------------

def test_add_link_writes_a_canonical_alias(site):
    path = write(site, "primary", post("P"))
    data = load("primary")
    res = client.post("/api/posts/primary/links",
                      json={"slug": "  Old Name!! ", "hash": data["hash"]})
    assert res.status_code == 200
    assert res.json()["meta"]["aliases"] == ["old-name"]
    assert aliases_on_disk(path) == ["/blog/old-name/"]


def test_add_link_lands_at_top_level_even_with_an_extra_table(site):
    text = post("P").replace(
        "date = 2026-01-01", 'date = 2026-01-01\n[extra]\npreview_image = "x"'
    )
    path = write(site, "primary", text)
    data = load("primary")
    client.post("/api/posts/primary/links", json={"slug": "old", "hash": data["hash"]})
    meta = read_meta(split_post(path.read_text())[0])
    assert meta["aliases"] == ["/blog/old/"]
    assert "aliases" not in meta["extra"]


def test_add_link_is_undoable(site):
    path = write(site, "primary", post("P"))
    data = load("primary")
    added = client.post("/api/posts/primary/links",
                        json={"slug": "old", "hash": data["hash"]}).json()
    assert added["can_undo"] is True
    undone = client.post("/api/posts/primary/undo", json={"hash": added["hash"]}).json()
    assert undone["meta"]["aliases"] == []
    assert aliases_on_disk(path) is None


def test_add_link_refuses_an_empty_slug(site):
    write(site, "primary", post("P"))
    data = load("primary")
    res = client.post("/api/posts/primary/links", json={"slug": "!!!", "hash": data["hash"]})
    assert res.status_code == 400


def test_add_link_refuses_another_posts_filename(site):
    write(site, "primary", post("P"))
    write(site, "taken", post("T"))
    data = load("primary")
    res = client.post("/api/posts/primary/links", json={"slug": "taken", "hash": data["hash"]})
    assert res.status_code == 409
    assert "taken" in res.json()["detail"]


def test_add_link_refuses_another_posts_alias(site):
    write(site, "primary", post("P"))
    write(site, "other", post("O", aliases=["/blog/claimed/"]))
    data = load("primary")
    res = client.post("/api/posts/primary/links", json={"slug": "claimed", "hash": data["hash"]})
    assert res.status_code == 409
    assert "other" in res.json()["detail"]


def test_add_link_refuses_its_own_primary(site):
    write(site, "primary", post("P"))
    data = load("primary")
    res = client.post("/api/posts/primary/links", json={"slug": "primary", "hash": data["hash"]})
    assert res.status_code == 409


def test_add_link_refuses_a_stale_hash(site):
    write(site, "primary", post("P"))
    res = client.post("/api/posts/primary/links", json={"slug": "old", "hash": "stale"})
    assert res.status_code == 409


# --- remove ----------------------------------------------------------------

def test_remove_link_drops_one_alias(site):
    path = write(site, "primary", post("P", aliases=["/blog/a/", "/blog/b/"]))
    data = load("primary")
    res = client.request("DELETE", "/api/posts/primary/links/a", json={"hash": data["hash"]})
    assert res.status_code == 200
    assert res.json()["meta"]["aliases"] == ["b"]
    assert aliases_on_disk(path) == ["/blog/b/"]


def test_removing_the_last_alias_removes_the_key(site):
    path = write(site, "primary", post("P", aliases=["/blog/a/"]))
    data = load("primary")
    client.request("DELETE", "/api/posts/primary/links/a", json={"hash": data["hash"]})
    assert aliases_on_disk(path) is None
    assert "aliases" not in path.read_text()


def test_remove_link_refuses_the_primary(site):
    write(site, "primary", post("P", aliases=["/blog/a/"]))
    data = load("primary")
    res = client.request("DELETE", "/api/posts/primary/links/primary", json={"hash": data["hash"]})
    assert res.status_code == 400


def test_remove_link_404s_an_unknown_link(site):
    write(site, "primary", post("P"))
    data = load("primary")
    res = client.request("DELETE", "/api/posts/primary/links/nope", json={"hash": data["hash"]})
    assert res.status_code == 404


def test_remove_link_keeps_entries_it_does_not_manage(site):
    # A hand-written alias outside /blog/ isn't one the UI shows, so it
    # can't be removed from here -- and a removal elsewhere mustn't drop it.
    path = write(site, "primary", post("P", aliases=["/elsewhere.html", "/blog/a/"]))
    data = load("primary")
    assert data["meta"]["aliases"] == ["a"]
    client.request("DELETE", "/api/posts/primary/links/a", json={"hash": data["hash"]})
    assert aliases_on_disk(path) == ["/elsewhere.html"]


# --- make primary / rename -------------------------------------------------

def test_make_primary_swaps_the_filename_and_the_alias(site):
    write(site, "first", post("P", aliases=["/blog/second/", "/blog/third/"]), commit=True)
    data = load("first")
    res = client.post("/api/posts/first/links/second/primary", json={"hash": data["hash"]})
    assert res.status_code == 200
    out = res.json()
    assert out["slug"] == "second"
    assert out["url"].endswith("/blog/second/")
    assert sorted(out["meta"]["aliases"]) == ["first", "third"]

    blog = site / "content" / "blog"
    assert not (blog / "first.md").exists()
    assert sorted(aliases_on_disk(blog / "second.md")) == ["/blog/first/", "/blog/third/"]


def test_make_primary_refuses_a_slug_that_is_not_one_of_its_links(site):
    write(site, "first", post("P"))
    write(site, "other", post("O"))
    data = load("first")
    res = client.post("/api/posts/first/links/other/primary", json={"hash": data["hash"]})
    assert res.status_code == 404
    assert (site / "content" / "blog" / "other.md").exists()


def test_make_primary_refuses_a_stale_hash(site):
    write(site, "first", post("P", aliases=["/blog/second/"]))
    res = client.post("/api/posts/first/links/second/primary", json={"hash": "stale"})
    assert res.status_code == 409


def test_make_primary_starts_a_fresh_undo_history(site):
    # Undo restores whole-file snapshots, and every snapshot taken before
    # the swap names the OLD primary nowhere in its aliases -- restoring one
    # at the new filename would 404 the old URL and alias the post to
    # itself. So the swap is the start of a new history, not a step in it.
    write(site, "first", post("P", aliases=["/blog/second/"]))
    data = load("first")
    edited = client.put("/api/posts/first/meta", json={"title": "Q", "hash": data["hash"]}).json()
    assert edited["can_undo"] is True
    # A stale history left under the target name by some earlier post must
    # not be inherited either.
    stale = history.HISTORY_DIR / "second"
    stale.mkdir(parents=True)
    (stale / "0.md").write_text("someone else's post\n")

    out = client.post("/api/posts/first/links/second/primary",
                      json={"hash": edited["hash"]}).json()
    assert out["can_undo"] is False
    assert not (history.HISTORY_DIR / "first").exists()


def test_rename_keeps_the_old_slug_as_a_redirect(site):
    write(site, "first", post("P"), commit=True)
    data = load("first")
    res = client.post("/api/posts/first/rename", json={"new_slug": "Brand New", "hash": data["hash"]})
    assert res.status_code == 200
    out = res.json()
    assert out["slug"] == "brand-new"
    assert out["meta"]["aliases"] == ["first"]
    assert "warning" not in out
    assert aliases_on_disk(site / "content" / "blog" / "brand-new.md") == ["/blog/first/"]


def test_rename_refuses_another_posts_alias(site):
    write(site, "first", post("P"))
    write(site, "other", post("O", aliases=["/blog/claimed/"]))
    data = load("first")
    res = client.post("/api/posts/first/rename", json={"new_slug": "claimed", "hash": data["hash"]})
    assert res.status_code == 409


def test_rename_to_its_own_alias_is_make_primary(site):
    write(site, "first", post("P", aliases=["/blog/second/"]))
    data = load("first")
    out = client.post("/api/posts/first/rename",
                      json={"new_slug": "second", "hash": data["hash"]}).json()
    assert out["slug"] == "second"
    assert out["meta"]["aliases"] == ["first"]


def test_rename_of_never_committed_post_works(site):
    write(site, "fresh", post("P", draft=True))
    data = load("fresh")
    res = client.post("/api/posts/fresh/rename", json={"new_slug": "fresher", "hash": data["hash"]})
    assert res.status_code == 200
    assert (site / "content" / "blog" / "fresher.md").exists()


def test_a_renamed_post_publishes(site):
    # The Publish path end to end, minus the push: _blog_paths reports the
    # staged rename as two paths, the old one no longer exists anywhere but
    # HEAD, and commit_paths has to cope with that rather than failing on
    # `git add` of a path that matches nothing.
    write(site, "first", post("P"), commit=True)
    data = load("first")
    client.post("/api/posts/first/rename", json={"new_slug": "second", "hash": data["hash"]})

    paths = app_module._blog_paths()
    assert sorted(paths) == ["content/blog/first.md", "content/blog/second.md"]
    assert commit_paths(site, paths, "rename")
    tree = _git(site, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert tree == ["content/blog/second.md"]
    assert "/blog/first/" in _git(site, "show", "HEAD:content/blog/second.md")


# --- new posts don't collide with an alias -------------------------------

def test_new_post_skips_a_slug_taken_by_an_alias(site):
    write(site, "other", post("O", aliases=["/blog/hello/"]))
    created = client.post("/api/posts", json={"title": "Hello"}).json()
    assert created["slug"] == "hello-2"


# --- review fixes ----------------------------------------------------------

def test_make_primary_refuses_another_posts_filename(site):
    # A hand-written alias that collides with a real post must not rename
    # this post on top of it.
    write(site, "first", post("P", aliases=["/blog/other/"]))
    write(site, "other", post("O"))
    data = load("first")
    res = client.post("/api/posts/first/links/other/primary", json={"hash": data["hash"]})
    assert res.status_code == 409
    assert "other" in res.json()["detail"]
    assert (site / "content" / "blog" / "first.md").exists()
    assert (site / "content" / "blog" / "other.md").read_text() == post("O")


def test_make_primary_refuses_an_alias_another_post_also_holds(site):
    write(site, "first", post("P", aliases=["/blog/shared/"]))
    write(site, "zeta", post("Z", aliases=["/blog/shared/"]))
    data = load("zeta")
    res = client.post("/api/posts/zeta/links/shared/primary", json={"hash": data["hash"]})
    assert res.status_code == 409


def _index_state(repo):
    return _git(repo, "ls-files", "-s"), _git(repo, "status", "--porcelain")


def test_make_primary_rolls_back_when_git_mv_fails(site, monkeypatch):
    path = write(site, "first", post("P", aliases=["/blog/second/"]), commit=True)
    path.write_text(post("P edited", aliases=["/blog/second/"]))  # unstaged edit
    before_bytes, before_index = path.read_bytes(), _index_state(site)
    data = load("first")

    real_run = subprocess.run

    def failing_mv(cmd, *args, **kwargs):
        if cmd[:1] == ["git"] and "mv" in cmd:
            raise subprocess.CalledProcessError(128, cmd, stderr="boom")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(app_module.subprocess, "run", failing_mv)
    res = client.post("/api/posts/first/links/second/primary", json={"hash": data["hash"]})
    monkeypatch.setattr(app_module.subprocess, "run", real_run)

    assert res.status_code == 500
    assert path.read_bytes() == before_bytes
    assert not (site / "content" / "blog" / "second.md").exists()
    assert _index_state(site) == before_index


def test_make_primary_rolls_back_when_the_write_fails(site, monkeypatch):
    path = write(site, "first", post("P", aliases=["/blog/second/"]))  # untracked
    before_bytes, before_index = path.read_bytes(), _index_state(site)
    data = load("first")

    def failing_write(target, text):
        raise OSError("disk full")

    monkeypatch.setattr(app_module, "_atomic_write_text", failing_write)
    res = client.post("/api/posts/first/links/second/primary", json={"hash": data["hash"]})

    assert res.status_code == 500
    assert path.read_bytes() == before_bytes
    assert not (site / "content" / "blog" / "second.md").exists()
    assert _index_state(site) == before_index


def test_make_primary_never_leaves_a_self_alias_on_disk(site):
    write(site, "first", post("P", aliases=["/blog/second/"]))
    data = load("first")
    client.post("/api/posts/first/links/second/primary", json={"hash": data["hash"]})
    assert aliases_on_disk(site / "content" / "blog" / "second.md") == ["/blog/first/"]
