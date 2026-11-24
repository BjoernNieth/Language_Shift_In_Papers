"""Tests for language_shift.arxiv_source without network access (_get is replaced).

    uv run pytest tests/test_arxiv_source.py -v
"""

import gzip

import pytest

from language_shift import arxiv_source as a

SOURCE = gzip.compress(b"\\documentclass{article}\\begin{document}Hi\\end{document}")


@pytest.fixture
def fake_get(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        return SOURCE, {"Content-Disposition": 'attachment; filename="x.gz"'}

    monkeypatch.setattr(a, "_get", get)
    return calls


def test_downloads_from_export_arxiv(tmp_path, fake_get):
    path = a.download_source("1811.01990", "v1", tmp_path)
    assert fake_get == ["https://export.arxiv.org/src/1811.01990v1"]
    assert path.name == "1811.01990v1.gz" and path.read_bytes() == SOURCE


def test_a_finished_download_is_not_fetched_again(tmp_path, fake_get):
    a.download_source("1811.01990", "v1", tmp_path)
    a.download_source("1811.01990", "v1", tmp_path)
    assert len(fake_get) == 1


def test_an_interrupted_download_is_fetched_again(tmp_path, fake_get):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "1811.01990v1.gz.part").write_bytes(b"\x1f\x8b truncated")
    path = a.download_source("1811.01990", "v1", tmp_path)
    assert len(fake_get) == 1 and path.name == "1811.01990v1.gz" and path.read_bytes() == SOURCE
