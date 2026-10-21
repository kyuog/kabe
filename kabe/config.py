"""Configuración persistente de Kabe (JSON plano, XDG)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict, field, fields
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "github_token": "",            # token personal opcional (hasta 5000 req/h)
    "min_width": 0,               # filtro manual de resolución mínima
    "min_height": 0,
    "match_monitor": True,        # mostrar sólo imágenes que cubran el monitor
    "thumb_size": 300,            # px del lado mayor de la miniatura
    "thumb_memory_limit": 24,     # miniaturas vivas en RAM
    "cache_limit_mb": 128,        # tope de caché en disco
    "index_ttl_hours": 12,        # caducidad del índice de repos en disco
    "sort": "relevance",          # relevance|recent|resolution|random
    "category": "",
    "repo": "",
    "aspect": "",                 # "", "16:9", "16:10", "21:9", "4:3", "3:2"
    "orientation": "",            # "", "landscape", "portrait", "square"
    "only_favorites": False,
    "only_downloaded": False,
    "rotation_enabled": False,
    "rotation_mode": "interval",  # interval|timeofday
    "rotation_interval_min": 60,
    "rotation_times": ["08:00", "13:00", "18:00", "22:00"],
    "rotation_playlists": [],     # ids de colecciones usadas por la rotación
    "rotation_apply_all": True,
    "wallpaper_style": "scaled",    # scaled|zoomed|centered|stretched|shrunk
    "wallpaper_backend": "",        # "" = detección automática
    "manual_resolution": "",        # "1920x1080" si la detección falla
    "tray_only": False,
    "start_in_tray": False,
    "close_to_tray": True,
    "language": "",
    "window_width": 1280,
    "window_height": 760,
}


@dataclass
class Config:
    github_token: str = ""
    min_width: int = 0
    min_height: int = 0
    match_monitor: bool = True
    thumb_size: int = 300
    thumb_memory_limit: int = 24
    cache_limit_mb: int = 128
    index_ttl_hours: int = 12
    sort: str = "relevance"
    category: str = ""
    repo: str = ""
    aspect: str = ""
    orientation: str = ""
    only_favorites: bool = False
    only_downloaded: bool = False
    rotation_enabled: bool = False
    rotation_mode: str = "interval"
    rotation_interval_min: int = 60
    rotation_times: list[str] = field(default_factory=list)
    rotation_playlists: list[int] = field(default_factory=list)
    rotation_apply_all: bool = True
    wallpaper_style: str = "scaled"
    wallpaper_backend: str = ""
    manual_resolution: str = ""
    tray_only: bool = False
    start_in_tray: bool = False
    close_to_tray: bool = True
    language: str = ""
    window_width: int = 1280
    window_height: int = 760

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            raw = json.loads(paths.config_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cfg
        if not isinstance(raw, dict):
            return cfg
        known = {f.name: f for f in fields(cls)}
        for key, value in raw.items():
            f = known.get(key)
            if f is None:
                continue
            try:
                setattr(cfg, key, _coerce(value, f.type))
            except (TypeError, ValueError):
                continue
        return cfg

    def save(self) -> None:
        paths.ensure_dirs()
        payload = asdict(self)
        target = paths.config_file()
        # Escritura atómica: un corte de luz no deja la config a medias.
        fd, tmp = tempfile.mkstemp(dir=str(paths.config_dir()), prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def set(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)


def _coerce(value: Any, typ: Any) -> Any:
    """Convierte valores del JSON al tipo declarado (best effort)."""
    text = typ if isinstance(typ, str) else getattr(typ, "__name__", "str")
    if text.startswith("bool"):
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")
    if text.startswith("int"):
        return int(value)
    if text.startswith("list"):
        if isinstance(value, list):
            return value
        return list(value)
    if text.startswith("str"):
        return "" if value is None else str(value)
    return value
