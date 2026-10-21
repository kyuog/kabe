"""Miniaturas: bajo demanda, con caché en disco y tope en memoria.

Reglas del proyecto:
  - sólo se cargan las miniaturas visibles;
  - se reducen a ~300 px con GdkPixbuf;
  - como mucho 60 miniaturas vivas en RAM (LRU);
  - al salir de pantalla se liberan.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Optional

from . import paths
from .util import short_hash

try:
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    HAVE_GDK = True
except (ImportError, ValueError):  # pragma: no cover
    HAVE_GDK = False


class Thumbnailer:
    """Caché de miniaturas en disco + LRU en memoria."""

    def __init__(self, size: int = 300, memory_limit: int = 60, cache_dir: str | None = None):
        self.size = size
        self.memory_limit = max(8, memory_limit)
        self.cache_dir = cache_dir or str(paths.thumbs_dir())
        self._memory: "OrderedDict[str, object]" = OrderedDict()
        self._lock = threading.RLock()
        os.makedirs(self.cache_dir, exist_ok=True)

    # ---------------------------------------------------------------- paths
    def cache_path(self, key: str) -> str:
        name = short_hash(f"{key}|{self.size}", 24)
        return os.path.join(self.cache_dir, name + ".jpg")

    # -------------------------------------------------------------- memoria
    def get_cached(self, key: str):
        """Miniatura ya presente en memoria (o None)."""
        with self._lock:
            pixbuf = self._memory.get(key)
            if pixbuf is not None:
                self._memory.move_to_end(key)
            return pixbuf

    def put_memory(self, key: str, pixbuf) -> None:
        with self._lock:
            self._memory[key] = pixbuf
            self._memory.move_to_end(key)
            while len(self._memory) > self.memory_limit:
                _key, old = self._memory.popitem(last=False)
                del old

    def release(self, keys: list[str]) -> None:
        """Libera las miniaturas que ya no se ven."""
        with self._lock:
            for key in keys:
                self._memory.pop(key, None)

    def clear_memory(self) -> None:
        with self._lock:
            self._memory.clear()

    @property
    def memory_count(self) -> int:
        with self._lock:
            return len(self._memory)

    # ---------------------------------------------------------------- disco
    def disk_path(self, key: str) -> str:
        return self.cache_path(key)

    def has_disk(self, key: str) -> bool:
        return os.path.exists(self.cache_path(key))

    def load_from_disk(self, key: str):
        path = self.cache_path(key)
        if not os.path.exists(path) or not HAVE_GDK:
            return None
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except Exception:
            return None
        self.put_memory(key, pixbuf)
        return pixbuf

    def save_from_file(self, key: str, image_path: str) -> Optional[str]:
        """Escala una imagen local a la miniatura y la guarda en disco."""
        pixbuf = self.load_scaled(image_path)
        if pixbuf is None:
            return None
        out = self.cache_path(key)
        try:
            pixbuf.savev(out, "jpeg", ["quality"], ["82"])
        except Exception:
            return None
        self.put_memory(key, pixbuf)
        return out

    def load_scaled(self, image_path: str, size: int | None = None):
        """Carga una imagen ya reducida.

        Se usa el cargador con `set_size()`: el JPEG se decodifica directamente
        al tamaño final y el PNG se decodifica por partes, así que una imagen
        4K no ocupa 30 MB de memoria sólo para sacar su miniatura.
        """
        if not HAVE_GDK:
            return None
        target = size or self.size
        loader = GdkPixbuf.PixbufLoader()
        try:
            loader.set_size(target, target)
            with open(image_path, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    loader.write(chunk)
            loader.close()
        except Exception:
            return None
        return loader.get_pixbuf()

    def save_from_bytes(self, key: str, data: bytes) -> Optional[str]:
        if not HAVE_GDK:
            return None
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
        except Exception:
            return None
        if pixbuf is None:
            return None
        scaled = pixbuf.scale_simple(
            self.size, max(1, int(self.size * pixbuf.get_height() / max(1, pixbuf.get_width()))),
            GdkPixbuf.InterpType.BILINEAR,
        )
        if scaled is None:
            scaled = pixbuf
        out = self.cache_path(key)
        try:
            scaled.savev(out, "jpeg", ["quality"], ["82"])
        except Exception:
            return None
        self.put_memory(key, scaled)
        return out

    def enforce_disk_limit(self, max_mb: int) -> int:
        """Borra las miniaturas más antiguas hasta estar dentro del límite."""
        return prune_directory(self.cache_dir, max_mb)


def prune_directory(directory: str, max_mb: int) -> int:
    """Borrado LRU por fecha de acceso. Devuelve los bytes liberados.

    Recorre también los subdirectorios (la caché de fuentes guarda un
    directorio por imagen).
    """
    if not os.path.isdir(directory) or max_mb <= 0:
        return 0
    limit = max_mb * 1024 * 1024
    entries: list[tuple[float, int, str]] = []
    total = 0
    for root, _dirs, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            total += stat.st_size
            entries.append((stat.st_atime, stat.st_size, path))
    if total <= limit:
        return 0
    entries.sort()
    freed = 0
    for _atime, size, path in entries:
        if total - freed <= limit:
            break
        try:
            os.unlink(path)
            freed += size
        except OSError:
            continue
    # Recoge los directorios que se quedaron vacíos.
    for root, dirs, files in os.walk(directory, topdown=False):
        if root != directory and not dirs and not files:
            try:
                os.rmdir(root)
            except OSError:
                pass
    return freed
