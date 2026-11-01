"""Cada parser, sin red, debe devolver la cifra de control registrada."""
from pathlib import Path

import pytest
import yaml

from latam_pop.adapters import REGISTRY
from latam_pop.adapters.sources import VenIne2001

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
REG = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf8"))["sources"]
CASES = [("ARG", "historical", "arg_2010.xls"), ("ARG", "projection", "arg_2022.xlsx"), ("BOL", "historical", "bol_anual.xlsx"),
         ("BOL", "projection", "bol_anual.xlsx"), ("CUB", "historical", "cepal.xlsx"), ("CUB", "projection", "cepal.xlsx"), ("CHL", "historical", "chl.xlsx"), ("CHL", "projection", "chl.xlsx"), ("BRA", "historical", "bra.xlsx"), ("BRA", "projection", "bra.xlsx"),
         ("COL", "historical", "col_hist.xlsx"), ("COL", "projection", "col_proj.xlsx"),
         ("CRI", "historical", "cri.xlsx"), ("CRI", "projection", "cri.xlsx"), ("ECU", "historical", "ecu.xlsx"),
         ("DOM", "historical", "dom.csv"), ("DOM", "projection", "dom.csv"), ("ECU", "projection", "ecu.xlsx"), ("GTM", "historical", "gtm.xlsx"), ("GTM", "projection", "gtm.xlsx"), ("HND", "projection", "hnd.pdf"), ("MEX", "historical", "mex_ind.csv"),
         ("MEX", "projection", "mex_ind.csv"), ("NIC", "historical", "nic.pdf"), ("PAN", "historical", "pan.xlsx"),
         ("PAN", "projection", "pan.xlsx"), ("PER", "historical", "per.pdf"), ("PER", "projection", "per.pdf"),
         ("PRY", "historical", "pry.xlsx"), ("PRY", "projection", "pry.xlsx"), ("SLV", "historical", "slv.xlsx"),
         ("SLV", "projection", "slv.xlsx"), ("URY", "historical", "ury_hist.xlsx"), ("URY", "projection", "ury_proj.xlsx"),
         ("VEN", "projection", "ven_2011.xls"), ("VEN", "historical", "ven_2001.pdf"), ("HTI", "historical", "cepal.xlsx"),
         ("HTI", "projection", "cepal.xlsx"), ("HND", "historical", "cepal.xlsx"), ("NIC", "projection", "cepal.xlsx")]


@pytest.mark.parametrize("iso3,kind,fixture", CASES)
def test_control_figure(iso3, kind, fixture):
    VenIne2001.transcription_root = ROOT
    e = REG[iso3][kind]
    rows = REGISTRY[e["adapter"]](iso3, kind, e).parse(FIX / fixture)
    c = e["control"]
    factor = 1000 if "miles" in c["unit"] else 1
    assert rows[c["year"]] == pytest.approx(float(c["value"]) * factor)


def test_honduras_quinquennial_and_typo():
    e = REG["HND"]["projection"]
    rows = REGISTRY[e["adapter"]]("HND", "projection", e).parse(FIX / "hnd.pdf")
    assert {2035, 2040, 2045, 2050} <= set(rows)
    assert rows[2030] == 10766670


def test_nicaragua_has_marked_years():
    e = REG["NIC"]["historical"]
    a = REGISTRY[e["adapter"]]("NIC", "historical", e)
    rows = a.parse(FIX / "nic.pdf")
    assert rows[1990] == 3959785 and rows[2006] == 5522606 and rows[2011] == 5996619
    assert a.segment_for(2005)[0] == "nic_inide_rev2004" and a.segment_for(2006)[0] == "nic_inide_rev2007"


def test_venezuela_transcription_rejects_bad_sum(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("year,total,hombres,mujeres\n1950,10,4,5\n")
    VenIne2001.transcription_root = tmp_path
    e = dict(REG["VEN"]["historical"], transcription="t.csv")
    with pytest.raises(Exception, match="inconsistente"):
        VenIne2001("VEN", "historical", e).parse(FIX / "ven_2001.pdf")
    VenIne2001.transcription_root = ROOT


def test_cepal_reads_one_country_in_persons():
    e = REG["HTI"]["projection"]
    rows = REGISTRY[e["adapter"]]("HTI", "projection", e).parse(FIX / "cepal.xlsx")
    assert rows[2024] == 11772557 and min(rows) == 1950 and max(rows) == 2100


def test_mexico_reads_national_row():
    e = REG["MEX"]["historical"]
    rows = REGISTRY[e["adapter"]]("MEX", "historical", e).parse(FIX / "mex_ind.csv")
    assert rows[1950] == 28463441 and rows[2070] == 141440479 and len(rows) == 121


def test_series_type_follows_source_labels():
    bol = REGISTRY["bol_ine"]("BOL", "historical", REG["BOL"]["historical"])
    assert bol.series_type_for(2023) == "estimate"
    chl = REGISTRY["chl_ine"]("CHL", "projection", REG["CHL"]["projection"])
    assert chl.series_type_for(2025) == "projection"
    cri = REGISTRY["cri_inec"]("CRI", "historical", REG["CRI"]["historical"])
    assert cri.series_type_for(2022) == "estimate"
    ven = REGISTRY["ven_ine_2011"]("VEN", "projection", REG["VEN"]["projection"])
    assert ven.series_type_for(2010) == "estimate" and ven.series_type_for(2015) == "projection"


def test_costa_rica_keeps_year_with_footnote():
    e = REG["CRI"]["historical"]
    rows = REGISTRY[e["adapter"]]("CRI", "historical", e).parse(FIX / "cri.xlsx")
    assert rows[2022] == pytest.approx(5104906.836650608)
    assert sorted(rows) == list(range(1950, 2101))
