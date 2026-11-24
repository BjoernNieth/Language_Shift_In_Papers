"""The last parse steps, from the LaTeX body to plain text for the tagger. Each step is
text -> (text, removed, problems), like the other steps in pipeline.STEPS.

    drop_appendix      cut at \\appendix (or \\begin{appendices})
    drop_front_matter  \\title, \\author, affiliations, keywords, ...; the abstract stays
    extract_tikz       tikzpicture blocks out (kept for the TikZ features)
    drop_floats        figures, tables, algorithms, code listings, \\caption, \\includegraphics
    drop_layout        \\vspace{..}, \\pagestyle{..}, \\vskip 0.5cm and other setup commands
    drop_headings      \\section{...} and the like, with their title
    move_footnotes     \\footnote{x} out of the sentence; x becomes a paragraph after it
    to_plain_text      everything else with pylatexenc: \\textit{x} -> x, `` -> ", \\"o -> ö, ...
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from pylatexenc import latexwalker
from pylatexenc.latex2text import LatexNodes2Text, MacroTextSpec, get_default_latex_context_db
from pylatexenc.macrospec import MacroSpec

from language_shift.latex_macros import _group_end, _skip_ws
from language_shift.latex_math import MATH_TOKEN

FRONT_MATTER = [
    "title", "subtitle", "author", "and", "affiliation", "affil", "address", "email", "institute",
    "institution", "thanks", "date", "keywords", "maketitle", "orcid", "titlerunning",
    "authorrunning", "shorttitle", "shortauthors", "IEEEauthorblockN", "IEEEauthorblockA",
    "icmltitle", "icmltitlerunning", "icmlauthor", "icmlaffiliation", "icmlcorrespondingauthor",
    "icmlkeywords", "printAffiliationsAndNotice", "pacs", "ccsdesc", "received", "accepted",
    "correspondingauthor", "corresp", "authornote", "authorrunninghead", "titlerunninghead",
    "subjclass", "facilities", "software", "dedicatory",
]
FRONT_MATTER_ENVS = ["keywords", "IEEEkeywords", "CCSXML", "teaserfigure", "frontmatter"]
FLOAT_ENVS = [
    "figure", "table", "wrapfigure", "wraptable", "sidewaysfigure", "sidewaystable", "SCfigure",
    "subfigure", "algorithm", "algorithm2e", "algorithmic", "lstlisting", "listing", "minted",
    "verbatim", "Verbatim", "tabular", "tabularx", "tabulary", "longtable", "tabu", "deluxetable",
    "supertabular", "xtabular", "threeparttable", "tblr", "longtblr", "picture",
]
FLOAT_COMMANDS = ["caption", "captionof", "subcaption", "includegraphics"]
HEADINGS = ["part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph"]
# Layout and setup commands whose arguments are not text (pylatexenc would keep them: "fancy")
SETUP = [
    "pagestyle", "thispagestyle", "setlength", "addtolength", "setcounter", "addtocounter",
    "graphicspath", "vspace", "hspace", "linespread", "fontsize", "numberwithin", "hypersetup",
    "definecolor", "colorlet", "usetikzlibrary", "tikzset", "pgfplotsset", "theoremstyle",
    "newtheorem", "newenvironment", "renewenvironment", "newcounter", "newlength", "settowidth",
    "bibliographystyle", "pagenumbering", "markboth", "markright", "enlargethispage",
]
# TeX-style lengths without braces (\vskip 0.5cm, \baselineskip=17pt, \kern-.2ex) and \\[-8pt]
_LENGTH = re.compile(r"\\[a-zA-Z@]+\s*=?\s*-?(?:\d+\.?\d*|\.\d+)\s*(?:true)?"
                     r"(?:pt|cm|mm|in|ex|em|bp|pc|sp|dd|cc|mu)(?![a-zA-Z])|(?<=\\\\)\[[^\]]*\]")


# ------------------------------------------------------------------ finding commands and environments
def _command_spans(text: str, names: list[str]):
    """Yields (start, end, args) for every \\name with its directly following [..] and {..}
    arguments (and a *). args are the contents of the {..} arguments."""
    pat = re.compile(r"\\(?:%s)(?![a-zA-Z@])\*?" % "|".join(map(re.escape, names)))
    for m in pat.finditer(text):
        end, args = m.end(), []
        while True:
            j = _skip_ws(text, end)
            if j < len(text) and text[j] in "[{" and (e := _group_end(text, j, text[j])) > 0:
                if text[j] == "{":
                    args.append(text[j + 1:e - 1])
                end = e
            else:
                break
        yield m.start(), end, args


def _env_spans(text: str, names: list[str]):
    """Yields (start, end) of every \\begin{name}...\\end{name} (also starred), outermost only."""
    pat = re.compile(r"\\(begin|end)\{(%s)\*?\}" % "|".join(map(re.escape, names)))
    depth, start = Counter(), None
    for m in pat.finditer(text):
        if m[1] == "begin":
            if not depth.total():
                start = m.start()
            depth[m[2]] += 1
        elif depth[m[2]]:
            depth[m[2]] -= 1
            if not depth.total():
                yield start, m.end()


def _cut(text: str, spans) -> tuple[str, list[str]]:
    out, removed, i = [], [], 0
    for s, e, *_ in spans:
        if s < i:
            continue
        out.append(text[i:s])
        removed.append(text[s:e])
        i = e
    return "".join(out) + text[i:], removed


# ------------------------------------------------------------------ steps
def drop_appendix(text: str) -> tuple[str, list, list]:
    m = re.search(r"\\appendix(?![a-zA-Z@])|\\begin\{appendix|\\begin\{appendices\}", text)
    if m is None:
        return text, [], []
    return text[:m.start()], [text[m.start():]], []


def drop_front_matter(text: str) -> tuple[str, list, list]:
    text, envs = _cut(text, _env_spans(text, FRONT_MATTER_ENVS))
    text, commands = _cut(text, _command_spans(text, FRONT_MATTER))
    return text, envs + commands, []


def extract_tikz(text: str) -> tuple[str, list, list]:
    text, blocks = _cut(text, _env_spans(text, ["tikzpicture"]))
    return text, blocks, []


def drop_floats(text: str) -> tuple[str, list, list]:
    text, envs = _cut(text, _env_spans(text, FLOAT_ENVS))
    text, commands = _cut(text, _command_spans(text, FLOAT_COMMANDS))
    return text, envs + commands, []


def drop_layout(text: str) -> tuple[str, list, list]:
    text, commands = _cut(text, _command_spans(text, SETUP))
    text, lengths = _cut(text, ((m.start(), m.end()) for m in _LENGTH.finditer(text)))
    return text, commands + lengths, []


def drop_headings(text: str) -> tuple[str, list, list]:
    text, removed = _cut(text, _command_spans(text, HEADINGS))
    return text, removed, []


def move_footnotes(text: str) -> tuple[str, list, list]:
    """Each footnote goes, as its own paragraph, after the paragraph it was in."""
    paragraphs = re.split(r"\n[ \t]*\n", text)
    out, notes = [], []
    for p in paragraphs:
        spans = [(s, e, a) for s, e, a in _command_spans(p, ["footnote"]) if a]
        p, _ = _cut(p, spans)
        out.append(p)
        out += [a[-1] for _, _, a in spans]
        notes += [a[-1] for _, _, a in spans]
    return "\n\n".join(out), notes, []


# ------------------------------------------------------------------ plain text
def _with_ours(db, macros):
    db.add_context_category("ours", macros=macros, prepend=True)  # ours win over the defaults
    return db


_WALKER_DB = _with_ours(latexwalker.get_default_latex_context_db(),
                        [MacroSpec("href", "{{"), MacroSpec("url", "{"), MacroSpec("item", "[")])
_TEXT_DB = _with_ours(get_default_latex_context_db(),
                      [MacroTextSpec("href", simplify_repl="%(2)s"), MacroTextSpec("url", discard=True),
                       MacroTextSpec("item", simplify_repl=" ")])
_TO_TEXT = LatexNodes2Text(latex_context=_TEXT_DB, math_mode="verbatim")


def _paragraph_to_text(latex: str) -> str:
    nodes = latexwalker.LatexWalker(latex, latex_context=_WALKER_DB, tolerant_parsing=True)
    return _TO_TEXT.nodelist_to_text(nodes.get_latex_nodes()[0])


def clean(text: str) -> str:
    """As in the EMNLP 2026 paper (Register_Aware_LLMs, scripts/utils.py string_cleaning), per
    paragraph: one space between words, none before punctuation, NFKC."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,?!'])", r"\1", text)
    return unicodedata.normalize("NFKC", text)


def to_plain_text(text: str) -> tuple[str, list, list]:
    """removed: which commands were converted, with counts (to see what pylatexenc handled)."""
    commands = Counter(re.findall(r"\\([a-zA-Z@]+)", text))
    paragraphs, problems = [], []
    for p in re.split(r"\n[ \t]*\n", text):
        try:
            p = _paragraph_to_text(p)
        except Exception as e:  # pylatexenc on unusual input: drop the commands, keep the words
            problems.append(f"pylatexenc {type(e).__name__}: {p[:80]!r}")
            p = re.sub(r"\\[a-zA-Z@]+\*?|[{}]", " ", p)
        if not (p := clean(p)):
            continue
        # A blank line around display math splits a sentence: "... we get\n\nMATHEXPR,\n\nwhere x".
        # A paragraph starting with MATHEXPR, punctuation or a lowercase letter continues the last one.
        if paragraphs and re.match(rf"{MATH_TOKEN}|[a-z.,;:)]", p):
            paragraphs[-1] += " " + p
        else:
            paragraphs.append(p)
    removed = [{"command": c, "count": n} for c, n in commands.most_common()]
    return "\n\n".join(paragraphs), removed, problems
