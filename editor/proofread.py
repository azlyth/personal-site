"""AI proofreading: spelling, grammar and punctuation only.

Claude proposes; this module disposes. Every suggestion is checked against
the block's exact source before Peter sees it, and again when he accepts it,
so a rewording can't arrive dressed as a fix and a fix can't land on text
that has moved. Pure apart from run_claude.
"""
from __future__ import annotations

import difflib
import hashlib
import html
import json
import os
import re
import subprocess
import tempfile

from editor import config
from editor.blocks import _md, parse_blocks

PROSE_KINDS = frozenset({"paragraph", "heading", "list", "blockquote", "pair"})
KINDS = frozenset({"spelling", "grammar", "punctuation"})
MAX_BEFORE = 80
MAX_WORD_EDITS = 2
# A spelling fix must still look like the word it fixes ("teh"->"the" is
# 0.67); a swap to a different word ("good"->"great") is a rewording.
MIN_SPELLING_SIMILARITY = 0.6
_MARKUP = set("[]()*_`#<>|")
_PROTECTED = re.compile(
    r"`[^`\n]*`"            # inline code
    r"|https?://[^\s)>\]]+"  # bare or linked URLs
    r"|\]\([^)\n]*\)"        # link destinations
    r"|<[^>\n]+>"            # HTML tags
    r"|!\[[^\]\n]*\]"         # inline image alt text
    r"|www\.\S+"             # bare www domains
)

PROMPT = """You are a proofreader for a personal blog. Fix ONLY real spelling, grammar and punctuation mistakes.

Do not rephrase, reword, restyle or tighten anything. Keep the author's wording, voice, sentence fragments, informal phrasing, names and capitalization choices. Do not touch markdown syntax, links, URLs, HTML or code. If a sentence is correct, leave it alone. Return nothing rather than something doubtful.

Return ONLY a JSON array and no other text:
[{"block": <block index>, "before": "<exact text from that block>", "after": "<corrected text>", "kind": "spelling" | "grammar" | "punctuation"}]
"before" must be copied character for character from the block, and be the shortest span (usually one word, at most a few) that appears exactly once in that block. Return [] if there are no mistakes.

"""


def block_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_prompt(blocks) -> str:
    parts = [f'<block index="{b.index}">\n{b.source}\n</block>' for b in blocks]
    return PROMPT + "\n\n".join(parts) + "\n"


# Belt and braces with `--tools ""`: denied by name too, so a future CLI
# default can't quietly hand the proofreader a shell. Same list as split's
# receipt reader (split/app/services/parse.py).
DENIED_TOOLS = "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Agent,Task"


def _child_env() -> dict:
    """The smallest environment the CLI runs in: no editor secrets."""
    env = {"HOME": os.environ.get("HOME", "/home/peter"),
           "PATH": os.environ.get("PATH", ""),
           "LANG": "C.UTF-8",
           "TERM": "dumb"}
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.environ["CLAUDE_CONFIG_DIR"]
    return env


def run_claude(prompt: str, timeout_s: int = 120) -> str:
    """Post text is untrusted input to the model, so it runs boxed in: an
    empty throwaway cwd (not the repo -- no project CLAUDE.md, nothing to
    read), no tools, no saved session, the prompt on stdin, and a minimal
    environment. Not --bare: that skips the OAuth login."""
    cmd = [config.claude_bin(), "-p", "--output-format", "text",
           "--tools", "", "--disallowedTools", DENIED_TOOLS,
           "--no-session-persistence"]
    model = config.proofread_model()
    if model:
        cmd += ["--model", model]
    with tempfile.TemporaryDirectory(prefix="proofread-") as cwd:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              timeout=timeout_s, check=True, cwd=cwd, env=_child_env())
    return proc.stdout


def _fenced_content(text: str) -> str | None:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return m.group(1).strip() if m else None


def parse_response(raw: str) -> list:
    text = raw.strip()
    # Try the whole response, then just the fenced block, before falling
    # back to scanning -- a stray "[...]" in surrounding prose (e.g. a
    # citation like "[1]") must not be mistaken for the real array.
    for candidate in (text, _fenced_content(text)):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, list):
            return data
    scan_text = _fenced_content(text) or text
    decoder = json.JSONDecoder()
    for i, ch in enumerate(scan_text):
        if ch != "[":
            continue
        try:
            data, _ = decoder.raw_decode(scan_text, i)
        except ValueError:
            continue
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            return data
    raise ValueError("no JSON array in the response")


def _word_edits(a: str, b: str) -> int:
    x, y = a.split(), b.split()
    prev = list(range(len(y) + 1))
    for i, xi in enumerate(x, 1):
        cur = [i]
        for j, yj in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (xi != yj)))
        prev = cur
    return prev[-1]


def _block_kinds(source: str) -> list[str]:
    return [b.kind for b in parse_blocks(source)]


def _problem(source: str, before, after, kind, block_kind=None) -> str | None:
    """Why this fix can't be offered, or None if it can."""
    if not isinstance(before, str) or not isinstance(after, str) or kind not in KINDS:
        return "malformed suggestion"
    if not before or before == after:
        return "no change"
    if "\n" in before or "\n" in after or len(before) > MAX_BEFORE:
        return "too long"
    if source.count(before) != 1:
        return "this text is no longer in the paragraph exactly once"
    if _word_edits(before, after) > MAX_WORD_EDITS:
        return "changes too many words"
    if kind == "spelling" and (
        difflib.SequenceMatcher(None, before, after).ratio() < MIN_SPELLING_SIMILARITY
    ):
        return "swaps the word rather than fixing its spelling"
    if _MARKUP & set(before + after):
        return "touches markdown"
    start = source.index(before)
    end = start + len(before)
    # Whole words only: "form" inside "formal" is not a fix to "formal".
    if before[0].isalnum() and start > 0 and source[start - 1].isalnum():
        return "starts inside a word"
    if before[-1].isalnum() and end < len(source) and source[end].isalnum():
        return "ends inside a word"
    for m in _PROTECTED.finditer(source):
        if m.start() < end and start < m.end():
            return "inside a link, code or HTML"
    # "1 Apples" -> "1. Apples" turns a paragraph into a list.
    expected = [block_kind] if block_kind else _block_kinds(source)
    if _block_kinds(source.replace(before, after, 1)) != expected:
        return "would change what kind of block this is"
    return None


def validate(index: int, source: str, items: list, block_kind: str | None = None) -> list[dict]:
    # Caller must pass only this block's own suggestions -- `before` is
    # matched against `source` alone, so an item meant for another block
    # would be checked (and possibly accepted) against the wrong text.
    kept = []
    for item in items:
        if not isinstance(item, dict):
            continue
        before, after, kind = item.get("before"), item.get("after"), item.get("kind")
        if _problem(source, before, after, kind, block_kind) is None:
            kept.append((source.index(before), before, after, kind))
    kept.sort(key=lambda k: k[0])
    out, last_end = [], -1
    for start, before, after, kind in kept:
        if start < last_end:
            continue  # overlaps an earlier fix
        out.append({"before": before, "after": after, "kind": kind})
        last_end = start + len(before)
    for n, s in enumerate(out):
        s["id"] = f"{index}-{n}"
    return [{"id": s["id"], "before": s["before"], "after": s["after"], "kind": s["kind"]} for s in out]


def _inside_tag(out: str, at: int) -> bool:
    return out.rfind("<", 0, at) > out.rfind(">", 0, at)


def review_html(source: str, suggestions: list[dict]) -> str | None:
    """The block rendered with its marks, or None when they can't all be
    placed safely -- the caller then drops the block's suggestions rather
    than offering a fix Peter can't see."""
    placed = sorted(suggestions, key=lambda s: source.index(s["before"]), reverse=True)
    marked = source
    tokens = []
    for n, s in enumerate(placed):
        at = marked.index(s["before"])
        # Private-use-area delimiters, not plain digits: a bare "0"/"1"
        # placeholder collides with any digit already in the source (e.g.
        # "In 2020, ...") and gets rewritten by the later str.replace too.
        token = "\ue000" + str(n) + "\ue001"
        marked = marked[:at] + token + marked[at + len(s["before"]):]
        tokens.append(token)
    out = _md.render(marked)
    for n, s in enumerate(placed):
        token = tokens[n]
        if out.count(token) != 1 or _inside_tag(out, out.index(token)):
            # The markdown render didn't preserve the token as a single,
            # unique run in text (it landed across an escaped/altered span,
            # or inside a tag's attribute) -- no safe place for the mark.
            return None
        sid = html.escape(s["id"], quote=True)
        out = out.replace(
            token,
            f'<del class="pr-old" data-sid="{sid}">{html.escape(s["before"])}</del>'
            f'<ins class="pr-new" data-sid="{sid}">{html.escape(s["after"])}</ins>',
            1,
        )
    return out


def apply_one(source: str, before: str, after: str, kind: str,
              block_kind: str | None = None) -> str:
    problem = _problem(source, before, after, kind, block_kind)
    if problem:
        raise ValueError(problem)
    return source.replace(before, after, 1)
