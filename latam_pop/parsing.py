"""Lectores de bajo nivel compartidos por los adaptadores."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import openpyxl
import xlrd


class ParseError(Exception):
    pass


def num(x) -> float | None:
    """Convierte celdas numéricas; acepta separadores en texto como '91,58,345' (errata del INE-HND)."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[ ,. ]", "", str(x))
    return float(s) if s.isdigit() else None


def year_of(x) -> int | None:
    v = num(x) if not isinstance(x, str) else (float(x.strip()) if re.fullmatch(r"\s*\d{4}(\.0)?\s*", x) else None)
    return int(v) if v is not None and v == int(v) and 1900 <= v <= 2150 else None


def clean(population: float) -> int | float:
    """Conserva el valor publicado; solo pasa a int lo que ya es entero."""
    return int(population) if float(population).is_integer() else float(population)


def xlsx_rows(path: Path, sheet: str | int = 0):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if isinstance(sheet, str) else wb.worksheets[sheet]
    ws.reset_dimensions()  # algunos libros declaran dimensión A1 y truncarían la lectura
    for r in ws.iter_rows(values_only=True):
        yield list(r)
    wb.close()


def xlsx_sheetnames(path: Path) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    names = wb.sheetnames
    wb.close()
    return names


def xls_rows(path: Path, sheet: int = 0):
    ws = xlrd.open_workbook(path).sheet_by_index(sheet)
    for i in range(ws.nrows):
        yield ws.row_values(i)


def xlsx_xml_rows(path: Path, sheet_name: str):
    """Lectura directa del XML, para libros que openpyxl rechaza (nombres definidos con #N/A)."""
    z = zipfile.ZipFile(path)
    wb = z.read("xl/workbook.xml").decode("utf8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf8")
    m = re.search(rf'<sheet [^>]*name="{re.escape(sheet_name)}"[^>]*r:id="([^"]+)"', wb)
    if not m:
        raise ParseError(f"No existe la hoja {sheet_name}")
    t = re.search(rf'<Relationship [^>]*Id="{m.group(1)}"[^>]*?Target="([^"]+)"', rels) or \
        re.search(rf'<Relationship [^>]*Target="([^"]+)"[^>]*Id="{m.group(1)}"', rels)
    target = t.group(1).lstrip("/")
    target = target if target.startswith("xl/") else "xl/" + target
    strings = [
        "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
        for si in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode("utf8"), re.S)
    ]
    for row in re.findall(r"<row [^>]*>(.*?)</row>", z.read(target).decode("utf8"), re.S):
        out = []
        for attrs, body in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
            v = re.search(r"<v>(.*?)</v>", body or "")
            if v:
                out.append(strings[int(v.group(1))] if 't="s"' in attrs else v.group(1))
        yield out


def wide_row(rows, label: str, first_year: int) -> dict[int, float]:
    """Tablas anchas: busca la fila de años y la fila cuyo rótulo es `label`."""
    years = None
    label = label.lower()
    for r in rows:
        if years is None and any(year_of(c) == first_year for c in r):
            years = r
            continue
        if years is not None and any(isinstance(c, str) and c.strip().lower() == label for c in r):
            out = {}
            for y, v in zip(years, r):
                yy, vv = year_of(y), num(v)
                if yy and vv is not None:
                    out[yy] = vv
            return out
    raise ParseError(f"No se halló la fila '{label}' con años desde {first_year}")
