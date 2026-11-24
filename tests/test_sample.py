"""Tests for language_shift.sample on a small made-up metadata table.

`draw` ranks every paper; the download takes the first n of each field and year. So "raising n keeps
the first n" holds as long as ranks do not change when the list is drawn again, which these tests check.

    uv run pytest tests/test_sample.py -v
"""

import polars as pl

from language_shift.sample import draw


def meta(n_per_year: int, years=(2020, 2021), prefix="p") -> pl.DataFrame:
    rows = [{"id": f"{prefix}{y}.{i:04d}", "primary_category": "cs.CL", "archive": "cs", "group": "cs",
             "v1_year": y, "v1_date": f"{y}-06-01"} for y in years for i in range(n_per_year)]
    rows.append({"id": "other.0001", "primary_category": "q-bio.NC", "archive": "q-bio", "group": "q-bio",
                 "v1_year": 2020, "v1_date": "2020-06-01"})  # not in the field
    rows.append({"id": "november.0001", "primary_category": "cs.CL", "archive": "cs", "group": "cs",
                 "v1_year": 2021, "v1_date": "2021-11-02"})  # after v1_until
    return pl.DataFrame(rows)


def cfg(seed: int = 1) -> dict:
    return {"seed": seed, "v1_from": "2020-01-01", "v1_until": "2021-10-31", "papers_per_field_year": 10,
            "fields": ["cs"]}


def test_every_paper_of_the_field_is_ranked_once():
    out = draw(meta(50), cfg())
    assert out.group_by("year").agg(pl.col("rank").sort()).sort("year")["rank"].to_list() == \
        [list(range(1, 51))] * 2
    assert "other.0001" not in out["id"].to_list()  # not in the field
    assert "november.0001" not in out["id"].to_list()  # after v1_until


def test_adding_a_year_changes_no_rank_of_the_other_years():
    out = draw(meta(50), cfg())
    wider = draw(meta(50, years=(2019, 2020, 2021)), {**cfg(), "v1_from": "2019-01-01"})
    assert wider.filter(pl.col("year") >= 2020).equals(out)


def test_the_seed_decides_the_order():
    assert draw(meta(50), cfg(seed=1)).equals(draw(meta(50), cfg(seed=1)))
    assert not draw(meta(50), cfg(seed=1)).equals(draw(meta(50), cfg(seed=2)))


def test_order_does_not_depend_on_row_order():
    m = meta(50)
    assert draw(m, cfg()).equals(draw(m.reverse(), cfg()))


def test_every_prefix_has_the_subfields_in_proportion():
    # 2020: 60 cs.CL and 20 cs.LG papers (75% / 25%) in one field
    rows = [{"id": f"{c}.{i:04d}", "primary_category": c, "archive": "cs", "group": "cs",
             "v1_year": 2020, "v1_date": "2020-06-01"} for c, k in [("cs.CL", 60), ("cs.LG", 20)]
            for i in range(k)]
    out = draw(pl.DataFrame(rows), cfg())
    for n in [4, 8, 20, 40, 80]:
        counts = out.filter(pl.col("rank") <= n)["subfield"].value_counts()
        assert dict(zip(counts["subfield"], counts["count"])) == {"cs.CL": 3 * n // 4, "cs.LG": n // 4}


def test_ids_survive_a_round_trip_through_the_csv(tmp_path, monkeypatch):
    import language_shift.sample as sample
    m = pl.DataFrame([{"id": "1811.01990", "primary_category": "cs.CL", "archive": "cs", "group": "cs",
                       "v1_year": 2020, "v1_date": "2020-06-01"}])
    monkeypatch.setattr(sample, "CANDIDATES", tmp_path / "c.csv")
    draw(m, cfg()).write_csv(sample.CANDIDATES)
    monkeypatch.setattr(sample, "METADATA", tmp_path / "m.csv")
    m.write_csv(sample.METADATA)
    monkeypatch.setattr(sample, "CONFIG", tmp_path / "config.toml")
    sample.CONFIG.write_text('seed = 1\nv1_from = "2020-01-01"\nv1_until = "2021-10-31"\n'
                             'papers_per_field_year = 1\nfields = ["cs"]\n')
    sample.main()
    assert pl.read_csv(sample.CANDIDATES, infer_schema_length=0)["id"].to_list() == ["1811.01990"]
