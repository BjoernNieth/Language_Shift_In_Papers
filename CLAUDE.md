# Language Shift in Papers

Has AI changed how papers are written? We test whether LLMs changed **register** (Biber features), **TikZ** use and
**math style** in arXiv LaTeX sources (2005–2026), beyond the word-level shifts already reported (Liang et al. 2024,
Kobak et al. 2024), and whether the change tracks each field's LLM use.

- **Target:** ACL 2027 via ARR (deadline early Jan 2027, check the exact date). Fallback: EMNLP 2027.
- **Plan:** `docs/research-plan.md` is the source of truth for hypotheses (H1 register, H2 TikZ, H3 paraphrase
  stability, exploratory math, comment scan), design, risks and the six-week timeline. Update it when the design
  changes. Don't let code and plan drift apart.
- **People:** Björn (first author), supervised by Emmanuelle. Amro's master project was the pilot. Credit it in the
  paper; this repo is a new design from scratch, not his code.
- **Second Brain:** project *Linguistics*. Background in `~/Documents/Second_Brain/wiki/ideas.md` and
  `wiki/publications/biber-register-aware-evaluation.md` (the EMNLP 2026 paper whose feature set and MMD method we
  reuse). Sessions are summarized into the vault's daily log, so state report-worthy outcomes clearly.

## Pipeline (planned)
`sample → download → parse → features → analysis`, one script per stage. Each stage reads the previous stage's
output from disk, is resumable, and skips work already done.

1. **Sample:** stratified 1000 papers per field per year (raised from 500 on 2026-11-24), 2005–2026 (extended from 2018 on 2026-11-24), fields CS, physics, math (each the whole arXiv group).
   Seed, first and last v1 date, fields and papers per field-year are in `config.toml`; `uv run python -m language_shift.sample`
   ranks every paper of the fields and years in `data/sample/candidates.csv` (2.7M rows, not committed; drawn fresh at every download start). A paper's rank depends only on
   the seed and its own field-year, so ranks
   never change: the download takes candidates in rank order until n LaTeX papers per field-year, so raising n
   keeps the first n. Every prefix has the subfields (primary categories) in that year's proportions. The
   download's record of the candidates it tried, with their status, is `sample/papers.csv` (committed).
2. **Download:** LaTeX sources of **v1 only** (later versions may be LLM-edited). From `export.arxiv.org`, one
   request per second (arXiv's bulk-data guidance; OAI-PMH metadata keeps the API's 3 seconds), a single
   connection, a descriptive User-Agent without personal data. `uv run python -m language_shift.download` only
   downloads and unpacks (a LaTeX paper = a .tex file with `\documentclass`; main file and flattening belong to
   parsing). It takes the candidates in rank order until n LaTeX papers per field-year and appends each one tried
   to `sample/papers.csv`; restarts continue from there. Temporary errors retry the same paper with growing
   pauses (never a tight loop); PDF-only, missing sources and unparsable archives move on to the next candidate.
3. **Parse:** LaTeX → plain prose (drop math, citations, floats); extract TikZ blocks, math environments and
   `%` comments separately. Keep the parser deterministic and test it on a handful of real sources.
   Steps are listed in `src/language_shift/pipeline.py` (`STEPS`); `uv run python -m language_shift.pipeline <id>v1`
   prints a per-step trace, writes every intermediate text to `data/trace/<id>/` and the final prose to
   `data/prose/<id>.txt`. `uv run python -m language_shift.tag` turns that into Biber features per window
   (`data/features/biber/<id>.parquet`). pybiber 0.3.1 needs `polars<2`.
4. **Features:** Biber features on fixed-length prose chunks, TikZ prevalence/counts/style, math macro and
   environment counts per 1k tokens. Biber code from the EMNLP 2026 paper:
   `github.com/BjoernNieth/Register_Aware_LLMs` (`scripts/02_get_biber_features.py`, `scripts/01_prepare_data.py`
   for the 400-word windows). It used `pybiber==0.2.0` + spaCy `en_core_web_trf`, re-creating `CorpusProcessor`
   per batch to avoid an inflated `f_23_wh_clause`. This study uses the newest pybiber (0.3.1+); numbers need
   not match the EMNLP paper (0.3.1 changed `f_13` and the default of `f_19`). Keep the `f_23` sanity check.
5. **Analysis:** MMD between years and against the pre-2022 reference, normalised by a permutation chance
   distribution; interrupted time series for TikZ; dose–response against field LLM use; paraphrase test.

## Data
- Raw sources, parsed text and feature tables live in `data/` (gitignored). Never commit downloaded papers.
- Commit code, the ID lists, small result tables and figures.

## Running
- Python with `uv` (`uv run python …`), dependencies in `pyproject.toml`, as in Björn's other repos.
- Flattening calls `latexpand` from TeX Live (tested with v1.7.2); it must be on the PATH.
- Sampling, download and parsing run on the Mac. The paraphrase test (open LLMs rewriting paragraphs) runs on the
  NHR@FAU clusters: use the `/hpc` skill (needs a `.hpc.toml` in this repo).

## Results and claims
- Record every result in `RESULTS.md` with date, command/commit, n and p-values. Correct earlier entries visibly
  (note the correction), don't silently rewrite them.
- Every figure and table is produced by a script in the repo.
- Guard against the known confounds before claiming an AI effect: topic drift (papers *about* LLMs, esp. `cs.CL`),
  templates and copied TikZ (deduplicate), pre-existing trends (compare against the 2018–2022 trend, not just
  before/after). Null results are reportable findings; say so rather than hunting for significance.
