"""Tests for language_shift.latex_text: one small LaTeX input per step, written by hand.

    uv run pytest tests/test_latex_text.py -v
"""

from language_shift import latex_text as lt


def text(step, latex: str) -> str:
    return step(latex)[0]


def test_appendix_is_cut():
    assert text(lt.drop_appendix, "Main.\n\\appendix\n\\section{A} App.") == "Main.\n"
    assert text(lt.drop_appendix, "Main.\\begin{appendices}App.\\end{appendices}") == "Main."


def test_front_matter_goes_but_the_abstract_stays():
    latex = "\\title{T}\\author{A \\and B}\\maketitle\n\\begin{abstract}ABS\\end{abstract}" \
            "\\begin{keywords}K\\end{keywords}"
    out = text(lt.drop_front_matter, latex)
    assert out.strip() == "\\begin{abstract}ABS\\end{abstract}"


def test_tikz_is_taken_out_and_kept():
    out, removed, _ = lt.extract_tikz("A \\begin{tikzpicture}\\draw (0,0) -- ($(1,1)$);\\end{tikzpicture} B")
    assert out == "A  B" and removed == ["\\begin{tikzpicture}\\draw (0,0) -- ($(1,1)$);\\end{tikzpicture}"]


def test_floats_and_captions_go_nested_tables_too():
    latex = ("Before. \\begin{table}\\caption{CAP}\\begin{tabular}{l}\\begin{tabular}{l}x\\end{tabular}"
             "\\end{tabular}\\end{table} After \\includegraphics[width=2cm]{f.png} and \\caption{LOOSE}.")
    assert text(lt.drop_floats, latex) == "Before.  After  and ."


def test_layout_commands_and_lengths_go():
    assert text(lt.drop_layout, "a\\vspace{3mm} b \\vskip 1.truecm c \\pagestyle{fancy}d") == "a b  c d"


def test_headings_go_with_their_title():
    assert text(lt.drop_headings, "\\section*{Intro}\nText. \\paragraph{Setup.} More.") == "\nText.  More."


def test_footnote_becomes_the_next_paragraph():
    out = text(lt.move_footnotes, "We do it.\\footnote{A note.} Really.\n\nNext paragraph.")
    assert out == "We do it. Really.\n\nA note.\n\nNext paragraph."


def test_plain_text():
    latex = ("We use \\textit{deep}~nets -- see ``this'' by M\\\"uller \\href{http://x}{here}.\n\n"
             "\\begin{itemize}\\item One. \\item Two.\\end{itemize}\n\nMATHEXPR,\n\nwhere it holds.")
    assert text(lt.to_plain_text, latex) == (
        "We use deep nets – see “this” by Müller here.\n\nOne. Two. MATHEXPR, where it holds.")
