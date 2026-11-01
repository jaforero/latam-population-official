"""Cada parser, sin red, debe devolver la cifra de control registrada."""
from pathlib import Path

import pytest
import yaml

from latam_pop.adapters import REGISTRY
from latam_pop.adapters.sources import VenIne2001

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
REG = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf8"))["sources"]
CASES = [("ARG", "historical", "arg_2010.xls"), ("ARG", "projection", "arg_2022.xlsx"), ("BOL", "historical", "bol_rev2020.xlsx"),
         ("BOL", "projection", "bol_rev2025.xlsx"), ("CHL", "historical", "chl.xlsx"), ("CHL", "projection", "chl.xlsx"), ("BRA", "historical", "bra.xlsx"), ("BRA", "projection", "bra.xlsx"),
         ("COL", "historical", "col_hist.xlsx"), ("COL", "projection", "col_proj.xlsx"),
         ("CRI", "historical", "cri_censos.xlsx"), ("CRI", "projection", "cri.xlsx"), ("ECU", "historical", "ecu.xlsx"),
         ("ECU", "projection", "ecu.xlsx"), ("HND", "projection", "hnd.pdf"), ("MEX", "historical", "mex.csv"),
         ("MEX", "projection", "mex.csv"), ("NIC", "historical", "nic.pdf"), ("PAN", "historical", "pan.xlsx"),
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


def test_mexico_sums_municipalities_and_checks_states(tmp_path):
    e = REG["MEX"]["projection"]
    a = REGISTRY[e["adapter"]]("MEX", "projection", e)
    assert a.parse(FIX / "mex.csv")[2025] == 133367428
    bad = tmp_path / "m.csv"
    bad.write_text("ANO,CLAVE_ENT,POB_MIT_MUN,POB_MIT_ENT\n2025,1,10,10\n2025,2,5,6\n", encoding="utf8")
    with pytest.raises(Exception, match="no coinciden"):
        a.parse(bad)


def test_mexico_also_accepts_national_file(tmp_path):
    e = REG["MEX"]["projection"]
    f = tmp_path / "n.csv"
    f.write_text("ANIO,ENTIDAD,CVE_GEO,POB_MIT_ANIO\n2025,República Mexicana,0,133367428\n2025,Colima,6,1\n", encoding="utf8")
    assert REGISTRY[e["adapter"]]("MEX", "projection", e).parse(f) == {2025: 133367428.0}


def test_bolivia_accepts_both_layouts(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["AÑOS", "POBLACIÓN"])
    wb.active.append([2025, 11945263])
    f = tmp_path / "b.xlsx"
    wb.save(f)
    e = REG["BOL"]["projection"]
    assert REGISTRY[e["adapter"]]("BOL", "projection", e).parse(f) == {2025: 11945263.0}


def test_series_type_follows_source_labels():
    cri = REGISTRY["cri_inec_censos"]("CRI", "historical", REG["CRI"]["historical"])
    assert cri.series_type_for(2011) == "observed" and cri.series_type_for(2022) == "estimate"
    bol = REGISTRY["bol_ine"]("BOL", "historical", REG["BOL"]["historical"])
    assert bol.series_type_for(2012) == "estimate" and bol.series_type_for(2013) == "projection"
    chl = REGISTRY["chl_ine"]("CHL", "projection", REG["CHL"]["projection"])
    assert chl.series_type_for(2025) == "projection"
