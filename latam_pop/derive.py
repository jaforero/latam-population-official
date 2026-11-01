"""Derivados: crecimiento anual y CAGR, siempre dentro de una misma serie."""
from __future__ import annotations

from .adapters.base import Record


def add_growth(records: list[Record]) -> None:
    """(P_t / P_{t-1}) − 1, solo si t-1 existe y es de la misma fuente y vintage."""
    prev: dict[tuple[str, str], Record] = {}
    for r in sorted(records, key=lambda x: x.year):
        key = (r.source_id, r.vintage)
        p = prev.get(key)
        r.growth = None
        if p and p.year == r.year - 1 and p.population and r.population is not None:
            r.growth = r.population / p.population - 1
        prev[key] = r


def cagr(records: list[Record], y0: int, y1: int) -> float | None:
    """Tasa compuesta entre dos años. None si cruzan una ruptura o falta alguno."""
    by = {r.year: r for r in records}
    a, b = by.get(y0), by.get(y1)
    if not a or not b or y1 <= y0 or not a.population or b.population is None:
        return None
    if (a.source_id, a.vintage) != (b.source_id, b.vintage):
        return None
    return (b.population / a.population) ** (1 / (y1 - y0)) - 1


def find_breaks(records: list[Record]) -> list[dict]:
    """Toda unión entre fuentes o vintages se registra; nunca se encadena ni se ajusta."""
    out = []
    ordered = sorted(records, key=lambda x: x.year)
    for a, b in zip(ordered, ordered[1:]):
        if (a.source_id, a.vintage) != (b.source_id, b.vintage):
            out.append(dict(year=b.year, from_source=a.source_id, to_source=b.source_id,
                            from_vintage=a.vintage, to_vintage=b.vintage,
                            from_tier=a.source_tier, to_tier=b.source_tier,
                            last_value=a.population, first_value=b.population))
    return out


def peak(records: list[Record]) -> dict:
    """Máximo según la serie que contiene la proyección más reciente; no mezcla vintages."""
    proj = [r for r in records if r.series_type == "projection"]
    if not proj:
        return dict(status="no_projection", year=None, population=None, source_id=None, horizon_end=None)
    last = max(proj, key=lambda r: r.year)
    same = [r for r in records if (r.source_id, r.vintage) == (last.source_id, last.vintage) and r.population is not None]
    top = max(same, key=lambda r: r.population)
    status = "no_peak_in_horizon" if top.year == last.year else "peak"
    return dict(status=status, year=None if status != "peak" else top.year,
                population=None if status != "peak" else top.population,
                source_id=last.source_id, horizon_end=last.year)
