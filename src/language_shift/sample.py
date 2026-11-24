from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config.toml"
METADATA = ROOT / "data" / "metadata" / "arxiv_metadata.csv"
CANDIDATES = ROOT / "data" / "sample" / "candidates.csv"


def rank_key(seed: int, arxiv_id: str) -> str:
    """ Get a hash out of seed and archive ID. This hash is used for random sampling. """
    return hashlib.sha256(f"{seed}:{arxiv_id}".encode()).hexdigest()


def draw(meta: pl.DataFrame, cfg: dict) -> pl.DataFrame:
    """Update the candidate list"""
    # A paper's field is its arXiv group (cs, physics, math), taken from its primary category
    papers = (meta
              # Check that the paper is in configured fields and was published in the correct years
              .filter(pl.col("group").is_in(cfg["fields"]),
                      # Check that the paper are in the latest month 
                      pl.col("v1_date").is_between(pl.lit(cfg["v1_from"]), pl.lit(cfg["v1_until"])))
              # Rename the columns for easier handling
              .select(pl.col("group").alias("field"), pl.col("v1_year").alias("year"), "id",
                      pl.col("primary_category").alias("subfield")))
    # Stratify by field, year and subfield
    stratum, cell = ["field", "year"], ["field", "year", "subfield"]
    papers = (papers
              # Get a hash of id and random seed for every paper
              .with_columns(pl.col("id").map_elements(lambda i: rank_key(cfg["seed"], i),
                                                      return_dtype=pl.String).alias("key"))
              # Sort by this key to get a repeatable random sampling
              .sort("key")
              # Assign a running number within the same field, year and subfield              
              .with_columns(pl.int_range(1, pl.len() + 1).over(cell).alias("i_sub"),
                            # Get the share of the subfiled for each field and year 
                            (pl.len().over(cell) / pl.len().over(stratum)).alias("share"))
              # Produce final sampling order by dividing the position within a subfield by 
              # the share of the subfield. -0.5 Avoids small subfields not beeing sampled for small
              .with_columns(((pl.col("i_sub") - 0.5) / pl.col("share")).alias("position"))
              .sort("position", "key")
              .with_columns(pl.int_range(1, pl.len() + 1).over(stratum).alias("rank"))
              .select("field", "year", "rank", "id", "subfield")
              .sort("field", "year", "rank"))
    return papers


def update_candidates() -> pl.DataFrame:
    """Update the candidate list in case the config has changed"""
    cfg = tomllib.loads(CONFIG.read_text())
    # Read in the collected metadata from ArXiv
    meta = pl.read_csv(METADATA, infer_schema_length=0).with_columns(pl.col("v1_year").cast(pl.Int64))
    # Update the candidate list
    out = draw(meta, cfg)
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)

    # Save the updated candidate list
    out.write_csv(CANDIDATES)
    print(f"{CANDIDATES}: {out.height} candidates")
    return out


def main() -> None:
    out = update_candidates()
    print(out.group_by("field", "year").len().pivot("year", index="field", values="len",
                                                    sort_columns=True))


if __name__ == "__main__":
    main()
