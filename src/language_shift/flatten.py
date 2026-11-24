"""Flatten a LaTeX project into one file with latexpand (TeX Live), keeping `%` comments.

    text, missing = flatten(root, Path("main.tex"))

Steps:
1. Refuse projects that \\input a file outside their folder (latexpand would read it).
2. Expand the author's \\input wrappers, e.g. \\newcommand{\\sec}[1]{\\input{sections/#1}}, in the
   main file. latexpand does not see through them.
3. Run latexpand. It inlines \\input, \\include and \\import, skips commented-out ones and honours
   \\endinput. It does not handle \\subfile; those stay as they are.
All other macros are expanded later, on the flat text (latex_macros.expand_document).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from language_shift.latex_macros import expand_macros, find_macros, remove_definitions

TIMEOUT = 60  # seconds; latexpand recurses forever on a file that inputs itself

_INCLUDES_A_FILE = re.compile(r"\\(?:input|include|subfile)(?![a-zA-Z@])")
# An uncommented \input{/abs/path} or \input{../x} (also \include, \import, \subimport)
_OUTSIDE = re.compile(
    r"(?m)^[^%\n]*\\(?:input|include|import|subimport)\*?\s*\{\s*(?:/|(?:[^{}]*/)?\.\./)")
_NOT_FOUND = re.compile(r"Could not find file \[(.*)\]")


class FlattenError(Exception):
    pass


def read_tex(path: Path) -> str:
    return decode(path.read_bytes())


def encoding(data: bytes) -> str:
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"  # common in pre-2010 sources


def decode(data: bytes) -> str:
    return data.decode(encoding(data))


def expand_input_wrappers(text: str) -> str:
    """Replaces calls of macros that \\input a file by that \\input, and drops their definitions."""
    macros, _ = find_macros(text)
    wrappers = {name: m for name, m in macros.items() if _INCLUDES_A_FILE.search(m.body)}
    return expand_macros(remove_definitions(text, wrappers), wrappers)


def flatten(root: Path, main: Path) -> tuple[str, list[str]]:
    """Returns the flat text of root/main and the include names latexpand could not find."""
    for f in root.rglob("*.tex"):
        if _OUTSIDE.search(read_tex(f)):
            raise FlattenError(f"{f.relative_to(root)} includes a file outside the paper folder")

    # latexpand reads only files, so the prepared main file goes next to the original, in the
    # original's encoding (included files may share it).
    data = (root / main).read_bytes()
    prepared = (root / main).with_name(".flatten-main.tex")
    prepared.write_bytes(expand_input_wrappers(decode(data)).encode(encoding(data)))
    try:
        r = subprocess.run(["latexpand", "--keep-comments", prepared.name], cwd=prepared.parent,
                           capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise FlattenError("latexpand timed out (a file that inputs itself?)") from None
    finally:
        prepared.unlink()
    if r.returncode != 0:
        raise FlattenError(f"latexpand failed: {decode(r.stderr).strip()}")
    missing = [n for n in _NOT_FOUND.findall(decode(r.stderr)) if "#" not in n]
    return decode(r.stdout), missing
