"""Draft preview: a Zola build of the working tree WITH drafts, into a
gitignored editor-owned dir. Never public/, never the live web container."""
from __future__ import annotations

import subprocess
import threading

from editor import config

PREVIEW_DIR = config.REPO / "editor" / ".preview" / "site"
SCRIPT = config.REPO / "scripts" / "build-preview.sh"

# One build at a time: two taps must not wipe each other's output dir.
_lock = threading.Lock()


def build() -> None:
    """Raises subprocess.CalledProcessError (stderr set) on a failed build."""
    with _lock:
        subprocess.run(
            [str(SCRIPT), f"{config.BASE_URL}/preview", str(PREVIEW_DIR)],
            cwd=config.REPO, check=True, capture_output=True, text=True,
        )
