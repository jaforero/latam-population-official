"""Agregado regional: suma de cifras oficiales. No es una cifra oficial y nunca completa un hueco.

- Solo hay total en los años con dato de los 20 países: un total parcial saltaría al entrar o salir un país.
- Crecimiento e índice comparan a cada país consigo mismo. Quien cruza una ruptura entre los dos años sale
  de ese cálculo y queda listado, igual que en su propia serie. Nada se encadena ni se ajusta.
- Una pirámide regional exige las 20 pirámides publicadas ese año y cuadrar con el total regional.
"""
from __future__ import annotations

from collections import Counter

from . import ISO3

NAME_ES, NAME_EN = "Región (20 países)", "Region (20 countries)"
NOTE = dict(
    es="Base derivada: suma propia de cifras con condiciones de uso distintas, incluidas CC BY-SA y ODbL; cada cifra conserva las de su fuente "
       "(campo license de cada componente). Depende de CEPAL/CELADE para los países listados en regional_fallback: sin ellos no habría total de los 20.",
    en="Derived database: our own sum of figures under different terms of use, including CC BY-SA and ODbL; each figure keeps those of its source "
       "(license field of each component). It relies on ECLAC/CELADE for the countries listed in regional_fallback: without them there would be no total of the 20.")
MAX_PYRAMID_GAP = 0.0005


def _key(r: dict) -> tuple[str, str]:
    return r["source_id"], r["vintage"]


def _compare(by: dict, a: int, b: int) -> dict:
    """Razón b/a solo con los países que tienen la misma serie en ambos años."""
    same = [i for i in ISO3 if _key(by[i][a]) == _key(by[i][b])]
    base = sum(by[i][a]["population"] for i in same)
    return dict(same=same, base=base, value=sum(by[i][b]["population"] for i in same),
                total_base=sum(by[i][a]["population"] for i in ISO3),
                excluded=[dict(iso3=i, from_vintage=by[i][a]["vintage"], to_vintage=by[i][b]["vintage"])
                          for i in ISO3 if i not in same])


def _point(by: dict, y: int, licenses: dict) -> dict:
    rows = {i: by[i][y] for i in ISO3}
    total = sum(r["population"] for r in rows.values())
    proj = [i for i, r in rows.items() if r["series_type"] == "projection"]
    return dict(year=y, population=round(total), n_countries=len(rows), n_projection=len(proj),
                projection_share=round(sum(rows[i]["population"] for i in proj) / total, 6),
                regional_fallback=[i for i, r in rows.items() if r["source_tier"] == "regional_fallback"],
                reference_dates=dict(sorted(Counter(r["reference_date"] or "no_declarada" for r in rows.values()).items())),
                shares={i: round(r["population"] / total, 6) for i, r in rows.items()},
                components=[dict(iso3=i, population=r["population"], series_type=r["series_type"], source_id=r["source_id"],
                                 source_tier=r["source_tier"], vintage=r["vintage"], reference_date=r["reference_date"],
                                 raw_file=r["raw_file"], license=licenses.get(r["source_id"])) for i, r in rows.items()])


def _periods(by: dict, years: list[int]) -> list[dict]:
    out = []
    for a, b in zip(years, years[1:]):
        c = _compare(by, a, b)
        rates = {i: (round((by[i][b]["population"] / by[i][a]["population"]) ** (1 / (b - a)) - 1, 8) if i in c["same"] else None)
                 for i in ISO3}
        out.append(dict(from_year=a, to_year=b, rate=round((c["value"] / c["base"]) ** (1 / (b - a)) - 1, 8),
                        n_countries=len(c["same"]), covers_share=round(c["base"] / c["total_base"], 6),
                        excluded=c["excluded"], country_rates=rates))
    return out


def _index(by: dict, years: list[int]) -> dict:
    out = {}
    for base in years:
        rows = []
        for y in years:
            c = _compare(by, base, y)
            rows.append(dict(year=y, index=round(c["value"] / c["base"] * 100, 4), n_countries=len(c["same"]),
                             covers_share=round(c["base"] / c["total_base"], 6), excluded=[e["iso3"] for e in c["excluded"]]))
        out[str(base)] = rows
    return out


def _pyramid(pyramids: dict, totals: dict[int, int]) -> tuple[dict, list[dict]]:
    """Suma grupo por grupo; un año sin alguna pirámide o que no cuadra con el total no se publica."""
    have = {i: {int(y): v for y, v in (pyramids.get(i) or {}).get("years", {}).items()} for i in ISO3}
    all_years = sorted({y for v in have.values() for y in v})
    ages = next((pyramids[i]["age_groups"] for i in ISO3 if have[i]), [])
    years, missing, issues = {}, {}, []
    for y in all_years:
        absent = [i for i in ISO3 if y not in have[i]]
        if absent:
            missing[str(y)] = absent
            continue
        rows = [have[i][y] for i in ISO3]
        m = [round(sum(r["m"][k] for r in rows)) for k in range(len(ages))]
        f = [round(sum(r["f"][k] for r in rows)) for k in range(len(ages))]
        total = totals.get(y)
        if total is None or abs(sum(m) + sum(f) - total) > MAX_PYRAMID_GAP * total:
            issues.append(dict(year=y, pyramid_total=sum(m) + sum(f), region_total=total))
            continue
        years[str(y)] = dict(m=m, f=f, n_countries=len(rows), n_projection=sum(r["series_type"] == "projection" for r in rows),
                             regional_fallback=[i for i in ISO3 if have[i][y]["source_tier"] == "regional_fallback"])
    return dict(age_groups=ages, years=years, missing_by_year=missing), issues


def build_region(countries: dict[str, list[dict]], pyramids: dict[str, dict], licenses: dict | None = None) -> tuple[dict, list[dict]]:
    """Devuelve el documento regional y los años de pirámide descartados por no cuadrar."""
    by = {i: {r["year"]: r for r in countries.get(i, []) if r.get("population") is not None} for i in ISO3}
    years = sorted(set.intersection(*(set(v) for v in by.values()))) if all(by.values()) else []
    points = [_point(by, y, licenses or {}) for y in years]
    pyramid, issues = _pyramid(pyramids, {p["year"]: p["population"] for p in points})
    return dict(id="REG", name_es=NAME_ES, name_en=NAME_EN, official=False, derived=True, note=NOTE, countries=ISO3, years=years, points=points,
                periods=_periods(by, years), index=_index(by, years), pyramid=pyramid), issues


def region_csv_rows(region: dict) -> list[dict]:
    """Una fila por año, con el crecimiento hacia el año siguiente; los componentes están en latam.csv."""
    nxt = {p["from_year"]: p for p in region["periods"]}
    rows = []
    for p in region["points"]:
        g = nxt.get(p["year"])
        rows.append(dict(year=p["year"], population=p["population"], n_countries=p["n_countries"], n_projection=p["n_projection"],
                         regional_fallback=" ".join(p["regional_fallback"]), annual_rate_to_next=g["rate"] if g else "",
                         next_year=g["to_year"] if g else "", countries_in_rate=g["n_countries"] if g else "",
                         excluded_from_rate=" ".join(e["iso3"] for e in g["excluded"]) if g else ""))
    return rows
