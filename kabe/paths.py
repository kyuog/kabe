"""Rutas XDG de Kabe.

Todo lo que Kabe escribe vive bajo los directorios estándar:

    ~/.config/kabe      configuración (config.json, repos.json del usuario)
    ~/.cache/kabe       cachés: índice SQLite, miniaturas, ETag, descargas
    ~/.local/share/kabe datos: descargas de imágenes, registro de rotación
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    raw = os.environ.get(var, "").strip()
    if raw and os.path.isabs(raw):
        return Path(raw)
    return Path.home() / default


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def config_dir() -> Path:
    return config_home() / "kabe"


def cache_dir() -> Path:
    return cache_home() / "kabe"


def data_dir() -> Path:
    return data_home() / "kabe"


def config_file() -> Path:
    return config_dir() / "config.json"


def db_file() -> Path:
    return cache_dir() / "index.sqlite3"


def thumbs_dir() -> Path:
    return cache_dir() / "thumbs"


def sources_dir() -> Path:
    """Copias locales de las imágenes remotas (se reutilizan al aplicar)."""
    return cache_dir() / "sources"


def downloads_dir() -> Path:
    return data_dir() / "wallpapers"


def http_cache_dir() -> Path:
    return cache_dir() / "http"


def state_file() -> Path:
    return data_dir() / "state.json"


def locale_dir() -> Path:
    """Directorio con los catálogos .mo instalados."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here / "locale",                      # dentro del paquete
        here.parent / "share" / "locale",     # instalación desde el repo
        here.parent.parent / "share" / "locale",
        Path("/usr/share/kabe/locale"),       # paquete del sistema
        Path("/usr/share/locale"),
    ):
        if candidate.is_dir():
            return candidate
    return Path("/usr/share/locale")


def ensure_dirs() -> None:
    """Crea la estructura de directorios con permisos razonables."""
    for d in (config_dir(), cache_dir(), data_dir(), thumbs_dir(), downloads_dir(),
              http_cache_dir(), sources_dir()):
        d.mkdir(parents=True, exist_ok=True)
    # El token de GitHub viaja en config.json: nadie más debe leerlo.
    try:
        os.chmod(config_dir(), 0o700)
    except OSError:
        pass
