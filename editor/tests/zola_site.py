"""Build the real templates with Zola, against a disposable copy of the site.

Shared by the tests that assert on rendered output. The build always runs
on a COPY in a temp dir, never on the working tree: `scripts/build-site.sh`
and the editor's Publish both render the working tree, so a fixture written
into the real `content/` could be published by a Publish that happens to
run at the same time.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import pytest

REPO = Path(__file__).resolve().parents[2]
BASE_URL = "https://cloudy.nyc"
ZOLA_IMAGE = "personal-site-zola"


def build_copy(prepare: Callable[[Path], None] | None = None) -> dict[str, str]:
    """Copy the site, let `prepare(root)` edit the copy, build it.

    Returns {output path relative to the build: text} for every .html and
    .xml file Zola wrote.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker is needed to run Zola")

    with tempfile.TemporaryDirectory(prefix="zola-site-") as tmp:
        root = Path(tmp)
        shutil.copy(REPO / "config.toml", root / "config.toml")
        for name in ("templates", "static", "content"):
            shutil.copytree(REPO / name, root / name)
        if prepare is not None:
            prepare(root)

        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "-e", "HOME=/tmp",
                "-v", f"{root}:/project",
                "-w", "/project",
                "--entrypoint", "zola",
                ZOLA_IMAGE,
                "build", "--base-url", BASE_URL,
                "--output-dir", "/project/out", "--force",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"zola build failed:\n{result.stdout}\n{result.stderr}")

        out = root / "out"
        return {
            str(path.relative_to(out)): path.read_text()
            for path in out.rglob("*")
            if path.is_file() and path.suffix in (".html", ".xml")
        }
