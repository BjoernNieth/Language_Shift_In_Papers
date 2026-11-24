"""Tests for language_shift.latex_macros on tests/fixtures/macros/<case>/.

Each case has input.tex (definitions + uses), expected.tex (written by hand from LaTeX's rules:
definitions removed, every use expanded) and expected_skipped.txt (name<TAB>reason per line).

    uv run pytest tests/test_macros.py -v
"""

from pathlib import Path

import pytest

from language_shift.latex_macros import expand_document

FIX = Path(__file__).parent / "fixtures" / "macros"
CASES = sorted(p.parent.name for p in FIX.glob("*/expected.tex"))


@pytest.mark.parametrize("case", CASES)
def test_expansion_matches_expected_file(case):
    root = FIX / case
    text, skipped = expand_document((root / "input.tex").read_text(encoding="utf-8"))
    assert text == (root / "expected.tex").read_text(encoding="utf-8")
    expected = [tuple(line.split("\t")) for line in
                (root / "expected_skipped.txt").read_text(encoding="utf-8").splitlines()]
    assert skipped == expected
