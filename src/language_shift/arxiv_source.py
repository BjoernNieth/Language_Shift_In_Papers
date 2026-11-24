"""Download the LaTeX source of one arXiv paper version and unpack it. Nothing else: choosing the
main file and flattening are part of parsing (find_main_tex here, used by pipeline.py).

    from language_shift.arxiv_source import fetch_paper
    paper = fetch_paper("1701.03483")              # v1 by default
    paper.kind, paper.tex_files, paper.documentclass_files

Layout on disk (all under data/, gitignored):
    data/sources/raw/<id>v1.<ext>        the file exactly as arXiv sent it
    data/sources/unpacked/<id>v1/         its contents
    data/sources/excluded.csv            papers dropped at download (PDF only); files kept for now

Pace: one request per second, one connection, from export.arxiv.org, the mirror arXiv sets aside for
programmatic access (https://info.arxiv.org/help/bulk_data.html: use export.arxiv.org; "a reasonable
rate [is] bursts at 4 requests per second with a 1 second sleep"). The 3-second rule of the API terms
(https://info.arxiv.org/help/api/tou.html) is for the legacy APIs and OAI-PMH (fetch_metadata.py).
Every request goes through `_get`, which enforces the pace.
Downloaded archives are untrusted: they are only unpacked (tar with the "data" filter, which blocks
absolute paths, links out of the folder and device files), never executed.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import http.client
import io
import json
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from language_shift.flatten import FlattenError, flatten, read_tex

SOURCE_URL = "https://export.arxiv.org/src/{id}{version}"
USER_AGENT = "arxiv-source-research/0.1"
MIN_INTERVAL = 1.0  # seconds between requests (decided 2026-11-24, see the module docstring)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "sources"

_last_request = 0.0


class SourceNotAvailable(Exception):
    """arXiv has no source for this id/version (HTTP 404) or refused it."""


class NotLatex(SourceNotAvailable):
    """The source is only a PDF. Such papers are excluded and logged in data/sources/excluded.csv."""


class TemporaryError(Exception):
    """The request failed for now (timeout, connection, HTTP 429 or 5xx): try the same paper again.
    retry_after: seconds the server asked us to wait (Retry-After header), or None."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class PaperSource:
    id: str
    version: str
    kind: str  # "tar" | "single" | "pdf" | "unknown"
    raw_path: Path
    dir: Path
    files: list[Path] = field(default_factory=list)  # all unpacked files, relative to dir
    tex_files: list[Path] = field(default_factory=list)  # *.tex, relative to dir
    # .tex files with an uncommented \documentclass (or \documentstyle): main-file candidates.
    # A paper with none is not counted as a LaTeX paper.
    documentclass_files: list[Path] = field(default_factory=list)


def safe_name(arxiv_id: str, version: str) -> str:
    """Old-style ids contain a slash (hep-th/9901001); file names must not."""
    return arxiv_id.replace("/", "_") + version


# ------------------------------------------------------------------ download
def _get(url: str) -> tuple[bytes, dict]:
    """GET with arXiv's pacing. Follows redirects (/e-print/ -> /src/)."""
    global _last_request
    wait = _last_request + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read(), dict(r.headers)
    finally:
        _last_request = time.monotonic()


def _extension(headers: dict, data: bytes) -> str:
    m = re.search(r'filename="?[^";]*?\.((?:tar\.)?gz|pdf|tar)"?', headers.get("Content-Disposition", ""))
    if m:
        return m.group(1)
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:2] == b"\x1f\x8b":
        return "gz"
    return "bin"


def download_source(arxiv_id: str, version: str = "v1", data_dir: Path = DATA_DIR) -> Path:
    """Saves the raw source to data/sources/raw/ and returns its path. Skips ids already there."""
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(arxiv_id, version)
    # a .part file is a download that was interrupted while writing: fetch again
    existing = sorted(p for p in raw_dir.glob(name + ".*") if p.suffix != ".part")
    if existing:
        return existing[0]
    try:
        data, headers = _get(SOURCE_URL.format(id=arxiv_id, version=version))
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):  # arXiv has no source for this version
            raise SourceNotAvailable(f"{arxiv_id}{version}: HTTP {e.code}") from e
        retry = e.headers.get("Retry-After") if e.headers else None
        raise TemporaryError(f"{arxiv_id}{version}: HTTP {e.code}",
                             float(retry) if retry and retry.isdigit() else None) from e
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as e:
        raise TemporaryError(f"{arxiv_id}{version}: {type(e).__name__}: {e}") from e
    path = raw_dir / f"{name}.{_extension(headers, data)}"
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.rename(path)
    return path


# ------------------------------------------------------------------ unpack
def unpack_source(raw_path: Path, dest: Path) -> str:
    """Unpacks raw_path into dest and returns the kind: tar, single, pdf or unknown."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    data = raw_path.read_bytes()

    # Check if the file is a pdf
    if data[:4] == b"%PDF":
        (dest / "paper.pdf").write_bytes(data)
        return "pdf"
    # Check if it is a zip
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    # Else unpack the tarfile
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(dest, filter="data")
        return "tar"
    except tarfile.ReadError:
        pass
    # Check if the zipped file was actually a PDF
    if data[:4] == b"%PDF":
        (dest / "paper.pdf").write_bytes(data)
        return "pdf"

    # Check if the content seems to be a single tex file
    if _looks_like_tex(data):
        (dest / "main.tex").write_bytes(data)
        return "single"
    # Else assume unkown format
    (dest / "source.bin").write_bytes(data)
    return "unknown"


def _looks_like_tex(data: bytes) -> bool:
    """ Check for common tex comments in file """
    head = data[:20000].decode("latin-1")
    return bool(re.search(r"\\(documentclass|documentstyle|begin\{document\}|section|input)\b", head))


# ------------------------------------------------------------------ main file
_DOCCLASS = re.compile(r"^[^%\n]*\\document(class|style)\b", re.M)
_BEGIN_DOC = re.compile(r"^[^%\n]*\\begin\{document\}", re.M)


def _readme_toplevel(root: Path) -> Path | None:
    """arXiv's new submission system writes 00README.json, naming the file the author marked
    as "toplevel" (https://info.arxiv.org/help/00README.html). Returns it if it exists."""
    readme = root / "00README.json"
    if not readme.is_file():
        return None
    try:
        sources = json.loads(readme.read_text(encoding="utf-8", errors="replace")).get("sources", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    for s in sources:
        if isinstance(s, dict) and s.get("usage") == "toplevel" and s.get("filename"):
            rel = Path(s["filename"])
            if (root / rel).is_file():
                return rel
    return None


def find_main_tex(root: Path, tex_files: list[Path]) -> tuple[Path | None, str, list[str]]:
    """Returns (main file, its flattened text, include names not found).

    The top-level file from 00README.json if there is one. Otherwise the .tex file with an
    uncommented \\documentclass (or \\documentstyle) that has \\begin{document} and the longest
    text *after flattening*: a short main.tex that only \\inputs its sections still beats a
    standalone figure. Candidates that cannot be flattened (see flatten.FlattenError) are skipped."""
    top = _readme_toplevel(root)
    candidates = [top] if top else [rel for rel in tex_files if _DOCCLASS.search(read_tex(root / rel))]
    best = None
    for rel in candidates:
        try:
            text, missing = flatten(root, rel)
        except FlattenError:
            continue
        score = (bool(_BEGIN_DOC.search(text)), len(text))
        if best is None or score > best[0]:
            best = (score, rel, text, missing)
    return best[1:] if best else (None, "", [])


# ------------------------------------------------------------------ exclusions
EXCLUDED_FIELDS = ["id", "version", "reason", "date"]


def _excluded_path(data_dir: Path) -> Path:
    return data_dir / "excluded.csv"


def is_excluded(arxiv_id: str, version: str = "v1", data_dir: Path = DATA_DIR) -> bool:
    """ Check if the paper was already excluded before """
    path = _excluded_path(data_dir)
    if not path.exists():
        return False
    with open(path, newline="") as f:
        return any(r["id"] == arxiv_id and r["version"] == version for r in csv.DictReader(f))


def _log_excluded(arxiv_id: str, version: str, reason: str, data_dir: Path) -> None:
    path = _excluded_path(data_dir)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, EXCLUDED_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"id": arxiv_id, "version": version, "reason": reason,
                    "date": dt.date.today().isoformat()})


# ------------------------------------------------------------------ download and unpack
def fetch_paper(arxiv_id: str, version: str = "v1", data_dir: Path = DATA_DIR) -> PaperSource:
    """ Download and unpack from ArXiv """
   
    if is_excluded(arxiv_id, version, data_dir):
        raise NotLatex(f"{arxiv_id}{version}: PDF only (already excluded)")
    raw = download_source(arxiv_id, version, data_dir)
    dest = data_dir / "unpacked" / safe_name(arxiv_id, version)
    kind = unpack_source(raw, dest)
    if kind == "pdf":  # files are kept for inspection (raw/ and unpacked/<id>v1/paper.pdf)
        # If the file is an PDF add it to the excluded files
        _log_excluded(arxiv_id, version, "pdf_only", data_dir)
        raise NotLatex(f"{arxiv_id}{version}: PDF only, excluded")
    
    files = sorted(p.relative_to(dest) for p in dest.rglob("*") if p.is_file())
    tex = [p for p in files if p.suffix.lower() == ".tex"]
    return PaperSource(id=arxiv_id, version=version, kind=kind, raw_path=raw, dir=dest, files=files,
                       tex_files=tex,
                       documentclass_files=[p for p in tex if _DOCCLASS.search(read_tex(dest / p))])
