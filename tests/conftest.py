import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


class FakeHttp:
    """Sirve fixtures en lugar de la red. Una URL en `fail` responde como si la fuente hubiera caído."""

    def __init__(self, reg, fail=()):
        self.fail = set(fail)
        self.map = {}
        names = {"arg_indec_2010": "arg_2010.xls", "arg_indec_2022": "arg_2022.xlsx", "bra_ibge": "bra.xlsx",
                 "col_dane_hist": "col_hist.xlsx", "col_dane_proj": "col_proj.xlsx", "ecu_inec": "ecu.xlsx",
                 "hnd_ine": "hnd.pdf", "nic_inide": "nic.pdf", "pan_inec": "pan.xlsx", "per_inei": "per.pdf",
                 "pry_ine": "pry.xlsx", "slv_onec": "slv.xlsx", "ury_ine_hist": "ury_hist.xlsx",
                 "ury_ine_proj": "ury_proj.xlsx", "ven_ine_2001": "ven_2001.pdf", "ven_ine_nacional": "ven_2011.xls", "dom_one": "dom.csv",
                 "un_wpp2024_total": "un_total.csv.gz", "un_wpp2024_age5": "un_age5.csv.gz", "chl_ine": "chl.xlsx", "arg_indec_2022_edades": "arg_edades.csv",
                 "bra_ibge_tab2": "bra_tab2.xlsx", "col_dane_edad_hist": "col_edad_hist.xlsx", "col_dane_edad_proj": "col_edad_proj.xlsx"}
        for v in reg["sources"].values():
            for e in v.values():
                if e.get("raw_key") in names:
                    self.map[e["url"]] = FIX / names[e["raw_key"]]
                for f in e.get("files", []) + [x for part in e.get("extra_parts", []) for x in part["files"]]:
                    if f.get("url"):
                        self.map[f["url"]] = FIX / names[f["raw_key"]]

    def get(self, url):
        from latam_pop.http import FetchError
        if url in self.fail or url not in self.map:
            raise FetchError(f"HTTP 503 en {url}")
        return self.map[url].read_bytes()


@pytest.fixture
def workdir(tmp_path):
    shutil.copy(ROOT / "sources.yaml", tmp_path / "sources.yaml")
    (tmp_path / "data" / "manual").mkdir(parents=True)
    shutil.copy(ROOT / "data/manual/ven_ine_censo2001_cuadro1.csv", tmp_path / "data/manual/")
    return tmp_path
