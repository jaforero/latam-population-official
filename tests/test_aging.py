"""El índice de envejecimiento sale de las pirámides publicadas y coincide con lo que publican las fuentes."""
import csv
import json
from pathlib import Path

import pytest

from latam_pop import ISO3, SCHEMA_VERSION
from latam_pop.aging import CSV_FIELDS, aging_csv_rows, build_aging, measure
from latam_pop.parsing import xlsx_rows
from latam_pop.pyramids import AGE_GROUPS

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "processed"
published_data = pytest.mark.skipif(not (P / "aging.json").exists(), reason="sin salidas")


def pyramid(young=10, adult=100, old=5):
    groups = [young] * 3 + [adult] * 10 + [old] * 4
    return dict(m=groups, f=groups, series_type="estimate", source_id="s", vintage="v", source_tier="national", reference_date="07-01")


def test_groups_are_the_expected_ones():
    assert AGE_GROUPS[:3] == ["0-4", "5-9", "10-14"] and AGE_GROUPS[13:] == ["65-69", "70-74", "75-79", "80+"]


def test_formula_counts_both_sexes_and_leaves_working_ages_out():
    assert measure(pyramid()) == dict(aging_index=round(100 * 40 / 60, 4), pop_0_14=60, pop_65_plus=40)
    assert measure(pyramid(adult=999_999))["aging_index"] == measure(pyramid(adult=1))["aging_index"]


def test_years_without_pyramid_stay_empty():
    doc = build_aging({"ARG": dict(status="ok", years={"2030": pyramid(), "2020": pyramid()})}, {})
    assert [r["year"] for r in doc["countries"]["ARG"]["rows"]] == [2020, 2030]
    assert doc["countries"]["BOL"]["rows"] == [] and doc["region"] == []


def test_change_of_source_or_vintage_is_a_break():
    other = dict(pyramid(), vintage="w")
    doc = build_aging({"ARG": dict(years={"2020": pyramid(), "2021": pyramid(), "2022": other})}, {})
    assert doc["countries"]["ARG"]["breaks"] == [dict(year=2022, from_vintage="v", to_vintage="w")]


def test_region_uses_only_its_published_pyramid():
    region = dict(years={"2025": dict(pyramid(), n_countries=20, n_projection=19, international_fallback=["CUB"])})
    doc = build_aging({}, region)
    assert [r["year"] for r in doc["region"]] == [2025] and doc["region"][0]["n_countries"] == 20
    rows = aging_csv_rows(doc)
    assert [(r["iso3"], r["source_tier"]) for r in rows] == [("REG", "derived")] and set(rows[0]) == set(CSV_FIELDS)


def published_row(path, sheet, label, year_header_row, offset=0):
    rows = list(xlsx_rows(path, sheet))
    years = {i: int(c) for i, c in enumerate(rows[year_header_row]) if isinstance(c, (int, float)) and 1900 < c < 2200}
    at = next(n for n, r in enumerate(rows) if any(isinstance(c, str) and label in c for c in r)) + offset
    return {y: rows[at][i] for i, y in years.items() if isinstance(rows[at][i], (int, float))}


@published_data
@pytest.mark.parametrize("iso,key,sheet,label,header,offset,tolerance", [
    ("CHL", "chl_ine", "Resultados Indicadores", "Indice de envejecimiento", None, 0, 0.06),  # publica un decimal
    ("CRI", "cri_inec", "C4. Indicadores", "Índice de envejecimiento (65+", 3, 1, 0.001),  # la fila siguiente es Total
    ("PRY", "pry_ine", "Medidas de Composición", "Indice de envejecimiento", None, 0, 0.001),
])
def test_matches_what_the_source_publishes(iso, key, sheet, label, header, offset, tolerance):
    path = next(p for p in sorted((ROOT / "data/raw" / iso / key).glob("*.xlsx")))
    if header is None:
        rows = list(xlsx_rows(path, sheet))
        at = next(n for n, r in enumerate(rows) if any(isinstance(c, str) and label in c for c in r))
        header = next(n for n in range(at - 1, -1, -1)
                      if sum(isinstance(c, (int, float)) and 1900 < c < 2200 and float(c).is_integer() for c in rows[n]) >= 5)
    source = published_row(path, sheet, label, header, offset)
    ours = {r["year"]: r["aging_index"] for r in json.loads((P / "aging.json").read_text(encoding="utf8"))["countries"][iso]["rows"]}
    common = sorted(set(source) & set(ours))
    assert len(common) >= 70, "La comparación debe cubrir casi toda la serie"
    assert max(abs(source[y] - ours[y]) for y in common) <= tolerance


@published_data
def test_published_file_follows_the_pyramids():
    doc = json.loads((P / "aging.json").read_text(encoding="utf8"))
    assert doc["schema_version"] == SCHEMA_VERSION and set(doc["countries"]) == set(ISO3)
    total = 0
    for iso in ISO3:
        years = json.loads((P / "pyramids" / f"{iso}.json").read_text(encoding="utf8"))["years"]
        rows = doc["countries"][iso]["rows"]
        assert [r["year"] for r in rows] == sorted(int(y) for y in years), f"{iso}: mismos años que su pirámide"
        for r in rows:
            v = years[str(r["year"])]
            assert r["aging_index"] == measure(v)["aging_index"] and r["source_id"] == v["source_id"] and r["aging_index"] > 0
        total += len(rows)
    region = json.loads((P / "region.json").read_text(encoding="utf8"))["pyramid"]["years"]
    assert [r["year"] for r in doc["region"]] == sorted(int(y) for y in region)
    with open(P / "aging.csv", encoding="utf8") as f:
        assert sum(1 for _ in csv.DictReader(f)) == total + len(doc["region"])
