"""Tests for language_shift.flatten on the small projects in tests/fixtures/flatten/<case>/.

Every fixture file contains a marker word (INTRO-TEXT, SHOWN-TEXT, ...). Each test states which
markers must and must not appear in the flat text, so you can check a test by opening the fixture.

    uv run pytest tests/test_flatten.py -v
"""

from pathlib import Path

import pytest

from language_shift.arxiv_source import find_main_tex
from language_shift.flatten import FlattenError, flatten

FIX = Path(__file__).parent / "fixtures" / "flatten"


def flat(case: str) -> tuple[str, list[str]]:
    return flatten(FIX / case, Path("main.tex"))


def test_input_include_and_bare_input_are_inlined():
    text, missing = flat("basic")
    for marker in ["INTRO-TEXT", "METHOD-TEXT", "RESULTS-TEXT", "CONCLUSION-TEXT"]:
        assert marker in text
    assert "\\subfile{appendix}" in text  # latexpand leaves \subfile alone
    assert missing == []


def test_nested_and_import():
    assert all(f"LEVEL-{i}" in flat("nested")[0] for i in range(4))
    text, _ = flat("imports")
    assert all(m in text for m in ["CH1-TEXT", "CH1-FIG", "CH1-SUBPART"])


def test_commented_inputs_are_kept_as_comments_not_inlined():
    text, _ = flat("comments")
    assert "HIDDEN" not in text
    assert "% \\input{hidden}" in text
    assert "SHOWN-TEXT" in text and "TRAILING-COMMENT" in text


def test_input_wrapper_macros_are_expanded():
    text, missing = flat("wrappers")
    assert "WRAPPED-INTRO" in text and "WRAPPED-CHAPTER" in text
    assert "\\newcommand{\\sec}" not in text  # wrapper definitions are dropped
    assert missing == []


def test_latin1_files_are_decoded():
    assert "Müller und Größe" in flat("latin1")[0]


def test_missing_files_are_reported_and_left_in_place():
    text, missing = flat("missing")
    assert missing == ["tcilatex", "nope.tex"]
    assert "\\input{tcilatex}" in text


def test_a_file_that_inputs_itself_raises(monkeypatch):
    monkeypatch.setattr("language_shift.flatten.TIMEOUT", 2)
    with pytest.raises(FlattenError, match="timed out"):
        flat("cycle")


def test_paths_outside_the_paper_folder_are_refused(tmp_path):
    (tmp_path / "secret.tex").write_text("SECRET\n")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("\\input{../secret}\n")
    with pytest.raises(FlattenError, match="outside"):
        flatten(paper, Path("main.tex"))


def test_no_temporary_file_is_left_behind():
    flat("basic")
    assert not list(FIX.rglob(".flatten-main.tex"))


# Choosing the main file ---------------------------------------------------------------------
def main_of(case: str):
    root = FIX / case
    return find_main_tex(root, sorted(p.relative_to(root) for p in root.glob("*.tex")))


def test_main_choice_uses_flattened_length():
    main, text, _ = main_of("choice")
    assert main == Path("main.tex")  # 4 lines itself, but longer than figure.tex once flattened
    assert "BODY" in text


def test_readme_toplevel_overrides_the_rule():
    main, text, _ = main_of("readme")
    assert main == Path("short.tex") and "SHORT" in text


def test_wrapper_defined_inside_the_document_body(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "intro.tex").write_text("INTRO\n")
    (tmp_path / "main.tex").write_text(
        "\\begin{document}\n\\newcommand\\part[1]{\\input{s/#1}}\n\\part{intro.tex}\n\\end{document}\n")
    text, missing = flatten(tmp_path, Path("main.tex"))
    assert "INTRO" in text and missing == []


def test_dots_in_a_comment_are_not_a_path_outside(tmp_path):
    (tmp_path / "main.tex").write_text("%% Please do not use \\input{...} here\nTEXT\n")
    assert "TEXT" in flatten(tmp_path, Path("main.tex"))[0]
