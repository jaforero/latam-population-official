"""Interfaz común de los adaptadores: fetch → parse → normalize."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..http import BlockedError, FetchError, Http
from ..parsing import clean
from ..store import RawFile, RawStore

REGISTRY: dict[str, type["Adapter"]] = {}
MAGIC = {"XLSX": b"PK", "XLS": b"\xd0\xcf\x11\xe0", "PDF": b"%PDF"}


def register(name: str):
    def deco(cls):
        REGISTRY[name] = cls
        cls.name = name
        return cls
    return deco


@dataclass
class Record:
    iso3: str
    year: int
    population: int | float | None
    series_type: str  # observed | estimate | projection
    source_id: str
    source_tier: str  # national | regional_fallback
    vintage: str
    scenario: str | None
    reference_date: str | None
    retrieved_at: str
    interpolated: bool = False
    growth: float | None = None
    raw_file: str | None = None


class Adapter:
    name = "base"

    def __init__(self, iso3: str, kind: str, entry: dict):
        self.iso3, self.kind, self.entry = iso3, kind, entry

    @property
    def scope(self) -> str:
        """Carpeta de data/raw/: el país, o `raw_scope` si varios países comparten un archivo."""
        return self.entry.get("raw_scope", self.iso3)

    @property
    def manual(self) -> bool:
        return self.entry.get("status") == "manual"

    def filename(self) -> str:
        return unquote(urlparse(self.entry["url"]).path).rsplit("/", 1)[-1] or "file"

    def check_content(self, content: bytes) -> None:
        method = self.entry["access_method"].split()[0]
        magic = MAGIC.get(method)
        if magic and not content.startswith(magic):
            raise FetchError(f"Se esperaba {method} y llegó otro contenido (¿página de bloqueo?)")
        if method in ("CSV", "API") and content.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
            raise FetchError(f"Se esperaba {method} y llegó HTML")

    def transform(self, content: bytes) -> bytes:
        return content

    def fetch(self, store: RawStore, http: Http) -> RawFile:
        if self.manual:
            cur = store.latest(self.scope, self.entry["raw_key"])
            if cur is None:
                raise BlockedError("Fuente manual sin archivo en data/raw/")
            return cur
        content = http.get(self.entry["url"])
        self.check_content(content)
        return store.save(self.scope, self.entry["raw_key"], self.filename(), self.transform(content), self.entry["url"])

    def parse(self, raw_path: Path) -> dict[int, float]:
        raise NotImplementedError

    def segment_for(self, year: int) -> tuple[str, str]:
        for s in self.entry.get("segments", []):
            if s["year_from"] <= year <= s["year_to"]:
                return s["source_id"], s["label"]
        return self.entry["source_id"], self.entry["vintage_label"]

    def series_type_for(self, year: int) -> str:
        """Sigue el rótulo de la fuente: `observed_until` para censos y `estimate_until` para el corte a proyección."""
        e = self.entry
        if year <= e.get("observed_until", 0):
            return "observed"
        if "estimate_until" in e:
            return "estimate" if year <= e["estimate_until"] else "projection"
        return "estimate" if self.kind == "historical" else "projection"

    def normalize(self, rows: dict[int, float], raw: RawFile) -> list[Record]:
        e = self.entry
        out = []
        for y in sorted(rows):
            if not e["year_from"] <= y <= e["year_to"]:
                continue
            stype = self.series_type_for(y)
            sid, label = self.segment_for(y)
            out.append(Record(self.iso3, y, clean(rows[y]), stype, sid, e["source_tier"], label,
                              e.get("scenario_code"), e.get("reference_code"), raw.retrieved_at,
                              raw_file=raw.path.as_posix()))
        return out
