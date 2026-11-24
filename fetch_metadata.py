"""Harvest metadata of all arXiv papers into one CSV (one row per paper, no abstracts).

Source: arXiv OAI-PMH, format arXivRaw (lists every version with date and size).
OAI filters by *last-modified* date, not publication date, so we harvest everything in monthly
chunks of last-modified date. Each finished chunk is saved to data/metadata/parts/, so the run
can stop and resume. At the end all parts are merged into data/metadata/arxiv_metadata.csv.

  uv run python fetch_metadata.py                                   # full harvest (several hours)
  uv run python fetch_metadata.py --start 2026-11 --end 2026-11     # only these chunks (test)
  uv run python fetch_metadata.py --merge-only                      # just rebuild the merged CSV
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE = "https://oaipmh.arxiv.org/oai"
USER_AGENT = "arxiv-metadata-research-harvest/0.1"
EARLIEST = dt.date(2005, 9, 16)  # earliest datestamp the OAI server accepts
DELAY = 3.0  # arXiv: at most one request every 3 seconds, one connection
NS = {"o": "http://www.openarchives.org/OAI/2.0/", "r": "http://arxiv.org/OAI/arXivRaw/"}

# Unlike other categories, pyhysics does not start with a single prefix. Here we collected all 
# prefixes from the official arXiv taxonomy list: https://arxiv.org/category_taxonomy
PHYSICS = {"astro-ph", "cond-mat", "gr-qc", "hep-ex", "hep-lat", "hep-ph", "hep-th", "math-ph",
           "nlin", "nucl-ex", "nucl-th", "physics", "quant-ph"}

FIELDS = ["id", "title", "primary_category", "categories", "archive", "group",
          "v1_date", "v1_year", "n_versions", "last_date", "v1_size_kb", "last_size_kb",
          "v1_source_type", "license", "doi", "journal_ref", "datestamp"]

SKIP_FIELDS = ["identifier", "datestamp", "reason"]  # reason: deleted | no_metadata | no_versions

OUT = Path("data/metadata")
PARTS = OUT / "parts"
SKIPPED = PARTS / "skipped"  # one file per month, merged into data/metadata/skipped.csv


def get(params: dict) -> ET.Element:
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(10):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            time.sleep(DELAY)
            return ET.fromstring(data)
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get("Retry-After", 30)) if e.code == 503 else 30 * (attempt + 1)
            print(f"  HTTP {e.code}, waiting {wait}s", flush=True)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
            print(f"  {type(e).__name__}: {e}, retrying in {30 * (attempt + 1)}s", flush=True)
            time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def text(el, path):
    x = el.find(path, NS)
    return " ".join(x.text.split()) if x is not None and x.text else ""


def iso(date: str) -> str:
    try:
        return parsedate_to_datetime(date).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def row(rec: ET.Element) -> tuple[dict | None, dict | None]:
    """Returns (csv row, None) for a usable record, or (None, skip entry) with the reason it was skipped."""
    head = rec.find("o:header", NS)
    skip = lambda reason: (None, {"identifier": text(head, "o:identifier"),
                                  "datestamp": text(head, "o:datestamp"), "reason": reason})
    if head.get("status") == "deleted":
        return skip("deleted")
    m = rec.find("o:metadata/r:arXivRaw", NS)
    if m is None:
        return skip("no_metadata")
    versions = m.findall("r:version", NS)
    if not versions:
        return skip("no_versions")
    first, last = versions[0], versions[-1]
    cats = text(m, "r:categories").split()
    prim = cats[0] if cats else ""
    # Derive archive from prefix of primary category
    archive = prim.split(".")[0]
    v1 = iso(text(first, "r:date"))
    return {
        "id": text(m, "r:id"),
        "title": text(m, "r:title"),
        "primary_category": prim,
        "categories": " ".join(cats),
        "archive": archive,
        # Physics has no single prefix so we group all physics papers together
        "group": "physics" if archive in PHYSICS else archive,
        "v1_date": v1,
        "v1_year": v1[:4],
        "n_versions": len(versions),
        "last_date": iso(text(last, "r:date")),
        "v1_size_kb": text(first, "r:size").removesuffix("kb"),
        "last_size_kb": text(last, "r:size").removesuffix("kb"),
        "v1_source_type": text(first, "r:source_type"),
        "license": text(m, "r:license"),
        "doi": text(m, "r:doi"),
        "journal_ref": text(m, "r:journal-ref"),
        "datestamp": text(head, "o:datestamp"),
    }, None


def harvest_month(month: dt.date) -> int:
    # Create the output path for this month
    part = PARTS / f"{month:%Y-%m}.csv"
    if part.exists():
        return -1

    # Set beginning and end to first and last day of month
    # (not before arXiv's earliest datestamp, not after today: the server rejects future dates)
    nxt = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    today = dt.datetime.now(dt.timezone.utc).date()
    params = {"verb": "ListRecords", "metadataPrefix": "arXivRaw",
              "from": f"{max(month, EARLIEST):%Y-%m-%d}",
              "until": f"{min(nxt - dt.timedelta(days=1), today):%Y-%m-%d}"}
    rows, skipped, page = [], [], 0
    while True:
        # Send request to ArXiv API
        root = get(params)

        # Check if there is an error in the request
        err = root.find("o:error", NS)
        if err is not None:
            if err.get("code") == "noRecordsMatch":
                break
            raise RuntimeError(f"{month:%Y-%m}: OAI error {err.get('code')}: {err.text}")

        
        lr = root.find("o:ListRecords", NS)
        for rec in lr.findall("o:record", NS):
            r, s = row(rec)
            if r:
                rows.append(r)
            else:
                skipped.append(s)
        page += 1
        # Check if answer contains an resumption Token 
        tok = lr.find("o:resumptionToken", NS)
        size = tok.get("completeListSize") if tok is not None else None
        print(f"  {month:%Y-%m} page {page}: {len(rows)} rows, {len(skipped)} skipped"
              + (f" / {size}" if size else ""), flush=True)

        # If no resumption Token, all records for month scraped
        if tok is None or not (tok.text or "").strip():
            break
        # Set request to get the next page for the month
        params = {"verb": "ListRecords", "resumptionToken": tok.text.strip()}
    # Skipped records first: the month only counts as done once its main part exists
    with open(SKIPPED / f"{month:%Y-%m}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, SKIP_FIELDS)
        w.writeheader()
        w.writerows(skipped)
    tmp = part.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.rename(part)  # only finished months count as done
    return len(rows)


def merge() -> None:
    best: dict[str, dict] = {}
    for part in sorted(PARTS.glob("*.csv")):
        with open(part, newline="") as f:
            for r in csv.DictReader(f):
                if r["id"] not in best or r["datestamp"] > best[r["id"]]["datestamp"]:
                    best[r["id"]] = r  # a paper modified during the harvest can appear twice
    out = OUT / "arxiv_metadata.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(sorted(best.values(), key=lambda r: (r["v1_date"], r["id"])))
    print(f"merged {len(best)} papers -> {out}")

    skipped = []
    for part in sorted(SKIPPED.glob("*.csv")):
        with open(part, newline="") as f:
            skipped += list(csv.DictReader(f))
    with open(OUT / "skipped.csv", "w", newline="") as f:
        w = csv.DictWriter(f, SKIP_FIELDS)
        w.writeheader()
        w.writerows(skipped)
    counts = Counter(s["reason"] for s in skipped)
    print(f"skipped {len(skipped)} records -> {OUT / 'skipped.csv'}"
          + (f" ({', '.join(f'{k}: {v}' for k, v in counts.most_common())})" if counts else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    # Start date of the harvest. Earliest day is 09 2005
    ap.add_argument("--start", default="2005-09", help="first last-modified month (YYYY-MM)")
    # End day as a default today
    ap.add_argument("--end", default=dt.date.today().strftime("%Y-%m"), help="last month (YYYY-MM)")
    # Only do the merge without scraping
    ap.add_argument("--merge-only", action="store_true")
    a = ap.parse_args()

    SKIPPED.mkdir(parents=True, exist_ok=True)

    if not a.merge_only:
        m = dt.date.fromisoformat(a.start + "-01")
        end = dt.date.fromisoformat(a.end + "-01")
        while m <= end:
            n = harvest_month(m)
            print(f"{m:%Y-%m}: " + ("already done" if n < 0 else f"{n} papers"), flush=True)
            # Set m to next month
            # 28 + 4 days always lands in next month, then going back to first day of month
            m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    merge()


if __name__ == "__main__":
    sys.exit(main())
