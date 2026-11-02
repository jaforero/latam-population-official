"""Construye dist/kaggle/ desde los productos procesados del repositorio, que siguen siendo la única fuente de verdad.

    python scripts/build_kaggle_dataset.py

Solo lee archivos canónicos (data/processed/, data/status.json, data/alerts.json) y la configuración versionada de
kaggle/. No toca data/raw/, no corrige cifras, no interpola ni encadena. Valida el resultado contra los productos de
origen y evalúa la puerta de licencias; el informe de la puerta queda en dist/ (fuera de lo que se sube a Kaggle).
Sale con código 1 si cambia el esquema o falla una validación.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from latam_pop import ISO3, SCHEMA_VERSION  # noqa: E402
from latam_pop.aging import measure  # noqa: E402
from latam_pop.pyramids import AGE_GROUPS  # noqa: E402
from latam_pop.region import MAX_PYRAMID_GAP  # noqa: E402

REPO_URL = "https://github.com/jaforero/latam-population-official"
DASHBOARD_URL = "https://dashboards.javierforero.co/poblacion-latam/"
REGION_NAME = "Region (20 countries)"
SEX = {"m": "male", "f": "female"}
CSV_FILES = ["population_latam.csv", "population_region.csv", "aging_index.csv", "population_pyramids.csv",
             "sources.csv", "source_breaks.csv", "quality_alerts.csv"]
DOC_FILES = ["README.md", "DATA_DICTIONARY.md", "SOURCES_AND_LICENSES.md", "manifest.json", "SOURCE_COMMIT.txt",
             "dataset-metadata.json"]
KAGGLE_LICENSES = {"CC0-1.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "CC-BY-NC-SA-4.0", "GPL-2.0", "ODbL-1.0", "DbCL-1.0",
                   "copyright-authors", "other", "unknown", "CC-BY-4.0", "CC-BY-NC-4.0", "PDDL", "CC-BY-3.0",
                   "CC-BY-3.0-IGO", "US-Government-Works", "CC-BY-NC-SA-3.0-IGO", "CDLA-Permissive-1.0",
                   "CDLA-Sharing-1.0", "CC-BY-ND-4.0", "CC-BY-NC-ND-4.0", "ODC-BY-1.0", "LGPL-3.0", "AGPL-3.0",
                   "FDL-1.3", "EU-ODP-Legal-Notice", "apache-2.0", "GPL-3.0"}
UPDATE_FREQUENCIES = {"not specified", "never", "annually", "quarterly", "monthly", "weekly", "daily", "hourly"}
# Límites de dataset-metadata.json (docs/datasets_metadata.md del Kaggle CLI).
LIMITS = dict(title=(6, 50), subtitle=(20, 80), slug=(3, 50))


class ExportError(Exception):
    pass


# ---------- lectura ----------

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf8"))


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf8", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def fmt(x) -> str:
    """Valor JSON → texto CSV sin cambiar el valor: 328587.0 se escribe 328587; los booleanos como en latam.csv."""
    if x is None:
        return ""
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def load(root: Path) -> dict:
    p = root / "data" / "processed"
    spec = yaml.safe_load((root / "kaggle" / "columns.yaml").read_text(encoding="utf8"))
    src = dict(
        spec=spec,
        policy=yaml.safe_load((root / "kaggle" / "license_policy.yaml").read_text(encoding="utf8")),
        manifest=read_json(p / "manifest.json"),
        licenses=read_json(p / "licenses.json"),
        status=read_json(root / "data" / "status.json"),
        alerts=read_json(root / "data" / "alerts.json"),
        region=read_json(p / "region.json"),
        aging=read_json(p / "aging.json"),
        countries={i: read_json(p / f"{i}.json") for i in ISO3},
        pyramids={i: read_json(p / "pyramids" / f"{i}.json") for i in ISO3},
    )
    for rel in spec["canonical_headers"]:
        header, rows = read_csv(root / rel)
        src[Path(rel).stem + "_csv"] = rows
        src[Path(rel).stem + "_header"] = header
    return src


def check_schema(src: dict) -> None:
    """Falla si el contrato cambió: otra versión de esquema u otras columnas en los productos canónicos."""
    spec = src["spec"]
    want = spec["expected_schema_version"]
    found = {"latam_pop.SCHEMA_VERSION": SCHEMA_VERSION}
    for k in ("manifest", "licenses", "status", "region", "aging"):
        found[k] = src[k].get("schema_version")
    for i in ISO3:
        found[f"{i}.json"] = src["countries"][i].get("schema_version")
        found[f"pyramids/{i}.json"] = src["pyramids"][i].get("schema_version")
    bad = {k: v for k, v in found.items() if v != want}
    if bad:
        raise ExportError(f"schema_version esperado {want}, encontrado {bad}. Revisa el cambio de contrato en README.md "
                          "y actualiza kaggle/columns.yaml (expected_schema_version y columnas) a propósito.")
    for rel, cols in spec["canonical_headers"].items():
        got = src[Path(rel).stem + "_header"]
        if got != cols:
            raise ExportError(f"{rel}: columnas {got} no coinciden con las esperadas {cols}. "
                              "El exportador no adivina significados: actualiza kaggle/columns.yaml.")
    if list(src["pyramids"][ISO3[0]]["age_groups"]) != AGE_GROUPS:
        raise ExportError("Los grupos de edad de las pirámides cambiaron respecto a latam_pop.pyramids.AGE_GROUPS.")
    if sorted(src["manifest"]["countries"]) != sorted(ISO3):
        raise ExportError(f"manifest.json no cubre exactamente los países del proyecto: {sorted(src['manifest']['countries'])}")


# ---------- tablas ----------

def build_tables(src: dict) -> dict[str, list[dict]]:
    lic = src["licenses"]["licenses"]
    names = {i: src["countries"][i]["name_en"] for i in ISO3}
    institution = {(i, s["source_id"]): s["institution"] for i in ISO3 for s in src["countries"][i]["segments"]}
    breaks = {(i, b["year"]) for i in ISO3 for b in src["countries"][i]["breaks"]}

    latam = []
    for r in src["latam_csv"]:
        i = r["iso3"]
        latam.append(dict(r, country=names[i], institution=institution[(i, r["source_id"])],
                          license_status=lic.get(r["license"], {}).get("status", ""),
                          source_break=str((i, int(r["year"])) in breaks)))

    points = {p["year"]: p for p in src["region"]["points"]}
    region = [dict(r, projection_share=fmt(points[int(r["year"])]["projection_share"]), official=fmt(src["region"]["official"]))
              for r in src["region_csv"]]

    def pyr_part(i: str, y) -> dict:
        doc = src["pyramids"][i]
        return doc["parts"][doc["years"][str(y)]["part"]]

    aging = [dict(r, license="" if r["iso3"] == "REG" else pyr_part(r["iso3"], r["year"])["license"]) for r in src["aging_csv"]]

    pyramids = []
    for i in ISO3:
        doc = src["pyramids"][i]
        for y, v in sorted(doc["years"].items(), key=lambda kv: int(kv[0])):
            part = doc["parts"][v["part"]]
            for s in ("m", "f"):
                for k, g in enumerate(doc["age_groups"]):
                    pyramids.append(dict(iso3=i, country=names[i], year=y, sex=SEX[s], age_group=g, age_order=str(k),
                                         population=fmt(v[s][k]), series_type=v["series_type"], source_id=v["source_id"],
                                         source_tier=v["source_tier"], vintage=v["vintage"],
                                         reference_date=fmt(v["reference_date"]), institution=part["institution"],
                                         license=part["license"]))
    reg_pyr = src["region"]["pyramid"]
    for y, v in sorted(reg_pyr["years"].items(), key=lambda kv: int(kv[0])):
        for s in ("m", "f"):
            for k, g in enumerate(reg_pyr["age_groups"]):
                pyramids.append(dict(iso3="REG", country=REGION_NAME, year=y, sex=SEX[s], age_group=g, age_order=str(k),
                                     population=fmt(v[s][k]), series_type="derived", source_id="", source_tier="derived",
                                     vintage="", reference_date="", institution="", license=""))

    sources = []
    for i in ISO3:
        st = src["status"]["countries"][i]
        for s in src["countries"][i]["segments"]:
            L = lic.get(s["license"], {})
            sources.append(dict(
                iso3=i, country=names[i], series=s["series"], institution=s["institution"], source_id=s["source_id"],
                source_tier=s["source_tier"], vintage=s["vintage"], reference_census=fmt(s.get("reference_census")),
                published_in=fmt(s.get("published")), scenario=fmt(s.get("scenario")),
                reference_date=fmt(s.get("reference_date")), year_from=fmt(s["year_from"]), year_to=fmt(s["year_to"]),
                source_url=s["source_url"], location_in_file=fmt(s.get("location_in_file")),
                access_method=fmt(s.get("access_method")), raw_file=s["raw_file"], raw_sha256=s["raw_sha256"],
                retrieved_at=s["retrieved_at"], retrieved_by=fmt(s.get("retrieved_by")),
                series_status=fmt(st["series"].get(s["series"], {}).get("status")),
                note=fmt((s.get("note") or {}).get("en")), **license_cols(s["license"], L)))
        doc = src["pyramids"][i]
        groups = defaultdict(list)
        for y, v in doc["years"].items():
            groups[(v["part"], v["source_id"], v["vintage"])].append((int(y), v))
        for (pi, sid, vint), ys in sorted(groups.items(), key=lambda kv: min(y for y, _ in kv[1])):
            part = doc["parts"][pi]
            L = lic.get(part["license"], {})
            sources.append(dict(
                iso3=i, country=names[i], series="pyramid", institution=part["institution"], source_id=sid,
                source_tier=part["source_tier"], vintage=vint, reference_census="", published_in="", scenario="",
                reference_date=" | ".join(sorted({fmt(v["reference_date"]) for _, v in ys})),
                year_from=str(min(y for y, _ in ys)), year_to=str(max(y for y, _ in ys)), source_url=part["source_url"],
                location_in_file=fmt(part.get("location_in_file")), access_method="",
                raw_file=" | ".join(f["path"] for f in part["raw_files"]),
                raw_sha256=" | ".join(f["sha256"] for f in part["raw_files"]),
                retrieved_at=" | ".join(sorted({f["retrieved_at"] for f in part["raw_files"]})),
                retrieved_by=" | ".join(sorted({fmt(f.get("retrieved_by")) for f in part["raw_files"]})),
                series_status=fmt(src["status"]["countries"][i].get("pyramid", {}).get("status")),
                note=fmt((doc.get("note") or {}).get("en")), **license_cols(part["license"], L)))

    breaks_rows = [dict(iso3=i, country=names[i], **{k: fmt(b[k]) for k in ("year", "from_source", "to_source", "from_vintage",
                                                                            "to_vintage", "from_tier", "to_tier", "last_value", "first_value")})
                   for i in ISO3 for b in src["countries"][i]["breaks"]]
    alerts = [dict(code=a["code"], iso3=a.get("iso3", ""), year=fmt(a.get("year")), years=fmt(a.get("years")),
                   source=fmt(a.get("source")), message=a["message"], fingerprint=a["fingerprint"]) for a in src["alerts"]["alerts"]]
    return {"population_latam.csv": latam, "population_region.csv": region, "aging_index.csv": aging,
            "population_pyramids.csv": pyramids, "sources.csv": sources, "source_breaks.csv": breaks_rows,
            "quality_alerts.csv": alerts}


def license_cols(key: str, L: dict) -> dict:
    return dict(license=key, license_status=L.get("status", ""), license_name=L.get("name", ""),
                license_url=L.get("license_url", ""), terms_url=L.get("terms_url", ""), attribution=L.get("attribution", ""))


# ---------- validación ----------

def validate(tables: dict[str, list[dict]], src: dict) -> list[str]:
    """Devuelve la lista de errores. Ninguno se corrige: se informa."""
    errs: list[str] = []
    spec = src["spec"]["files"]
    universe = set(ISO3)
    for name, rows in tables.items():
        cols = [c["name"] for c in spec[name]["columns"]]
        for n, r in enumerate(rows):
            if list(r) != cols:
                errs.append(f"{name}: la fila {n} tiene columnas {list(r)}; el diccionario declara {cols}")
                break
        key = spec[name]["key"]
        dup = [k for k, c in Counter(tuple(r[x] for x in key) for r in rows).items() if c > 1]
        if dup:
            errs.append(f"{name}: clave {key} duplicada en {dup[:5]}")
        for c in spec[name]["columns"]:
            if not c["nullable"] and any(r[c["name"]] == "" for r in rows):
                errs.append(f"{name}: {c['name']} vacío aunque el diccionario lo declara no nulo")
    latam = tables["population_latam.csv"]

    # Cobertura: los 20 países, en la tabla principal y en las fuentes.
    for name in ("population_latam.csv", "sources.csv"):
        got = {r["iso3"] for r in tables[name]}
        if got != universe:
            errs.append(f"{name}: países {sorted(got)} ≠ universo del proyecto {sorted(universe)}")
    for name in ("population_pyramids.csv", "aging_index.csv"):
        if not {r["iso3"] for r in tables[name]} <= universe | {"REG"}:
            errs.append(f"{name}: ISO3 fuera del universo del proyecto")

    # Integridad de la tabla principal.
    for r in latam:
        if r["population"] and float(r["population"]) < 0:
            errs.append(f"population_latam.csv: población negativa {r['iso3']} {r['year']}")
        if r["series_type"] not in ("observed", "estimate", "projection"):
            errs.append(f"population_latam.csv: series_type inválido {r['series_type']}")
        if r["source_tier"] not in ("national", "international_fallback"):
            errs.append(f"population_latam.csv: source_tier inválido {r['source_tier']}")
        if r["interpolated"] != "False":
            errs.append(f"population_latam.csv: interpolated≠False en {r['iso3']} {r['year']}")
        if not (1900 <= int(r["year"]) <= 2200):
            errs.append(f"population_latam.csv: año fuera de rango {r['iso3']} {r['year']}")
    for r in tables["population_pyramids.csv"]:
        if float(r["population"]) < 0:
            errs.append(f"population_pyramids.csv: población negativa {r['iso3']} {r['year']} {r['sex']} {r['age_group']}")
        if r["age_group"] not in AGE_GROUPS or r["sex"] not in SEX.values():
            errs.append(f"population_pyramids.csv: grupo o sexo fuera del contrato {r['age_group']} {r['sex']}")

    # Reconciliación con los productos canónicos: mismos valores, mismas filas.
    canon = src["latam_csv"]
    if len(latam) != len(canon) or any({k: r[k] for k in c} != c for r, c in zip(latam, canon)):
        errs.append("population_latam.csv no reproduce data/processed/latam.csv campo por campo")
    n_records = sum(len(src["countries"][i]["records"]) for i in ISO3)
    if n_records != len(latam):
        errs.append(f"latam.csv tiene {len(latam)} filas y los JSON por país {n_records}")
    for out, rel in (("population_region.csv", "region_csv"), ("aging_index.csv", "aging_csv")):
        rows, c_rows = tables[out], src[rel]
        if len(rows) != len(c_rows) or any({k: r[k] for k in c} != c for r, c in zip(rows, c_rows)):
            errs.append(f"{out} no reproduce su producto canónico")
    total = {(r["iso3"], r["year"]): float(r["population"]) for r in latam if r["population"]}
    sums: dict = defaultdict(float)
    for r in tables["population_pyramids.csv"]:
        sums[(r["iso3"], r["year"])] += float(r["population"])
    for (i, y), s in sums.items():
        ref = total.get((i, y)) if i != "REG" else next((float(r["population"]) for r in tables["population_region.csv"] if r["year"] == y), None)
        if ref is None:
            errs.append(f"population_pyramids.csv: {i} {y} sin población total con qué cuadrar")
        elif abs(s - ref) / ref > MAX_PYRAMID_GAP:
            errs.append(f"population_pyramids.csv: {i} {y} suma {s:.0f} y el total es {ref:.0f} (> {MAX_PYRAMID_GAP:.2%})")
    pyr_keys = {(i, int(y)) for i in ISO3 for y in src["pyramids"][i]["years"]}
    if {(r["iso3"], int(r["year"])) for r in tables["population_pyramids.csv"] if r["iso3"] != "REG"} != pyr_keys:
        errs.append("population_pyramids.csv no cubre exactamente los años de las pirámides canónicas")
    for r in tables["aging_index.csv"]:
        if r["iso3"] == "REG":
            continue
        m = measure(src["pyramids"][r["iso3"]]["years"][r["year"]])
        if fmt(m["aging_index"]) != r["aging_index"] and float(r["aging_index"]) != m["aging_index"]:
            errs.append(f"aging_index.csv: {r['iso3']} {r['year']} no coincide con la pirámide publicada")

    # Trazabilidad: cada serie usada tiene su fila en sources.csv y su licencia registrada.
    seg = {(r["iso3"], r["source_id"], r["vintage"]) for r in tables["sources.csv"]}
    for name in ("population_latam.csv", "population_pyramids.csv", "aging_index.csv"):
        miss = {(r["iso3"], r["source_id"], r["vintage"]) for r in tables[name] if r["iso3"] != "REG"} - seg
        if miss:
            errs.append(f"{name}: series sin fila en sources.csv: {sorted(miss)[:5]}")
    known = set(src["licenses"]["licenses"])
    for name in ("population_latam.csv", "population_pyramids.csv", "sources.csv"):
        bad = {r["license"] for r in tables[name] if r["iso3"] != "REG"} - known
        if bad:
            errs.append(f"{name}: licencias sin revisión en licenses.json: {sorted(bad)}")
    return errs


# ---------- puerta de licencias ----------

def license_gate(tables: dict[str, list[dict]], src: dict) -> dict:
    lic = src["licenses"]["licenses"]
    policy = src["policy"]
    acks = policy.get("acknowledgements") or {}
    used: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    for name in ("population_latam.csv", "population_pyramids.csv", "aging_index.csv"):
        for r in tables[name]:
            if r["iso3"] != "REG":
                used[r["license"]][name].add(r["iso3"])
    for r in tables["population_latam.csv"]:
        used[r["license"]]["population_region.csv"].add(r["iso3"])  # la región suma a los 20

    items = []
    for key in sorted(used):
        L = lic[key]
        files = {f: sorted(c) for f, c in used[key].items()}
        countries = sorted({c for v in files.values() for c in v})
        reasons, severity = [], None
        if L["status"] == "restricted":
            severity, reasons = "blocker_hard", ["The text found limits redistribution or derivative works."]
        elif L["status"] == "no_license":
            severity = "blocker"
            reasons.append("No licence or redistribution permission was found. Absence of a licence is not permission.")
        elif L["status"] == "own_terms":
            if L.get("raw_copy") not in ("allowed", "allowed_with_source"):
                reasons.append(f"Redistribution of the data is not stated (raw_copy={L.get('raw_copy')}).")
            if L.get("commercial") != "allowed":
                reasons.append(f"Commercial use is not generally authorized (commercial={L.get('commercial')}).")
            severity = "review" if reasons else None
        elif L["status"] != "open_license":
            severity, reasons = "blocker", [f"Unknown status: {L['status']}"]
        ack = acks.get(key)
        if ack and ack.get("decision") == "exclude":
            raise ExportError(f"license_policy.yaml: decision 'exclude' para {key} no está implementada; "
                              "excluir un país cambia el alcance del dataset y debe hacerse a propósito.")
        items.append(dict(key=key, institution=L["institution"], status=L["status"], name=L.get("name", ""),
                          countries=countries, files=files, raw_copy=L.get("raw_copy"), commercial=L.get("commercial"),
                          share_alike=L.get("share_alike"), attribution=L.get("attribution", ""),
                          license_url=L.get("license_url", ""), terms_url=L.get("terms_url", ""),
                          summary_en=(L.get("summary") or {}).get("en", ""), severity=severity, reasons=reasons,
                          acknowledged=bool(ack) and severity != "blocker_hard", acknowledgement=ack))
    sa = sorted({it["name"] for it in items if it["share_alike"]})
    sa_families = {("ODbL" if "ODbL" in n else "CC BY-SA") for n in sa}
    mix = None
    if len(sa_families) > 1:
        ack = acks.get("share_alike_mix")
        mix = dict(key="share_alike_mix", licenses=sa, severity="review", acknowledged=bool(ack), acknowledgement=ack,
                   countries=sorted({c for it in items if it["share_alike"] for c in it["countries"]}),
                   reasons=["CC BY-SA 4.0 and ODbL each require derived databases to be shared under the same licence. "
                            "A combined product (regional population, ageing index and pyramid) cannot satisfy both "
                            "with a single licence."])
    kl = policy.get("kaggle_license")
    problems = []
    if kl not in KAGGLE_LICENSES:
        problems.append(f"kaggle_license '{kl}' no es un nombre aceptado por Kaggle")
    non_open = [it["key"] for it in items if it["status"] != "open_license"]
    if kl not in ("other", "unknown") and (non_open or mix):
        problems.append(f"kaggle_license '{kl}' otorgaría una licencia uniforme que las fuentes no respaldan "
                        f"({', '.join(non_open) or 'share-alike mixto'}); use 'other'.")
    pending = [it for it in items if it["severity"] and not it["acknowledged"]] + ([mix] if mix and not mix["acknowledged"] else [])
    return dict(status="PASS" if not pending and not problems else "BLOCKED", kaggle_license=kl, items=items,
                share_alike_mix=mix, problems=problems, pending=[p["key"] for p in pending],
                counts=dict(Counter(it["status"] for it in items)))


# ---------- documentación ----------

def md_table(header: list[str], rows: list[list]) -> str:
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] +
                     ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows])


def data_dictionary(spec: dict, stats: dict) -> str:
    out = ["# Data dictionary", "",
           "Generated from `kaggle/columns.yaml` by `scripts/build_kaggle_dataset.py`.", "",
           "**Origin:** `original` = copied unchanged from the repository's processed products; "
           "`derived` = calculated by the repository (not published by any institution); "
           "`added` = joined by the exporter from canonical files, without changing any value.", "",
           "Empty cells are missing values (null). Nothing is filled, interpolated or smoothed.", ""]
    for name, f in spec["files"].items():
        out += [f"## `{name}`", "", f["description"].strip(), "",
                f"- **One row =** {f['row']}", f"- **Unique key:** `{' + '.join(f['key'])}`",
                f"- **Rows:** {stats[name]['rows']:,}", f"- **Built from:** `{f['from']}`", "",
                md_table(["variable", "type", "unit", "nullable", "origin", "definition", "possible values"],
                         [[f"`{c['name']}`", c["type"], c.get("unit") or "", "yes" if c["nullable"] else "no", c["origin"],
                           " ".join(str(c["definition"]).split()), c.get("values", "")] for c in f["columns"]]), ""]
    return "\n".join(out)


def sources_and_licenses(gate: dict, tables: dict) -> str:
    seg = defaultdict(set)
    for r in tables["sources.csv"]:
        seg[r["license"]].add(f"{r['iso3']} {r['series']}")
    out = ["# Sources and licences", "",
           "Each figure in this dataset keeps the terms of use of the institution that published it. This dataset "
           "does **not** grant a new licence over the data: the Kaggle licence field is set to "
           f"**`{gate['kaggle_license']}`** and points here.", "",
           "The review below comes from `data/processed/licenses.json` in the source repository (reviewed "
           "2026-11-01). It is a technical reading of published texts, **not a legal opinion**. "
           "`no_license` means no applicable permission was found: it is neither a prohibition nor a permission.", "",
           "## How to attribute", "",
           "When you reuse figures, cite the original institution with the text in the `attribution` column of "
           "`sources.csv` (also listed below), indicate that the data were transformed (total population extracted, "
           "UN thousands converted to persons, age groups summed into 17 common groups) and cite this dataset.", "",
           "## Summary by institution", "",
           md_table(["licence key", "institution", "countries", "status", "terms found", "redistribution", "commercial",
                     "share-alike", "used in"],
                    [[f"`{it['key']}`", it["institution"], ", ".join(it["countries"]), f"`{it['status']}`", it["name"],
                      it["raw_copy"], it["commercial"], "yes" if it["share_alike"] else "no",
                      ", ".join(f"`{f}`" for f in sorted(it["files"]))] for it in gate["items"]]), "",
           "## Details", ""]
    for it in gate["items"]:
        out += [f"### {it['institution']} (`{it['key']}`)", "",
                f"- **Status:** `{it['status']}` — {it['name']}",
                f"- **Countries / series:** {', '.join(sorted(seg[it['key']]))}"]
        if it["license_url"]:
            out.append(f"- **Licence:** {it['license_url']}")
        if it["terms_url"]:
            out.append(f"- **Terms read at:** {it['terms_url']}")
        out += [f"- **Required / recommended attribution:** {it['attribution']}", f"- **Summary:** {it['summary_en']}", ""]
    out += ["## Combined and derived files", "",
            "`population_region.csv`, the `REG` rows of `aging_index.csv` and `population_pyramids.csv` are the "
            "repository's own sums of figures under all the terms above, including CC BY-SA 4.0 (Argentina, Chile, "
            "Costa Rica) and ODbL (Dominican Republic). Each component keeps the terms of its source.", "",
            "## Raw files", "",
            "The original files downloaded from each institution (`data/raw/` in the repository) are **not** included "
            "in this dataset. The `raw_file` and `raw_sha256` columns identify them in the GitHub repository.", ""]
    return "\n".join(out)


def blockers_md(gate: dict) -> str:
    out = ["# Publication blockers (Kaggle)", "",
           f"License gate: **{gate['status']}**. Public publication is stopped until each item below is resolved "
           "or explicitly acknowledged by the dataset owner in `kaggle/license_policy.yaml` (`acknowledgements`). "
           "Building, validating and a **private** Kaggle upload are not affected.", "",
           "This is a conservative technical assessment based on the terms recorded by the project "
           "(`data/processed/licenses.json`), not a legal opinion.", ""]
    for p in gate["problems"]:
        out += [f"- **Configuration:** {p}"]
    rows = []
    for it in gate["items"]:
        if it["severity"] and not it["acknowledged"]:
            risk = {"blocker_hard": "High", "blocker": "High", "review": "Medium"}[it["severity"]]
            rec = {"blocker_hard": "Do not publish publicly while this source is included.",
                   "blocker": "Ask the institution for written permission or a licence; or record an explicit owner "
                              "decision in license_policy.yaml. Do not drop the country silently.",
                   "review": "Confirm the terms allow redistributing derived tables (and commercial reuse by "
                             "third parties under Kaggle); record the decision in license_policy.yaml."}[it["severity"]]
            rows.append([f"{it['institution']} (`{it['key']}`)", ", ".join(it["countries"]),
                         ", ".join(f"`{f}`" for f in sorted(it["files"])), f"`{it['status']}` — {it['name']}",
                         f"{risk}: " + " ".join(it["reasons"]), rec])
    mix = gate["share_alike_mix"]
    if mix and not mix["acknowledged"]:
        rows.append(["Share-alike mix (`share_alike_mix`)", ", ".join(mix["countries"]),
                     "`population_region.csv`, `aging_index.csv` (REG), `population_pyramids.csv` (REG)",
                     "; ".join(mix["licenses"]), "Medium: " + " ".join(mix["reasons"]),
                     "Keep the Kaggle licence as `other` with per-row terms, or publish combined files under one "
                     "share-alike licence only after review; record the decision in license_policy.yaml."])
    out += [md_table(["source", "country", "published files affected", "licence / terms found", "risk", "recommendation"], rows), ""]
    return "\n".join(out)


def fill(template: str, values: dict) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", str(v))
    if "{{" in template:
        raise ExportError(f"Plantilla con marcadores sin resolver: {template[template.index('{{'):][:40]}")
    return template


def readme_values(tables: dict, src: dict, commit: str, gate: dict) -> dict:
    latam = tables["population_latam.csv"]
    names = {i: src["countries"][i]["name_en"] for i in ISO3}
    by = defaultdict(list)
    for r in latam:
        by[r["iso3"]].append(r)
    crows = []
    for i in ISO3:
        rs = by[i]
        ys = [int(r["year"]) for r in rs]
        est = [int(r["year"]) for r in rs if r["series_type"] == "estimate"]
        prj = [int(r["year"]) for r in rs if r["series_type"] == "projection"]
        intl = [int(r["year"]) for r in rs if r["source_tier"] == "international_fallback"]
        insts = list(dict.fromkeys(r["institution"] for r in rs))
        crows.append([f"`{i}`", names[i], f"{min(ys)}-{max(ys)}", f"{min(est)}-{max(est)}" if est else "—",
                      f"{min(prj)}-{max(prj)}" if prj else "—", " · ".join(insts),
                      f"{min(intl)}-{max(intl)}" if intl else "—", sum(r["source_break"] == "True" for r in rs)])
    years = [int(r["year"]) for r in latam]
    files = [[f"`{n}`", f"{len(tables[n]):,}", " ".join(src['spec']['files'][n]["description"].split())] for n in CSV_FILES]
    return dict(
        countries_table=md_table(["ISO3", "country", "years", "estimates", "projections", "institution(s)",
                                  "UN fallback years", "source breaks"], crows),
        country_list=", ".join(f"{names[i]} ({i})" for i in ISO3),
        year_min=min(years), year_max=max(years), n_rows=f"{len(latam):,}",
        n_estimate=f"{sum(r['series_type'] == 'estimate' for r in latam):,}",
        n_projection=f"{sum(r['series_type'] == 'projection' for r in latam):,}",
        n_fallback=f"{sum(r['source_tier'] == 'international_fallback' for r in latam):,}",
        n_breaks=len(tables["source_breaks.csv"]),
        fallback_summary=", ".join(f"{names[r[0].strip('`')]} ({r[6]})" for r in crows if r[6] != "—"),
        files_table=md_table(["file", "rows", "content"], files),
        region_years=", ".join(r["year"] for r in tables["population_region.csv"]),
        region_pyramid_years=", ".join(sorted(src["region"]["pyramid"]["years"])),
        schema_version=src["spec"]["expected_schema_version"], commit=commit or "unknown",
        commit_short=(commit or "unknown")[:7], data_updated=src["status"].get("last_data_update", ""),
        kaggle_license=gate["kaggle_license"], repo_url=REPO_URL, dashboard_url=DASHBOARD_URL,
        license_counts=", ".join(f"{v} `{k}`" for k, v in sorted(gate["counts"].items())),
    )


DOC_DESCRIPTIONS = {
    "README.md": "Overview: contents, the 20 countries, methodology, source hierarchy, citation and limitations.",
    "DATA_DICTIONARY.md": "Every column of every CSV: type, unit, nullability, origin (original, derived or added) and definition.",
    "SOURCES_AND_LICENSES.md": "Terms of use of each institution, required attribution and which files each source feeds.",
    "manifest.json": "Package manifest: source repository commit, data-contract version, rows and SHA-256 of each CSV.",
    "SOURCE_COMMIT.txt": "Repository commit, data-contract version and last data update this version was built from.",
}


def resources(spec: dict) -> list[dict]:
    return [dict(path=n, description=" ".join(f["description"].split()),
                 schema=dict(fields=[dict(name=c["name"], description=" ".join(str(c["definition"]).split()), type=c["type"])
                                     for c in f["columns"]]))
            for n, f in spec["files"].items()] + [dict(path=n, description=d) for n, d in DOC_DESCRIPTIONS.items()]


def check_metadata(meta: dict) -> list[str]:
    errs = []
    owner, _, slug = meta["id"].partition("/")
    for k, (lo, hi) in LIMITS.items():
        v = slug if k == "slug" else meta[k]
        if not (lo <= len(v) <= hi):
            errs.append(f"dataset-metadata.json: {k} '{v}' mide {len(v)} (Kaggle exige {lo}-{hi})")
    if not owner or not slug.replace("-", "").isalnum() or slug != slug.lower():
        errs.append(f"dataset-metadata.json: id '{meta['id']}' inválido (owner/slug en minúsculas, letras, números y guiones)")
    if len(meta["licenses"]) != 1 or meta["licenses"][0]["name"] not in KAGGLE_LICENSES:
        errs.append(f"dataset-metadata.json: licenses {meta['licenses']} inválida para Kaggle")
    if not meta.get("description"):
        errs.append("dataset-metadata.json: description vacía")
    return errs


# ---------- escritura ----------

def csv_text(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def safe_reset(out: Path, root: Path) -> None:
    """Borra solo una salida generada dentro de dist/ del repositorio."""
    out = out.resolve()
    dist = (root / "dist").resolve()
    if dist not in out.parents:
        raise ExportError(f"Salida {out} fuera de {dist}: no se borra nada fuera de dist/.")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)


def build(root: Path = ROOT, out: Path | None = None, today: str | None = None) -> dict:
    root = Path(root).resolve()
    out = Path(out) if out else root / "dist" / "kaggle"
    src = load(root)
    check_schema(src)
    tables = build_tables(src)
    errs = validate(tables, src)
    gate = license_gate(tables, src)

    commit = git(root, "rev-parse", "HEAD")
    dirty = bool(git(root, "status", "--porcelain", "--", "data", "sources.yaml", "latam_pop", "kaggle", "scripts/build_kaggle_dataset.py"))
    spec = src["spec"]
    texts = {n: csv_text(tables[n], [c["name"] for c in spec["files"][n]["columns"]]) for n in CSV_FILES}
    stats = {n: dict(rows=len(tables[n]), columns=len(spec["files"][n]["columns"]), sha256=sha(texts[n])) for n in CSV_FILES}
    content_sha = sha("".join(f"{n}:{stats[n]['sha256']}\n" for n in CSV_FILES))

    vals = readme_values(tables, src, commit, gate)
    readme = fill((root / "kaggle" / "README.template.md").read_text(encoding="utf8"), vals)
    meta = json.loads((root / "kaggle" / "dataset-metadata.template.json").read_text(encoding="utf8"))
    meta["licenses"] = [{"name": gate["kaggle_license"]}]
    meta["description"] = readme
    meta["resources"] = resources(spec)
    errs += check_metadata(meta)
    if errs:
        raise ExportError("Validación fallida:\n- " + "\n- ".join(errs))

    series_fp = {f"{r['iso3']}:{r['series']}:{r['source_id']}": f"{r['vintage']}|{r['raw_sha256']}" for r in tables["sources.csv"]}
    manifest = dict(
        dataset_id=meta["id"], source_repository=REPO_URL, source_commit=commit or None, source_tree_clean=not dirty,
        schema_version=spec["expected_schema_version"], data_last_update=src["status"].get("last_data_update"),
        generated=today or src["status"].get("last_data_update"), content_sha256=content_sha,
        countries=ISO3, files=stats, license_gate=dict(status=gate["status"], kaggle_license=gate["kaggle_license"],
                                                       pending=gate["pending"], counts=gate["counts"]),
        series=series_fp)

    safe_reset(out, root)
    for n in CSV_FILES:
        (out / n).write_text(texts[n], encoding="utf8")
    (out / "README.md").write_text(readme, encoding="utf8")
    (out / "DATA_DICTIONARY.md").write_text(data_dictionary(spec, stats), encoding="utf8")
    (out / "SOURCES_AND_LICENSES.md").write_text(sources_and_licenses(gate, tables), encoding="utf8")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    (out / "SOURCE_COMMIT.txt").write_text(
        f"repository: {REPO_URL}\ncommit: {commit or 'unknown'}\nclean: {str(not dirty).lower()}\n"
        f"schema_version: {spec['expected_schema_version']}\ndata_last_update: {manifest['data_last_update']}\n", encoding="utf8")
    (out / "dataset-metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf8")

    # El informe de la puerta queda junto al paquete, no dentro: no se sube a Kaggle.
    (out.parent / "license_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=1, default=list) + "\n", encoding="utf8")
    blockers = out.parent / "PUBLICATION_BLOCKERS.md"
    if gate["status"] == "BLOCKED":
        blockers.write_text(blockers_md(gate), encoding="utf8")
    elif blockers.exists():
        blockers.unlink()
    unexpected = sorted(p.name for p in out.iterdir()) != sorted(CSV_FILES + DOC_FILES)
    if unexpected:
        raise ExportError(f"dist/kaggle contiene archivos no previstos: {sorted(p.name for p in out.iterdir())}")
    settings = metadata_settings(root, out.parent / "kaggle_metadata", meta, gate, src["policy"], tables)
    return dict(out=out, stats=stats, gate=gate, manifest=manifest, meta=meta, settings=settings)


def user_sources(tables: dict) -> str:
    """Procedencia para la ficha de Kaggle: cada institución con sus archivos de origen."""
    by = defaultdict(lambda: dict(countries=set(), urls=set(), attribution=""))
    for r in tables["sources.csv"]:
        b = by[r["institution"]]
        b["countries"].add(r["iso3"])
        b["urls"].add(r["source_url"])
        b["attribution"] = r["attribution"]
    lines = [f"Built from {REPO_URL}, which records the file, SHA-256 and table of every figure.", ""]
    for inst, b in sorted(by.items()):
        lines.append(f"- **{inst}** ({', '.join(sorted(b['countries']))}): {b['attribution']}")
        lines += [f"  - {u}" for u in sorted(b["urls"])]
    return "\n".join(lines)


def metadata_settings(root: Path, out: Path, meta: dict, gate: dict, policy: dict, tables: dict) -> dict:
    """Carpeta para `kaggle datasets metadata --update`, separada del paquete para no subir la portada como dato.

    Ese comando toma isPrivate del archivo y, si falta, deja el dataset público: aquí se escribe siempre y solo es
    false con la puerta de licencias en PASS y `visibility: public` en license_policy.yaml.
    """
    public = policy.get("visibility") == "public" and gate["status"] == "PASS"
    settings = dict(meta, isPrivate=not public, userSpecifiedSources=user_sources(tables),
                    expectedUpdateFrequency=policy.get("expected_update_frequency", "not specified"))
    if settings["expectedUpdateFrequency"] not in UPDATE_FREQUENCIES:
        raise ExportError(f"expected_update_frequency inválida: {settings['expectedUpdateFrequency']}")
    safe_reset(out, root)
    cover = root / "kaggle" / "dataset-cover-image.png"
    if cover.exists():
        shutil.copy(cover, out / cover.name)
    (out / "dataset-metadata.json").write_text(json.dumps(settings, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    return settings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="carpeta de salida (por defecto dist/kaggle, debe quedar dentro de dist/)")
    a = ap.parse_args()
    try:
        res = build(out=a.out)
    except ExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    m = res["manifest"]
    print(f"Paquete: {res['out'].relative_to(ROOT) if ROOT in res['out'].parents else res['out']}")
    print(f"Commit: {m['source_commit']} (limpio: {m['source_tree_clean']}) · esquema {m['schema_version']}")
    for n, s in res["stats"].items():
        print(f"  {n:26} {s['rows']:>7,} filas  {s['columns']:>2} columnas")
    g = res["gate"]
    print(f"Puerta de licencias: {g['status']} · licencia Kaggle '{g['kaggle_license']}' · {g['counts']}")
    if g["status"] != "PASS":
        print(f"  Pendientes: {', '.join(g['pending'])}. Ver dist/PUBLICATION_BLOCKERS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
