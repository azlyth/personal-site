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


def test_parse_response_ignores_stray_brackets_in_prose():
    raw = 'See [1] above:\n[{"block": 0, "before": "a", "after": "b", "kind": "spelling"}] Thanks [ok]'
    data = proofread.parse_response(raw)
    assert data == [{"block": 0, "before": "a", "after": "b", "kind": "spelling"}]


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


def test_review_html_does_not_mangle_digits():
    source = "In 2020, I will recieve it."
    sugg = proofread.validate(0, source, [ok("recieve", "receive")])
    html = proofread.review_html(source, sugg)
    assert "2020" in html
    assert '<del class="pr-old" data-sid="0-0">recieve</del>' in html
    assert '<ins class="pr-new" data-sid="0-0">receive</ins>' in html


def test_review_html_two_suggestions_one_block():
    source = "Thier house is is big."
    sugg = proofread.validate(0, source, [
        ok("house is", "house's", kind="grammar"),
        ok("Thier", "Their"),
    ])
    html = proofread.review_html(source, sugg)
    assert '<del class="pr-old" data-sid="0-0">Thier</del>' in html
    assert '<ins class="pr-new" data-sid="0-0">Their</ins>' in html
    assert '<del class="pr-old" data-sid="0-1">house is</del>' in html
    assert '<ins class="pr-new" data-sid="0-1">house&#x27;s</ins>' in html


def test_review_html_heading_block():
    source = "## Teh heading"
    sugg = proofread.validate(0, source, [ok("Teh", "The")])
    html = proofread.review_html(source, sugg)
    assert html.startswith("<h2>")
    assert '<del class="pr-old" data-sid="0-0">Teh</del>' in html
    assert '<ins class="pr-new" data-sid="0-0">The</ins>' in html


def test_review_html_list_block():
    source = "- recieve it\n- ok"
    sugg = proofread.validate(0, source, [ok("recieve", "receive")])
    html = proofread.review_html(source, sugg)
    assert "<ul>" in html and "<li>" in html
    assert '<del class="pr-old" data-sid="0-0">recieve</del>' in html
    assert '<ins class="pr-new" data-sid="0-0">receive</ins>' in html


def test_review_html_preserves_literal_zero():
    source = "I owe you $0 and will recieve it."
    sugg = proofread.validate(0, source, [ok("recieve", "receive")])
    html = proofread.review_html(source, sugg)
    assert "$0" in html
    assert '<del class="pr-old" data-sid="0-0">recieve</del>' in html
    assert '<ins class="pr-new" data-sid="0-0">receive</ins>' in html


def test_apply_one_replaces_exactly_once_and_rechecks():
    assert proofread.apply_one("I recieve it.", "recieve", "receive", "spelling") == "I receive it."
    with pytest.raises(ValueError):
        proofread.apply_one("teh and teh", "teh", "the", "spelling")
    with pytest.raises(ValueError):
        proofread.apply_one("I receive it.", "recieve", "receive", "spelling")


def test_build_prompt_lists_blocks_by_index():
    blocks = parse_blocks("Para one.\n\n## Head\n\nPara two.\n")
    prompt = proofread.build_prompt(blocks)
    assert '<block index="0">\nPara one.\n</block>' in prompt
    assert '<block index="2">' in prompt
    assert "only" in prompt.lower() and "json" in prompt.lower()


# --- final-review guardrails -------------------------------------------------

def test_run_claude_is_sandboxed(monkeypatch):
    seen = {}

    def run(args, **kw):
        import os
        seen["args"], seen["kw"] = args, kw
        seen["cwd_existed"] = os.path.isdir(kw["cwd"])
        seen["cwd_listing"] = os.listdir(kw["cwd"])

        class P:
            stdout = "[]"
        return P()

    monkeypatch.setattr(proofread.subprocess, "run", run)
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    assert proofread.run_claude("PROMPT TEXT") == "[]"
    args, kw = seen["args"], seen["kw"]
    assert "PROMPT TEXT" not in args and kw["input"] == "PROMPT TEXT"
    assert args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args
    assert "--bare" not in args
    assert seen["cwd_existed"] and seen["cwd_listing"] == []
    import os
    assert not os.path.exists(kw["cwd"])  # removed afterwards
    assert "/projects/" not in kw["cwd"]
    assert "SMTP_PASSWORD" not in kw["env"] and "HOME" in kw["env"]


@pytest.mark.parametrize("before,after", [("apples", "oranges"), ("good", "great")])
def test_spelling_must_look_like_the_word(before, after):
    source = f"I like {before} a lot."
    assert proofread.validate(0, source, [ok(before, after)]) == []


def test_spelling_floor_keeps_real_typos_and_grammar_is_exempt():
    assert proofread.validate(0, "teh cat", [ok("teh", "the")])
    assert proofread.validate(0, "They was here.", [ok("was", "were", kind="grammar")])


def test_grammar_limited_to_two_word_edits():
    source = "one two three four"
    assert proofread.validate(0, source, [ok("one two", "uno dos", kind="grammar")])
    assert proofread.validate(0, source, [ok("one two three", "uno dos tres", kind="grammar")]) == []


def test_before_must_sit_on_word_boundaries():
    assert proofread.validate(0, "Its formal now", [ok("form", "from")]) == []
    assert proofread.validate(0, "Its formal now", [ok("mal", "mall")]) == []
    assert proofread.validate(0, "teh cat", [ok("teh", "the")])
    # punctuation-led spans aren't held to it
    assert proofread.validate(0, "Hello ,world", [ok(" ,", ",", kind="punctuation")])


def test_inline_image_alt_and_www_domains_protected():
    assert proofread.validate(0, "See ![teh pic](x.jpg) ok", [ok("teh", "the")]) == []
    assert proofread.validate(0, "Go to www.exmaple.com today", [ok("exmaple", "example")]) == []


def test_review_html_none_when_a_mark_lands_in_a_tag():
    # Inline HTML may break its tag across a line, which _PROTECTED's
    # one-line pattern can't see; the render puts the mark in an attribute.
    source = 'Hi <span\nclass="teh">ok</span> there.'
    sugg = [{"id": "0-0", "before": "teh", "after": "the", "kind": "spelling"}]
    assert proofread.review_html(source, sugg) is None


@pytest.mark.parametrize("source,before,after,kind", [
    ("1 Apples are red.", "1 Apples", "1. Apples", "punctuation"),
    ("Apples are red.", "Apples", "- Apples", "grammar"),
])
def test_fix_must_not_change_block_type(source, before, after, kind):
    assert proofread.validate(0, source, [ok(before, after, kind=kind)]) == []
    with pytest.raises(ValueError):
        proofread.apply_one(source, before, after, kind)


def test_apply_one_uses_the_suggestion_kind():
    assert proofread.apply_one("They was here.", "was", "were", "grammar") == "They were here."
    with pytest.raises(ValueError):
        proofread.apply_one("I like apples.", "apples", "oranges", "spelling")
