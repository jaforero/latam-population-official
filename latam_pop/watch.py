"""Vigilancia de portales: avisa si cambian los enlaces relevantes. No modifica datos."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

from .http import FetchError, Http
from .validate import alert


def link_digest(html: str, base: str, pattern: str) -> str:
    links = {urljoin(base, h) for h in re.findall(r'href=["\']([^"\'#]+)', html)}
    hits = sorted(u for u in links if re.search(pattern, u, re.I))
    return hashlib.sha256("\n".join(hits).encode()).hexdigest()


def run_watch(items: list[dict], http: Http, state: dict) -> tuple[dict, list[dict]]:
    alerts, new = [], dict(state)
    for w in items:
        try:
            digest = link_digest(http.get(w["url"]).decode("utf8", "ignore"), w["url"], w["pattern"])
        except FetchError:
            new.setdefault(w["url"], "unreachable")
            continue
        old = state.get(w["url"])
        if old and old != digest:
            what = "Volvió a responder" if old == "unreachable" else "Cambió"
            alerts.append(alert("watch_change", w["iso3"], f"{what} el portal {w['url']}: {w['reason']}", digest=digest))
        new[w["url"]] = digest
    return new, alerts
