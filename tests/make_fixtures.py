"""Regenera tests/fixtures/ desde data/raw/: copia los crudos pequeños y recorta los grandes conservando su estructura.
Uso: python tests/make_fixtures.py"""
import csv
import glob
import json
import shutil
from pathlib import Path

import openpyxl
import pypdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures"
OUT.mkdir(exist_ok=True)


def latest(iso, key):
    return sorted(p for p in glob.glob(str(ROOT / f"data/raw/{iso}/{key}/*")) if not p.endswith(".meta.json"))[-1]


def trim_xlsx(src, dst, sheet, keep):
    ws = openpyxl.load_workbook(src, read_only=True, data_only=True)[sheet]
    ws.reset_dimensions()
    wb = openpyxl.Workbook()
    out = wb.active
    out.title = sheet
    for i, r in enumerate(ws.iter_rows(values_only=True), 1):
        out.append(list(r) if keep(i, r) else [])
    wb.save(dst)


for name, iso, key in [("arg_2010.xls", "ARG", "arg_indec_2010"), ("arg_2022.xlsx", "ARG", "arg_indec_2022"),
                       ("col_hist.xlsx", "COL", "col_dane_hist"), ("col_proj.xlsx", "COL", "col_dane_proj"),
                       ("pan.xlsx", "PAN", "pan_inec"), ("slv.xlsx", "SLV", "slv_onec"),
                       ("ury_hist.xlsx", "URY", "ury_ine_hist"), ("ury_proj.xlsx", "URY", "ury_ine_proj"),
                       ("ven_2011.xls", "VEN", "ven_ine_2011"), ("bol_rev2020.xlsx", "BOL", "bol_ine_rev2020"),
                       ("bol_rev2025.xlsx", "BOL", "bol_ine_rev2025"), ("bol_rev2014.xls", "BOL", "bol_ine_rev2014")]:
    shutil.copy(latest(iso, key), OUT / name)

trim_xlsx(latest("BRA", "bra_ibge"), OUT / "bra.xlsx", "4) INDICADORES", lambda i, r: i < 8 or r[3] == "Brasil")
trim_xlsx(latest("ECU", "ecu_inec"), OUT / "ecu.xlsx", "1.1",
          lambda i, r: i < 16 or (len(r) > 1 and isinstance(r[1], str) and r[1].strip() == "Total Nacional"))
trim_xlsx(latest("PRY", "pry_ine"), OUT / "pry.xlsx", "Poblac a mitad de año 1950-2050", lambda i, r: i < 10)
trim_xlsx(latest("CRI", "cri_inec"), OUT / "cri.xlsx", "C1. Población total", lambda i, r: True)
trim_xlsx(latest("CHL", "chl_ine"), OUT / "chl.xlsx", "Población al 30 de junio", lambda i, r: i < 14)
trim_xlsx(latest("_regional", "cepal_rev2024"), OUT / "cepal.xlsx", "CAD01", lambda i, r: True)


def pdf_pages(src, dst, pages):
    w = pypdf.PdfWriter()
    r = pypdf.PdfReader(src)
    for p in pages:
        w.add_page(r.pages[p - 1])
    w.write(dst)


pdf_pages(latest("HND", "hnd_ine"), OUT / "hnd.pdf", [26, 74, 94, 247, 248, 252, 256, 260, 264])
pdf_pages(latest("NIC", "nic_inide"), OUT / "nic.pdf", [45])
pdf_pages(latest("PER", "per_inei"), OUT / "per.pdf", [15, 16])
pdf_pages(latest("VEN", "ven_ine_2001"), OUT / "ven_2001.pdf", [30])

with open(latest("MEX", "mex_conapo_mitad"), encoding="utf-8-sig", newline="") as f, \
        open(OUT / "mex.csv", "w", encoding="utf8", newline="") as out:
    writer = csv.DictWriter(out, ["ANIO", "ENTIDAD", "CVE_GEO", "EDAD", "SEXO", "POBLACION"], lineterminator="\n")
    writer.writeheader()
    for r in csv.DictReader(f):
        if r["ANIO"] in ("2019", "2025"):
            writer.writerow({k: r[k] for k in writer.fieldnames})
print(json.dumps(sorted(p.name for p in OUT.iterdir())))
