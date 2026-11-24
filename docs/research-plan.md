# Has AI changed how we write papers? Register, TikZ and math in arXiv LaTeX sources

*Research plan · draft 2026-11-17 · target ACL 2027 (ARR, deadline ~early Jan 2027 — check), fallback EMNLP 2027*

## Question
Since ChatGPT (Nov 2022), word choice in scientific writing has shifted measurably ("delve", "intricate"; Liang et al. 2024, Kobak et al. 2024). These studies look only at **words** in **abstracts and introductions**. We ask whether LLMs have also changed **grammar and register**, and **non-prose parts of papers** (TikZ figures, math), and whether these changes track how much each field uses LLMs.

Amro's master project (2026) was a pilot on this question (Biber features + MMD over years, paraphrase test). It showed the question is answerable but could not separate AI influence from ordinary drift. This study is a new design from scratch.

## Hypotheses
- **H1 – Register:** after 2022, the year-to-year shift in Biber features (MMD against a chance baseline) exceeds the pre-2022 drift, and the excess is largest in fields with high LLM use.
- **H2 – TikZ:** the share of papers with TikZ figures (and TikZ figures per paper) rises above the extrapolated 2018–2022 trend, most in high-LLM-use fields. LLMs make TikZ cheap to write.
- **H3 – Paraphrase stability:** LLM rewriting changes recent texts less than older ones, most in high-LLM-use fields (same principle as rewriting-based AI-text detection, Mao et al. 2024, RAIDAR).
- **Exploratory – Math:** LaTeX math style (environments, macros, `\left…\right`, `\operatorname`, macro density). No fixed hypothesis.
- **Bonus – Comments:** LaTeX comments are never published, so leftover prompts or LLM output there is direct evidence. Cheap to scan.

## Design
- **Corpus:** arXiv LaTeX sources, stratified sample of 1000 papers per field per year (raised from 500 on 2026-11-24), 2005–2026 (extended from 2018–2026 on 2026-11-24 for a longer pre-LLM baseline), **v1 only** (revisions of old papers may be LLM-edited later). Downloaded one by one through the arXiv API at the allowed rate (66 field-years × 1000 = 66k LaTeX papers ≈ 2–3 days, ≈ 280 GB at one request per second). Existing corpora (RedPajama-arXiv, unarXive) stop around 2023 or strip comments and LaTeX.
- **Fields** (by LLM use as in Liang et al. 2024): CS (high), physics (medium), math (low), each the whole arXiv group by primary category (decided 2026-11-24; subfield mix is controlled in the analysis), plus possibly one field with little TikZ so far.
- **Features:**
  - Prose: LaTeX → plain text, the Biber feature set from the EMNLP 2026 paper, fixed-length chunks.
    Parsing decisions (2026-11-19): inline math → placeholder word; `\cite`/`\ref` → placeholder words
    (keeps sentences grammatical for the POS-based features); text after `\appendix` is cut; floats are
    dropped from the prose, their captions go to a separate field (may be combined with prose later).
    Revised 2026-11-23: captions are dropped too (no separate field); the abstract and all main text are
    kept; front matter (title, authors, affiliations, keywords) and headings are dropped; footnotes go
    into the text as a paragraph after the one they belong to. Prose is cut into consecutive windows of
    whole sentences (>400 words, cap 440, as in the EMNLP 2026 paper); a last shorter window is dropped.
  - TikZ: prevalence and count, TikZ vs. `\includegraphics`, code length; second stage: style features (comments, `\tikzset`/`every node/.style`, libraries, coordinate precision).
  - Math: environment and macro counts per 1k tokens.
- **Analysis:**
  - MMD between consecutive years and against a pre-2022 reference, normalised by a permutation chance distribution, as in the Biber paper.
  - TikZ: interrupted time series (trend 2018–2022 vs. 2023–2026) per field.
  - Dose–response: effect size against field LLM-use estimates.
- **Paraphrase test:** current open models on the cluster rewrite sampled paragraphs; Biber-feature distance between original and rewrite, by year and field.

## Main risks and how to handle them
- **Topic drift:** papers *about* LLMs read differently from papers *written with* LLMs, especially in `cs.CL`. Control by comparing within subfields, or excluding LLM-topic papers by keywords. Math and physics are not affected.
- **Templates and copied TikZ:** Overleaf templates and reused figures shift features without AI. Partly absorbed by the field comparison; deduplicate TikZ blocks across papers.
- **Pre-existing TikZ growth:** handled by the trend extrapolation, not a before/after contrast.
- **Null results:** "words changed, register didn't" is itself a finding. The paper stays reportable.
- **Scope:** prose (H1, H3) is the core result. TikZ (H2) is the second contribution, math and comments are extras that can be dropped.

## Timeline (6 weeks, BMFTR sketch due 30.11 in parallel)
| Week | Work |
|---|---|
| 18–24 Nov | Sampling and download script; download overnight |
| 25 Nov–1 Dec | LaTeX parsing; Biber, TikZ and math features (BMFTR deadline 30.11) |
| 2–8 Dec | MMD with chance baseline; TikZ time series; comment scan |
| 9–15 Dec | Paraphrase test on the cluster; dose–response analysis |
| 16–22 Dec | Writing |
| early Jan | Polish and submit |

## To discuss with Emmanuelle
- Is this the right "safe" paper for ACL, compared with the Biber-guided writing agent (with Jan)?
- Authorship, and how to credit Amro's pilot.
- Fields: add a field with little TikZ? (Physics: all of physics by primary category, decided 2026-11-24.)
- ~~Is ~500 papers per field-year enough?~~ Raised to 1000 per field-year (2026-11-24).

## Key references
- Liang et al. 2024, *Mapping the Increasing Use of LLMs in Scientific Papers* (COLM). Field-level LLM-use estimates; numbers to be checked.
- Kobak et al. 2024, excess vocabulary in PubMed abstracts after ChatGPT.
- Mao et al. 2024, RAIDAR: AI-text detection via rewriting.
- Björn's EMNLP 2026 Biber paper: feature set and MMD method.
- Not yet in Zotero: all three external papers above.
