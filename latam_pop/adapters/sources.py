"""Un adaptador por fuente. Cada parse devuelve {año: población} tal como la publica la fuente."""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pypdf

from ..parsing import ParseError, num, wide_row, xls_rows, xlsx_rows, xlsx_sheetnames, xlsx_xml_rows, year_of
from .base import Adapter, register


def first_two(rows) -> dict[int, float]:
    """Tablas largas: primera celda no vacía = año, segunda = total."""
    out = {}
    for r in rows:
        v = [c for c in r if c not in (None, "")]
        if len(v) >= 2 and year_of(v[0]) and num(v[1]) is not None:
            out.setdefault(year_of(v[0]), num(v[1]))
    return out


def pdf_pages(path: Path):
    return [p.extract_text() or "" for p in pypdf.PdfReader(path).pages]


@register("arg_indec_2010")
class ArgIndec2010(Adapter):
    def parse(self, raw):
        return first_two(xls_rows(raw))


@register("arg_indec_2022")
class ArgIndec2022(Adapter):
    def parse(self, raw):
        return first_two(xlsx_xml_rows(raw, "01-TOTAL DEL PAÍS"))


@register("bol_ine")
class BolIne(Adapter):
    def parse(self, raw):
        return first_two(xlsx_rows(raw))


@register("bra_ibge")
class BraIbge(Adapter):
    def parse(self, raw):
        out, h = {}, None
        for r in xlsx_rows(raw):
            if h is None:
                if "POP_T" in r:
                    h = {c: i for i, c in enumerate(r) if c}
                continue
            if r[h["LOCAL"]] == "Brasil":
                out[int(r[h["ANO"]])] = float(r[h["POP_T"]])
        if not out:
            raise ParseError("Sin filas de Brasil")
        return out


@register("col_dane")
class ColDane(Adapter):
    def parse(self, raw):
        out = {}
        for sheet in xlsx_sheetnames(raw):
            if sheet.lower().startswith(("índice", "indice", "pped")):
                continue
            for r in xlsx_rows(raw, sheet):
                for i, c in enumerate(r[:-2]):
                    if year_of(c) and r[i + 1] == "Total" and num(r[i + 2]) is not None:
                        out[year_of(c)] = num(r[i + 2])
        return out


@register("cri_inec")
class CriInec(Adapter):
    def parse(self, raw):
        return first_two(xlsx_rows(raw, "C1. Población total"))


@register("ecu_inec")
class EcuInec(Adapter):
    def parse(self, raw):
        years = None
        for r in xlsx_rows(raw, "1.1"):
            if years is None and any(year_of(c) == 1950 for c in r):
                years = {year_of(c): i for i, c in enumerate(r) if year_of(c)}
            elif years and len(r) > 1 and isinstance(r[1], str) and r[1].strip() == "Total Nacional":
                # Cada año ocupa tres columnas: Hombre, Mujer, Total.
                return {y: float(r[i + 2]) for y, i in years.items()}
        raise ParseError("Sin fila Total Nacional")


@register("hnd_ine")
class HndIne(Adapter):
    """Tomo 9: una página por año hasta 2030; los quinquenios 2030-2050 se ubican con el índice del propio tomo."""

    def parse(self, raw):
        pages = [" ".join(t.split()) for t in pdf_pages(raw)]
        out = {}
        for t in pages:
            m = re.search(r"(20[123]\d)\|\s*Proyecci.n de poblaci.n total", t)
            total = re.search(r"Total (\d[\d,]{6,}) ", t)
            if m and total and "por sexo, según grupos de edad" in t:
                out.setdefault(int(m.group(1)), num(total.group(1)))
        index = next((t for t in pages if "Proyecciones totales quinquenales" in t), "")
        for y, page in re.findall(r"\b(20[345][05]) (\d{3})\b", index):
            t = next((t for t in pages if re.search(rf"Vivienda 2013 {page} ", t)), "")
            total = re.search(r"\b(\d{1,2},\d{3},\d{3})\b", t)
            if total:
                out.setdefault(int(y), num(total.group(1)))
        return out


@register("mex_conapo")
class MexConapo(Adapter):
    def parse(self, raw):
        data = Path(raw).read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin1")
        out = {}
        for r in csv.DictReader(io.StringIO(text)):
            if r["CVE_GEO"].strip() == "0" or r["ENTIDAD"].lower().startswith("rep"):
                out[int(r["ANIO"])] = float(r["POB_MIT_ANIO"])
        return out


@register("nic_inide")
class NicInide(Adapter):
    def parse(self, raw):
        for t in pdf_pages(raw):
            if "II.1.2" in t and re.search(r"POBLACI.N ESTIMADA AL 30 DE JUNIO", t):
                rows = re.findall(r"\b((?:19|20)\d\d)(?:\s*[a-c]/)?\s+(\d,\d{3},\d{3})\s", t + " ")
                if rows:
                    return {int(y): num(v) for y, v in rows}
        raise ParseError("No se halló el cuadro II.1.2")


@register("pan_inec")
class PanInec(Adapter):
    def parse(self, raw):
        out = {}
        for sheet in xlsx_sheetnames(raw):
            years = None
            for r in xlsx_rows(raw, sheet):
                if any(isinstance(c, str) and c.strip() == "Sexo y edad" for c in r):
                    years = r
                elif years and any(isinstance(c, str) and c.strip() == "TOTAL" for c in r):
                    for y, v in zip(years, r):
                        if year_of(y) and num(v) is not None:
                            out[year_of(y)] = num(v)
                    break
        return out


@register("per_inei")
class PerInei(Adapter):
    def parse(self, raw):
        out = {}
        for t in pdf_pages(raw):
            if re.search(r"CUADRO N. ?1\b", t) and "SEGÚN AÑO CALENDARIO" in t:
                for y, v in re.findall(r"^\s*((?:19|20)\d\d)\s+(\d{1,2} \d{3} \d{3})\s", t, re.M):
                    out[int(y)] = num(v)
        return out


@register("pry_ine")
class PryIne(Adapter):
    def parse(self, raw):
        return wide_row(xlsx_rows(raw, "Poblac a mitad de año 1950-2050"), "Total País", 1950)


@register("slv_onec")
class SlvOnec(Adapter):
    def filename(self):
        return "El_Salvador_Poblacion_Nacional_2005-2050_rev2021.xlsx"

    def parse(self, raw):
        return wide_row(xlsx_rows(raw, "Población Total"), "Total", 2005)


@register("ury_ine")
class UryIne(Adapter):
    def parse(self, raw):
        return wide_row(xlsx_rows(raw), "Ambos sexos", self.entry["year_from"])


@register("ven_ine_2001")
class VenIne2001(Adapter):
    """El PDF es un escaneo: el crudo es el PDF y las cifras salen de la transcripción verificada."""
    transcription_root = Path(".")

    def parse(self, raw):
        path = self.transcription_root / self.entry["transcription"]
        with open(path, encoding="utf8") as f:
            rows = list(csv.DictReader(f))
        out = {}
        for r in rows:
            if int(r["total"]) != int(r["hombres"]) + int(r["mujeres"]):
                raise ParseError(f"Transcripción inconsistente en {r['year']}")
            out[int(r["year"])] = float(r["total"])
        return out


@register("ven_ine_2011")
class VenIne2011(Adapter):
    def parse(self, raw):
        return wide_row(xls_rows(raw), "Total", 2000)


@register("cepal")
class Cepal(Adapter):
    def filename(self):
        return f"cepalstat_indicador1_miembro{self.entry['cepal_member']}.json"

    def transform(self, content):
        """Quita header y footer: cambian en cada llamada (hora, IP) y no son dato."""
        doc = json.loads(content)
        return json.dumps(doc["body"], ensure_ascii=False, sort_keys=True, indent=0).encode("utf8")

    def parse(self, raw):
        body = json.loads(Path(raw).read_text(encoding="utf8"))
        years = {}
        for d in body["dimensions"]:
            if d["name"].startswith("Años"):
                years = {m["id"]: int(m["name"]) for m in d["members"]}
        if not years:
            raise ParseError("La API no trae la dimensión de años")
        return {years[r["dim_29117"]]: float(r["value"]) * 1000 for r in body["data"]}
