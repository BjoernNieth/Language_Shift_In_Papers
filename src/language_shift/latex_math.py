"""Find math in LaTeX prose, cut it out, and put a placeholder word in its place.

    from language_shift.latex_math import replace_math
    text, maths, problems = replace_math(body)

"Let $f(x)$ be convex. Then \\[ f(y) \\ge 0. \\]"  ->  "Let MATHEXPR be convex. Then MATHEXPR."

Input: LaTeX *without comments* (strip them first: a `$` inside a comment would pair with a real one).
Output: the text with every math span replaced by MATH_TOKEN, a list of the cut-out spans (`Math`, for
the math-style features) and a list of problems (unbalanced delimiters), which leave the text unchanged
from that point on the same paragraph.

Recognised math:
  inline   $...$   \\(...\\)   \\begin{math}...\\end{math}
  display  $$...$$   \\[...\\]   \\begin{<env>}...\\end{<env>} for env in DISPLAY_ENVS (also starred)
Skipped without change: \\$ (a dollar sign), verbatim-like environments and \\verb|...|, whose content is
not LaTeX.

Display math often ends with the sentence's punctuation inside it ("\\[ x = y. \\]"). That punctuation
is moved after the placeholder, so sentence splitting still sees the end of the sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MATH_TOKEN = "MATHEXPR"  # one fixed word; how spaCy tags it is checked in the dev notebook

DISPLAY_ENVS = ["equation", "align", "alignat", "flalign", "gather", "multline", "eqnarray",
                "displaymath", "dmath", "dgroup", "darray", "subequations"]
INLINE_ENVS = ["math"]
VERBATIM_ENVS = ["verbatim", "Verbatim", "lstlisting", "minted", "alltt", "comment"]

_ENV_RE = re.compile(r"\\begin\s*\{(?P<name>[a-zA-Z]+)(?P<star>\*?)\}")
_ENSUREMATH_RE = re.compile(r"\\ensuremath\s*\{")


def _group_end(text: str, i: int) -> int:
    """i points at "{": index after the matching "}", or -1."""
    depth = 0
    j = i
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


_VERB_RE =re.compile(r"\\verb\*?(?P<d>[^a-zA-Z\s])")
_TRAILING_PUNCT = re.compile(r"([.,;:!?])(?:\s|\\[,;:!> ]|\\q?quad\b|~|\\hfill\b)*$")


@dataclass
class Math:
    kind: str    # "inline" | "display"
    delim: str   # "$", "$$", "\\(", "\\[", or the environment name ("align*")
    latex: str   # the content between the delimiters
    start: int   # offset in the input text


@dataclass
class Problem:
    message: str
    start: int


def _skip_command(text: str, i: int) -> int:
    """i points at a backslash: return the index after the control sequence."""
    if i + 1 >= len(text):
        return i + 1
    if text[i + 1].isalpha():
        j = i + 1
        while j < len(text) and text[j].isalpha():
            j += 1
        return j
    return i + 2  # \$, \\, \[, \{ ... : two characters


def _find_closing(text: str, i: int, closer: str) -> int:
    """Index of `closer` ("$", "$$", "\\)", "\\]") at or after i, skipping escaped characters
    (\\$ is a dollar sign, \\\\[2pt] is a line break). Only counts a closer outside braces, so
    $x \\text{ if $y$}$ closes at the last $. -1 if not found."""
    depth = 0
    while i < len(text):
        if depth == 0 and text.startswith(closer, i):
            return i
        if closer == "$" and text.startswith("\n\n", i):  # inline math never spans a paragraph
            return -1
        if text[i] == "\\":
            i = _skip_command(text, i)
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}" and depth > 0:
            depth -= 1
        i += 1
    return -1


def _find_env_end(text: str, i: int, name: str) -> tuple[int, int]:
    """(start, end) of the \\end{name} matching a \\begin{name} that ended at i. Counts nesting."""
    pat = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
    depth = 1
    for m in pat.finditer(text, i):
        depth += 1 if m[1] == "begin" else -1
        if depth == 0:
            return m.start(), m.end()
    return -1, -1


_LABEL = re.compile(r"\\(label|tag\*?|nonumber|notag)\b\s*(\{[^{}]*\})?")


def _placeholder(latex: str, kind: str) -> str:
    """Display math gets spaces around it (it may sit between two words without any). Whitespace
    is normalised at the end of the pipeline, not here."""
    if kind == "display":
        m = _TRAILING_PUNCT.search(_LABEL.sub("", latex).strip())
        if m:
            return f" {MATH_TOKEN}{m[1]} "
        return f" {MATH_TOKEN} "
    return MATH_TOKEN


def replace_math(text: str) -> tuple[str, list[Math], list[Problem]]:
    out: list[str] = []
    maths: list[Math] = []
    problems: list[Problem] = []
    i, n = 0, len(text)

    def take(kind: str, delim: str, content_start: int, content_end: int, after: int):
        nonlocal i
        latex = text[content_start:content_end]
        maths.append(Math(kind, delim, latex, i))
        out.append(_placeholder(latex, kind))
        i = after

    while i < n:
        c = text[i]
        if c == "\\":
            if text.startswith("\\(", i) or text.startswith("\\[", i):
                closer = "\\)" if text[i + 1] == "(" else "\\]"
                j = _find_closing(text, i + 2, closer)
                if j < 0:
                    problems.append(Problem(f"no closing {closer}", i))
                    out.append(text[i:i + 2]); i += 2
                    continue
                take("inline" if closer == "\\)" else "display", text[i:i + 2], i + 2, j, j + 2)
                continue
            em = _ENSUREMATH_RE.match(text, i)
            if em:  # \ensuremath{...} is math wherever it stands
                e = _group_end(text, em.end() - 1)
                if e > 0:
                    take("inline", "\\ensuremath", em.end(), e - 1, e)
                    continue
            m = _ENV_RE.match(text, i)
            if m:
                name, full = m["name"], m["name"] + m["star"]
                if name in DISPLAY_ENVS or name in INLINE_ENVS or name in VERBATIM_ENVS:
                    s, e = _find_env_end(text, m.end(), full)
                    if s < 0:
                        problems.append(Problem(f"no \\end{{{full}}}", i))
                        out.append(m[0]); i = m.end()
                        continue
                    if name in VERBATIM_ENVS:
                        out.append(text[i:e]); i = e
                    else:
                        take("inline" if name in INLINE_ENVS else "display", full, m.end(), s, e)
                    continue
            v = _VERB_RE.match(text, i)
            if v:
                j = text.find(v["d"], v.end())
                j = n - 1 if j < 0 else j
                out.append(text[i:j + 1]); i = j + 1
                continue
            j = _skip_command(text, i)
            out.append(text[i:j]); i = j
            continue
        if c == "$":
            double = text.startswith("$$", i)
            closer = "$$" if double else "$"
            j = _find_closing(text, i + len(closer), closer)
            if j < 0:
                problems.append(Problem(f"no closing {closer}", i))
                out.append(closer); i += len(closer)
                continue
            take("display" if double else "inline", closer, i + len(closer), j, j + len(closer))
            continue
        out.append(c)
        i += 1

    return "".join(out), maths, problems
