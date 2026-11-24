"""Prose of each paper -> Biber features per window of about 400 words.

    uv run python -m language_shift.tag              # every data/prose/<id>.txt not tagged yet
    uv run python -m language_shift.tag 2508.04926v1 # only these (tags again if done)

Output: data/features/biber/<id>.parquet, one row per window with paper, window (0, 1, ...),
n_words and the 67 pybiber features. Read all with pl.read_parquet("data/features/biber/*.parquet").

Windows as in the EMNLP 2026 paper (Register_Aware_LLMs, scripts/utils.py window_text_soft_doc):
whole sentences (split by en_core_web_sm) until the window has more than 400 words, cut hard at
440 words. Words are tokens that are not punctuation or space. Here the whole paper is cut into
consecutive windows; a last window of 400 words or fewer is dropped.

Tagging as in the EMNLP paper (scripts/02_get_biber_features.py): en_core_web_trf without NER,
pybiber (0.3.1 here) with force_ttr=True, a new CorpusProcessor per batch (here: per paper), which
avoided inflated f_23_wh_clause values; a window with f_23_wh_clause >= 1000 stops the run.
"""

from __future__ import annotations

import argparse

import polars as pl
import pybiber as pb
import spacy

from language_shift.arxiv_source import DATA_DIR
from language_shift.pipeline import PROSE_DIR

BIBER_DIR = DATA_DIR.parent / "features" / "biber"
WINDOW, CAP = 400, 440


def _is_word(token) -> bool:
    return not (token.is_punct or token.is_space)


def windows(doc, size: int = WINDOW, cap: int = CAP) -> list[str]:
    out, sents, n = [], [], 0
    for sent in doc.sents:
        sents.append(sent)
        n += sum(map(_is_word, sent))
        if n > size:
            out.append(_capped(sents, cap))
            sents, n = [], 0
    return out


def _capped(sents, cap: int) -> str:
    parts, n = [], 0
    for token in (t for s in sents for t in s):
        parts.append(token.text_with_ws)
        n += _is_word(token)
        if n >= cap:
            break
    return "".join(parts).strip()


def tag_paper(paper: str, text: str, splitter, tagger) -> pl.DataFrame | None:
    """Biber features for each window of one paper; None if the paper has no full window."""
    texts = windows(splitter(text))
    if not texts:
        return None
    df = pl.DataFrame({"doc_id": [f"{paper}#{k}" for k in range(len(texts))], "text": texts})
    tokens = pb.CorpusProcessor().process_corpus(df, nlp_model=tagger, n_process=1, show_progress=False)
    features = pb.biber(tokens, force_ttr=True)
    if (bad := features.filter(pl.col("f_23_wh_clause") >= 1000)).height:
        raise AssertionError(f"f_23_wh_clause >= 1000 in {bad['doc_id'].to_list()}")
    n_words = [sum(map(_is_word, splitter(t))) for t in texts]
    info = pl.DataFrame({"doc_id": df["doc_id"], "paper": [paper] * len(texts),
                         "window": list(range(len(texts))), "n_words": n_words})
    return info.join(features, on="doc_id", how="left", maintain_order="left")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="*", help="papers to (re)tag; default: all not tagged yet")
    ap.add_argument("--gpu", action="store_true", help="spaCy on the GPU (CUDA or Apple MPS)")
    args = ap.parse_args()
    papers = args.ids or sorted(p.stem for p in PROSE_DIR.glob("*.txt")
                                if not (BIBER_DIR / f"{p.stem}.parquet").exists())
    if args.gpu:
        spacy.require_gpu()
    splitter = spacy.load("en_core_web_sm", disable=["ner"])
    tagger = spacy.load("en_core_web_trf", disable=["ner"])
    splitter.max_length = tagger.max_length = 5_000_000  # whole papers, not only 1M characters
    BIBER_DIR.mkdir(parents=True, exist_ok=True)
    for i, paper in enumerate(papers, 1):
        out = tag_paper(paper, (PROSE_DIR / f"{paper}.txt").read_text(encoding="utf-8"), splitter, tagger)
        if out is None:
            print(f"[{i}/{len(papers)}] {paper}: shorter than one window, skipped")
            continue
        tmp = BIBER_DIR / f"{paper}.parquet.part"
        out.write_parquet(tmp)
        tmp.rename(tmp.with_suffix(""))  # no half-written file under the final name
        print(f"[{i}/{len(papers)}] {paper}: {out.height} windows")


if __name__ == "__main__":
    main()
