"""Punta a punta sin red, con fixtures."""
import csv
import json

import yaml

from conftest import FakeHttp
from latam_pop import ISO3
from latam_pop.build import run


def load(p):
    return json.loads(p.read_text(encoding="utf8"))


def reg(root):
    return yaml.safe_load((root / "sources.yaml").read_text(encoding="utf8"))


def test_end_to_end(workdir):
    r = reg(workdir)
    rep = run(workdir, http=FakeHttp(r), watch=False, today="2026-11-01")
    assert rep["failures"] == []
    for iso in ISO3:
        assert (workdir / f"data/processed/{iso}.json").exists()
    arg = load(workdir / "data/processed/ARG.json")
    assert arg["breaks"][0]["year"] == 2022
    assert next(x for x in arg["records"] if x["year"] == 2022)["growth"] is None
    assert next(x for x in arg["records"] if x["year"] == 2023)["growth"] is not None
    assert arg["peak"]["status"] == "no_peak_in_horizon"
    st = load(workdir / "data/status.json")["countries"]
    assert st["CHL"]["series"]["projection"]["status"] == "pendiente"
    assert st["BOL"]["series"]["historical"]["status"] == "manual_pendiente"
    assert st["COL"]["series"]["projection"]["source_tier"] == "national"
    assert st["HTI"]["series"]["projection"]["source_tier"] == "regional_fallback"
    with open(workdir / "data/processed/latam.csv", encoding="utf8") as f:
        rows = list(csv.DictReader(f))
    assert rows and all((workdir / x["raw_file"]).exists() for x in rows)
    assert {"manifest.json", "latam.csv"} <= {p.name for p in (workdir / "data/processed").iterdir()}


def test_failing_country_keeps_last_data_and_others_continue(workdir):
    r = reg(workdir)
    run(workdir, http=FakeHttp(r), watch=False, today="2026-11-01")
    before = load(workdir / "data/processed/COL.json")["records"]
    url = r["sources"]["COL"]["historical"]["url"]
    rep = run(workdir, http=FakeHttp(r, fail={url}), watch=False, today="2026-11-08")
    assert [f["iso3"] for f in rep["failures"]] == ["COL"]
    assert load(workdir / "data/processed/COL.json")["records"] == before
    st = load(workdir / "data/status.json")["countries"]["COL"]["series"]["historical"]
    assert st["status"] == "stale" and "503" in st["error"] and st["last_success"] == "2026-11-01"
    assert load(workdir / "data/status.json")["countries"]["ARG"]["series"]["historical"]["status"] == "ok"


def test_failure_without_previous_data_does_not_crash(workdir):
    r = reg(workdir)
    url = r["sources"]["URY"]["historical"]["url"]
    rep = run(workdir, http=FakeHttp(r, fail={url}), watch=False, today="2026-11-01")
    assert load(workdir / "data/status.json")["countries"]["URY"]["series"]["historical"]["status"] == "error"
    assert any(f["iso3"] == "URY" for f in rep["failures"])
    assert load(workdir / "data/processed/URY.json")["records"]


def test_no_changes_means_no_file_changes(workdir):
    r = reg(workdir)
    run(workdir, http=FakeHttp(r), watch=False, today="2026-11-01")
    files = {p: p.read_bytes() for p in (workdir / "data").rglob("*") if p.is_file()}
    run(workdir, http=FakeHttp(r), watch=False, today="2026-11-08")
    assert files == {p: p.read_bytes() for p in (workdir / "data").rglob("*") if p.is_file()}


def test_manual_ingest_activates_country(workdir):
    from pathlib import Path
    from latam_pop.store import RawStore
    r = reg(workdir)
    fix = Path(__file__).parent / "fixtures" / "cri.xlsx"
    RawStore(workdir / "data/raw").save("CRI", "cri_inec", "cri.xlsx", fix.read_bytes(), "u", "manual")
    run(workdir, http=FakeHttp(r), watch=False, today="2026-11-01")
    cri = load(workdir / "data/processed/CRI.json")
    assert cri["records"] and load(workdir / "data/status.json")["countries"]["CRI"]["series"]["projection"]["status"] == "manual"
