import pytest

from editor import config, proofread
from editor.blocks import parse_blocks


def ok(before, after, kind="spelling", block=0):
    return {"block": block, "before": before, "after": after, "kind": kind}


def test_claude_bin_default_is_absolute(monkeypatch):
    monkeypatch.delenv("EDITOR_CLAUDE_BIN", raising=False)
    assert config.claude_bin() == "/home/peter/.local/bin/claude"


def test_clean_suggestion_survives_with_id():
    out = proofread.validate(3, "I will recieve it.", [ok("recieve", "receive", block=3)])
    assert out == [{"id": "3-0", "before": "recieve", "after": "receive", "kind": "spelling"}]


def test_drops_before_not_in_source():
    assert proofread.validate(0, "It’s fine.", [ok("It's", "It is")]) == []


def test_drops_ambiguous_before():
    assert proofread.validate(0, "teh cat and teh dog", [ok("teh", "the")]) == []
    out = proofread.validate(0, "teh cat and teh dog", [ok("teh cat", "the cat")])
    assert [s["before"] for s in out] == ["teh cat"]


@pytest.mark.parametrize("item", [
    ok("same", "same"),
    ok("a\nb", "a b"),
    ok("x" * 81, "y" * 81),
    ok("one two three four five", "five four three two one", kind="grammar"),
    ok("bold", "**bold**"),
    ok("word", "word", kind="style"),
    {"block": 0, "before": 5, "after": "x", "kind": "spelling"},
])
def test_guardrails_drop(item):
    source = "same a b bold word one two three four five " + "x" * 81
    assert proofread.validate(0, source, [item]) == []


def test_link_text_ok_url_dropped():
    source = "See [the documantation](https://exmaple.com/docs) now."
    out = proofread.validate(0, source, [
        ok("documantation", "documentation"),
        ok("exmaple", "example"),
    ])
    assert [s["before"] for s in out] == ["documantation"]


def test_code_and_html_spans_protected():
    source = 'Run `teh tool` and <span class="teh">ok</span> teh end.'
    out = proofread.validate(0, source, [ok("teh end", "the end")])
    assert [s["before"] for s in out] == ["teh end"]
    assert proofread.validate(0, "Run `teh tool` ok", [ok("teh tool", "the tool")]) == []


def test_overlapping_later_dropped_and_sorted_by_position():
    source = "Thier house is is big."
    out = proofread.validate(0, source, [
        ok("is is", "is", kind="grammar"),
        ok("house is", "house's", kind="grammar"),
        ok("Thier", "Their"),
    ])
    # sorted by position: "house is" (at 6) wins, "is is" (at 12) overlaps it
    assert [s["before"] for s in out] == ["Thier", "house is"]
    assert [s["id"] for s in out] == ["0-0", "0-1"]


def test_parse_response_handles_fence_and_prose():
    raw = 'Here you go:\n```json\n[{"block": 1, "before": "a", "after": "b", "kind": "spelling"}]\n```'
    assert proofread.parse_response(raw)[0]["block"] == 1
    assert proofread.parse_response("[]") == []
    with pytest.raises(ValueError):
        proofread.parse_response("no json here")


def test_review_html_marks_in_place():
    source = "I will recieve *it* soon."
    sugg = proofread.validate(0, source, [ok("recieve", "receive")])
    html = proofread.review_html(source, sugg)
    assert '<del class="pr-old" data-sid="0-0">recieve</del>' in html
    assert '<ins class="pr-new" data-sid="0-0">receive</ins>' in html
    assert "<em>it</em>" in html and html.startswith("<p>")


def test_review_html_escapes():
    source = "a & b recieve"
    sugg = proofread.validate(0, source, [ok("recieve", "receive")])
    assert "a &amp; b" in proofread.review_html(source, sugg)


def test_apply_one_replaces_exactly_once_and_rechecks():
    assert proofread.apply_one("I recieve it.", "recieve", "receive") == "I receive it."
    with pytest.raises(ValueError):
        proofread.apply_one("teh and teh", "teh", "the")
    with pytest.raises(ValueError):
        proofread.apply_one("I receive it.", "recieve", "receive")


def test_build_prompt_lists_blocks_by_index():
    blocks = parse_blocks("Para one.\n\n## Head\n\nPara two.\n")
    prompt = proofread.build_prompt(blocks)
    assert '<block index="0">\nPara one.\n</block>' in prompt
    assert '<block index="2">' in prompt
    assert "only" in prompt.lower() and "json" in prompt.lower()
