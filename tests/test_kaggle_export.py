"""El paquete Kaggle reproduce los productos canónicos sin cambiar su significado y respeta la puerta de licencias."""
import copy
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from latam_pop import ISO3
from latam_pop.pyramids import AGE_GROUPS

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "processed"
sys.path.insert(0, str(ROOT / "scripts"))
import build_kaggle_dataset as bk  # noqa: E402

pytestmark = pytest.mark.skipif(not (P / "manifest.json").exists(), reason="sin salidas")


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    # La salida debe quedar dentro de dist/ de la raíz: se copia el repo mínimo a un directorio temporal.
    root = tmp_path_factory.mktemp("repo")
    for d in ("data/processed", "kaggle", "latam_pop"):
        shutil.copytree(ROOT / d, root / d)
    for f in ("data/status.json", "data/alerts.json", "sources.yaml"):
        shutil.copy(ROOT / f, root / f)
    res = bk.build(root=root)
    res["tables"] = {n: read(res["out"] / n) for n in bk.CSV_FILES}
    return res


def read(path):
    with open(path, encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


def canon(name):
    return read(P / name)


# ---------- estructura ----------

def test_package_has_exactly_the_planned_files(pkg):
    assert sorted(p.name for p in pkg["out"].iterdir()) == sorted(bk.CSV_FILES + bk.DOC_FILES)
    assert not any("raw" in p.parts for p in pkg["out"].rglob("*")), "data/raw/ no se redistribuye"


def test_columns_match_the_dictionary(pkg):
    spec = yaml.safe_load((ROOT / "kaggle/columns.yaml").read_text(encoding="utf8"))["files"]
    for name, rows in pkg["tables"].items():
        assert list(rows[0]) == [c["name"] for c in spec[name]["columns"]], name


def test_schema_change_stops_the_export(tmp_path):
    src = bk.load(ROOT)
    bad = copy.deepcopy(src)
    bad["latam_header"] = bad["latam_header"] + ["nuevo"]
    with pytest.raises(bk.ExportError, match="columnas"):
        bk.check_schema(bad)
    bad = copy.deepcopy(src)
    bad["manifest"]["schema_version"] = "3.0"
    with pytest.raises(bk.ExportError, match="schema_version"):
        bk.check_schema(bad)


def test_output_is_only_cleaned_inside_dist(tmp_path):
    with pytest.raises(bk.ExportError):
        bk.safe_reset(tmp_path / "elsewhere", tmp_path / "repo")


# ---------- cobertura ----------

def test_exactly_the_20_project_countries(pkg):
    assert len(ISO3) == 20
    for name in ("population_latam.csv", "sources.csv"):
        assert {r["iso3"] for r in pkg["tables"][name]} == set(ISO3), name
    assert {r["iso3"] for r in pkg["tables"]["population_pyramids.csv"]} == set(ISO3) | {"REG"}
    assert {r["iso3"] for r in pkg["tables"]["aging_index.csv"]} == set(ISO3) | {"REG"}
    assert pkg["manifest"]["countries"] == ISO3


def test_no_country_disappears(pkg):
    want = Counter(r["iso3"] for r in canon("latam.csv"))
    assert Counter(r["iso3"] for r in pkg["tables"]["population_latam.csv"]) == want


# ---------- unicidad ----------

@pytest.mark.parametrize("name,key", [
    ("population_latam.csv", ("iso3", "year")),
    ("population_pyramids.csv", ("iso3", "year", "sex", "age_group")),
    ("aging_index.csv", ("iso3", "year")),
    ("population_region.csv", ("year",)),
    ("sources.csv", ("iso3", "series", "source_id", "vintage")),
    ("source_breaks.csv", ("iso3", "year")),
    ("quality_alerts.csv", ("fingerprint",)),
])
def test_natural_keys_are_unique(pkg, name, key):
    rows = pkg["tables"][name]
    assert len({tuple(r[k] for k in key) for r in rows}) == len(rows)


# ---------- integridad ----------

def test_main_table_integrity(pkg):
    rows = pkg["tables"]["population_latam.csv"]
    years = [int(r["year"]) for r in canon("latam.csv")]
    for r in rows:
        assert r["population"] == "" or float(r["population"]) >= 0
        assert min(years) <= int(r["year"]) <= max(years)
        assert r["series_type"] in ("observed", "estimate", "projection")
        assert r["source_tier"] in ("national", "international_fallback")
        assert r["scenario"] in ("single", "medium", "recommended", "")
        assert r["reference_date"] in ("06-30", "07-01", "01-01", "mid-year", "census", "")
        assert r["interpolated"] == "False", "Ninguna serie se interpola"
        assert r["source_break"] in ("True", "False")
        assert r["license_status"] in ("open_license", "own_terms", "no_license", "restricted")


def test_pyramids_use_only_contract_groups(pkg):
    rows = pkg["tables"]["population_pyramids.csv"]
    assert {r["age_group"] for r in rows} == set(AGE_GROUPS)
    assert {r["sex"] for r in rows} == {"male", "female"}
    assert all(float(r["population"]) >= 0 for r in rows)
    per_year = Counter((r["iso3"], r["year"]) for r in rows)
    assert set(per_year.values()) == {34}, "17 grupos × 2 sexos por año, sin grupos inventados"


def test_growth_is_empty_at_every_break(pkg):
    for r in pkg["tables"]["population_latam.csv"]:
        if r["source_break"] == "True":
            assert r["growth"] == ""


def test_derived_files_say_they_are_not_official(pkg):
    assert {r["official"] for r in pkg["tables"]["population_region.csv"]} == {"False"}
    reg = [r for r in pkg["tables"]["aging_index.csv"] if r["iso3"] == "REG"]
    assert reg and all(r["source_tier"] == "derived" and r["series_type"] == "derived" for r in reg)
    readme = (pkg["out"] / "README.md").read_text(encoding="utf8")
    assert "derived, not official" in readme
    for claim in ("most complete", "most accurate", "definitive dataset", "official Latin America dataset"):
        assert claim not in readme.lower()


# ---------- reconciliación ----------

@pytest.mark.parametrize("out,src", [("population_latam.csv", "latam.csv"), ("population_region.csv", "region.csv"),
                                     ("aging_index.csv", "aging.csv")])
def test_reproduces_canonical_product(pkg, out, src):
    got, want = pkg["tables"][out], canon(src)
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert {k: g[k] for k in w} == w


def test_pyramids_match_canonical_json_and_totals(pkg):
    rows = pkg["tables"]["population_pyramids.csv"]
    total = {(r["iso3"], r["year"]): float(r["population"]) for r in canon("latam.csv")}
    total.update({("REG", r["year"]): int(r["population"]) for r in canon("region.csv")})
    sums = Counter()
    for r in rows:
        sums[(r["iso3"], r["year"])] += float(r["population"])
    for k, s in sums.items():
        assert abs(s - total[k]) / total[k] <= 0.0005, k
    for i in ISO3:
        doc = json.loads((P / "pyramids" / f"{i}.json").read_text(encoding="utf8"))
        mine = [r for r in rows if r["iso3"] == i]
        assert {int(r["year"]) for r in mine} == {int(y) for y in doc["years"]}
        for r in mine[:34]:
            v = doc["years"][r["year"]]
            assert float(r["population"]) == v["m" if r["sex"] == "male" else "f"][int(r["age_order"])]
            assert (r["source_id"], r["vintage"], r["source_tier"]) == (v["source_id"], v["vintage"], v["source_tier"])


def test_region_matches_canonical_json(pkg):
    doc = json.loads((P / "region.json").read_text(encoding="utf8"))
    rows = pkg["tables"]["population_region.csv"]
    assert [int(r["year"]) for r in rows] == doc["years"]
    for r, p in zip(rows, doc["points"]):
        assert int(r["population"]) == p["population"] and float(r["projection_share"]) == p["projection_share"]


def test_breaks_match_country_files(pkg):
    want = {(i, b["year"]) for i in ISO3 for b in json.loads((P / f"{i}.json").read_text(encoding="utf8"))["breaks"]}
    assert {(r["iso3"], int(r["year"])) for r in pkg["tables"]["source_breaks.csv"]} == want
    assert {(r["iso3"], int(r["year"])) for r in pkg["tables"]["population_latam.csv"] if r["source_break"] == "True"} == want


# ---------- trazabilidad ----------

def test_every_series_is_traceable(pkg):
    src = {(r["iso3"], r["source_id"], r["vintage"]): r for r in pkg["tables"]["sources.csv"]}
    for name in ("population_latam.csv", "population_pyramids.csv", "aging_index.csv"):
        for r in pkg["tables"][name]:
            if r["iso3"] == "REG":
                continue
            s = src[(r["iso3"], r["source_id"], r["vintage"])]
            assert s["source_url"].startswith("http") and s["raw_sha256"] and s["institution"]
            assert s["license"] == r["license"] and s["license_status"]


def test_manifest_records_commit_schema_and_hashes(pkg):
    m = pkg["manifest"]
    assert m["schema_version"] == "2.1" and m["source_repository"].startswith("https://github.com/jaforero/")
    assert set(m["files"]) == set(bk.CSV_FILES) and len(m["content_sha256"]) == 64
    assert "commit:" in (pkg["out"] / "SOURCE_COMMIT.txt").read_text(encoding="utf8")


# ---------- licencias y metadata ----------

def test_license_gate_is_conservative(pkg):
    g = pkg["gate"]
    lic = json.loads((P / "licenses.json").read_text(encoding="utf8"))["licenses"]
    for it in g["items"]:
        if lic[it["key"]]["status"] == "no_license":
            assert it["severity"] == "blocker", "Ausencia de licencia no es permiso"
    if any(lic[k]["status"] != "open_license" for k in (it["key"] for it in g["items"])):
        assert g["kaggle_license"] in ("other", "unknown")
    if any(it["severity"] and not it["acknowledged"] for it in g["items"]):
        assert g["status"] == "BLOCKED"
        assert (pkg["out"].parent / "PUBLICATION_BLOCKERS.md").exists()


def test_gate_rejects_a_standard_licence_over_mixed_terms():
    src = bk.load(ROOT)
    src["policy"] = dict(kaggle_license="CC-BY-4.0", acknowledgements={})
    g = bk.license_gate(bk.build_tables(src), src)
    assert g["status"] == "BLOCKED" and g["problems"]


def test_restricted_source_cannot_be_acknowledged():
    src = bk.load(ROOT)
    src["licenses"]["licenses"]["conapo"]["status"] = "restricted"
    src["policy"] = dict(kaggle_license="other", acknowledgements={"conapo": {"decision": "publish"}})
    g = bk.license_gate(bk.build_tables(src), src)
    assert "conapo" in g["pending"] and g["status"] == "BLOCKED"


def test_kaggle_metadata_is_valid(pkg):
    meta = json.loads((pkg["out"] / "dataset-metadata.json").read_text(encoding="utf8"))
    assert bk.check_metadata(meta) == []
    assert meta["id"] == "jaforero/latin-america-population-20-countries"
    assert meta["licenses"] == [{"name": pkg["gate"]["kaggle_license"]}]
    assert {r["path"] for r in meta["resources"]} == set(bk.CSV_FILES)
    text = json.dumps(meta).lower()
    for secret in ("token", "api_key", "password", "kaggle.json"):
        assert secret not in text
