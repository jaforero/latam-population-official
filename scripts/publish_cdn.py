"""Publica data/ sin data/raw/ en la rama que sirve jsDelivr, purga su caché y comprueba archivo por archivo.

Sale con error si, agotados los reintentos, algún archivo del respaldo no coincide con main.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = "jaforero/latam-population-official"
BRANCH = "respaldo-cdn"
CDN = f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/"
PURGE = f"https://purge.jsdelivr.net/gh/{REPO}@{BRANCH}/"
USER_AGENT = f"{REPO} (publish_cdn)"
MAX_BYTES = 40 * 1024 * 1024  # jsDelivr rechaza los paquetes de más de 50 MB
WAITS = (0, 20, 40, 60, 120, 240, 300, 300)  # segundos antes de cada revisión


def git(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, input=stdin).stdout.strip()


def light_tree(source: str) -> str:
    """Árbol con data/ de `source` sin data/raw/. Reusa sus objetos: la rama no agrega archivos al repositorio."""
    entries = [e for e in git("ls-tree", f"{source}:data").splitlines() if e.split("\t")[1] != "raw"]
    data = git("mktree", "--missing", stdin="\n".join(entries) + "\n")
    return git("mktree", "--missing", stdin=f"040000 tree {data}\tdata\n")


def list_blobs(tree: str) -> dict[str, tuple[str, int]]:
    """{ruta: (hash del blob, bytes)}."""
    blobs = {}
    for line in git("ls-tree", "-r", "-l", tree).splitlines():
        meta, path = line.split("\t", 1)
        _, _, sha, size = meta.split()
        blobs[path] = (sha, int(size))
    return blobs


def changed_paths(old_tree: str, new_tree: str) -> list[str]:
    """Rutas agregadas, modificadas o eliminadas entre dos árboles."""
    return git("diff-tree", "-r", "--no-renames", "--name-only", old_tree, new_tree).splitlines()


def publish(source: str = "origin/main") -> tuple[str, list[str]]:
    """Deja la rama igual a data/ de `source`, siempre con avance rápido. Devuelve el árbol y lo que cambió."""
    tree = light_tree(source)
    size = sum(s for _, s in list_blobs(tree).values())
    if size > MAX_BYTES:
        raise SystemExit(f"La rama pesaría {size / 1048576:.1f} MB: jsDelivr la rechazaría. No se publica.")
    remote = git("ls-remote", "--heads", "origin", BRANCH)
    tip = None
    if remote:
        git("fetch", "--depth=1", "origin", BRANCH)
        tip = remote.split()[0]
        old_tree = git("rev-parse", f"{tip}^{{tree}}")
        if old_tree == tree:
            print(f"La rama ya coincide con {source}.")
            return tree, []
    message = f"Publica data/ de main@{git('rev-parse', '--short', source)}"
    commit = git("commit-tree", tree, *(["-p", tip] if tip else []), "-m", message)
    git("push", "origin", f"{commit}:refs/heads/{BRANCH}")
    print(f"{message}: {commit[:8]}, {size / 1048576:.2f} MB.")
    changed = changed_paths(old_tree, tree) if tip else list(list_blobs(tree))
    return tree, changed


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def cdn_state(path: str) -> str:
    """Hash del archivo que sirve jsDelivr, o la falla como texto."""
    try:
        return blob_sha(fetch(CDN + urllib.parse.quote(path)))
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except OSError as e:
        return f"sin respuesta: {e}"


def purge(path: str) -> None:
    try:
        answer = json.loads(fetch(PURGE + urllib.parse.quote(path)))
    except (OSError, ValueError) as e:
        print(f"  purga fallida de {path}: {e}")
        return
    if any(p.get("throttled") for p in answer.get("paths", {}).values()):
        print(f"  purga limitada por jsDelivr: {path}")


def sync(expected: dict[str, str], changed: list[str], waits=WAITS, state=cdn_state, purge_one=purge, sleep=time.sleep) -> dict[str, str]:
    """Purga lo que cambió aunque desde aquí se vea bien (otro nodo puede tener la copia vieja) y revisa todo.

    Devuelve {ruta: estado} de lo que sigue sin coincidir al final.
    """
    for path in changed:
        purge_one(path)
    pending = dict(expected)
    for attempt, wait in enumerate(waits, 1):
        sleep(wait)
        pending = {p: s for p in pending if (s := state(p)) != expected[p]}
        print(f"Revisión {attempt}: {len(expected) - len(pending)} de {len(expected)} archivos al día.")
        if not pending:
            return {}
        for path in pending:
            purge_one(path)
    return pending


def main() -> int:
    tree, changed = publish()
    expected = {path: sha for path, (sha, _) in list_blobs(tree).items()}
    behind = sync(expected, changed)
    for path, state in sorted(behind.items()):
        print(f"ATRASADO {path}: {state}, se esperaba {expected[path]}")
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main())
