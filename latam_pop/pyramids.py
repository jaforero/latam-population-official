"""Pirámides de población: cada parser devuelve {año: {"m": [...], "f": [...]}} en 17 grupos comunes (0-4 … 80+).
Solo se suman grupos publicados por la fuente; nunca se desagrega ni se interpola."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pypdf

from .parsing import ParseError, num, xls_rows, xlsx_rows, xlsx_sheetnames, year_of
from .validate import alert

AGE_GROUPS = [f"{a}-{a + 4}" for a in range(0, 80, 5)] + ["80+"]
PARSERS = {}


def parser(name):
    def deco(fn):
        PARSERS[name] = fn
        return fn
    return deco


def parse_age(x) -> tuple[int, int | None] | None:
    """(desde, hasta) de un rótulo de edad; hasta=None en el grupo abierto. None si no es una edad."""
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return (int(x), int(x)) if float(x).is_integer() and 0 <= x <= 120 else None
    s = str(x).strip().lower()
    m = re.fullmatch(r"(\d{1,3})(?:\.0)?(?:\s*años?)?", s)
    if m:
        return int(m.group(1)), int(m.group(1))
    m = re.fullmatch(r"(\d{1,3})\s*(?:-|–|a)\s*(\d{1,3})(?:\s*años)?", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"(\d{1,3})\s*(?:\+|y \+|años y más|año y más|y más|o más|y mas|o mas)", s)
    if m:
        return int(m.group(1)), None
    return None


def harmonize(cells: dict[tuple[int, int | None], float]) -> list[float]:
    """Suma a 17 grupos. Si la fuente trae grupos quinquenales y edades simples, usa los grupos para no contar doble."""
    five = {k: v for k, v in cells.items() if k[1] is None or k[1] - k[0] == 4}
    groups = five if any(k[1] is not None for k in five) else {k: v for k, v in cells.items() if k[1] is None or k[1] == k[0]}
    out = [0.0] * len(AGE_GROUPS)
    seen = set()
    for (lo, _hi), v in groups.items():
        i = min(lo // 5, 16)
        out[i] += v
        seen.add(i)
    if len(seen) != len(AGE_GROUPS):
        raise ParseError(f"Faltan grupos de edad: {sorted(set(range(17)) - seen)}")
    return out


def finish(raw: dict[int, dict[str, dict]]) -> dict[int, dict[str, list[float]]]:
    return {y: {s: harmonize(c) for s, c in v.items()} for y, v in raw.items() if set(v) == {"m", "f"}}


def sex_of(label) -> str | None:
    s = str(label).strip().lower()
    if re.match(r"(hombres?|varones|masculina|male)\b", s):
        return "m"
    if re.match(r"(mujeres?|femenina|female)\b", s):
        return "f"
    return None


def year_columns(r) -> dict[int, int]:
    """Columnas de una fila de años a intervalo fijo. Una fila de datos con cifras como 2.045 no debe pasar por encabezado."""
    cols = {j: year_of(c) for j, c in enumerate(r) if year_of(c)}
    ys = list(cols.values())
    steps = {b - a for a, b in zip(ys, ys[1:])}
    if len(steps) == 1 and (steps == {1} and len(ys) >= 3 or steps == {5} and len(ys) >= 5):
        return cols
    return {}


def add(store, year, sex, age, value):
    store.setdefault(year, {}).setdefault(sex, {})[age] = value


def blocks(rows, store, fixed_sex=None):
    """Tablas anchas con bloques por sexo: una fila de años y filas 'edad, valor, valor…'."""
    cols, sex = {}, fixed_sex
    for r in rows:
        years = year_columns(r)
        if years:
            cols = years
            continue
        cells = [c for c in r if c not in (None, "")]
        if not cells or not cols:
            continue
        label = cells[0]
        if fixed_sex is None:
            if str(label).strip().lower().startswith(("ambos", "total país", "total pais")):
                sex = None
                continue
            s = sex_of(label)
            if s:
                sex = s
                continue
        age = parse_age(label)
        if not age or not sex:
            continue
        for j, y in cols.items():
            v = num(r[j]) if j < len(r) else None
            if v is not None:
                add(store, y, sex, age, v)


def sheet_blocks(path, sheets=None) -> dict:
    store: dict = {}
    for s in sheets or xlsx_sheetnames(path):
        blocks(xlsx_rows(path, s), store)
    return finish(store)


@parser("chl")
def chl(paths):
    return sheet_blocks(paths["chl_ine"], ["Población al 30 de junio"])


@parser("gtm")
def gtm(paths):
    return sheet_blocks(paths["gtm_ine"], ["Población total"])


@parser("pan")
def pan(paths):
    return sheet_blocks(paths["pan_inec"])


@parser("pry")
def pry(paths):
    return sheet_blocks(paths["pry_ine"], ["Poblac a mitad de año 1950-2050"])


@parser("ury")
def ury(paths):
    store: dict = {}
    blocks(xlsx_rows(paths["ury_ine_hist"]), store)
    blocks(xlsx_rows(paths["ury_ine_proj"]), store)
    return finish(store)


@parser("slv")
def slv(paths):
    store: dict = {}
    blocks(xlsx_rows(paths["slv_onec"], "Masculina"), store, "m")
    blocks(xlsx_rows(paths["slv_onec"], "Femenina"), store, "f")
    return finish(store)


@parser("cri")
def cri(paths):
    """Bloques por década: la fila 'Grupos de edades' marca dónde empiezan Total, Hombres y Mujeres; la siguiente trae los años."""
    store: dict = {}
    sections: list[tuple[int, str]] = []
    cols: dict[int, tuple[int, str]] = {}
    awaiting_years = False
    for r in xlsx_rows(paths["cri_inec"], "C2. Edades quinquenales"):
        if r and str(r[0]).strip().lower().startswith("grupos"):
            sections = [(j, c) for j, c in enumerate(r) if j and isinstance(c, str) and c.strip()]
            awaiting_years = True
            continue
        if awaiting_years:
            cols = {}
            for j, c in enumerate(r):
                owner = [name for pos, name in sections if pos <= j]
                if year_of(c) and owner and sex_of(owner[-1]):
                    cols[j] = (year_of(c), sex_of(owner[-1]))
            awaiting_years = False
            continue
        age = parse_age(r[0]) if r and r[0] is not None else None
        if age:
            for j, (y, sex) in cols.items():
                v = num(r[j]) if j < len(r) else None
                if v is not None:
                    add(store, y, sex, age, v)
    return finish(store)


@parser("ecu")
def ecu(paths):
    """Cada año ocupa tres columnas: Hombre, Mujer, Total."""
    store: dict = {}
    cols = {}
    for r in xlsx_rows(paths["ecu_inec"], "1.2"):
        years = year_columns(r)
        if years:
            cols = years
            continue
        age = parse_age(r[1]) if len(r) > 1 and r[1] is not None else None
        if age and cols:
            for j, y in cols.items():
                add(store, y, "m", age, float(r[j]))
                add(store, y, "f", age, float(r[j + 1]))
    return finish(store)


@parser("bra")
def bra(paths):
    store: dict = {}
    h = None
    for r in xlsx_rows(paths["bra_ibge_tab2"]):
        if h is None:
            if "LOCAL" in r:
                h = r
            continue
        if r[h.index("LOCAL")] == "Brasil":
            sex = {"homens": "m", "mulheres": "f"}.get(str(r[h.index("SEXO")]).strip().lower())
            age = parse_age(r[0])
            if sex and age:
                for j, c in enumerate(h):
                    if year_of(c) and num(r[j]) is not None:
                        add(store, year_of(c), sex, age, num(r[j]))
    return finish(store)


def _col_rows(path, store):
    sheet = [s for s in xlsx_sheetnames(path) if s.lower().startswith(("pobnacional", "nacional"))][0]
    h = None
    for r in xlsx_rows(path, sheet):
        if h is None:
            if sum(1 for c in r if isinstance(c, str) and re.match(r"Hombres[ _]\d", c)) > 10:
                h = {j: (("m" if c.startswith("H") else "f"), int(re.search(r"\d+", c).group()), "más" in c.lower() or "+" in c)
                     for j, c in enumerate(r) if isinstance(c, str) and re.match(r"(Hombres|Mujeres)[ _]\d", c)}
            continue
        y = next((year_of(c) for c in r if year_of(c)), None)
        if y and "Total" in r:
            for j, (sex, age, opened) in h.items():
                if num(r[j]) is not None:
                    add(store, y, sex, (age, None if opened else age), num(r[j]))


@parser("col")
def col(paths):
    store: dict = {}
    _col_rows(paths["col_dane_edad_hist"], store)
    _col_rows(paths["col_dane_edad_proj"], store)
    return finish(store)


@parser("arg")
def arg(paths):
    text = Path(paths["arg_indec_2022_edades"]).read_bytes().decode("latin1")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    next(reader)
    national: dict = {}
    states: dict = {}
    for row in reader:
        if len(row) < 5:
            continue
        jur, sex, age, pop, year = [c.strip() for c in row[:5]]
        target = national if jur == "1" else states
        # Metadatos de INDEC: 1 = Mujer, 2 = Varón.
        k = (int(year), {"1": "f", "2": "m"}[sex], int(age))
        # INDEC usa "-" para el cero en jurisdicciones pequeñas.
        target[k] = target.get(k, 0.0) + (0.0 if pop == "-" else float(pop))
    data = national or states
    top = max(k[2] for k in data)
    store: dict = {}
    for (y, s, a), v in data.items():
        add(store, y, s, (a, None if a == top else a + 4), v)
    return finish(store)


@parser("mex")
def mex(paths):
    text = Path(paths["mex_conapo_mitad"]).read_bytes().decode("utf-8-sig")
    national: dict = {}
    states: dict = {}
    for r in csv.DictReader(io.StringIO(text)):
        k = (int(r["ANIO"]), {"hombres": "m", "mujeres": "f"}[r["SEXO"].strip().lower()], int(r["EDAD"]))
        target = national if r["CVE_GEO"].strip() == "0" else states
        target[k] = target.get(k, 0.0) + float(r["POBLACION"])
    store: dict = {}
    for (y, s, a), v in {**states, **national}.items():
        add(store, y, s, (a, a), v)
    return finish(store)


@parser("hnd")
def hnd(paths):
    labels = [f"{a}-{a + 4}" for a in range(0, 95, 5)] + ["95+"]
    store: dict = {}
    for p in pypdf.PdfReader(paths["hnd_ine"]).pages:
        t = p.extract_text() or ""
        if "por sexo, según grupos de edad" not in t:
            continue
        m = re.search(r"(20[1-5]\d)\|", t)
        if not m:
            continue
        y = int(m.group(1))
        if y in store:
            continue
        rows = re.findall(r"^(\d{1,2}-\d{1,2}|\d{2}\+) +([\d,]+) +([\d,]+) +([\d,]+) ", t, re.M)
        if rows:
            pairs = {r[0]: (num(r[2]), num(r[3])) for r in rows}
        else:
            nums = re.findall(r"^([\d,]{5,}) +([\d,]+) +([\d,]+) +[\d.]+ +[\d.]+ +[\d.]+ +[\d.]+", t, re.M)
            pairs = {lab: (num(n[1]), num(n[2])) for lab, n in zip(labels, nums[1:])}
        for lab, (h, f) in pairs.items():
            add(store, y, "m", parse_age(lab), h)
            add(store, y, "f", parse_age(lab), f)
    return finish(store)


@parser("nic")
def nic(paths):
    store: dict = {}
    for p in pypdf.PdfReader(paths["nic_inide"]).pages:
        t = p.extract_text() or ""
        m = re.search(r"SEGÚN DEPARTAMENTO Y GRUPOS\s+DE EDADES QUINQUENALES, (20\d\d)", t)
        if not m or "La República" not in t:
            continue
        y = int(m.group(1))
        body = t[t.index("La República"):].splitlines()[1:]
        for line in body:
            r = re.match(r"\s*(\d{2}\s*-\s*\d{2}|\d{2}\s*y\s*\+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", line)
            if r:
                age = parse_age(r.group(1))
                add(store, y, "m", age, num(r.group(3)))
                add(store, y, "f", age, num(r.group(4)))
            elif re.match(r"\s*[A-ZÁÉÍÓÚ]", line):
                break
    return finish(store)


@parser("per")
def per(paths):
    """Cuadro 2 del Boletín 24. El modo de maquetación conserva las columnas: los miles van con un espacio, las columnas con varios."""
    store: dict = {}
    for p in pypdf.PdfReader(paths["per_inei"]).pages:
        plain = p.extract_text() or ""
        ym = re.search(r"edad((?: (?:19|20)\d\d)+)", plain)
        if not re.search(r"CUADRO N. ?2\b", plain) or "SEGÚN SEXO Y GRUPO" not in plain or not ym:
            continue
        years = [int(y) for y in ym.group(1).split()]
        sex = None
        for line in p.extract_text(extraction_mode="layout").splitlines():
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) != len(years) + 1:
                continue
            label = parts[0]
            s = sex_of(label)
            if s or label == "Total":
                sex = s
                continue
            age = parse_age(re.sub(r"\s*-\s*", "-", label))
            if age and sex:
                for y, v in zip(years, parts[1:]):
                    add(store, y, sex, age, float(v.replace(" ", "")))
    return finish(store)


@parser("ven")
def ven(paths):
    store: dict = {}
    blocks(xls_rows(paths["ven_ine_nacional"]), store)
    return finish(store)


@parser("dom")
def dom(paths):
    """Rótulos como '  5  y 9' o '10 y14': la 'y' separa los extremos del grupo."""
    store: dict = {}
    reader = csv.reader(io.StringIO(Path(paths["dom_one"]).read_bytes().decode("latin1")), delimiter=";")
    next(reader)
    for r in reader:
        sex = sex_of(r[1]) if len(r) >= 4 else None
        if sex:
            add(store, int(r[3]), sex, parse_age(re.sub(r"\s*y\s*(?=\d)", "-", r[0].strip())), float(r[2]))
    return finish(store)


MAX_TOTAL_GAP = 0.0005  # Una pirámide que se aparte más del total oficial de ese año no se publica.


def rounded(v: float) -> int | float:
    return int(v) if float(v).is_integer() else round(float(v), 3)


def build_pyramid(iso3, cfg, by_year, store, http, content_check) -> tuple[dict, list[dict], list[dict]]:
    """Devuelve el documento del país, sus alertas y sus fallas. Una falla aquí no afecta la serie principal."""
    alerts, failures = [], []
    doc = dict(status=cfg["status"], parser=cfg.get("parser"), institution=cfg.get("institution"), source_url=cfg.get("url"),
               location_in_file=cfg.get("location_in_file"), reason=cfg.get("reason"), note=cfg.get("note"),
               age_groups=AGE_GROUPS, raw_files=[], years={})
    if not cfg.get("parser"):
        return doc, alerts, failures
    paths = {}
    for f in cfg["files"]:
        key, scope = f["raw_key"], f.get("scope", iso3)
        raw = None
        if f.get("url") and http is not None:
            try:
                content = http.get(f["url"])
                content_check(content, f["url"])
                raw = store.save(scope, key, f.get("filename") or f["url"].rsplit("/", 1)[-1], content, f["url"])
            except Exception as e:  # noqa: BLE001  se conserva el último crudo válido
                failures.append(dict(iso3=iso3, series="pyramid", error=f"{type(e).__name__}: {str(e)[:180]}"))
                doc["status"] = "stale"
        raw = raw or store.latest(scope, key)
        if raw is None:
            doc["status"] = "manual_pendiente" if cfg["status"] == "manual" else "error"
            return doc, alerts, failures
        paths[key] = raw.path
        doc["raw_files"].append(dict(path=raw.path.as_posix(), sha256=raw.sha256, retrieved_at=raw.retrieved_at, retrieved_by=raw.retrieved_by))
    try:
        data = PARSERS[cfg["parser"]](paths)
    except Exception as e:  # noqa: BLE001  un país que falla no detiene a los demás
        failures.append(dict(iso3=iso3, series="pyramid", error=f"parse: {type(e).__name__}: {str(e)[:180]}"))
        doc["status"] = "error"
        return doc, alerts, failures
    mismatched, odd_sex = [], []
    for y in sorted(data):
        rec = by_year.get(y)
        if rec is None or rec.population is None:
            continue
        m, f = data[y]["m"], data[y]["f"]
        if abs(sum(m) + sum(f) - rec.population) > max(1.0, MAX_TOTAL_GAP * rec.population):
            mismatched.append(y)
            continue
        if m[0] < f[0] or m[16] > f[16]:
            odd_sex.append(y)
        doc["years"][str(y)] = dict(m=[rounded(v) for v in m], f=[rounded(v) for v in f], series_type=rec.series_type,
                                    source_id=rec.source_id, vintage=rec.vintage, source_tier=rec.source_tier,
                                    reference_date=rec.reference_date)
    if mismatched:
        alerts.append(alert("pyramid_total_mismatch", iso3, f"Pirámide no publicada en {len(mismatched)} años: no cuadra con el total oficial ({mismatched[:8]})",
                            years=",".join(map(str, mismatched))))
    if odd_sex:
        alerts.append(alert("pyramid_sex_ratio", iso3, f"Revisar sexos: 0-4 con más mujeres o 80+ con más hombres en {len(odd_sex)} años ({odd_sex[:8]})",
                            years=",".join(map(str, odd_sex))))
    return doc, alerts, failures
