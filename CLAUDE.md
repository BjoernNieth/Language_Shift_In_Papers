# Language Shift in Papers

Has AI changed how papers are written? We test whether LLMs changed **register** (Biber features), **TikZ** use and
**math style** in arXiv LaTeX sources (2018–2026), beyond the word-level shifts already reported (Liang et al. 2024,
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

1. **Sample:** stratified ~500 papers per field per year, 2018–2026, fields CS (`cs.CL`/`cs.LG`), physics, math.
   Fixed seed. The list of sampled arXiv IDs is committed (small, makes the corpus reproducible).
2. **Download:** LaTeX sources of **v1 only** (later versions may be LLM-edited). arXiv's API rules: at most one
   request every 3 seconds, a single connection, a descriptive User-Agent without personal data. Log failures and
   PDF-only papers, don't retry in a tight loop.
3. **Parse:** LaTeX → plain prose (drop math, citations, floats); extract TikZ blocks, math environments and
   `%` comments separately. Keep the parser deterministic and test it on a handful of real sources.
4. **Features:** Biber features on fixed-length prose chunks (the feature code from the EMNLP 2026 paper; its
   location still has to be added here), TikZ prevalence/counts/style, math macro and environment counts per 1k tokens.
5. **Analysis:** MMD between years and against the pre-2022 reference, normalised by a permutation chance
   distribution; interrupted time series for TikZ; dose–response against field LLM use; paraphrase test.

## Data
- Raw sources, parsed text and feature tables live in `data/` (gitignored). Never commit downloaded papers.
- Commit code, the ID lists, small result tables and figures.

## Running
- Python with `uv` (`uv run python …`), dependencies in `pyproject.toml`, as in Björn's other repos.
- Sampling, download and parsing run on the Mac. The paraphrase test (open LLMs rewriting paragraphs) runs on the
  NHR@FAU clusters: use the `/hpc` skill (needs a `.hpc.toml` in this repo).

## Results and claims
- Record every result in `RESULTS.md` with date, command/commit, n and p-values. Correct earlier entries visibly
  (note the correction), don't silently rewrite them.
- Every figure and table is produced by a script in the repo.
- Guard against the known confounds before claiming an AI effect: topic drift (papers *about* LLMs, esp. `cs.CL`),
  templates and copied TikZ (deduplicate), pre-existing trends (compare against the 2018–2022 trend, not just
  before/after). Null results are reportable findings; say so rather than hunting for significance.
