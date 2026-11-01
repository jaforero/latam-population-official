"""Los datos publicados cumplen el contrato y las reglas de fuentes."""
import csv
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from latam_pop import ISO3, SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "processed"
REG = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf8"))["sources"]
FIELDS = {"iso3", "year", "population", "series_type", "source_id", "source_tier", "vintage", "scenario",
          "reference_date", "retrieved_at", "interpolated", "growth", "raw_file"}
pytestmark = pytest.mark.skipif(not (P / "manifest.json").exists(), reason="sin salidas")


@pytest.mark.parametrize("iso", ISO3)
def test_country_file(iso):
    d = json.loads((P / f"{iso}.json").read_text(encoding="utf8"))
    assert d["schema_version"] == SCHEMA_VERSION and d["iso3"] == iso
    for r in d["records"]:
        assert FIELDS <= set(r) and r["series_type"] in ("observed", "estimate", "projection")
        assert r["interpolated"] is False, "Ninguna serie se interpola"
        assert (ROOT / r["raw_file"]).exists(), "Cada cifra apunta a un archivo crudo"
    for s in d["segments"]:
        assert hashlib.sha256((ROOT / s["raw_file"]).read_bytes()).hexdigest() == s["raw_sha256"]
    assert len({r["year"] for r in d["records"]}) == len(d["records"])


def test_fallback_only_where_declared():
    allowed = {(i, k) for i, v in REG.items() for k, e in v.items() if k != "pyramid" and e["source_tier"] == "international_fallback"}
    assert allowed == {("CUB", "historical"), ("CUB", "projection"), ("HND", "historical"), ("HTI", "historical"), ("HTI", "projection"), ("NIC", "projection")}
    with open(P / "latam.csv", encoding="utf8") as f:
        for r in csv.DictReader(f):
            if r["source_tier"] == "international_fallback":
                assert r["iso3"] in {"CUB", "HND", "HTI", "NIC"}
                assert not (r["iso3"] == "HND" and int(r["year"]) >= 2013)
                assert not (r["iso3"] == "NIC" and int(r["year"]) <= 2025)


def test_fallback_uses_current_wpp():
    for i, k in (("CUB", "historical"), ("CUB", "projection"), ("HND", "historical"), ("HTI", "historical"), ("HTI", "projection"), ("NIC", "projection")):
        assert REG[i][k]["source_id"] == "un_wpp2024" and REG[i][k]["url"].startswith("https://population.un.org/")


def test_costa_rica_has_complete_annual_series():
    d = json.loads((P / "CRI.json").read_text(encoding="utf8"))
    assert [r["year"] for r in d["records"]] == list(range(1950, 2101)) and d["peak"]["year"] == 2044


def test_mexico_reaches_the_published_peak():
    d = json.loads((P / "MEX.json").read_text(encoding="utf8"))
    assert [r["year"] for r in d["records"]] == list(range(1950, 2071))
    assert d["peak"]["year"] == 2052 and d["peak"]["population"] == 147022927
    assert d["records"][0]["population"] == 28463441


def test_bolivia_uses_one_revision_without_breaks():
    d = json.loads((P / "BOL.json").read_text(encoding="utf8"))
    assert [r["year"] for r in d["records"]] == list(range(2000, 2051)) and d["breaks"] == []
    assert {r["vintage"] for r in d["records"]} == {"Rev. 2025"}
    assert next(r for r in d["records"] if r["year"] == 2023)["population"] == 11872175


def test_cuba_is_marked_as_international():
    d = json.loads((P / "CUB.json").read_text(encoding="utf8"))
    assert {r["source_tier"] for r in d["records"]} == {"international_fallback"} and d["segments"][0]["note"]["es"]


@pytest.mark.parametrize("iso", ISO3)
def test_pyramid_file(iso):
    d = json.loads((P / "pyramids" / f"{iso}.json").read_text(encoding="utf8"))
    assert d["schema_version"] == SCHEMA_VERSION and len(d["age_groups"]) == 17
    main = {r["year"]: r for r in json.loads((P / f"{iso}.json").read_text(encoding="utf8"))["records"]}
    assert d["years"]
    for y, v in d["years"].items():
        rec = main[int(y)]
        assert len(v["m"]) == len(v["f"]) == 17 and all(x >= 0 for x in v["m"] + v["f"])
        assert sum(v["m"]) + sum(v["f"]) == pytest.approx(rec["population"], abs=max(1.5, 0.0005 * rec["population"])), f"{iso} {y} no cuadra"
        assert d["parts"][v["part"]]["source_tier"] == rec["source_tier"]
        assert v["source_id"] == rec["source_id"] and v["series_type"] == rec["series_type"]
    for f in d["raw_files"]:
        assert hashlib.sha256((ROOT / f["path"]).read_bytes()).hexdigest() == f["sha256"]


def test_status_reports_pyramid_coverage():
    st = json.loads((ROOT / "data/status.json").read_text(encoding="utf8"))["countries"]
    assert {i for i, c in st.items() if c["pyramid"]["years"]} == set(ISO3)


def test_nicaragua_national_figure_prevails_in_2025():
    rows = {r["year"]: r for r in json.loads((P / "NIC.json").read_text(encoding="utf8"))["records"]}
    assert rows[2025]["population"] == 6946351 and rows[2025]["source_tier"] == "national"
    assert rows[2026]["source_tier"] == "international_fallback"


def test_five_yearly_series_have_no_invented_years():
    for iso, last in (("DOM", 2050), ("VEN", 2050)):
        rows = json.loads((P / f"{iso}.json").read_text(encoding="utf8"))["records"]
        recent = [r["year"] for r in rows if r["year"] >= 2000]
        assert recent == list(range(2000, last + 1, 5)) and all(r["interpolated"] is False for r in rows)


def test_no_excluded_sources():
    bad = ("worldbank", "wikipedia", "statista", "datosmacro", "ourworldindata", "oncubanews")
    for v in REG.values():
        for e in v.values():
            assert not any(b in e["url"] for b in bad)


def test_status_covers_20_countries_and_two_series():
    st = json.loads((ROOT / "data/status.json").read_text(encoding="utf8"))["countries"]
    assert set(st) == set(ISO3) and all(set(c["series"]) == {"historical", "projection"} for c in st.values())


LICENSES = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf8"))["licenses"]
LICENSE_STATUS = {"open_license", "own_terms", "no_license", "restricted"}
READ_HOW = {"direct", "browser", "in_file", "search_excerpt", "provided_by_owner"}


def source_entries():
    for iso, v in REG.items():
        for kind, e in v.items():
            yield iso, kind, e
            for part in e.get("extra_parts", []):
                yield iso, kind, part


def test_every_source_points_to_a_reviewed_license():
    for iso, kind, e in source_entries():
        key = e.get("license")
        assert key in LICENSES, f"{iso} {kind} sin licencia revisada"
        assert LICENSES[key]["institution"] == e["institution"] and iso in LICENSES[key]["countries"]


@pytest.mark.parametrize("key", sorted(LICENSES))
def test_license_entry_is_complete(key):
    v = LICENSES[key]
    assert v["status"] in LICENSE_STATUS and v["read_how"] in READ_HOW
    assert v["terms_url"].startswith("https://") and v["name"] and v["attribution"]
    assert v["summary"]["es"] and v["summary"]["en"]
    if v["status"] == "open_license":
        assert v["license_url"].startswith("https://")
    if v["status"] == "restricted":
        assert v["raw_copy"] == "restricted", "Lo que restringe no se declara como copia permitida"


def test_published_data_carries_license():
    published = json.loads((P / "licenses.json").read_text(encoding="utf8"))
    assert published["schema_version"] == SCHEMA_VERSION and published["licenses"] == LICENSES
    assert published["review"]["reviewed"] and published["review"]["caveat"]["en"]
    for iso in ISO3:
        d = json.loads((P / f"{iso}.json").read_text(encoding="utf8"))
        assert all(s["license"] in LICENSES for s in d["segments"])
        pyr = json.loads((P / "pyramids" / f"{iso}.json").read_text(encoding="utf8"))
        assert all(part["license"] in LICENSES for part in pyr["parts"])
    with open(P / "latam.csv", encoding="utf8") as f:
        for r in csv.DictReader(f):
            assert r["license"] in LICENSES and r["iso3"] in LICENSES[r["license"]]["countries"]


def test_no_cepal_material_is_published():
    """Sus términos no permiten redistribuir ni crear otros trabajos: ni crudos, ni fixtures, ni cifras."""
    tracked = [p for base in ("data", "tests/fixtures") for p in (ROOT / base).rglob("*") if p.is_file()]
    assert not [p for p in tracked if "cepal" in p.name.lower() or "cepal" in p.parent.name.lower() or "COMPARATIVO" in p.name]
    assert "cepal" not in (P / "latam.csv").read_text(encoding="utf8").lower()
    assert not [k for k, v in LICENSES.items() if "CEPAL" in v["institution"]]
