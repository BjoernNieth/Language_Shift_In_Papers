from __future__ import annotations

import argparse
import csv
import datetime as dt
import time
import tomllib
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

import polars as pl

from language_shift.arxiv_source import NotLatex, SourceNotAvailable, TemporaryError, fetch_paper
from language_shift.sample import CONFIG, ROOT, update_candidates

RECORD = ROOT / "sample" / "papers.csv"
FIELDS = ["field", "year", "rank", "id", "subfield", "status", "detail", "date"]
MAX_TRIES = 8


def try_paper(arxiv_id: str, fetch: Callable = fetch_paper,
              sleep: Callable = time.sleep) -> tuple[str, str]:
    """ Try to download a paper and check wheter it is latex code """
    for attempt in range(MAX_TRIES):
        try:
            # Fetch the paper from ArXiv by the id
            paper = fetch(arxiv_id)
            if paper.documentclass_files:
                return "latex", " ".join(map(str, paper.documentclass_files))[:300]
            return "no_tex", paper.kind
        except NotLatex:
            return "pdf_only", ""
        except SourceNotAvailable as e:
            return "no_source", str(e)
        except TemporaryError as e:
            wait = e.retry_after or min(60 * 2 ** attempt, 1800)
            print(f"  {e}; waiting {wait:.0f} s (try {attempt + 1}/{MAX_TRIES})", flush=True)
            sleep(wait)
        except Exception as e:  # a bug or an odd archive: record it, don't stop the night's run
            return "error", f"{type(e).__name__}: {e}"[:300]
    raise SystemExit(f"{arxiv_id}: arXiv keeps failing; stopped. Run again later to continue.")


def read_record(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(candidates: pl.DataFrame, n: int, record: Path, fetch: Callable = fetch_paper,
        sleep: Callable = time.sleep) -> None:
    """ Run the download of a candidate list. Fetch and Sleep are callable to give mock functions during test time """
    # Get already downloaded papers
    done = read_record(record)
    tried = {r["id"] for r in done}
    latex = Counter((r["field"], int(r["year"])) for r in done if r["status"] == "latex")

    # Build a queue for each year and field
    queues: dict[tuple[str, int], Iterator[dict]] = {
        key: (row for row in part.sort("rank").iter_rows(named=True) if row["id"] not in tried)
        for key, part in candidates.group_by("field", "year", maintain_order=True)}
    # Keep track of which queue already has enough latex papers
    active = sorted(k for k in queues if latex[k] < n)

    # Keep track of the papers which are downloaded
    record.parent.mkdir(parents=True, exist_ok=True)
    new_file = not record.exists()
    with open(record, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, FIELDS)
        if new_file:
            writer.writeheader()
        # While there are active groups
        while active:
            # Loop through all active queues
            for key in list(active):
                # Get the next paper in queue
                row = next(queues[key], None)
                # A queue might have less than the configured papers for earlier years
                if row is None:
                    print(f"{key}: out of candidates with {latex[key]} LaTeX papers", flush=True)
                    active.remove(key)
                    continue
                # Try to download the paper 
                status, detail = try_paper(row["id"], fetch, sleep)
                # Write down the results of the download
                writer.writerow({**row, "status": status, "detail": detail,
                                 "date": dt.date.today().isoformat()})
                # Flush results to disk before starting a new request
                f.flush()
                # If the paper has latex code increment counter
                latex[key] += status == "latex"
                print(f"{row['field']} {row['year']} #{row['rank']} {row['id']}: {status} "
                      f"({latex[key]}/{n})", flush=True)
                if latex[key] >= n:
                    active.remove(key)
    print("done:", dict(sorted(latex.items())))


def main() -> None:
    cfg = tomllib.loads(CONFIG.read_text())
    ap = argparse.ArgumentParser(description="Download the first n LaTeX papers per field and year.")
    ap.add_argument("--n", type=int, default=cfg["papers_per_field_year"],
                    help="LaTeX papers per field and year (default: papers_per_field_year)")
    args = ap.parse_args()
    # Update the candidate list and start the download
    run(update_candidates(), args.n, RECORD)


if __name__ == "__main__":
    main()
