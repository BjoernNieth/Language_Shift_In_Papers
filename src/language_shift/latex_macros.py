"""Expand the author's own macros, with and without arguments, the way LaTeX does.

    from language_shift.latex_macros import expand_document
    text, skipped = expand_document(flat_text)      # definitions removed, uses expanded

or in parts:
    macros, skipped = find_macros(text)             # {"be": Macro(0, None, "\\begin{equation}"), ...}
    body = expand_macros(remove_definitions(body), macros)

Why: authors write \\be ... \\ee for \\begin{equation} ... \\end{equation} (18% of a first sample of 80
papers), wrap math in macros (\\Line{He}{ii}{4686} -> "He ii $\\lambda$4686") and put notes in macros
(\\fc{...} -> \\textcolor{purple}{François: ...}). Without expansion the math step misses math and the
prose loses or gains text.

Recognised definitions:
    \\newcommand{\\x}[n][default]{...}  (also \\newcommand\\x, \\renewcommand, \\providecommand,
    \\DeclareRobustCommand, starred forms)
    \\def\\x{...}  \\def\\x#1#2{...}
    \\DeclareMathOperator{\\x}{text}  ->  \\operatorname{text}
Not expanded, returned in `skipped`: \\def with delimited parameters (\\def\\x#1.{...}), whose
argument rules are TeX-specific.

Argument reading follows LaTeX: spaces before an argument are skipped; an argument is a {group} or a
single token (\\abs x -> x, \\abs\\alpha -> \\alpha); an optional first argument is [..] or the default.
After a macro *without* arguments, spaces and one newline are dropped, as TeX does ("\\eg is" prints
"e.g.is", which is why authors write "\\eg\\ is"). Expansion repeats until nothing changes, at most
MAX_ROUNDS times, and stops if the text grows beyond MAX_GROWTH times its size (recursive macros).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

MAX_ROUNDS = 10
MAX_GROWTH = 10

_NAME = r"[a-zA-Z@]+"
_DEF_START = re.compile(
    r"\\(?P<kind>(?:renew|provide|new)command|DeclareRobustCommand)\*?\s*"
    rf"(?:\{{\s*\\(?P<n1>{_NAME})\s*\}}|\\(?P<n2>{_NAME}))"
    rf"|\\(?P<kind2>def)\s*\\(?P<n3>{_NAME})(?P<params>[^{{}}\n]{{0,40}}?)(?=\{{)"
    rf"|\\(?P<kind3>DeclareMathOperator)\*?\s*\{{\s*\\(?P<n4>{_NAME})\s*\}}"
)


@dataclass
class Macro:
    nargs: int
    default: str | None  # default of an optional first argument, None if it has none
    body: str


# ------------------------------------------------------------------ reading LaTeX
def _skip_ws(text: str, i: int) -> int:
    """Skips spaces/tabs and one newline, never a paragraph break (empty line)."""
    seen_nl = False
    while i < len(text) and text[i] in " \t\n":
        if text[i] == "\n":
            if seen_nl:
                break
            seen_nl = True
        i += 1
    return i


def _group_end(text: str, i: int, open_: str = "{") -> int:
    """i points at "{" or "[": index after the matching "}" / "]", or -1. Skips escaped characters.
    For [..] only a ] outside braces counts, as in LaTeX ([a{]}b] is one optional argument)."""
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if open_ == "{" and depth == 0:
                return j + 1
        elif c == "]" and open_ == "[" and depth == 0:
            return j + 1
        j += 1
    return -1


def _token_end(text: str, i: int) -> int:
    """End of a single-token argument starting at i: a control sequence or one character."""
    if text[i] == "\\":
        j = i + 1
        if j < len(text) and (text[j].isalpha() or text[j] == "@"):
            while j < len(text) and (text[j].isalpha() or text[j] == "@"):
                j += 1
            return j
        return min(j + 1, len(text))
    return i + 1


# ------------------------------------------------------------------ definitions
def _parse_def(text: str, m: re.Match) -> tuple[str, Macro | None, int, str]:
    """(name, macro or None if skipped, end of the whole definition or -1, skip reason)."""
    name = m["n1"] or m["n2"] or m["n3"] or m["n4"]
    i = m.end()
    if m["kind3"]:  # \DeclareMathOperator{\x}{text}
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != "{" or (end := _group_end(text, i)) < 0:
            return name, None, -1, "unparsable"
        return name, Macro(0, None, "\\operatorname{" + text[i + 1:end - 1] + "}"), end, ""
    if m["kind2"]:  # \def\x<params>{body}
        params = m["params"].strip()
        if i >= len(text) or text[i] != "{" or (end := _group_end(text, i)) < 0:
            return name, None, -1, "unparsable"
        if params and not re.fullmatch(r"(#\d)+", params):
            return name, None, end, f"delimited parameters {params!r}"
        return name, Macro(len(params) // 2, None, text[i + 1:end - 1]), end, ""
    # \newcommand family
    nargs, default = 0, None
    i = _skip_ws(text, i)
    if i < len(text) and text[i] == "[":
        e = _group_end(text, i, "[")
        if e < 0 or not text[i + 1:e - 1].strip().isdigit():
            return name, None, -1, "unparsable"
        nargs = int(text[i + 1:e - 1])
        i = _skip_ws(text, e)
        if i < len(text) and text[i] == "[":
            e = _group_end(text, i, "[")
            if e < 0:
                return name, None, -1, "unparsable"
            default = text[i + 1:e - 1]
            i = _skip_ws(text, e)
    if i >= len(text) or text[i] != "{" or (end := _group_end(text, i)) < 0:
        return name, None, -1, "unparsable"
    return name, Macro(nargs, default, text[i + 1:end - 1]), end, ""


def find_macros(text: str) -> tuple[dict[str, Macro], list[tuple[str, str]]]:
    """All macro definitions in text (give preamble + body). Later definitions win.
    Returns (macros, skipped) with skipped = [(name, reason)]."""
    macros: dict[str, Macro] = {}
    skipped: list[tuple[str, str]] = []
    for m in _DEF_START.finditer(text):
        name, macro, _, reason = _parse_def(text, m)
        if macro is None:
            skipped.append((name, reason))
        else:
            macros[name] = macro
    return macros, skipped


def remove_definitions(text: str, names: Collection[str] | None = None) -> str:
    """Removes the definitions themselves, so their bodies (with #1 etc.) don't end up in the text.
    Only those of `names` if given."""
    out, i = [], 0
    for m in _DEF_START.finditer(text):
        if m.start() < i:
            continue
        name, _, end, _ = _parse_def(text, m)
        if end > 0 and (names is None or name in names):
            out.append(text[i:m.start()])
            # A definition on its own line takes its newline with it; otherwise an empty line
            # (a paragraph break) would be left behind.
            if m.start() == 0 or text[m.start() - 1] == "\n":
                end = re.compile(r"[ \t]*\n?").match(text, end).end()
            i = end
    out.append(text[i:])
    return "".join(out)


# ------------------------------------------------------------------ expansion
def _substitute(body: str, args: list[str]) -> str:
    def rep(m: re.Match) -> str:
        if m[0] == "##":
            return "#"
        k = int(m[0][1]) - 1
        return args[k] if k < len(args) else m[0]
    return re.sub(r"##|#[1-9]", rep, body)


def _with_separator(body: str) -> str:
    """A result ending in a command name (\\alpha) needs a space, or it would merge with the next
    letters (\\alphax)."""
    return body + " " if re.search(rf"\\{_NAME}$", body) else body


def _read_args(text: str, j: int, mac: Macro) -> tuple[list[str], int] | None:
    """Reads mac.nargs arguments starting at j. None if they are not all there."""
    args: list[str] = []
    for k in range(mac.nargs):
        j = _skip_ws(text, j)
        if k == 0 and mac.default is not None:
            if j < len(text) and text[j] == "[" and (e := _group_end(text, j, "[")) > 0:
                args.append(text[j + 1:e - 1])
                j = e
            else:
                args.append(mac.default)
            continue
        if j >= len(text) or text[j] == "}" or text[j] == "\n":
            return None
        if text[j] == "{":
            e = _group_end(text, j)
            if e < 0:
                return None
            args.append(text[j + 1:e - 1])
        else:
            e = _token_end(text, j)
            args.append(text[j:e])
        j = e
    return args, j


def _expand_once(text: str, macros: dict[str, Macro], pat: re.Pattern) -> str:
    out, i = [], 0
    for m in pat.finditer(text):
        if m.start() < i:
            continue
        mac = macros[m[1]]
        if mac.nargs == 0:
            out.append(text[i:m.start()])
            out.append(_with_separator(mac.body))
            i = _skip_ws(text, m.end())
            continue
        read = _read_args(text, m.end(), mac)
        if read is None:  # not enough arguments: leave this use as it is
            continue
        args, j = read
        out.append(text[i:m.start()])
        out.append(_with_separator(_substitute(mac.body, args)))
        i = j
    out.append(text[i:])
    return "".join(out)


def expand_macros(text: str, macros: dict[str, Macro]) -> str:
    if not macros:
        return text
    names = sorted(macros, key=len, reverse=True)
    pat = re.compile(r"\\(" + "|".join(map(re.escape, names)) + r")(?![a-zA-Z@])")
    limit = MAX_GROWTH * max(len(text), 1000)
    for _ in range(MAX_ROUNDS):
        new = _expand_once(text, macros, pat)
        if new == text or len(new) > limit:
            break
        text = new
    return text


def expand_document(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Find all definitions in text, remove them and expand all uses. Text should have no comments."""
    macros, skipped = find_macros(text)
    return expand_macros(remove_definitions(text), macros), skipped
