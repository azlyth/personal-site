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


def test_raises_when_hostname_is_tunnelled(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(EXPOSED)
    with pytest.raises(RuntimeError, match="publicly routed"):
        assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_passes_when_hostname_is_absent(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(SAFE)
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)


def test_passes_when_config_is_missing(tmp_path):
    # A missing tunnel config means no tunnel, which is safe.
    assert_not_publicly_routed("edit.cloudy.nyc", tmp_path / "nope.yml")


def test_substring_hostname_does_not_false_positive(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("ingress:\n  - hostname: noedit.cloudy.nyc\n")
    assert_not_publicly_routed("edit.cloudy.nyc", cfg)
