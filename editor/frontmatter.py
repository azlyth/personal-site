"""Read and write the TOML frontmatter Zola puts between +++ delimiters.

Uses tomlkit rather than tomllib so that editing one field leaves the
formatting, ordering and comments of every other field untouched.
"""
from __future__ import annotations

import re

import tomlkit

DELIM = "+++"

# The closing delimiter must be a line consisting of exactly +++ (trailing
# whitespace tolerated, nothing else). A bare substring search for "\n+++"
# would also match "++++", "+++foo", or a "+++"-prefixed line that happens
# to appear inside a multi-line TOML string in the frontmatter itself or a
# fenced code block in the body -- silently truncating the frontmatter and
# corrupting the split.
_CLOSING_DELIM_RE = re.compile(r"^\+\+\+[ \t]*$", re.MULTILINE)


def split_post(text: str) -> tuple[str, str]:
    """Split a post file into (frontmatter_toml, body).

    The body is returned exactly as it appears after the closing +++
    delimiter line's own line terminator, with no normalisation: if the
    file had a blank line before the body, the returned body starts with
    "\\n"; if it didn't, it doesn't. Preserving that separator verbatim
    is what lets join_post round-trip byte-for-byte regardless of which
    style a given post uses.
    """
    if not text.startswith(DELIM):
        raise ValueError("post does not start with +++ frontmatter")

    rest = text[len(DELIM):]
    match = _CLOSING_DELIM_RE.search(rest)
    if match is None:
        raise ValueError("unterminated +++ frontmatter")

    frontmatter = rest[:match.start()].strip("\n")
    body = rest[match.end() + 1:]
    return frontmatter, body


def join_post(frontmatter_toml: str, body: str) -> str:
    fm = frontmatter_toml.rstrip("\n")
    return f"{DELIM}\n{fm}\n{DELIM}\n{body}"


def read_meta(frontmatter_toml: str) -> dict:
    return tomlkit.parse(frontmatter_toml).unwrap()


def _is_table(item) -> bool:
    return isinstance(item, (tomlkit.items.Table, tomlkit.items.AoT))


def set_meta(frontmatter_toml: str, key: str, value) -> str:
    """Set a TOP-LEVEL frontmatter key, creating it if it isn't there."""
    doc = tomlkit.parse(frontmatter_toml)
    if key in doc:
        doc[key] = value
        return tomlkit.dumps(doc)

    # A brand-new key, and TOML has no way to say "top level" after the
    # fact: everything following a `[table]` header belongs to that table,
    # so appending `draft = true` to a document that already has `[extra]`
    # writes it INSIDE extra and Zola never sees the flag. Lift the tables
    # out, add the key, put them back on the end.
    # (scripts/build-site.sh hits the same trap generating feed keys.)
    tables = [(k, doc[k]) for k in list(doc.keys()) if _is_table(doc[k])]
    for name, _ in tables:
        del doc[name]
    doc[key] = value
    for name, table in tables:
        doc[name] = table
    return tomlkit.dumps(doc)


def set_extra(frontmatter_toml: str, key: str, value) -> str:
    """Set a key inside the `[extra]` table, creating the table if needed.

    `[extra]` is Zola's namespace for fields it doesn't define itself --
    the templates read `page.extra.preview_image` from here.
    """
    doc = tomlkit.parse(frontmatter_toml)
    if "extra" not in doc:
        # No blank line before the header: tomlkit renders a new table
        # flush against the last key and ignores both `doc.add(nl())` and
        # the table's own `trivia.indent`. Cosmetic only -- not worth
        # hand-splicing the serialised output to fix.
        doc["extra"] = tomlkit.table()
    doc["extra"][key] = value
    return tomlkit.dumps(doc)


def clear_extra(frontmatter_toml: str, key: str) -> str:
    """Remove a key from `[extra]`, and the table with it if it empties.

    A no-op when either is already absent, so clearing a value that was
    never set doesn't need a caller-side guard.
    """
    doc = tomlkit.parse(frontmatter_toml)
    extra = doc.get("extra")
    if extra is None or key not in extra:
        return tomlkit.dumps(doc)
    del extra[key]
    if not extra:
        del doc["extra"]
    return tomlkit.dumps(doc)
