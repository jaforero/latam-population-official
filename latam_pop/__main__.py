"""Uso: python -m latam_pop run | python -m latam_pop ingest ISO3 serie ARCHIVO"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .build import run
from .store import RawStore


def main() -> int:
    ap = argparse.ArgumentParser(prog="latam_pop")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Ejecuta el pipeline")
    r.add_argument("--no-watch", action="store_true")
    i = sub.add_parser("ingest", help="Registra un archivo descargado a mano")
    i.add_argument("iso3")
    i.add_argument("series", choices=["historical", "projection"])
    i.add_argument("file", type=Path)
    i.add_argument("--raw-key", help="Entrada de earlier_sources a la que pertenece el archivo")
    a = ap.parse_args()
    if a.cmd == "ingest":
        e = yaml.safe_load(Path("sources.yaml").read_text(encoding="utf8"))["sources"][a.iso3][a.series]
        if a.raw_key:
            e = next(x for x in e.get("earlier_sources", []) if x["raw_key"] == a.raw_key)
        saved = RawStore(Path("data/raw")).save(e.get("raw_scope", a.iso3), e["raw_key"], a.file.name, a.file.read_bytes(), e["url"], "manual")
        print(f"{saved.path} sha256={saved.sha256}")
        return 0
    rep = run(Path("."), watch=not a.no_watch)
    print(f"Fallas: {len(rep['failures'])} · Alertas: {len(rep['alerts'])}")
    for f in rep["failures"]:
        print(" FALLA", f["iso3"], f["series"], f["error"])
    for x in rep["alerts"]:
        print(" ALERTA", x["iso3"], x["code"], x["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
