"""Orquesta el pipeline y escribe las salidas de contrato."""
from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

import yaml

from . import ISO3, SCHEMA_VERSION
from .adapters import REGISTRY, Record
from .adapters.sources import VenIne2001
from .derive import add_growth, find_breaks, peak
from .http import BlockedError, FetchError, Http
from .parsing import ParseError
from .store import RawStore
from .validate import alert, check_against_previous, check_entry, check_growth
from .watch import run_watch

NAMES = {
    "ARG": ("Argentina", "Argentina"), "BOL": ("Bolivia", "Bolivia"), "BRA": ("Brasil", "Brazil"),
    "CHL": ("Chile", "Chile"), "COL": ("Colombia", "Colombia"), "CRI": ("Costa Rica", "Costa Rica"),
    "CUB": ("Cuba", "Cuba"), "DOM": ("República Dominicana", "Dominican Republic"),
    "ECU": ("Ecuador", "Ecuador"), "GTM": ("Guatemala", "Guatemala"), "HND": ("Honduras", "Honduras"),
    "HTI": ("Haití", "Haiti"), "MEX": ("México", "Mexico"), "NIC": ("Nicaragua", "Nicaragua"),
    "PAN": ("Panamá", "Panama"), "PER": ("Perú", "Peru"), "PRY": ("Paraguay", "Paraguay"),
    "SLV": ("El Salvador", "El Salvador"), "URY": ("Uruguay", "Uruguay"), "VEN": ("Venezuela", "Venezuela"),
}
VOLATILE = ("generated_at", "last_success", "last_data_update")
CSV_FIELDS = ["iso3", "year", "population", "series_type", "source_id", "source_tier", "vintage", "scenario",
              "reference_date", "retrieved_at", "interpolated", "growth", "raw_file"]


def strip_volatile(x):
    if isinstance(x, dict):
        return {k: strip_volatile(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [strip_volatile(v) for v in x]
    return x


def write_stable(path: Path, doc) -> bool:
    """No reescribe si solo cambiarían marcas de tiempo: así no hay commit sin datos nuevos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if strip_volatile(json.loads(path.read_text(encoding="utf8"))) == strip_volatile(doc):
                return False
        except json.JSONDecodeError:
            pass
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    return True


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return default


def resolve_overlaps(records: list[Record]) -> tuple[list[Record], list[dict]]:
    """Si un año tiene dato nacional y regional, prevalece el nacional y queda registrado."""
    by: dict[int, list[Record]] = {}
    for r in records:
        by.setdefault(r.year, []).append(r)
    kept, dropped = [], []
    for y in sorted(by):
        rows = by[y]
        national = [r for r in rows if r.source_tier == "national"]
        if national and len(national) < len(rows):
            dropped += [dict(year=y, dropped_source=r.source_id, kept_source=national[0].source_id)
                        for r in rows if r.source_tier != "national"]
            kept += national
        else:
            kept += rows
    return kept, dropped


def run(root: Path = Path("."), http: Http | None = None, watch: bool = True, today: str | None = None) -> dict:
    root = Path(root)
    reg = yaml.safe_load((root / "sources.yaml").read_text(encoding="utf8"))
    sources = reg["sources"]
    store = RawStore(root / "data" / "raw")
    http = http or Http()
    VenIne2001.transcription_root = root
    now = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    processed = root / "data" / "processed"
    prev_manifest = read_json(processed / "manifest.json", {}).get("countries", {})
    prev_status = read_json(root / "data" / "status.json", {}).get("countries", {})
    changes = read_json(root / "data" / "source_changes.json", [])
    alerts, failures, all_rows, status, manifest = [], [], [], {}, {}

    for iso3 in ISO3:
        records: list[Record] = []
        series_status, segments, cur = {}, [], {}
        for kind in ("historical", "projection"):
            entry = sources[iso3][kind]
            prev_s = prev_status.get(iso3, {}).get("series", {}).get(kind, {})
            st = dict(status=entry["status"], source_tier=entry["source_tier"], institution=entry["institution"],
                      source_id=entry.get("source_id"), vintage=entry.get("vintage_label"),
                      url=entry["url"], last_success=prev_s.get("last_success"), retrieved_at=None, error=None,
                      reason=entry.get("public_reason"), note=entry.get("public_note"))
            series_status[kind] = st
            if not entry.get("adapter"):
                st["error"] = entry.get("pending_reason")
                continue
            adapter = REGISTRY[entry["adapter"]](iso3, kind, entry)
            raw, stale = None, None
            try:
                raw = adapter.fetch(store, http)
            except BlockedError as e:
                raw = store.latest(adapter.scope, entry["raw_key"])
                if raw is None:
                    st["status"] = "manual_pendiente" if adapter.manual else "error"
                    st["error"] = str(e)
                    if not adapter.manual:
                        failures.append(dict(iso3=iso3, series=kind, error=str(e)))
                    continue
                stale = None if adapter.manual else str(e)
            except FetchError as e:
                raw = store.latest(adapter.scope, entry["raw_key"])
                failures.append(dict(iso3=iso3, series=kind, error=str(e)))
                if raw is None:
                    st.update(status="error", error=str(e))
                    continue
                stale = str(e)
            try:
                rows = adapter.parse(raw.path)
                if not rows:
                    raise ParseError("El parser no devolvió filas")
                recs = adapter.normalize(rows, raw)
                for r in recs:
                    r.raw_file = Path(r.raw_file).resolve().relative_to(root.resolve()).as_posix()
            except Exception as e:  # noqa: BLE001  un país que falla no detiene a los demás
                failures.append(dict(iso3=iso3, series=kind, error=f"parse: {type(e).__name__}: {str(e)[:200]}"))
                st.update(status="error", error=f"{type(e).__name__}: {str(e)[:200]}")
                continue
            alerts += check_entry(iso3, kind, entry, rows, recs)
            records += recs
            st.update(status="stale" if stale else entry["status"], error=stale, retrieved_at=raw.retrieved_at,
                      raw_file=recs[0].raw_file if recs else None, raw_sha256=raw.sha256, retrieved_by=raw.retrieved_by)
            if not stale:
                st["last_success"] = now
            segs = {(r.source_id, r.vintage) for r in recs}
            for sid, label in sorted(segs):
                yrs = [r.year for r in recs if r.source_id == sid]
                segments.append(dict(source_id=sid, series=kind, source_tier=entry["source_tier"],
                                     institution=entry["institution"], source_url=entry["url"], vintage=label,
                                     reference_census=entry["vintage"].get("reference_census"),
                                     published=entry["vintage"].get("published"), scenario=entry.get("scenario_code"),
                                     reference_date=entry.get("reference_code"), year_from=min(yrs), year_to=max(yrs),
                                     access_method=entry["access_method"], raw_file=recs[0].raw_file,
                                     raw_sha256=raw.sha256, retrieved_at=raw.retrieved_at,
                                     retrieved_by=raw.retrieved_by, location_in_file=entry.get("location_in_file"),
                                     note=entry.get("public_note"), transcription=entry.get("transcription")))
            last = recs[-1] if recs else None
            cur[kind] = dict(source_id=last.source_id if last else None, vintage=last.vintage if last else None,
                             source_tier=entry["source_tier"], institution=entry["institution"],
                             url=entry["url"], raw_sha256=raw.sha256, retrieved_at=raw.retrieved_at)

        records, dropped = resolve_overlaps(records)
        for d in dropped:
            alerts.append(alert("national_replaces_regional", iso3,
                                f"{d['year']}: {d['kept_source']} sustituye a {d['dropped_source']}",
                                year=d["year"], to=d["kept_source"]))
        records.sort(key=lambda r: r.year)
        add_growth(records)
        alerts += check_growth(iso3, records)
        new_alerts = check_against_previous(iso3, prev_manifest.get(iso3), cur)
        alerts += new_alerts
        for a in new_alerts:
            if a["code"] in ("national_replaces_regional", "tier_change", "vintage_change"):
                changes.append(dict(date=now, iso3=iso3, code=a["code"], message=a["message"]))
        breaks = find_breaks(records)
        doc = dict(schema_version=SCHEMA_VERSION, iso3=iso3, name_es=NAMES[iso3][0], name_en=NAMES[iso3][1],
                   status={k: v["status"] for k, v in series_status.items()},
                   reasons={k: v["reason"] for k, v in series_status.items() if v["reason"]},
                   segments=segments, breaks=breaks, peak=peak(records),
                   records=[asdict(r) for r in records])
        write_stable(processed / f"{iso3}.json", doc)
        all_rows += records
        status[iso3] = dict(name_es=NAMES[iso3][0], name_en=NAMES[iso3][1], series=series_status)
        manifest[iso3] = cur

    with_csv = processed / "latam.csv"
    tmp = processed / ".latam.csv.tmp"
    with open(tmp, "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in all_rows:
            w.writerow(asdict(r))
    if with_csv.exists() and with_csv.read_bytes() == tmp.read_bytes():
        tmp.unlink()
    else:
        tmp.replace(with_csv)

    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    write_stable(processed / "manifest.json", dict(schema_version=SCHEMA_VERSION, generated_at=stamp, countries=manifest,
                                                  decisions=reg.get("decisions")))
    latest = max((s.get("last_success") or "" for c in status.values() for s in c["series"].values()), default=None)
    write_stable(root / "data" / "status.json", dict(schema_version=SCHEMA_VERSION, generated_at=stamp,
                                                     last_data_update=latest or None, countries=status))
    write_stable(root / "data" / "source_changes.json", changes)

    if watch:
        state_path = root / "data" / "watch_state.json"
        state, watch_alerts = run_watch(reg.get("watch", []), http, read_json(state_path, {}))
        alerts += watch_alerts
        write_stable(state_path, state)

    report = dict(failures=failures, alerts=alerts)
    write_stable(root / "data" / "alerts.json", report)
    (root / "build").mkdir(exist_ok=True)
    (root / "build" / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf8")
    return report
