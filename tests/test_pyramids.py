"""Pirámides: cada parser, sin red, debe cuadrar con el total oficial y con la identidad de los sexos."""
from pathlib import Path

import pytest

from latam_pop.adapters.base import Record
from latam_pop.pyramids import AGE_GROUPS, PARSERS, build_pyramid, harmonize, parse_age, year_columns
from latam_pop.store import RawStore

FIX = Path(__file__).parent / "fixtures"
CASES = [
    ("arg", {"arg_indec_2022_edades": "arg_edades.csv"}, 2025, 46387098),
    ("bra", {"bra_ibge_tab2": "bra_tab2.xlsx"}, 2025, 213421037),
    ("chl", {"chl_ine": "chl.xlsx"}, 2026, 20150948),
    ("col", {"col_dane_edad_hist": "col_edad_hist.xlsx", "col_dane_edad_proj": "col_edad_proj.xlsx"}, 2025, 53057212),
    ("cri", {"cri_inec": "cri_c2.xlsx"}, 2025, 5191823.08),
    ("ecu", {"ecu_inec": "ecu.xlsx"}, 2025, 18103660),
    ("gtm", {"gtm_ine": "gtm.xlsx"}, 2025, 18079810),
    ("hnd", {"hnd_ine": "hnd.pdf"}, 2025, 10039862),
    ("hnd", {"hnd_ine": "hnd.pdf"}, 2035, 11464062),
    ("mex", {"mex_conapo_mitad": "mex.csv"}, 2025, 133367428),
    ("nic", {"nic_inide": "nic.pdf"}, 2025, 6946351),
    ("pan", {"pan_inec": "pan.xlsx"}, 2025, 4598365),
    ("per", {"per_inei": "per.pdf"}, 2025, 34350244),
    ("pry", {"pry_ine": "pry.xlsx"}, 2025, 6417076),
    ("slv", {"slv_onec": "slv.xlsx"}, 2025, 6366086),
    ("ury", {"ury_ine_hist": "ury_hist.xlsx", "ury_ine_proj": "ury_proj.xlsx"}, 2025, 3485931.25),
]


def load(parser, files):
    return PARSERS[parser]({k: FIX / v for k, v in files.items()})


@pytest.mark.parametrize("parser,files,year,total", CASES)
def test_parser_matches_official_total(parser, files, year, total):
    y = load(parser, files)[year]
    assert len(y["m"]) == len(y["f"]) == len(AGE_GROUPS) == 17
    assert sum(y["m"]) + sum(y["f"]) == pytest.approx(total, abs=1)
    assert y["m"][0] > y["f"][0], "Nacen más hombres que mujeres"
    assert y["f"][16] > y["m"][16], "En 80+ hay más mujeres que hombres"


def test_argentina_sex_codes_follow_indec_metadata():
    y = load("arg", {"arg_indec_2022_edades": "arg_edades.csv"})[2025]
    assert sum(y["m"]) == 22810428 and sum(y["f"]) == 23576670


@pytest.mark.parametrize("label,expected", [
    ("0 a 4", (0, 4)), ("00 - 04", (0, 4)), (" 00-04", (0, 4)), ("100+", (100, None)), ("85 y más", (85, None)),
    ("80 y +", (80, None)), ("100 años y más", (100, None)), ("90 y más", (90, None)), (7, (7, 7)), ("7.0", (7, 7)),
    ("Total", None), ("Hombres", None),
])
def test_parse_age(label, expected):
    assert parse_age(label) == expected


def test_harmonize_does_not_double_count_groups_and_single_ages():
    cells = {(a, a + 4): 10.0 for a in range(0, 80, 5)}
    cells.update({(a, a): 2.0 for a in range(0, 80)})
    cells[(80, None)] = 7.0
    assert sum(harmonize(cells)) == 167.0


def test_harmonize_folds_older_groups_into_80_plus():
    cells = {(a, a + 4): 1.0 for a in range(0, 100, 5)}
    cells[(100, None)] = 1.0
    assert harmonize(cells)[16] == 5.0


def test_harmonize_rejects_missing_groups():
    with pytest.raises(Exception, match="Faltan grupos"):
        harmonize({(0, 4): 1.0})


def test_year_columns_ignores_data_rows_with_year_like_values():
    assert year_columns(["Sexo", 2000, 2001, 2002]) == {1: 2000, 2: 2001, 3: 2002}
    assert year_columns([85, 2045, 2061, 2118]) == {}


# 0-4 con más hombres y 80+ con más mujeres; suma 321.
GOOD = {"m": [10.0] * 16 + [8.0], "f": [9.0] * 16 + [9.0]}


def rec(y, p):
    return Record("XXX", y, p, "projection", "s", "national", "v", None, None, "2026-01-01")


def cfg(parser="fake"):
    return dict(status="ok", parser=parser, institution="I", url="u", files=[dict(raw_key="k")])


def fake_store(tmp_path):
    s = RawStore(tmp_path)
    s.save("XXX", "k", "f.csv", b"x", "u", today="2026-01-01")
    return s


def test_pyramid_year_that_does_not_match_official_total_is_not_published(tmp_path):
    PARSERS["fake"] = lambda paths: {2025: GOOD, 2026: {"m": [99.0] * 16 + [8.0], "f": [9.0] * 16 + [9.0]}}
    doc, alerts, failures = build_pyramid("XXX", cfg(), {2025: rec(2025, 321), 2026: rec(2026, 321)}, fake_store(tmp_path), None, None)
    assert list(doc["years"]) == ["2025"] and failures == []
    assert [a["code"] for a in alerts] == ["pyramid_total_mismatch"]
    del PARSERS["fake"]


def test_pyramid_only_uses_years_of_the_main_series(tmp_path):
    PARSERS["fake"] = lambda paths: {2025: GOOD, 2030: GOOD}
    doc, _, _ = build_pyramid("XXX", cfg(), {2025: rec(2025, 321)}, fake_store(tmp_path), None, None)
    assert list(doc["years"]) == ["2025"]
    del PARSERS["fake"]


def test_pyramid_flags_implausible_sex_structure(tmp_path):
    PARSERS["fake"] = lambda paths: {2025: {"m": [9.0] * 17, "f": [10.0] * 17}}
    _, alerts, _ = build_pyramid("XXX", cfg(), {2025: rec(2025, 323)}, fake_store(tmp_path), None, None)
    assert [a["code"] for a in alerts] == ["pyramid_sex_ratio"]
    del PARSERS["fake"]


def test_parser_failure_does_not_raise(tmp_path):
    def boom(paths):
        raise ValueError("formato nuevo")
    PARSERS["fake"] = boom
    doc, _, failures = build_pyramid("XXX", cfg(), {}, fake_store(tmp_path), None, None)
    assert doc["status"] == "error" and failures[0]["series"] == "pyramid"
    del PARSERS["fake"]
