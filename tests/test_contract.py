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


def test_cepal_only_where_declared():
    allowed = {(i, k) for i, v in REG.items() for k, e in v.items() if e["source_tier"] == "regional_fallback"}
    assert allowed == {("HND", "historical"), ("HTI", "historical"), ("HTI", "projection"), ("NIC", "projection")}
    with open(P / "latam.csv", encoding="utf8") as f:
        for r in csv.DictReader(f):
            if r["source_tier"] == "regional_fallback":
                assert r["iso3"] in {"HND", "HTI", "NIC"}
                assert not (r["iso3"] == "HND" and int(r["year"]) >= 2013)
                assert not (r["iso3"] == "NIC" and int(r["year"]) <= 2024)


def test_cepal_uses_current_revision():
    for i, k in (("HND", "historical"), ("HTI", "historical"), ("HTI", "projection"), ("NIC", "projection")):
        assert REG[i][k]["source_id"] == "cepal_celade_rev2024" and REG[i][k]["url"].startswith("https://celade.cepal.org/")


def test_costa_rica_has_complete_annual_series():
    d = json.loads((P / "CRI.json").read_text(encoding="utf8"))
    assert [r["year"] for r in d["records"]] == list(range(1950, 2101)) and d["peak"]["year"] == 2044


def test_mexico_reaches_the_published_peak():
    d = json.loads((P / "MEX.json").read_text(encoding="utf8"))
    assert [r["year"] for r in d["records"]] == list(range(1970, 2071))
    assert d["peak"]["year"] == 2052 and d["peak"]["population"] == 147022927


def test_bolivia_never_fills_2023_or_uses_old_projection():
    d = json.loads((P / "BOL.json").read_text(encoding="utf8"))
    years = [r["year"] for r in d["records"]]
    assert 2023 not in years and years == list(range(2000, 2023)) + list(range(2024, 2035))
    assert [b["year"] for b in d["breaks"]] == [2012, 2024]
    assert {r["vintage"] for r in d["records"] if r["year"] >= 2024} == {"Rev. 2025"}


def test_pending_countries_show_no_figures():
    for iso in ("CUB", "DOM", "GTM"):
        assert json.loads((P / f"{iso}.json").read_text(encoding="utf8"))["records"] == []


def test_no_excluded_sources():
    bad = ("worldbank", "population.un.org", "wikipedia", "statista", "datosmacro", "ourworldindata", "oncubanews")
    for v in REG.values():
        for e in v.values():
            assert not any(b in e["url"] for b in bad)


def test_status_covers_20_countries_and_two_series():
    st = json.loads((ROOT / "data/status.json").read_text(encoding="utf8"))["countries"]
    assert set(st) == set(ISO3) and all(set(c["series"]) == {"historical", "projection"} for c in st.values())
