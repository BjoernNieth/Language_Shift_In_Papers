"""Tests for language_shift.pipeline on tests/fixtures/pipeline/tiny/ (one line of each kind).

    uv run pytest tests/test_pipeline.py -v
"""

from pathlib import Path

from language_shift.pipeline import format_trace, run, write_trace

TINY = Path(__file__).parent / "fixtures" / "pipeline" / "tiny"


def test_steps_run_in_order_and_each_does_its_job():
    steps = {s.name: s for s in run(TINY)}
    assert list(steps) == ["flatten", "comments", "macros", "body", "conditionals", "appendix",
                           "front_matter", "tikz", "floats", "layout", "math", "refs", "headings",
                           "footnotes", "plain_text"]
    assert "See Table" in steps["flatten"].text
    assert "TODO" not in steps["comments"].text
    assert "GreatNet" in steps["macros"].text and "\\newcommand" not in steps["macros"].text
    assert "\\documentclass" not in steps["body"].text
    assert "HIDDEN-TEXT" not in steps["conditionals"].text
    assert "MATHEXPR" in steps["math"].text and "$" not in steps["math"].text
    final = "We train GreatNet on MATHEXPR data CITEREF. See Table XREF."
    assert steps["plain_text"].text.split() == final.split()


def test_trace_files_and_summary(tmp_path):
    steps = run(TINY)
    write_trace(steps, tmp_path)
    assert (tmp_path / "15_plain_text.tex").read_text() == steps[-1].text
    assert (tmp_path / "03_macros.removed.jsonl").read_text().count("\n") == 2  # two definitions
    summary = format_trace("tiny", steps)
    assert "main file: main.tex" in summary and "15 plain_text" in summary
