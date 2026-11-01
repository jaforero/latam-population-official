"""Cada parser, sin red, debe devolver la cifra de control registrada."""
import json
from pathlib import Path

import pytest
import yaml

from latam_pop.adapters import REGISTRY
from latam_pop.adapters.sources import VenIne2001

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
REG = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf8"))["sources"]
CASES = [("ARG", "historical", "arg_2010.xls"), ("ARG", "projection", "arg_2022.xlsx"), ("BOL", "historical", "bol.xlsx"),
         ("BOL", "projection", "bol.xlsx"), ("BRA", "historical", "bra.xlsx"), ("BRA", "projection", "bra.xlsx"),
         ("COL", "historical", "col_hist.xlsx"), ("COL", "projection", "col_proj.xlsx"),
         ("CRI", "historical", "cri.xlsx"), ("CRI", "projection", "cri.xlsx"), ("ECU", "historical", "ecu.xlsx"),
         ("ECU", "projection", "ecu.xlsx"), ("HND", "projection", "hnd.pdf"), ("MEX", "historical", "mex.csv"),
         ("MEX", "projection", "mex.csv"), ("NIC", "historical", "nic.pdf"), ("PAN", "historical", "pan.xlsx"),
         ("PAN", "projection", "pan.xlsx"), ("PER", "historical", "per.pdf"), ("PER", "projection", "per.pdf"),
         ("PRY", "historical", "pry.xlsx"), ("PRY", "projection", "pry.xlsx"), ("SLV", "historical", "slv.xlsx"),
         ("SLV", "projection", "slv.xlsx"), ("URY", "historical", "ury_hist.xlsx"), ("URY", "projection", "ury_proj.xlsx"),
         ("VEN", "projection", "ven_2011.xls"), ("VEN", "historical", "ven_2001.pdf"), ("HTI", "historical", "cepal_hti.json"),
         ("HTI", "projection", "cepal_hti.json"), ("HND", "historical", "cepal_hnd.json"), ("NIC", "projection", "cepal_nic.json")]


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


def test_cepal_strips_volatile_fields():
    e = REG["HTI"]["historical"]
    a = REGISTRY["cepal"]("HTI", "historical", e)
    wrapped = b'{"header":{"timestamp":1},"footer":{"ip":"1.2.3.4"},"body":{"data":[]}}'
    assert b"ip" not in a.transform(wrapped) and b"timestamp" not in a.transform(wrapped)
    assert json.loads(a.transform(wrapped)) == {"data": []}
