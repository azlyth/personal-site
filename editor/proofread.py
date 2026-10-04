"""AI proofreading: spelling, grammar and punctuation only.

Claude proposes; this module disposes. Every suggestion is checked against
the block's exact source before Peter sees it, and again when he accepts it,
so a rewording can't arrive dressed as a fix and a fix can't land on text
that has moved. Pure apart from run_claude.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess

from editor import config
from editor.blocks import _md

PROSE_KINDS = frozenset({"paragraph", "heading", "list", "blockquote", "pair"})
KINDS = frozenset({"spelling", "grammar", "punctuation"})
MAX_BEFORE = 80
MAX_WORD_EDITS = 3
_MARKUP = set("[]()*_`#<>|")
_PROTECTED = re.compile(
    r"`[^`\n]*`"            # inline code
    r"|https?://[^\s)>\]]+"  # bare or linked URLs
    r"|\]\([^)\n]*\)"        # link destinations
    r"|<[^>\n]+>"            # HTML tags
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


def run_claude(prompt: str, timeout_s: int = 120) -> str:
    cmd = [config.claude_bin(), "-p", prompt]
    model = config.proofread_model()
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=True)
    return proc.stdout


def parse_response(raw: str) -> list:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    text = fenced.group(1) if fenced else raw
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        raise ValueError("no JSON array in the response")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("response is not a list")
    return data


def _word_edits(a: str, b: str) -> int:
    x, y = a.split(), b.split()
    prev = list(range(len(y) + 1))
    for i, xi in enumerate(x, 1):
        cur = [i]
        for j, yj in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (xi != yj)))
        prev = cur
    return prev[-1]


def _problem(source: str, before, after, kind="spelling") -> str | None:
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
    if _MARKUP & set(before + after):
        return "touches markdown"
    start = source.index(before)
    end = start + len(before)
    for m in _PROTECTED.finditer(source):
        if m.start() < end and start < m.end():
            return "inside a link, code or HTML"
    return None


def validate(index: int, source: str, items: list) -> list[dict]:
    kept = []
    for item in items:
        if not isinstance(item, dict):
            continue
        before, after, kind = item.get("before"), item.get("after"), item.get("kind")
        if _problem(source, before, after, kind) is None:
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


def review_html(source: str, suggestions: list[dict]) -> str:
    marked = source
    placed = sorted(suggestions, key=lambda s: source.index(s["before"]), reverse=True)
    for n, s in enumerate(placed):
        at = marked.index(s["before"])
        marked = marked[:at] + f"{n}" + marked[at + len(s["before"]):]
    out = _md.render(marked)
    for n, s in enumerate(placed):
        sid = html.escape(s["id"], quote=True)
        out = out.replace(
            f"{n}",
            f'<del class="pr-old" data-sid="{sid}">{html.escape(s["before"])}</del>'
            f'<ins class="pr-new" data-sid="{sid}">{html.escape(s["after"])}</ins>',
        )
    return out


def apply_one(source: str, before: str, after: str) -> str:
    problem = _problem(source, before, after)
    if problem:
        raise ValueError(problem)
    return source.replace(before, after, 1)
