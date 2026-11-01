"""Reglas de negocio: derivados, rupturas, validaciones, descarga."""
import pytest

from latam_pop.adapters import REGISTRY
from latam_pop.adapters.base import Record
from latam_pop.build import resolve_overlaps, strip_volatile, write_stable
from latam_pop.derive import add_growth, cagr, find_breaks, peak
from latam_pop.http import FetchError
from latam_pop.store import RawStore
from latam_pop.validate import check_against_previous, check_entry, check_growth, expected_years


def rec(y, p, sid="a", tier="national", stype="estimate", v="v1"):
    return Record("XXX", y, p, stype, sid, tier, v, None, None, "2026-01-01")


def test_growth_within_series():
    rs = [rec(2000, 100), rec(2001, 110)]
    add_growth(rs)
    assert rs[0].growth is None and rs[1].growth == pytest.approx(0.10)


def test_no_growth_across_break_or_gap():
    rs = [rec(2000, 100), rec(2001, 110, sid="b"), rec(2005, 120, sid="b")]
    add_growth(rs)
    assert all(r.growth is None for r in rs)


def test_cagr_refuses_breaks():
    rs = [rec(2000, 100), rec(2010, 200), rec(2011, 300, sid="b")]
    assert cagr(rs, 2000, 2010) == pytest.approx(2 ** 0.1 - 1)
    assert cagr(rs, 2000, 2011) is None and cagr(rs, 2000, 2005) is None


def test_breaks_recorded_with_cut_year():
    b = find_breaks([rec(2021, 45), rec(2022, 46, sid="b", v="v2")])
    assert b[0]["year"] == 2022 and b[0]["from_source"] == "a" and b[0]["to_source"] == "b"


def test_peak_statuses():
    up = [rec(2030, 1, stype="projection"), rec(2040, 2, stype="projection")]
    assert peak(up)["status"] == "no_peak_in_horizon" and peak(up)["horizon_end"] == 2040
    hump = [rec(2030, 1, stype="projection"), rec(2035, 3, stype="projection"), rec(2040, 2, stype="projection")]
    assert peak(hump)["year"] == 2035
    assert peak([rec(2000, 1)])["status"] == "no_projection"


def test_peak_ignores_other_vintages():
    rs = [rec(2020, 99, sid="old"), rec(2030, 1, stype="projection"), rec(2040, 2, stype="projection")]
    assert peak(rs)["status"] == "no_peak_in_horizon"


def test_national_prevails_over_regional():
    kept, dropped = resolve_overlaps([rec(2025, 10, sid="cepal", tier="regional_fallback"), rec(2025, 9, sid="ine"), rec(2026, 11, sid="cepal", tier="regional_fallback")])
    assert [r.source_id for r in kept] == ["ine", "cepal"]
    assert dropped == [dict(year=2025, dropped_source="cepal", kept_source="ine")]


def test_alerts_duplicate_gap_control():
    e = dict(year_from=2000, year_to=2002, control=dict(year=2000, value=1, unit="personas"))
    rs = [rec(2000, 2), rec(2000, 2)]
    codes = {a["code"] for a in check_entry("XXX", "historical", e, {2000: 2}, rs)}
    assert codes == {"duplicate_year", "gap", "control_mismatch"}


def test_alert_annual_change_does_not_correct():
    rs = [rec(2000, 100), rec(2001, 105)]
    add_growth(rs)
    assert check_growth("XXX", rs)[0]["code"] == "annual_change" and rs[1].population == 105


def test_quinquennial_expected_years():
    assert expected_years(dict(year_from=2028, year_to=2040, annual_until=2030, step_after=5)) == [2028, 2029, 2030, 2035, 2040]
    assert expected_years(dict(year_from=2000, year_to=2010, annual_until=1999, step_after=5)) == [2000, 2005, 2010]


def test_year_of_accepts_footnote_marks_only():
    from latam_pop.parsing import year_of
    assert year_of("2022a/") == 2022 and year_of("2022") == 2022 and year_of(2022.0) == 2022
    assert year_of("Total") is None and year_of("2022 hombres") is None and year_of(123) is None


def test_vintage_and_tier_change_alerts():
    prev = dict(projection=dict(source_id="cepal", vintage="r1", source_tier="regional_fallback"))
    cur = dict(projection=dict(source_id="ine", vintage="r2", source_tier="national"))
    assert {a["code"] for a in check_against_previous("XXX", prev, cur)} == {"vintage_change", "national_replaces_regional"}


def test_store_keeps_hash_and_dedupes(tmp_path):
    s = RawStore(tmp_path)
    a = s.save("ARG", "k", "f.xls", b"123", "u", today="2026-01-01")
    b = s.save("ARG", "k", "f.xls", b"123", "u", today="2026-02-02")
    c = s.save("ARG", "k", "f.xls", b"456", "u", today="2026-03-03")
    assert a.path == b.path and b.retrieved_at == "2026-01-01"
    assert s.latest("ARG", "k").path == c.path and c.path.exists()


def test_store_latest_respects_order_within_a_day(tmp_path):
    s = RawStore(tmp_path)
    for content in (b"zzz", b"aaa", b"mmm"):
        last = s.save("ARG", "k", "f.xls", content, "u", today="2026-01-01")
    assert s.latest("ARG", "k").sha256 == last.sha256


def test_blocked_page_is_not_saved_as_data():
    e = dict(access_method="XLSX", url="http://x/f.xlsx", status="ok")
    a = REGISTRY["bol_ine"]("BOL", "historical", e)
    with pytest.raises(FetchError):
        a.check_content(b"<!DOCTYPE html><title>Just a moment</title>")


def test_stable_write_ignores_timestamps(tmp_path):
    p = tmp_path / "x.json"
    assert write_stable(p, dict(a=1, generated_at="t1"))
    assert not write_stable(p, dict(a=1, generated_at="t2"))
    assert write_stable(p, dict(a=2, generated_at="t2"))
    assert strip_volatile(dict(a=1, last_success="x")) == dict(a=1)
