"""Cliente HTTP de Kabe: urllib estándar, ETag, token opcional, descargas
cancelables en segundo plano y respeto de los límites de la API de GitHub.

No usa requests: la biblioteca estándar cubre todo lo que necesitamos y
evita una dependencia más en sistemas modestos.
"""

from __future__ import annotations

import gzip
import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import paths
from .util import short_hash

USER_AGENT = "kabe-wallpaper/0.1 (+https://github.com/kabe-app)"
GITHUB_API = "https://api.github.com"


class HttpError(Exception):
    """Error de red con contexto suficiente para mostrarlo en la UI."""

    def __init__(self, message: str, status: int = 0, url: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.url = url


class Cancelled(Exception):
    """La operación se canceló a petición del usuario."""


@dataclass
class RateLimit:
    """Estado del cupo de la API de GitHub."""

    limit: int = 60
    remaining: int = 60
    reset: int = 0
    authenticated: bool = False

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    @property
    def reset_in(self) -> int:
        return max(0, self.reset - int(time.time()))


class HttpClient:
    """Cliente HTTP pequeño y reutilizable."""

    def __init__(self, token: str = "", timeout: int = 20, retries: int = 2):
        self.token = (token or "").strip()
        self.timeout = timeout
        self.retries = retries
        self.rate_limit = RateLimit(authenticated=bool(self.token))
        self._local = threading.local()
        self._cache_dir = paths.http_cache_dir()

    # ------------------------------------------------------------- internos
    def _opener(self) -> urllib.request.OpenerDirector:
        opener = getattr(self._local, "opener", None)
        if opener is None:
            ctx = ssl.create_default_context()
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ctx),
                urllib.request.HTTPRedirectHandler(),
            )
            self._local.opener = opener
        return opener

    def _headers(self, extra: dict[str, str] | None = None, token: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
        }
        if token and self.token:
            headers["Authorization"] = f"token {self.token}"
        if extra:
            headers.update(extra)
        return headers

    def _update_rate_limit(self, headers: Any) -> None:
        try:
            remaining = headers.get("X-RateLimit-Remaining")
            limit = headers.get("X-RateLimit-Limit")
            reset = headers.get("X-RateLimit-Reset")
        except AttributeError:
            return
        if remaining is not None:
            self.rate_limit.remaining = int(remaining)
        if limit is not None:
            self.rate_limit.limit = int(limit)
        if reset is not None:
            self.rate_limit.reset = int(reset)

    # --------------------------------------------------------------- public
    def get_json(
        self,
        url: str,
        token: bool = False,
        use_cache: bool = True,
        cancel: threading.Event | None = None,
    ) -> tuple[Any, bool]:
        """Devuelve (datos, desde_cache).

        Usa If-None-Match con el ETag guardado en disco: si GitHub responde
        304 no gastamos cuota y devolvemos el cuerpo cacheado.
        """
        cache_path = self._cache_path(url)
        etag = ""
        if use_cache and os.path.exists(cache_path):
            etag = self._read_meta(cache_path).get("etag", "")

        headers = self._headers({"Accept": "application/vnd.github+json"}, token=token)
        if etag:
            headers["If-None-Match"] = etag

        req = urllib.request.Request(url, headers=headers, method="GET")
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            _check_cancel(cancel)
            try:
                with self._opener().open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    self._update_rate_limit(resp.headers)
                    body = _decode(raw, resp.headers.get("Content-Encoding"))
                    try:
                        data = json.loads(body.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise HttpError("Respuesta ilegible del servidor", 0, url) from exc
                    if use_cache:
                        self._write_cache(cache_path, data, resp.headers.get("ETag", ""))
                    return data, False
            except urllib.error.HTTPError as exc:
                self._update_rate_limit(exc.headers)
                if exc.code == 304 and use_cache and os.path.exists(cache_path):
                    return self._read_cache(cache_path), True
                if exc.code in (403, 429):
                    raise HttpError(
                        "Límite de la API alcanzado. Añade un token de GitHub en Preferencias "
                        "o espera a que se reinicie el cupo.",
                        exc.code,
                        url,
                    ) from exc
                if exc.code == 404:
                    raise HttpError("No encontrado (404)", exc.code, url) from exc
                last_exc = exc
            except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError) as exc:
                last_exc = exc
            if attempt < self.retries:
                time.sleep(0.6 * (attempt + 1))

        message = getattr(last_exc, "reason", None) or str(last_exc) or "error de red"
        raise HttpError(f"Sin conexión ({message})", 0, url)

    def get_bytes(
        self,
        url: str,
        start: int = 0,
        end: int | None = None,
        timeout: int | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        """Petición de rango (Range). Sirve para leer la cabecera de un JPEG/PNG
        sin descargarse la imagen completa.

        Si el servidor ignora el Range, se corta la lectura en el tamaño
        pedido: nunca se descarga un fondo de 4K para mirar sus primeros
        bytes.
        """
        headers = self._headers()
        limit: int | None = None
        if end is None and start == 0:
            pass
        else:
            end = end if end is not None else start
            headers["Range"] = f"bytes={start}-{end}"
            limit = max(1, end - start + 1)
        req = urllib.request.Request(url, headers=headers, method="GET")
        with self._opener().open(req, timeout=timeout or self.timeout) as resp:
            data = resp.read(limit) if limit else resp.read()
            meta = {k.lower(): v for k, v in resp.headers.items()}
            return data, meta

    def download(
        self,
        url: str,
        dest_path: str,
        progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
        timeout: int = 60,
    ) -> int:
        """Descarga a disco. Devuelve los bytes escritos."""
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        headers = self._headers()
        req = urllib.request.Request(url, headers=headers, method="GET")
        written = 0
        tmp = dest_path + ".part"
        with self._opener().open(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            with open(tmp, "wb") as fh:
                while True:
                    _check_cancel(cancel)
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total)
        os.replace(tmp, dest_path)
        return written

    def download_bytes(
        self, url: str, cancel: threading.Event | None = None, timeout: int = 30
    ) -> bytes:
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        with self._opener().open(req, timeout=timeout) as resp:
            return resp.read()

    # --------------------------------------------------------------- caché
    def _cache_path(self, url: str) -> str:
        os.makedirs(self._cache_dir, exist_ok=True)
        return os.path.join(self._cache_dir, short_hash(url, 24) + ".json")

    def _read_meta(self, path: str) -> dict[str, Any]:
        try:
            with open(path + ".meta", "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _write_cache(self, path: str, data: Any, etag: str) -> None:
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, path)
            with open(path + ".meta", "w", encoding="utf-8") as fh:
                json.dump({"etag": etag, "fetched_at": int(time.time())}, fh)
        except OSError:
            pass

    def _read_cache(self, path: str) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def cache_age(self, url: str) -> float:
        """Antigüedad del cuerpo cacheado en segundos (inf si no hay)."""
        meta = self._read_meta(self._cache_path(url))
        fetched = meta.get("fetched_at")
        if not fetched:
            return float("inf")
        return time.time() - float(fetched)

    def cached_json(self, url: str) -> Any:
        """Cuerpo cacheado en disco (o None). No hace peticiones."""
        return self._read_cache(self._cache_path(url))

    def drop_cache(self, url: str) -> None:
        path = self._cache_path(url)
        for suffix in ("", ".meta"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


def _decode(raw: bytes, encoding: str | None) -> bytes:
    if encoding == "gzip":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def github_repo_url(owner: str, name: str) -> str:
    return f"https://github.com/{owner}/{name}"


def github_raw_url(owner: str, name: str, branch: str, path: str) -> str:
    quoted = urllib.parse.quote(path)
    return f"https://raw.githubusercontent.com/{owner}/{name}/{urllib.parse.quote(branch)}/{quoted}"


def github_blob_url(owner: str, name: str, branch: str, path: str) -> str:
    quoted = urllib.parse.quote(path)
    return f"https://raw.githubusercontent.com/{owner}/{name}/{urllib.parse.quote(branch)}/{quoted}"
