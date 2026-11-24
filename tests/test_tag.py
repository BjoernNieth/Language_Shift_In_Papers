"""Tests for the windowing in language_shift.tag (the spaCy sentence splitter, no tagging).

    uv run pytest tests/test_tag.py -v
"""

import pytest
import spacy

from language_shift.tag import windows


@pytest.fixture(scope="module")
def nlp():
    return spacy.load("en_core_web_sm", disable=["ner"])


def test_windows_of_whole_sentences_last_short_one_dropped(nlp):
    sentence = "This short sentence has exactly eight words in it. "  # 9 words, 1 punctuation
    text = sentence * 100  # 900 words
    out = windows(nlp(text), size=400, cap=440)
    # a window closes after the sentence that takes it over 400 words: 45 sentences = 405 words
    assert len(out) == 2  # 405 + 405; the rest (90 words) is dropped
    assert all(w.endswith("in it.") for w in out)


def test_a_long_sentence_is_cut_at_the_cap(nlp):
    text = "word " * 600 + "."
    (window,) = windows(nlp(text), size=400, cap=440)
    assert len(window.split()) == 440
