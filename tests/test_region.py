"""El agregado regional no rellena, no encadena y no publica totales parciales."""
import json
from pathlib import Path

import pytest

from latam_pop import ISO3, SCHEMA_VERSION
from latam_pop.region import build_region

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "processed"
AGES = [f"g{i}" for i in range(17)]


def rec(iso, y, pop, source="s", vintage="v", kind="estimate", tier="national"):
    return dict(iso3=iso, year=y, population=pop, series_type=kind, source_id=f"{iso}_{source}", vintage=vintage,
                source_tier=tier, reference_date="07-01", raw_file=f"data/raw/{iso}.csv")


def world(years=(2020, 2025, 2030), pop=100):
    return {i: [rec(i, y, pop + (y - 2020)) for y in years] for i in ISO3}


def pyr(total, kind="estimate", tier="national"):
    m = [total // 34] * 17
    return dict(m=m, f=[total - sum(m) - 16 * m[0]] + m[1:], series_type=kind, source_tier=tier)


def test_total_is_a_plain_sum_of_the_20_countries():
    doc, _ = build_region(world(), {})
    assert doc["years"] == [2020, 2025, 2030] and doc["official"] is False
    assert doc["points"][0]["population"] == 20 * 100 and doc["points"][1]["population"] == 20 * 105
    assert doc["points"][0]["shares"]["COL"] == pytest.approx(0.05)


def test_a_year_missing_one_country_has_no_total():
    w = world()
    w["ARG"] = [r for r in w["ARG"] if r["year"] != 2025]
    doc, _ = build_region(w, {})
    assert doc["years"] == [2020, 2030] and 2025 not in [p["year"] for p in doc["points"]]


def test_no_total_at_all_if_a_country_has_no_data():
    w = world()
    w["ARG"] = []
    doc, _ = build_region(w, {})
    assert doc["years"] == [] and doc["periods"] == [] and doc["index"] == {}


def test_growth_excludes_the_country_that_crosses_a_break():
    w = world()
    w["ARG"] = [rec("ARG", 2020, 100), rec("ARG", 2025, 500, vintage="otra"), rec("ARG", 2030, 510, vintage="otra")]
    doc, _ = build_region(w, {})
    first, second = doc["periods"]
    assert first["n_countries"] == 19 and [e["iso3"] for e in first["excluded"]] == ["ARG"]
    assert first["country_rates"]["ARG"] is None
    assert first["rate"] == pytest.approx((105 / 100) ** (1 / 5) - 1, abs=1e-7), "ARG no debe afectar la tasa"
    assert second["n_countries"] == 20 and second["country_rates"]["ARG"] == pytest.approx((510 / 500) ** (1 / 5) - 1, abs=1e-7)
    assert doc["points"][1]["population"] == 19 * 105 + 500, "El total sí suma la cifra oficial de cada año"


def test_index_is_100_in_base_and_never_chains():
    w = world()
    w["ARG"] = [rec("ARG", 2020, 100), rec("ARG", 2025, 500, vintage="otra"), rec("ARG", 2030, 510, vintage="otra")]
    doc, _ = build_region(w, {})
    rows = {r["year"]: r for r in doc["index"]["2025"]}
    assert rows[2025]["index"] == 100 and rows[2025]["n_countries"] == 20
    assert rows[2020]["excluded"] == ["ARG"] and rows[2020]["index"] == pytest.approx(100 / 105 * 100, abs=1e-3)
    assert rows[2030]["excluded"] == [] and rows[2030]["n_countries"] == 20


def test_pyramid_requires_all_20_and_sums_group_by_group():
    w = world((2025,), 3400)
    pyramids = {i: dict(age_groups=AGES, years={"2025": pyr(3405), "2030": pyr(3410)}) for i in ISO3}
    del pyramids["BOL"]["years"]["2030"]
    doc, issues = build_region(w, pyramids)
    assert list(doc["pyramid"]["years"]) == ["2025"] and doc["pyramid"]["missing_by_year"]["2030"] == ["BOL"] and not issues
    y = doc["pyramid"]["years"]["2025"]
    assert sum(y["m"]) + sum(y["f"]) == 20 * 3405 and y["n_countries"] == 20


def test_pyramid_that_does_not_match_the_total_is_not_published():
    w = world((2025,), 3400)
    pyramids = {i: dict(age_groups=AGES, years={"2025": pyr(9000)}) for i in ISO3}
    doc, issues = build_region(w, pyramids)
    assert doc["pyramid"]["years"] == {} and issues[0]["year"] == 2025


@pytest.mark.skipif(not (P / "region.json").exists(), reason="sin salidas")
class TestPublished:
    region = json.loads((P / "region.json").read_text(encoding="utf8")) if (P / "region.json").exists() else {}
    licenses = json.loads((P / "licenses.json").read_text(encoding="utf8"))["licenses"] if (P / "licenses.json").exists() else {}
    main = {i: {r["year"]: r for r in json.loads((P / f"{i}.json").read_text(encoding="utf8"))["records"]} for i in ISO3} if (P / "ARG.json").exists() else {}

    def test_contract(self):
        assert self.region["schema_version"] == SCHEMA_VERSION and self.region["official"] is False and self.region["derived"] is True
        assert self.region["note"]["es"] and self.region["note"]["en"]
        assert self.region["countries"] == ISO3

    def test_years_are_exactly_those_with_all_20(self):
        common = sorted(set.intersection(*(set(v) for v in self.main.values())))
        assert self.region["years"] == common and common

    def test_totals_add_up_to_the_published_country_figures(self):
        for p in self.region["points"]:
            assert p["population"] == pytest.approx(sum(self.main[i][p["year"]]["population"] for i in ISO3), abs=1)
            assert p["n_countries"] == 20 and sum(p["shares"].values()) == pytest.approx(1, abs=1e-4)
            for c in p["components"]:
                assert (ROOT / c["raw_file"]).exists(), "Cada componente apunta a su archivo crudo"
                assert c["license"] in self.licenses, "Cada componente conserva la licencia de su fuente"

    def test_breaks_never_enter_growth_or_index(self):
        for g in self.region["periods"]:
            for i in ISO3:
                a, b = self.main[i][g["from_year"]], self.main[i][g["to_year"]]
                same = (a["source_id"], a["vintage"]) == (b["source_id"], b["vintage"])
                assert (g["country_rates"][i] is not None) == same, f"{i} {g['from_year']}"
        for base, rows in self.region["index"].items():
            assert next(r for r in rows if r["year"] == int(base))["index"] == 100

    def test_pyramid_years_have_the_20_countries(self):
        for y, v in self.region["pyramid"]["years"].items():
            assert v["n_countries"] == 20 and len(v["m"]) == len(v["f"]) == 17
            total = next(p["population"] for p in self.region["points"] if p["year"] == int(y))
            assert sum(v["m"]) + sum(v["f"]) == pytest.approx(total, abs=0.0005 * total)
