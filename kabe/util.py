"""Utilidades pequeñas sin dependencias externas."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import unicodedata
from typing import Iterable

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def strip_accents(text: str) -> str:
    """Quita tildes: 'Ñandú' -> 'Nandu'."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y sin signos: base de la búsqueda tolerante."""
    return strip_accents(text or "").lower()


def keywords(text: str) -> list[str]:
    """Trocea un nombre de archivo en palabras útiles."""
    base = os.path.splitext(os.path.basename(text or ""))[0]
    base = re.sub(r"[-_.\s]+", " ", base)
    base = strip_accents(base).lower()
    out: list[str] = []
    for word in base.split():
        word = word.strip()
        if len(word) < 2 or word.isdigit():
            continue
        out.append(word)
    return out


def short_hash(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:length]


def human_size(num: float) -> str:
    """Tamaño en lenguaje humano: '3,4 MB'."""
    if num < 1024:
        return f"{int(num)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        num /= 1024.0
        if num < 1024 or unit == "TB":
            if num >= 10:
                return f"{num:.0f} {unit}"
            return f"{num:.1f}".replace(".", ",") + f" {unit}"
    return f"{num:.1f} TB"


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def free_space(path: str) -> int:
    try:
        usage = shutil.disk_usage(path)
        return usage.free
    except OSError:
        return 0


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        low = item.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(item)
    return out


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", normalize(text)).strip("-")


def trim_memory() -> None:
    """Devuelve al sistema la memoria libre del heap (glibc).

    Al decodificar una imagen grande, GdkPixbuf reserva decenas de MB que
    luego quedan en caché del allocator. Con malloc_trim el RSS baja de
    golpe en vez de quedarse en el pico.
    """
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
