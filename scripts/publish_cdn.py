"""Publica data/ sin data/raw/ en la rama que sirve jsDelivr y comprueba lo que queda servido.

jsDelivr cachea las rutas de una rama hasta 12 horas y limita las purgas por ruta, pero las rutas por commit son
inmutables. Por eso cada publicación son dos commits: uno con los datos y otro que agrega respaldo.json, el puntero
a ese commit. Solo se purga el puntero, así que quien lee el respaldo pasa de una versión completa a la siguiente,
sin mezclar archivos de dos publicaciones.

Sale con error si, agotados los reintentos, algún archivo o el puntero no coincide con lo publicado.
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
POINTER = "respaldo.json"
CDN = f"https://cdn.jsdelivr.net/gh/{REPO}@"
PURGE = f"https://purge.jsdelivr.net/gh/{REPO}@"
USER_AGENT = f"{REPO} (publish_cdn)"
MAX_BYTES = 40 * 1024 * 1024  # jsDelivr rechaza los paquetes de más de 50 MB
FILE_WAITS = (0, 30, 60, 120)  # segundos entre revisiones de los archivos, que no dependen de ninguna purga
POINTER_WAITS = (60, 120, 240, 480, 900)  # cada espera gasta una purga: jsDelivr las limita por ruta y por hora
MAX_POINTER_SECONDS = 75 * 60


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


def pointer_text(commit: str, main: str) -> str:
    return json.dumps({"commit": commit, "main": main}, indent=1) + "\n"


def read_pointer(tip: str) -> dict | None:
    try:
        return json.loads(git("show", f"{tip}:{POINTER}"))
    except (subprocess.CalledProcessError, ValueError):
        return None


def publish(source: str = "origin/main") -> tuple[str, str, bool]:
    """Deja la rama igual a data/ de `source`, siempre con avance rápido.

    Devuelve (commit con los datos, hash esperado del puntero, si hubo publicación nueva).
    """
    tree = light_tree(source)
    size = sum(s for _, s in list_blobs(tree).values())
    if size > MAX_BYTES:
        raise SystemExit(f"La rama pesaría {size / 1048576:.1f} MB: jsDelivr la rechazaría. No se publica.")
    remote = git("ls-remote", "--heads", "origin", BRANCH)
    tip = None
    if remote:
        tip = remote.split()[0]
        git("fetch", "--depth=1", "origin", BRANCH)
        pointer = read_pointer(tip)
        if pointer and git("rev-parse", f"{tip}:data") == git("rev-parse", f"{tree}:data"):
            print(f"La rama ya coincide con {source}.")
            return pointer["commit"], git("rev-parse", f"{tip}:{POINTER}"), False
    main = git("rev-parse", source)
    data_commit = git("commit-tree", tree, *(["-p", tip] if tip else []), "-m", f"Publica data/ de main@{main[:7]}")
    text = pointer_text(data_commit, main)
    blob = git("hash-object", "-w", "--stdin", stdin=text)
    full = git("mktree", "--missing", stdin=f"040000 tree {git('rev-parse', f'{tree}:data')}\tdata\n100644 blob {blob}\t{POINTER}\n")
    top = git("commit-tree", full, "-p", data_commit, "-m", f"Apunta el respaldo a {data_commit[:8]}")
    git("push", "origin", f"{top}:refs/heads/{BRANCH}")
    print(f"Publica data/ de main@{main[:7]}: datos en {data_commit[:8]}, {size / 1048576:.2f} MB.")
    return data_commit, blob, True


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def cdn_state(ref: str, path: str) -> str:
    """Hash del archivo que sirve jsDelivr en esa referencia, o la falla como texto."""
    try:
        return blob_sha(fetch(f"{CDN}{ref}/{urllib.parse.quote(path)}"))
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except OSError as e:
        return f"sin respuesta: {e}"


def purge_pointer() -> int:
    """Purga el puntero. Devuelve los segundos que faltan para poder purgar otra vez, si jsDelivr la limitó."""
    try:
        answer = json.loads(fetch(f"{PURGE}{BRANCH}/{POINTER}"))
    except (OSError, ValueError) as e:
        print(f"Purga fallida: {e}")
        return 0
    limits = [p.get("throttlingReset", 0) for p in answer.get("paths", {}).values() if p.get("throttled")]
    if limits:
        print(f"jsDelivr limitó la purga: se libera en {limits[0]} s.")
    return limits[0] if limits else 0


def check_files(commit: str, expected: dict[str, str], waits=FILE_WAITS, state=cdn_state, sleep=time.sleep) -> dict[str, str]:
    """Revisa cada archivo por commit, sin caché de rama de por medio. Devuelve {ruta: estado} de lo que no coincide."""
    pending = dict(expected)
    for wait in waits:
        sleep(wait)
        pending = {p: s for p in pending if (s := state(commit, p)) != expected[p]}
        print(f"Archivos por commit: {len(expected) - len(pending)} de {len(expected)} correctos.")
        if not pending:
            break
    return pending


def sync_pointer(expected: str, new: bool, waits=POINTER_WAITS, limit=MAX_POINTER_SECONDS, state=cdn_state, purge_one=purge_pointer,
                 sleep=time.sleep) -> str | None:
    """Lleva el puntero servido al esperado. Devuelve None si queda al día, o el último estado visto.

    Una publicación nueva se purga siempre, aunque desde aquí se vea bien: otro nodo puede tener la copia vieja. Al
    verlo al día se purga una vez más, porque una purga anterior pudo llegar antes de que jsDelivr viera el commit.
    """
    pending_purge = new
    purged = False
    last = state(BRANCH, POINTER)
    elapsed = 0
    for wait in (*waits, None):
        current = last == expected
        if current and not pending_purge:
            print("Puntero al día.")
            return None
        reset = purge_one()
        if current and purged and reset:
            print("Puntero al día; jsDelivr limitó solo la purga de confirmación.")
            return None
        purged = purged or not reset
        pending_purge = not current or reset > 0
        if wait is None:
            break
        delay = max(wait, reset + 5)
        if elapsed + delay > limit:
            break
        sleep(delay)
        elapsed += delay
        last = state(BRANCH, POINTER)
        print(f"Puntero tras {elapsed} s: {'al día' if last == expected else last}.")
    return None if last == expected else last


def main() -> int:
    source = "origin/main"
    data_commit, pointer_sha, new = publish(source)
    expected = {path: sha for path, (sha, _) in list_blobs(light_tree(source)).items()}
    wrong = check_files(data_commit, expected)
    for path, state in sorted(wrong.items()):
        print(f"ERROR {path}: {state}, se esperaba {expected[path]}")
    if wrong:
        return 1
    behind = sync_pointer(pointer_sha, new)
    if behind is not None:
        print(f"ATRASADO {POINTER}: {behind}, se esperaba {pointer_sha}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
