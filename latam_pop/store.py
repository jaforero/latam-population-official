"""Almacén de archivos crudos: data/raw/<iso3>/<raw_key>/<fecha>_<sha12>_<nombre> + .meta.json."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawFile:
    path: Path
    sha256: str
    retrieved_at: str
    url: str
    retrieved_by: str  # script | manual


class RawStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _dir(self, iso3: str, key: str) -> Path:
        return self.root / iso3 / key

    def latest(self, iso3: str, key: str) -> RawFile | None:
        d = self._dir(iso3, key)
        metas = sorted(d.glob("*.meta.json")) if d.exists() else []
        if not metas:
            return None
        m = json.loads(metas[-1].read_text(encoding="utf8"))
        return RawFile(d / m["file"], m["sha256"], m["retrieved_at"], m["url"], m["retrieved_by"])

    def save(self, iso3: str, key: str, name: str, content: bytes, url: str,
             retrieved_by: str = "script", today: str | None = None) -> RawFile:
        """Guarda solo si el hash cambió; si no, devuelve el archivo vigente con su fecha original."""
        sha = hashlib.sha256(content).hexdigest()
        cur = self.latest(iso3, key)
        if cur and cur.sha256 == sha:
            return cur
        today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
        d = self._dir(iso3, key)
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\-]", "_", name, flags=re.ASCII) or "file"
        fname = f"{today}_{sha[:12]}_{safe}"
        (d / fname).write_bytes(content)
        meta = dict(file=fname, sha256=sha, bytes=len(content), retrieved_at=today, url=url, retrieved_by=retrieved_by)
        (d / f"{fname}.meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
        return RawFile(d / fname, sha, today, url, retrieved_by)
