"""Modelos de datos de Kabe (dataclasses puras, sin dependencias de GTK)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jfif", ".jxl",
}

# Extensiones de vídeo: pueden aplicarse como fondo animado.
VIDEO_EXTS = {
    ".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".gifv", ".mp4v",
}

# Extensiones que sabemos leer con GdkPixbuf en la mayoría de sistemas.
PREVIEW_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".jfif"}

KIND_IMAGE = "image"
KIND_VIDEO = "video"

RESOLUTION_UNKNOWN = "unknown"
RESOLUTION_KNOWN = "known"
RESOLUTION_FAILED = "failed"


@dataclass
class Repo:
    """Repositorio de wallpapers indexado desde GitHub (o carpeta local)."""

    id: Optional[int] = None
    provider: str = "github"
    owner: str = ""
    name: str = ""
    branch: str = "main"
    folder: str = ""            # subcarpeta dentro del repo ("" = raíz)
    license: str = ""
    license_verified: bool = False
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    author: str = ""
    homepage: str = ""
    enabled: bool = True
    added_at: int = 0
    tree_sha: str = ""
    tree_etag: str = ""
    tree_fetched_at: int = 0
    item_count: int = 0

    @property
    def slug(self) -> str:
        if self.provider == "github":
            return f"{self.owner}/{self.name}"
        return self.name or self.folder

    @property
    def license_label(self) -> str:
        """Texto de licencia listo para la interfaz."""
        if self.license_verified and self.license:
            return self.license
        return "licencia no verificada"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WallpaperItem:
    """Una imagen del catálogo (remota o local)."""

    id: Optional[int] = None
    provider: str = "github"
    repo_id: Optional[int] = None
    repo_slug: str = ""
    repo_owner: str = ""
    repo_name: str = ""
    repo_branch: str = "main"
    path: str = ""              # ruta dentro del repo, o ruta absoluta (local)
    name: str = ""
    folder: str = ""
    category: str = ""
    kind: str = KIND_IMAGE      # image | video
    duration: int = 0           # duración del vídeo en segundos
    tags: list[str] = field(default_factory=list)
    ext: str = ""
    url: str = ""               # URL directa al binario
    page_url: str = ""          # URL de la ficha en GitHub
    blob_url: str = ""          # API blob (permite Range y tamaño)
    license: str = ""
    license_verified: bool = False
    author: str = ""
    bytes: int = 0
    width: int = 0
    height: int = 0
    aspect: str = ""            # relación de aspecto cacheada ("16:9")
    resolution_status: str = RESOLUTION_UNKNOWN
    resolution_checked_at: int = 0
    blob_sha: str = ""
    added_at: int = 0
    downloaded_path: str = ""
    is_favorite: bool = False
    is_downloaded: bool = False

    # -------------------------------------------------------------- helpers
    @property
    def ratio(self) -> float:
        if self.width and self.height:
            return self.width / self.height
        return 0.0

    @property
    def megapixels(self) -> float:
        return (self.width * self.height) / 1_000_000 if self.width and self.height else 0.0

    @property
    def resolution_label(self) -> str:
        """Etiqueta corta de resolución: 4K, 5K, 8K, 1440p…"""
        w, h = self.width, self.height
        if not w or not h:
            return "?" if self.kind != KIND_VIDEO else "vídeo"
        long_side = max(w, h)
        short_side = min(w, h)
        if long_side >= 7680:
            return "8K"
        if long_side >= 5120:
            return "5K"
        if long_side >= 3840:
            return "4K"
        if long_side >= 2560:
            return "QHD"
        if long_side >= 1920:
            return "FHD"
        if long_side >= 1280:
            return "HD"
        return f"{w}×{h}"

    @property
    def is_video(self) -> bool:
        return self.kind == KIND_VIDEO

    @property
    def duration_label(self) -> str:
        from .video import format_duration
        return format_duration(self.duration) if self.duration else ""

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return ""
        if self.width > self.height * 1.02:
            return "landscape"
        if self.height > self.width * 1.02:
            return "portrait"
        return "square"

    @property
    def aspect_label(self) -> str:
        """Relación de aspecto reducida (16:9, 21:9…)."""
        if not self.width or not self.height:
            return ""
        from math import gcd
        g = gcd(self.width, self.height)
        w, h = self.width // g, self.height // g
        if w > 32 or h > 32:
            return f"{self.width}:{self.height}"
        return f"{w}:{h}"

    def keyword_blob(self) -> str:
        """Texto indexado: ruta + carpetas + nombre + etiquetas."""
        parts = [self.name.replace("_", " ").replace("-", " ")]
        if self.folder:
            parts.append(self.folder.replace("/", " "))
        parts.extend(self.tags)
        return " ".join(p for p in parts if p)


@dataclass
class Monitor:
    """Monitor detectado."""

    name: str = ""             # nombre técnico: HDMI-1, DP-2…
    label: str = ""            # nombre comercial si se conoce
    backend: str = ""          # xrandr, wlr-randr, hyprctl, gdk…
    width: int = 0
    height: int = 0
    refresh: float = 0.0       # Hz
    scale: float = 1.0
    x: int = 0
    y: int = 0
    rotation: int = 0          # 0 normal, 90, 180, 270
    primary: bool = False
    connected: bool = True
    physical_mm: tuple[int, int] = (0, 0)

    @property
    def ratio(self) -> float:
        return (self.width / self.height) if self.height else 0.0

    @property
    def effective_width(self) -> int:
        return int(self.width * self.scale)

    @property
    def effective_height(self) -> int:
        return int(self.height * self.scale)

    @property
    def orientation(self) -> str:
        if self.width > self.height:
            return "landscape"
        if self.height > self.width:
            return "portrait"
        return "square"

    @property
    def resolution_label(self) -> str:
        return f"{self.width}×{self.height}"

    @property
    def refresh_label(self) -> str:
        return f"{self.refresh:.0f} Hz" if self.refresh else ""


@dataclass
class MonitorLayout:
    """Conjunto de monitores con su disposición en el escritorio."""

    monitors: list[Monitor] = field(default_factory=list)
    backend: str = ""
    error: str = ""

    def __iter__(self):
        return iter(self.monitors)

    def __len__(self) -> int:
        return len(self.monitors)

    @property
    def total_width(self) -> int:
        if not self.monitors:
            return 0
        return max(m.x + m.effective_width for m in self.monitors)

    @property
    def total_height(self) -> int:
        if not self.monitors:
            return 0
        return max(m.y + m.effective_height for m in self.monitors)

    @property
    def primary(self) -> Optional[Monitor]:
        for m in self.monitors:
            if m.primary:
                return m
        return self.monitors[0] if self.monitors else None


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS
