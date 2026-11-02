"""Publica dist/kaggle/ en Kaggle con las puertas de validación y licencias.

    python scripts/publish_kaggle.py status                 # informe de preparación, sin subir nada
    python scripts/publish_kaggle.py create                 # primera publicación, PRIVADA
    python scripts/publish_kaggle.py create --public        # primera publicación pública (exige licencias en PASS)
    python scripts/publish_kaggle.py version                # nueva versión solo si cambió el contenido

Siempre reconstruye el paquete antes de subir. Nunca borra versiones anteriores (no usa --delete-old-versions).
Las credenciales las resuelve el Kaggle CLI (`kaggle auth login`, KAGGLE_API_TOKEN o ~/.kaggle/access_token);
este script nunca las lee, imprime ni escribe.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_kaggle_dataset import ROOT, ExportError, build  # noqa: E402


def kaggle_bin() -> list[str]:
    exe = os.environ.get("KAGGLE_BIN") or shutil.which("kaggle") or str(Path(sys.executable).parent / "kaggle")
    return [exe]


def kaggle(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(kaggle_bin() + list(args), capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", "Kaggle CLI no instalado")


def remote_state(dataset_id: str) -> str:
    """'missing_cli', 'unauthenticated', 'absent' (no existe o no es visible) o 'exists'."""
    r = kaggle("datasets", "status", dataset_id)
    out = (r.stdout + r.stderr).lower()
    if r.returncode == 127:
        return "missing_cli"
    if "authentication required" in out or "unauthorized" in out or "401" in out:
        return "unauthenticated"
    if r.returncode != 0 or "404" in out or "not found" in out:
        return "absent"
    return "exists"


def remote_manifest(dataset_id: str) -> dict | None:
    with tempfile.TemporaryDirectory() as tmp:
        r = kaggle("datasets", "download", dataset_id, "-f", "manifest.json", "-p", tmp, "--force")
        files = list(Path(tmp).rglob("manifest.json"))
        if r.returncode != 0 or not files:
            return None
        return json.loads(files[0].read_text(encoding="utf8"))


def version_notes(m: dict, prev: dict | None) -> str:
    changed = []
    if prev:
        old, new = prev.get("series", {}), m["series"]
        for k in sorted(set(old) | set(new)):
            if old.get(k) != new.get(k):
                iso, series, sid = k.split(":", 2)
                vintage = (new.get(k) or old.get(k)).split("|")[0]
                changed.append(f"{iso} {series} {sid} ({vintage}){'' if k in new else ' removed'}")
        if prev.get("schema_version") != m["schema_version"]:
            changed.insert(0, f"schema {prev.get('schema_version')} -> {m['schema_version']}")
    lines = [f"Source repository commit: {(m['source_commit'] or 'unknown')[:7]}", f"Schema: {m['schema_version']}",
             f"Updated: {', '.join(changed[:12]) + (' ...' if len(changed) > 12 else '') if changed else 'derived tables and documentation'}",
             f"Generated: {date.today().isoformat()}"]
    return "\n".join(lines)


def readiness(res: dict | None, err: str | None, auth: str, public: bool) -> tuple[str, bool]:
    ok = res is not None
    gate = res["gate"]["status"] if ok else "UNKNOWN"
    lines = ["KAGGLE PUBLICATION READINESS", "",
             f"Data validation: {'PASS' if ok else 'FAIL'}",
             f"20-country coverage: {'PASS' if ok else 'FAIL'}",
             f"Schema validation: {'PASS' if ok else 'FAIL'}",
             f"Provenance: {'PASS' if ok else 'FAIL'}",
             f"License review: {'PASS' if gate == 'PASS' else 'BLOCKED'}",
             f"Kaggle metadata: {'PASS' if ok else 'FAIL'}",
             f"Authentication: {'READY' if auth in ('exists', 'absent') else 'MISSING'}"]
    if ok:
        lines += ["", "Recommended dataset ID:", res["meta"]["id"]]
        if not res["manifest"]["source_tree_clean"]:
            lines += ["", "Warning: uncommitted changes in data/, sources.yaml, latam_pop/, kaggle/ or the builder."]
    safe = ok and gate == "PASS" and auth in ("exists", "absent")
    lines += ["", "Safe to publish publicly:", "YES" if safe else "NO"]
    if err:
        lines += ["", f"Error: {err}"]
    if gate == "BLOCKED":
        lines += ["", "License blockers: dist/PUBLICATION_BLOCKERS.md"]
    if auth == "missing_cli":
        lines += ["", "Install the Kaggle CLI: pip install kaggle"]
    elif auth == "unauthenticated":
        lines += ["", "Authenticate: kaggle auth login  (or export KAGGLE_API_TOKEN in your shell; never in the repo)"]
    return "\n".join(lines), safe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["status", "create", "version"])
    ap.add_argument("--public", action="store_true", help="create: publicar como público (exige la puerta en PASS)")
    ap.add_argument("--private-dataset", action="store_true",
                    help="version: confirma que el dataset en Kaggle es privado; permite versionar con la puerta bloqueada")
    ap.add_argument("--allow-dirty", action="store_true", help="permite subir con cambios sin commit (solo privado)")
    ap.add_argument("--force", action="store_true", help="version: subir aunque el contenido no haya cambiado")
    ap.add_argument("-m", "--message", help="version: nota adicional al final de las notas generadas")
    a = ap.parse_args()

    res, err = None, None
    try:
        res = build()
    except ExportError as e:
        err = str(e)
    dataset_id = res["meta"]["id"] if res else "jaforero/latin-america-population-20-countries"
    auth = remote_state(dataset_id)
    report, safe = readiness(res, err, auth, a.public)
    print(report)
    if a.action == "status" or res is None:
        return 0 if res else 1
    if auth in ("missing_cli", "unauthenticated"):
        print("\nNo se sube nada: falta autenticación con Kaggle.", file=sys.stderr)
        return 2
    m, gate = res["manifest"], res["gate"]["status"]
    if not m["source_tree_clean"] and (a.public or not a.allow_dirty or a.action == "version"):
        print("\nNo se sube nada: hay cambios sin commit; la versión no sería trazable a un commit.", file=sys.stderr)
        return 2
    path = str(res["out"])

    if a.action == "create":
        if auth == "exists":
            print(f"\n{dataset_id} ya existe: usa `version`.", file=sys.stderr)
            return 2
        if a.public and not safe:
            print("\nNo se publica públicamente: la puerta de licencias está bloqueada.", file=sys.stderr)
            return 2
        args = ["datasets", "create", "-p", path] + (["--public"] if a.public else [])
    else:
        if auth != "exists":
            print(f"\n{dataset_id} no existe o no es visible con estas credenciales: usa `create`.", file=sys.stderr)
            return 2
        if gate != "PASS" and not a.private_dataset:
            print("\nNo se versiona: la puerta de licencias está bloqueada. Si el dataset en Kaggle es privado, "
                  "repite con --private-dataset.", file=sys.stderr)
            return 2
        prev = remote_manifest(dataset_id)
        if prev and prev.get("content_sha256") == m["content_sha256"] and not a.force:
            print(f"\nSin cambios de contenido respecto a la versión publicada ({m['content_sha256'][:12]}). No se sube nada.")
            return 0
        notes = version_notes(m, prev) + (f"\n{a.message}" if a.message else "")
        print(f"\nNotas de versión:\n{notes}")
        args = ["datasets", "version", "-p", path, "-m", notes]  # nunca --delete-old-versions
    print(f"\n$ kaggle {' '.join(args[:4])} ...")
    r = kaggle(*args)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
