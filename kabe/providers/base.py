"""Proveedores de fondos.

Un proveedor sabe listar imágenes y decir de dónde vienen. La galería no
sabe (ni necesita saber) si son de GitHub, de una carpeta local o del futuro
Wallhaven: sólo consume la interfaz `Provider`.
"""

from __future__ import annotations

import abc

from ..models import WallpaperItem


class Provider(abc.ABC):
    """Interfaz común de cualquier fuente de fondos."""

    id: str = "base"
    name: str = "Base"

    @abc.abstractmethod
    def list_items(self) -> list[WallpaperItem]:
        """Devuelve el catálogo completo de la fuente."""

    @abc.abstractmethod
    def media_url(self, item: WallpaperItem) -> str:
        """URL directa al archivo de imagen."""

    def page_url(self, item: WallpaperItem) -> str:
        """URL donde el usuario puede ver la ficha y la licencia."""
        return ""

    def license_of(self, item: WallpaperItem) -> str:
        return item.license or "licencia no verificada"

    def author_of(self, item: WallpaperItem) -> str:
        return item.author
