"""Citations, cross-references, labels and the bibliography.

    from language_shift.latex_refs import replace_refs
    text, refs, problems = replace_refs(body)

"as shown by \\citet{smith20} in Figure~\\ref{fig:a}"  ->  "as shown by CITEREF in Figure~XREF"

Run after macro expansion (\\figref{x} may expand to Figure~\\ref{x}) and after the math step (a \\ref
inside an equation stays part of the stored math).

  citations   -> CITE_TOKEN   \\cite, \\citep, \\citet, \\parencite, \\textcite, ... (CITE_COMMANDS)
  references  -> REF_TOKEN    \\ref, \\eqref, \\autoref, \\cref, ... (REF_COMMANDS)
  removed     -> nothing      \\label, \\nocite, \\bibliography, \\bibliographystyle,
                              \\printbibliography, \\addbibresource, thebibliography environment
One placeholder per command, however many keys it has (\\cite{a,b,c} is one bracket in the text).
Optional arguments ([see][p.~5]) go with the command. Starred forms are included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from language_shift.latex_macros import _group_end, _skip_ws

CITE_TOKEN = "CITEREF"
REF_TOKEN = "XREF"

CITE_COMMANDS = [
    "cite", "citep", "citet", "citealp", "citealt", "citeauthor", "citeyear", "citeyearpar",
    "citenum", "citetext", "shortcite", "parencite", "textcite", "autocite", "footcite",
    "smartcite", "supercite", "fullcite", "Cite", "Citep", "Citet", "Citealp", "Citealt",
    "Citeauthor", "Parencite", "Textcite", "Autocite",
    "onlinecite", "citeN", "citeA", "citeNP", "citeyearNP", "citeasnoun", "citealias",
    "citepalias", "citetalias",                                    # REVTeX, ACM, apacite, natbib
    "cites", "parencites", "textcites", "autocites", "footcites",  # biblatex: several {keys}
]
MULTI_CITE = {"cites", "parencites", "textcites", "autocites", "footcites"}
REF_COMMANDS = [
    "ref", "eqref", "autoref", "Autoref", "cref", "Cref", "crefrange", "Crefrange", "pageref",
    "nameref", "vref", "Vref", "subref", "labelcref", "cpageref", "Cpageref",
    "eref", "Eref", "fref", "Fref", "sref", "Sref", "tref", "Tref",  # IOP journal classes
]
# footnote marks in title/author blocks (elsarticle, IEEEtran)
REMOVE_COMMANDS = ["label", "nocite", "bibliography", "bibliographystyle", "addbibresource",
                   "tnoteref", "fnref", "corref", "IEEEauthorrefmark"]
REMOVE_NO_ARG = ["printbibliography"]

_ALL = sorted(CITE_COMMANDS + REF_COMMANDS + REMOVE_COMMANDS + REMOVE_NO_ARG, key=len, reverse=True)
_CMD = re.compile(r"\\(" + "|".join(_ALL) + r")(?![a-zA-Z@])(\*?)")
_BIB_ENV = re.compile(r"\\begin\s*\{thebibliography\}.*?\\end\s*\{thebibliography\}", re.S)


@dataclass
class Ref:
    kind: str     # "cite" | "ref" | "removed"
    command: str  # e.g. "citep", "label"
    keys: str     # the mandatory argument, e.g. "smith20,jones21"
    start: int    # offset in the text passed in (after the bibliography was cut)


@dataclass
class Problem:
    message: str
    start: int


def replace_refs(text: str) -> tuple[str, list[Ref], list[Problem]]:
    refs: list[Ref] = []
    problems: list[Problem] = []

    def cut_bib(m: re.Match) -> str:
        refs.append(Ref("removed", "thebibliography", "", m.start()))
        return ""

    text = _BIB_ENV.sub(cut_bib, text)

    def own_line_end(start: int, end: int) -> int:
        """A removed command alone on its line takes the newline with it, so no empty line
        (= paragraph break) is left behind."""
        line_start = text.rfind("\n", 0, start) + 1
        if text[line_start:start].strip():
            return end
        return re.compile(r"[ \t]*\n?").match(text, end).end()

    out: list[str] = []
    i = 0
    for m in _CMD.finditer(text):
        if m.start() < i:
            continue
        name = m[1]
        j = m.end()
        while (k := _skip_ws(text, j)) < len(text) and text[k] == "[":  # optional arguments
            e = _group_end(text, k, "[")
            if e < 0:
                break
            j = e
        if name in REMOVE_NO_ARG:
            refs.append(Ref("removed", name, "", m.start()))
            out.append(text[i:m.start()])
            i = own_line_end(m.start(), j)
            continue
        j = _skip_ws(text, j)
        if j >= len(text) or text[j] != "{" or (e := _group_end(text, j)) < 0:
            problems.append(Problem(f"\\{name} without {{argument}}", m.start()))
            continue
        keys = text[j + 1:e - 1].strip()
        if name in MULTI_CITE:  # \cites[pre][post]{a}[pre][post]{b}: read all groups
            while True:
                k = _skip_ws(text, e)
                while k < len(text) and text[k] == "[" and (ke := _group_end(text, k, "[")) > 0:
                    k = _skip_ws(text, ke)
                if k >= len(text) or text[k] != "{" or (ke := _group_end(text, k)) < 0:
                    break
                keys += "," + text[k + 1:ke - 1].strip()
                e = ke
        if name in CITE_COMMANDS:
            kind, repl = "cite", CITE_TOKEN
        elif name in REF_COMMANDS:
            kind, repl = "ref", REF_TOKEN
        else:
            kind, repl = "removed", ""
        refs.append(Ref(kind, name, keys, m.start()))
        out.append(text[i:m.start()])
        out.append(repl)
        i = own_line_end(m.start(), e) if kind == "removed" else e
    out.append(text[i:])
    return "".join(out), refs, problems
