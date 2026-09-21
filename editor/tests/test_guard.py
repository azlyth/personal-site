import pytest

from editor.guard import assert_not_publicly_routed

EXPOSED = """
ingress:
  - hostname: cloudy.nyc
    service: https://192.168.1.185:443
  - hostname: edit.cloudy.nyc
    service: https://192.168.1.185:443
  - service: http_status:404
"""

SAFE = """
ingress:
  - hostname: cloudy.nyc
    service: https://192.168.1.185:443
  - service: http_status:404
"""


def _http_routing_dir(tmp_path):
    """A directory shaped like the real sibling repo: <root>/cloudflared/config.yml."""
    repo_dir = tmp_path / "http-routing"
    (repo_dir / "cloudflared").mkdir(parents=True)
    return repo_dir / "cloudflared" / "config.yml"


def test_raises_when_hostname_is_tunnelled(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text(EXPOSED)
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_passes_when_hostname_is_absent(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text(SAFE)
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_passes_when_config_is_missing_but_directory_exists(tmp_path):
    # The sibling repo directory is present but has no cloudflared/config.yml
    # at all — that genuinely means no tunnel is configured, which is safe.
    cfg = _http_routing_dir(tmp_path)
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_raises_when_http_routing_directory_itself_is_missing(tmp_path):
    # config.CLOUDFLARED_CONFIG is a hardcoded sibling path. If the whole
    # http-routing directory is absent (moved repo, typo, bad checkout), the
    # path assumption this guard relies on is broken and we cannot verify
    # anything — that must fail loudly, not read as "safe".
    cfg = tmp_path / "http-routing" / "cloudflared" / "config.yml"
    with pytest.raises(RuntimeError):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_substring_hostname_does_not_false_positive(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("ingress:\n  - hostname: noedit.cloudy.nyc\n")
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_quoted_hostname_still_matches(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text(
        'ingress:\n  - hostname: "edit.cloudy.nyc"\n    service: https://x\n'
    )
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_trailing_comment_still_matches(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text(
        "ingress:\n  - hostname: edit.cloudy.nyc  # temporary\n    service: https://x\n"
    )
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_flow_mapping_still_matches(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("ingress:\n  - {hostname: edit.cloudy.nyc, service: https://x}\n")
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_no_ingress_key_is_safe(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("tunnel: abc123\nwarp-routing:\n  enabled: false\n")
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_ingress_entry_without_hostname_does_not_crash(tmp_path):
    # The real config's catch-all entry looks exactly like this.
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("ingress:\n  - service: http_status:404\n")
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_malformed_yaml_raises(tmp_path):
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("ingress: [unclosed\n  - hostname: edit.cloudy.nyc\n")
    with pytest.raises(RuntimeError):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_case_insensitive_hostname_still_matches(tmp_path):
    # DNS and cloudflared routing are case-insensitive; a differently-cased
    # ingress entry genuinely publishes the host.
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("ingress:\n  - hostname: Edit.Cloudy.NYC\n    service: https://x\n")
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_trailing_dot_hostname_still_matches(tmp_path):
    # The fully-qualified form (trailing dot) routes identically to the
    # bare form.
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("ingress:\n  - hostname: edit.cloudy.nyc.\n    service: https://x\n")
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_wildcard_hostname_covers_our_host(tmp_path):
    # A wildcard ingress entry would route edit.cloudy.nyc even though it
    # never string-matches it literally.
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text('ingress:\n  - hostname: "*.cloudy.nyc"\n    service: https://x\n')
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_bare_wildcard_hostname_covers_everything(tmp_path):
    # A bare "*" ingress entry (match-everything) covers our host too, even
    # though it has no literal dot for the "*.suffix" branch to key on.
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text('ingress:\n  - hostname: "*"\n    service: https://x\n')
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_top_level_list_document_raises_cleanly(tmp_path):
    # A config whose top-level YAML document is a list (not a mapping) must
    # raise a clear RuntimeError, not an uncaught AttributeError from
    # data.get(...).
    cfg = _http_routing_dir(tmp_path)
    cfg.write_text("- hostname: edit.cloudy.nyc\n- service: http_status:404\n")
    with pytest.raises(RuntimeError):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)
