"""Tests for language_shift.latex_refs on tests/fixtures/refs/<case>/.

input.tex, expected.tex (written by hand), expected_refs.json ([kind, command, keys] per record)
and expected_problems.json ([message] per problem).

    uv run pytest tests/test_refs.py -v
"""

import json
from pathlib import Path

import pytest

from language_shift.latex_refs import replace_refs

FIX = Path(__file__).parent / "fixtures" / "refs"
CASES = sorted(p.parent.name for p in FIX.glob("*/expected.tex"))


@pytest.mark.parametrize("case", CASES)
def test_matches_expected_files(case):
    root = FIX / case
    text, refs, problems = replace_refs((root / "input.tex").read_text(encoding="utf-8"))
    assert text == (root / "expected.tex").read_text(encoding="utf-8")
    assert [[r.kind, r.command, r.keys] for r in refs] == \
        json.loads((root / "expected_refs.json").read_text(encoding="utf-8"))
    assert [[p.message] for p in problems] == \
        json.loads((root / "expected_problems.json").read_text(encoding="utf-8"))
