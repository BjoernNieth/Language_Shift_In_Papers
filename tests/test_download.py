"""Tests for language_shift.download with a fake fetch_paper (no network).

    uv run pytest tests/test_download.py -v
"""

import csv
import urllib.error
from email.message import Message
from types import SimpleNamespace

import polars as pl
import pytest

from language_shift import arxiv_source
from language_shift.arxiv_source import NotLatex, SourceNotAvailable, TemporaryError
from language_shift.download import MAX_TRIES, run, try_paper

# two strata with 6 candidates each; ids name what the fake arXiv answers
IDS = {("cs", 2020): ["a1", "pdf2", "a3", "gone4", "a5", "a6"],
       ("math", 2020): ["b1", "b2", "bad3", "b4", "b5", "b6"]}
CANDIDATES = pl.DataFrame([{"field": f, "year": y, "rank": r, "id": i, "subfield": f}
                           for (f, y), ids in IDS.items() for r, i in enumerate(ids, 1)])


class FakeArxiv:
    def __init__(self, stop_after=None):
        self.calls, self.stop_after = [], stop_after

    def __call__(self, arxiv_id):
        if self.stop_after is not None and len(self.calls) == self.stop_after:
            raise KeyboardInterrupt  # the user presses Ctrl-C
        self.calls.append(arxiv_id)
        if arxiv_id.startswith("pdf"):
            raise NotLatex(arxiv_id)
        if arxiv_id.startswith("gone"):
            raise SourceNotAvailable(arxiv_id)
        if arxiv_id.startswith("bad"):
            raise ValueError("odd archive")
        return SimpleNamespace(documentclass_files=["main.tex"], kind="tar")


def record(path):
    with open(path, newline="") as f:
        return [(r["id"], r["status"]) for r in csv.DictReader(f)]


def test_a_paper_without_documentclass_is_not_latex():
    paper = SimpleNamespace(documentclass_files=[], kind="unknown")
    assert try_paper("x1", lambda i: paper) == ("no_tex", "unknown")


def test_takes_candidates_in_rank_order_until_n_latex(tmp_path):
    arxiv = FakeArxiv()
    run(CANDIDATES, 3, tmp_path / "papers.csv", fetch=arxiv)
    rows = record(tmp_path / "papers.csv")
    cs = [r for r in rows if r[0] in IDS[("cs", 2020)]]
    assert cs == [("a1", "latex"), ("pdf2", "pdf_only"), ("a3", "latex"), ("gone4", "no_source"),
                  ("a5", "latex")]
    math = [r for r in rows if r[0] in IDS[("math", 2020)]]
    assert math == [("b1", "latex"), ("b2", "latex"), ("bad3", "error"), ("b4", "latex")]
    assert "a6" not in arxiv.calls and "b5" not in arxiv.calls


def test_fields_take_turns(tmp_path):
    arxiv = FakeArxiv()
    run(CANDIDATES, 3, tmp_path / "papers.csv", fetch=arxiv)
    assert arxiv.calls[:4] == ["a1", "b1", "pdf2", "b2"]


def test_a_restart_continues_without_repeating_anything(tmp_path):
    path = tmp_path / "papers.csv"
    with pytest.raises(KeyboardInterrupt):
        run(CANDIDATES, 3, path, fetch=FakeArxiv(stop_after=3))
    second = FakeArxiv()
    run(CANDIDATES, 3, path, fetch=second)
    assert "a1" not in second.calls and "b1" not in second.calls and "pdf2" not in second.calls
    uninterrupted = tmp_path / "once.csv"
    run(CANDIDATES, 3, uninterrupted, fetch=FakeArxiv())
    assert sorted(record(path)) == sorted(record(uninterrupted))


def test_raising_n_later_keeps_the_first_papers(tmp_path):
    path = tmp_path / "papers.csv"
    run(CANDIDATES, 2, path, fetch=FakeArxiv())
    first = record(path)
    run(CANDIDATES, 3, path, fetch=FakeArxiv())
    assert record(path)[:len(first)] == first
    assert sum(s == "latex" for _, s in record(path)) == 6


def test_a_temporary_failure_retries_the_same_paper():
    answers = [TemporaryError("HTTP 503", retry_after=7), TemporaryError("timeout"),
               SimpleNamespace(documentclass_files=["main.tex"], kind="tar")]
    waits = []

    def fetch(arxiv_id):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    assert try_paper("x1", fetch, waits.append) == ("latex", "main.tex")
    assert waits == [7, 120]  # the server's Retry-After, then the second backoff step


def test_lasting_failures_stop_the_run_without_recording(tmp_path):
    def fetch(arxiv_id):
        raise TemporaryError("HTTP 503")

    waits = []
    with pytest.raises(SystemExit):
        run(CANDIDATES, 3, tmp_path / "papers.csv", fetch=fetch, sleep=waits.append)
    assert len(waits) == MAX_TRIES and max(waits) == 1800
    assert record(tmp_path / "papers.csv") == []


@pytest.mark.parametrize("code, error", [(404, SourceNotAvailable), (410, SourceNotAvailable),
                                         (503, TemporaryError), (429, TemporaryError)])
def test_http_errors_are_sorted_into_permanent_and_temporary(tmp_path, monkeypatch, code, error):
    def get(url):
        headers = Message()
        headers["Retry-After"] = "30"
        raise urllib.error.HTTPError(url, code, "x", headers, None)

    monkeypatch.setattr(arxiv_source, "_get", get)
    with pytest.raises(error) as e:
        arxiv_source.download_source("1811.01990", "v1", tmp_path)
    if error is TemporaryError:
        assert e.value.retry_after == 30
