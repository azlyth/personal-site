"""Read and write the TOML frontmatter Zola puts between +++ delimiters.

Uses tomlkit rather than tomllib so that editing one field leaves the
formatting, ordering and comments of every other field untouched.
"""
from __future__ import annotations

import tomlkit

DELIM = "+++"


def split_post(text: str) -> tuple[str, str]:
    """Split a post file into (frontmatter_toml, body)."""
    if not text.startswith(DELIM):
        raise ValueError("post does not start with +++ frontmatter")

    rest = text[len(DELIM):]
    end = rest.find(f"\n{DELIM}")
    if end == -1:
        raise ValueError("unterminated +++ frontmatter")

    frontmatter = rest[:end].lstrip("\n")
    body = rest[end + len(DELIM) + 1:].lstrip("\n")
    return frontmatter, body


def join_post(frontmatter_toml: str, body: str) -> str:
    fm = frontmatter_toml.rstrip("\n")
    return f"{DELIM}\n{fm}\n{DELIM}\n\n{body}"


def read_meta(frontmatter_toml: str) -> dict:
    return tomlkit.parse(frontmatter_toml).unwrap()


def set_meta(frontmatter_toml: str, key: str, value) -> str:
    doc = tomlkit.parse(frontmatter_toml)
    doc[key] = value
    return tomlkit.dumps(doc)
