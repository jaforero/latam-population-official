"""Descarga con agente identificado, TLS activo y respeto de robots.txt. Nunca elude bloqueos."""
from __future__ import annotations

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "latam-population-official/1.0 (+https://github.com/jaforero/latam-population-official)"
TIMEOUT = 180


class FetchError(Exception):
    pass


class BlockedError(FetchError):
    """El sitio no permite la descarga automática (robots.txt). Pasa a manual."""


class Http:
    def __init__(self, pause: float = 1.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.pause = pause
        self._robots: dict[str, RobotFileParser | None] = {}
        self._cache: dict[str, requests.Response] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            parser = None
            try:
                r = self.s.get(base + "/robots.txt", timeout=30)
                if r.status_code == 200 and "html" not in r.headers.get("content-type", "").lower():
                    parser = RobotFileParser()
                    parser.parse(r.text.splitlines())
            except requests.RequestException:
                parser = None
            self._robots[base] = parser
        parser = self._robots[base]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> bytes:
        if url in self._cache:
            return self._cache[url].content
        if not self.allowed(url):
            raise BlockedError(f"robots.txt prohíbe {url}")
        last = None
        for attempt in range(2):
            try:
                r = self.s.get(url, timeout=TIMEOUT)
                if r.status_code == 200:
                    self._cache[url] = r
                    time.sleep(self.pause)
                    return r.content
                last = f"HTTP {r.status_code}"
                if r.status_code in (401, 403, 404):
                    break
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {str(e)[:160]}"
            time.sleep(self.pause * (attempt + 1))
        raise FetchError(f"{last} en {url}")
