"""Regenera tests/fixtures/ desde data/raw/: copia los crudos pequeños y recorta los grandes conservando su estructura.
BOL, CRI y MEX son fuentes manuales: sus fixtures imitan el formato con cifras de control, no son copias del original.
Uso: python tests/make_fixtures.py"""
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
                       ("ven_2011.xls", "VEN", "ven_ine_2011"), ("cepal_hti.json", "HTI", "cepal_hti"),
                       ("cepal_hnd.json", "HND", "cepal_hnd"), ("cepal_nic.json", "NIC", "cepal_nic")]:
    shutil.copy(latest(iso, key), OUT / name)

trim_xlsx(latest("BRA", "bra_ibge"), OUT / "bra.xlsx", "4) INDICADORES", lambda i, r: i < 8 or r[3] == "Brasil")
trim_xlsx(latest("ECU", "ecu_inec"), OUT / "ecu.xlsx", "1.1",
          lambda i, r: i < 16 or (len(r) > 1 and isinstance(r[1], str) and r[1].strip() == "Total Nacional"))
trim_xlsx(latest("PRY", "pry_ine"), OUT / "pry.xlsx", "Poblac a mitad de año 1950-2050", lambda i, r: i < 10)


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

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "7"
for r in [["Cuadro N°7"], ["BOLIVIA: POBLACIÓN ESTIMADA"], ["AÑOS", "POBLACIÓN AL 01 DE ENERO", "TASA"],
          [2023, 11872175, 0.62], [2024, 11916453, 0.37], [2025, 11945263, 0.24], [2026, 11970000, 0.2]]:
    ws.append(r)
wb.save(OUT / "bol.xlsx")
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "C1. Población total"
for r in [[" "], ["Costa Rica. Población total"], [], ["Año", "Población"], [None, "Total", "Hombres", "Mujeres"],
          [2021, 5077666.8598168921, 2538898.1, 2538768.7], [2025, 5191823.0799561152, 2592026.8, 2599796.2]]:
    ws.append(r)
wb.save(OUT / "cri.xlsx")
(OUT / "mex.csv").write_text("RENGLON,ANIO,ENTIDAD,CVE_GEO,POB_MIT_ANIO\n1,2019,República Mexicana,0,127215666\n"
                             "2,2025,República Mexicana,0,133367428\n3,2025,Aguascalientes,1,1500000\n", encoding="utf8")
print(json.dumps(sorted(p.name for p in OUT.iterdir())))
