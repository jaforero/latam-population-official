"""Validaciones: producen alertas, nunca correcciones."""
from __future__ import annotations

from collections import Counter

from .adapters.base import Record

MAX_ANNUAL_CHANGE = 0.04


def alert(code: str, iso3: str, message: str, **extra) -> dict:
    fp = ":".join(str(x) for x in (code, iso3, *[extra[k] for k in sorted(extra)]))
    return dict(code=code, iso3=iso3, message=message, fingerprint=fp, **extra)


def expected_years(entry: dict) -> list[int]:
    if entry.get("years_published"):
        return list(entry["years_published"])
    a, b = entry["year_from"], entry["year_to"]
    until, step = entry.get("annual_until"), entry.get("step_after", 5)
    if until is None:
        return list(range(a, b + 1))
    years = list(range(a, min(until, b) + 1))
    # Años quinquenales: primer múltiplo del paso tras el tramo anual.
    next_y = max(a, until + 1)
    next_y += (step - next_y % step) % step
    return years + list(range(next_y, b + 1, step))


def check_entry(iso3: str, kind: str, entry: dict, rows: dict[int, float], records: list[Record]) -> list[dict]:
    out = []
    dup = [y for y, n in Counter(r.year for r in records).items() if n > 1]
    for y in dup:
        out.append(alert("duplicate_year", iso3, f"Año duplicado {y} en {kind}", year=y, series=kind))
    have = {r.year for r in records}
    missing = [y for y in expected_years(entry) if y not in have]
    if missing:
        out.append(alert("gap", iso3, f"Faltan años en {kind}: {missing[:20]}", series=kind, years=",".join(map(str, missing))))
    c = entry.get("control")
    if c:
        factor = 1000 if "miles" in c.get("unit", "") else 1
        expected = float(c["value"]) * factor
        got = rows.get(c["year"])
        if got is None or abs(got - expected) > 0.5:
            out.append(alert("control_mismatch", iso3, f"Control {kind} {c['year']}: registro {expected}, archivo {got}",
                             series=kind, year=c["year"], expected=expected, got=got))
    return out


def check_growth(iso3: str, records: list[Record]) -> list[dict]:
    return [alert("annual_change", iso3, f"Variación anual de {r.growth:+.2%} en {r.year} ({r.source_id})",
                  year=r.year, source=r.source_id)
            for r in records if r.growth is not None and abs(r.growth) > MAX_ANNUAL_CHANGE]


def check_against_previous(iso3: str, prev: dict | None, cur: dict) -> list[dict]:
    """Compara con el manifiesto anterior: cambio de vintage o de nivel de fuente."""
    out = []
    if not prev:
        return out
    for kind, c in cur.items():
        p = prev.get(kind)
        if not p or not c.get("source_id"):
            continue
        if p.get("source_id") and p.get("vintage") != c.get("vintage"):
            out.append(alert("vintage_change", iso3, f"{kind}: vintage {p.get('vintage')} → {c.get('vintage')}",
                             series=kind, to=c.get("vintage")))
        if p.get("source_tier") and p.get("source_tier") != c.get("source_tier"):
            code = "national_replaces_regional" if c.get("source_tier") == "national" else "tier_change"
            out.append(alert(code, iso3, f"{kind}: nivel {p.get('source_tier')} → {c.get('source_tier')} ({c.get('source_id')})",
                             series=kind, to=c.get("source_id")))
    return out
