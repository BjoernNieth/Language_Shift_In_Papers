"""Remove everything LaTeX never typesets as comment-like text, and keep it for the comment scan.

    from language_shift.latex_comments import remove_comments, remove_conditionals
    text, comments, problems = remove_comments(flat_text)       # step 1, whole file
    ...  split off the body, expand macros ...
    body, hidden, problems2 = remove_conditionals(body)         # after macro expansion

remove_comments runs first, on the whole flattened file: a commented-out %\\begin{document} must not
be taken for the real one. remove_conditionals runs after macro expansion: authors hide text with
macros like \\newcommand{\\hide}[1]{\\iffalse #1\\fi}; removing \\iffalse before expansion would empty
the definition and let the hidden text into the prose.

Removed and collected (`Comment.kind`):
  "line"     % comments, as TeX does: from % to the end of the line, including the newline
             ("foo%\\nbar" -> "foobar"). \\% is a percent sign. A line that is only a comment vanishes.
  "env"      \\begin{comment} ... \\end{comment}, and every environment declared with
             \\excludecomment{name}. As in the comment package, the rest of the \\begin line and of
             the \\end line are dropped too.
  "iffalse"  \\iffalse ... \\fi (the \\else branch, if any, stays), and the \\else branch of
             \\iftrue ... \\else ... \\fi. Nested conditionals inside are counted, so their \\fi
             doesn't end the block early.
Problems (unclosed environments or conditionals) are reported; the text from there on stays.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_COMMENT = re.compile(r"(?<!\\)(?:\\\\)*%")  # first % not escaped as \%
_EXCLUDE_DECL = re.compile(r"\\excludecomment\s*\{\s*([a-zA-Z*]+)\s*\}")
# Conditionals that need a \fi. \ifthenelse is a macro with arguments, not a TeX conditional, and
# \newif\ifx only declares one.
_COND = re.compile(r"(?<!\\newif)\\(if(?!thenelse\b)[a-zA-Z@]*|fi|else)(?![a-zA-Z@])")
_START = re.compile(r"\\(iffalse|iftrue)(?![a-zA-Z@])")


@dataclass
class Comment:
    kind: str  # "line" | "env" | "iffalse"
    text: str
    line: int  # line number (1-based) in the text where it started


@dataclass
class Problem:
    message: str
    line: int


def _line_comments_and_envs(text: str, envs: set[str]) -> tuple[str, list[Comment], list[Problem]]:
    out: list[str] = []
    comments: list[Comment] = []
    problems: list[Problem] = []
    begin = re.compile(r"\\begin\s*\{(" + "|".join(map(re.escape, sorted(envs))) + r")\}")
    lines = text.splitlines(keepends=True)
    k = 0
    while k < len(lines):
        line = lines[k]
        m = _COMMENT.search(line)
        code = line[: m.end() - 1] if m else line
        b = begin.search(code)
        if b:
            end = re.compile(r"\\end\s*\{" + re.escape(b[1]) + r"\}")
            for k2 in range(k + 1, len(lines)):
                if end.search(lines[k2]):
                    comments.append(Comment("env", "".join(lines[k + 1:k2]), k + 1))
                    out.append(code[: b.start()])
                    k = k2 + 1
                    break
            else:
                problems.append(Problem(f"no \\end{{{b[1]}}}", k + 1))
                out.append(line)
                k += 1
            continue
        if m:
            comments.append(Comment("line", line[m.end():].rstrip("\n"), k + 1))
            out.append(code)
        else:
            out.append(line)
        k += 1
    return "".join(out), comments, problems


def _conditionals(text: str, _unused=None) -> tuple[str, list[Comment], list[Problem]]:
    comments: list[Comment] = []
    problems: list[Problem] = []
    pos = 0

    def line_of(offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    while (s := _START.search(text, pos)) is not None:
        depth, else_at, fi = 0, None, None
        for c in _COND.finditer(text, s.end()):
            if c[1] == "fi":
                if depth == 0:
                    fi = c
                    break
                depth -= 1
            elif c[1] == "else":
                if depth == 0 and else_at is None:
                    else_at = c
            else:
                depth += 1
        if fi is None:
            problems.append(Problem(f"no \\fi for \\{s[1]}", line_of(s.start())))
            pos = s.end()
            continue
        first = text[s.end(): else_at.start() if else_at else fi.start()]
        second = text[else_at.end(): fi.start()] if else_at else ""
        dead, live = (first, second) if s[1] == "iffalse" else (second, first)
        if dead.strip():
            comments.append(Comment("iffalse", dead, line_of(s.start())))
        text = text[: s.start()] + live + text[fi.end():]
        pos = s.start()  # the live part is scanned again (it may contain more \iffalse)
    return text, comments, problems


def remove_comments(text: str) -> tuple[str, list[Comment], list[Problem]]:
    """% comments and comment environments (kinds "line", "env")."""
    envs = {"comment"} | set(_EXCLUDE_DECL.findall(text))
    return _line_comments_and_envs(text, envs)


def remove_conditionals(text: str) -> tuple[str, list[Comment], list[Problem]]:
    """\\iffalse ... \\fi and the \\else branch of \\iftrue (kind "iffalse"). Line numbers refer to
    the text passed in, after earlier blocks were removed."""
    return _conditionals(text, None)
