"""Tests for language_shift.latex_comments on tests/fixtures/comments/<case>/.

input.tex, expected.tex (written by hand from TeX's rules), expected_comments.json
([kind, text, line] per removed comment) and expected_problems.json ([message, line]).

    uv run pytest tests/test_comments.py -v
"""

import json
from pathlib import Path

import pytest

from language_shift.latex_comments import remove_comments, remove_conditionals

FIX = Path(__file__).parent / "fixtures" / "comments"
STEP = {"line_and_env": remove_comments, "conditionals": remove_conditionals}


@pytest.mark.parametrize("case", sorted(STEP))
def test_matches_expected_files(case):
    root = FIX / case
    text, comments, problems = STEP[case]((root / "input.tex").read_text(encoding="utf-8"))
    assert text == (root / "expected.tex").read_text(encoding="utf-8")
    assert [[c.kind, c.text, c.line] for c in comments] == \
        json.loads((root / "expected_comments.json").read_text(encoding="utf-8"))
    assert [[p.message, p.line] for p in problems] == \
        json.loads((root / "expected_problems.json").read_text(encoding="utf-8"))


def test_hide_macro_works_when_conditionals_run_after_macros():
    from language_shift.latex_macros import expand_document
    text, _ = expand_document("\\newcommand{\\hide}[1]{\\iffalse #1\\fi}\nA \\hide{secret} B\n")
    text, hidden, _ = remove_conditionals(text)
    assert "secret" not in text
    assert [c.text for c in hidden] == [" secret"]
