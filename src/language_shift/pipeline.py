"""LaTeX source of one paper -> text for the tagger, as a list of named steps you can trace.

    uv run python -m language_shift.pipeline 2508.04926v1 [more ids]

prints one line per step and writes every intermediate text to data/trace/<id>/:
    01_flatten.tex       the main file with all \\input inlined (flatten.py)
    02_comments.tex      % comments and comment environments removed
    03_macros.tex        the author's macros expanded, their definitions removed
    04_body.tex          only the text between \\begin{document} and \\end{document}
    05_conditionals.tex  \\iffalse ... \\fi removed (after macros: \\hide{x} may expand to it)
    06_appendix.tex      everything from \\appendix on removed
    07_front_matter.tex  title, authors, affiliations, keywords removed; the abstract stays
    08_tikz.tex          tikzpicture blocks taken out (in 08_tikz.removed.jsonl)
    09_floats.tex        figures, tables, algorithms, listings, captions, \\includegraphics removed
    10_layout.tex        \\vspace{..}, \\pagestyle{..}, \\vskip 0.5cm and other setup commands removed
    11_math.tex          math replaced by MATHEXPR
    12_refs.tex          \\cite -> CITEREF, \\ref -> XREF, labels and bibliography removed
    13_headings.tex      \\section{...} etc. removed with their titles
    14_footnotes.tex     each footnote moved to its own paragraph after the one it was in
    15_plain_text.tex    plain text (pylatexenc), one paragraph per block: this goes to the tagger
and next to each NN_<step>.tex what the step took out (NN_<step>.removed.jsonl) and its problems
(NN_<step>.problems.jsonl). `diff 02_comments.tex 03_macros.tex` shows exactly what one step did.

The last step's text goes to the tagger (tag.py).

In code:
    steps = run(Path("data/sources/unpacked/2508.04926v1"))
    steps[-1].text
Every step after flatten is a function text -> (text, removed, problems); to add one, write it and
add it to STEPS.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from dataclasses import dataclass
from pathlib import Path

from language_shift.arxiv_source import DATA_DIR, fetch_paper, find_main_tex
from language_shift.latex_comments import remove_comments, remove_conditionals
from language_shift.latex_macros import expand_macros, find_macros, remove_definitions
from language_shift.latex_math import replace_math
from language_shift.latex_refs import replace_refs
from language_shift.latex_text import (drop_appendix, drop_floats, drop_front_matter, drop_headings,
                                       drop_layout, extract_tikz, move_footnotes, to_plain_text)

TRACE_DIR = DATA_DIR.parent / "trace"
PROSE_DIR = DATA_DIR.parent / "prose"  # <id>.txt: the final text of each paper, input of tag.py


@dataclass
class Step:
    name: str
    text: str
    removed: list  # what the step took out of the text (comments, macro definitions, math, ...)
    problems: list


def expand_all_macros(text: str) -> tuple[str, list, list]:
    macros, skipped = find_macros(text)
    defined = [{"name": n, **dataclasses.asdict(m)} for n, m in macros.items()]
    return expand_macros(remove_definitions(text), macros), defined, skipped


def keep_body(text: str) -> tuple[str, list, list]:
    m = re.search(r"\\begin\{document\}(.*?)(?:\\end\{document\}|$)", text, re.S)
    if m is None:
        return text, [], ["no \\begin{document}: kept the whole text"]
    return m[1], [{"preamble": text[: m.start()], "after_end": text[m.end():]}], []


STEPS = [
    ("comments", remove_comments),
    ("macros", expand_all_macros),
    ("body", keep_body),
    ("conditionals", remove_conditionals),
    ("appendix", drop_appendix),
    ("front_matter", drop_front_matter),
    ("tikz", extract_tikz),  # before math: TikZ coordinates use $...$
    ("floats", drop_floats),
    ("layout", drop_layout),
    ("math", replace_math),
    ("refs", replace_refs),
    ("headings", drop_headings),
    ("footnotes", move_footnotes),
    ("plain_text", to_plain_text),
]


def run(paper_dir: Path) -> list[Step]:
    tex = sorted(p.relative_to(paper_dir) for p in paper_dir.rglob("*.tex"))
    main, text, missing = find_main_tex(paper_dir, tex)
    if main is None:
        raise ValueError(f"{paper_dir.name}: no main .tex file found")
    steps = [Step("flatten", text, [{"main": str(main)}], [f"not found: {n}" for n in missing])]
    for name, step in STEPS:
        text, removed, problems = step(text)
        steps.append(Step(name, text, removed, problems))
    return steps


# ------------------------------------------------------------------ trace
def write_trace(steps: list[Step], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("[0-9][0-9]_*"):
        old.unlink()  # a step list that changed would otherwise leave stale files
    for i, s in enumerate(steps, 1):
        stem = out / f"{i:02d}_{s.name}"
        stem.with_suffix(".tex").write_text(s.text, encoding="utf-8")
        for kind, items in [("removed", s.removed), ("problems", s.problems)]:
            lines = [json.dumps(_plain(x), ensure_ascii=False) + "\n" for x in items]
            Path(f"{stem}.{kind}.jsonl").write_text("".join(lines), encoding="utf-8")


def format_trace(paper: str, steps: list[Step]) -> str:
    rows = [f"{paper}   main file: {steps[0].removed[0]['main']}",
            f"  {'step':<15}{'chars':>10}{'removed':>9}{'problems':>10}"]
    for i, s in enumerate(steps, 1):
        rows.append(f"  {i:02d} {s.name:<12}{len(s.text):>10,}{len(s.removed):>9}{len(s.problems):>10}")
        rows += [f"       ! {_plain(p)}" for p in s.problems[:3]]
        if len(s.problems) > 3:
            rows.append(f"       ! ... {len(s.problems) - 3} more")
    return "\n".join(rows)


def _plain(x):
    return dataclasses.asdict(x) if dataclasses.is_dataclass(x) else x


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="+", help="arXiv ids with version, e.g. 2508.04926v1")
    ap.add_argument("--out", type=Path, default=TRACE_DIR)
    args = ap.parse_args()
    for paper in args.ids:
        paper_dir = DATA_DIR / "unpacked" / paper.replace("/", "_")
        if not paper_dir.is_dir():  # not downloaded yet
            arxiv_id, version = re.fullmatch(r"(.+?)(v\d+)", paper).groups()
            paper_dir = fetch_paper(arxiv_id, version).dir
        steps = run(paper_dir)
        write_trace(steps, args.out / paper_dir.name)
        print(format_trace(paper, steps))
        print(f"  files: {args.out / paper_dir.name}/\n")
        PROSE_DIR.mkdir(parents=True, exist_ok=True)
        (PROSE_DIR / f"{paper_dir.name}.txt").write_text(steps[-1].text, encoding="utf-8")


if __name__ == "__main__":
    main()
