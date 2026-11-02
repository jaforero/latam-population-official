"""Índice de envejecimiento: personas de 65 años y más por cada 100 menores de 15, con las pirámides publicadas.

Solo existe en los años con pirámide y nada se interpola. Si cambia la fuente o la edición, queda una ruptura.
"""
from __future__ import annotations

from . import ISO3
from .pyramids import AGE_GROUPS, rounded

UNDER_15 = (AGE_GROUPS.index("0-4"), AGE_GROUPS.index("15-19"))
OVER_65 = (AGE_GROUPS.index("65-69"), len(AGE_GROUPS))
FORMULA = "100 * pop_65_plus / pop_0_14"
DEFINITION = dict(
    es="Personas de 65 años y más por cada 100 menores de 15. Cálculo propio con las pirámides publicadas de cada país.",
    en="People aged 65 and over per 100 people under 15. Our own calculation from each country's published pyramids.")
CSV_FIELDS = ["iso3", "year", "aging_index", "pop_0_14", "pop_65_plus", "series_type", "source_id", "source_tier", "vintage", "reference_date"]


def measure(pyramid_year: dict) -> dict:
    def people(lo: int, hi: int) -> float:
        return sum(pyramid_year["m"][lo:hi]) + sum(pyramid_year["f"][lo:hi])
    young, old = people(*UNDER_15), people(*OVER_65)
    return dict(aging_index=round(100 * old / young, 4), pop_0_14=rounded(young), pop_65_plus=rounded(old))


def _country(doc: dict) -> dict:
    rows, breaks = [], []
    for y, v in sorted(doc.get("years", {}).items(), key=lambda kv: int(kv[0])):
        row = dict(year=int(y), **measure(v), series_type=v["series_type"], source_id=v["source_id"], vintage=v["vintage"],
                   source_tier=v["source_tier"], reference_date=v["reference_date"])
        if rows and (rows[-1]["source_id"], rows[-1]["vintage"]) != (row["source_id"], row["vintage"]):
            breaks.append(dict(year=row["year"], from_vintage=rows[-1]["vintage"], to_vintage=row["vintage"]))
        rows.append(row)
    return dict(status=doc.get("status"), rows=rows, breaks=breaks)


def build_aging(pyramids: dict[str, dict], region_pyramid: dict) -> dict:
    region = [dict(year=int(y), **measure(v), n_countries=v["n_countries"], n_projection=v["n_projection"],
                   international_fallback=v["international_fallback"])
              for y, v in sorted(region_pyramid.get("years", {}).items(), key=lambda kv: int(kv[0]))]
    return dict(definition=DEFINITION, formula=FORMULA, countries={i: _country(pyramids.get(i, {})) for i in ISO3}, region=region)


def aging_csv_rows(aging: dict) -> list[dict]:
    rows = [dict(iso3=i, **{k: r[k] for k in CSV_FIELDS[1:]}) for i in ISO3 for r in aging["countries"][i]["rows"]]
    rows += [dict(iso3="REG", year=r["year"], aging_index=r["aging_index"], pop_0_14=r["pop_0_14"], pop_65_plus=r["pop_65_plus"],
                  series_type="derived", source_id="", source_tier="derived", vintage="", reference_date="") for r in aging["region"]]
    return rows
