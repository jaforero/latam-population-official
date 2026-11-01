"""Abre issues con lo nuevo de build/run_report.json. Una alerta ya reportada no se repite; una falla se reabre si no hay issue abierto."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

LABEL = "pipeline"
TITLES = {
    "failure": "Falla de adaptador",
    "national": "Fuente nacional detectada donde se usaba CEPAL",
    "validation": "Validación del pipeline",
}


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def category(a: dict) -> str:
    return "national" if a["code"] in ("national_replaces_regional", "watch_change") else "validation"


def main() -> None:
    rep = json.loads(Path("build/run_report.json").read_text(encoding="utf8"))
    gh("label", "create", LABEL, "--color", "4E00FF", "--description", "Generado por el pipeline", "--force")
    issues = json.loads(gh("issue", "list", "--label", LABEL, "--state", "all", "--limit", "500", "--json", "body,state"))
    fp_re = re.compile(r"<!-- fp:(.*?) -->")
    known_all = {fp for i in issues for fp in fp_re.findall(i["body"] or "")}
    known_open = {fp for i in issues if i["state"] == "OPEN" for fp in fp_re.findall(i["body"] or "")}
    groups: dict[str, list[tuple[str, str]]] = {}
    for f in rep["failures"]:
        fp = f"failure:{f['iso3']}:{f['series']}"
        if fp not in known_open:
            groups.setdefault("failure", []).append((fp, f"**{f['iso3']} · {f['series']}**: {f['error']}"))
    for a in rep["alerts"]:
        if a["fingerprint"] not in known_all:
            groups.setdefault(category(a), []).append((a["fingerprint"], f"**{a['iso3']} · {a['code']}**: {a['message']}"))
    for cat, items in groups.items():
        body = "\n".join(f"- {text} <!-- fp:{fp} -->" for fp, text in items)
        body += "\n\nLos datos no se corrigen automáticamente. Consulta el README: «Cuando una fuente cambia de formato»."
        gh("issue", "create", "--title", f"{TITLES[cat]} ({len(items)})", "--label", LABEL, "--body", body)
        print(f"Issue creado: {TITLES[cat]} ({len(items)})")
    if not groups:
        print("Sin novedades para reportar.")


if __name__ == "__main__":
    main()
