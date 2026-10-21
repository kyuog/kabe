"""Proveedor de carpetas locales: el usuario apunta a un directorio y Kabe
lo indexa como si fuera un repositorio más."""

from __future__ import annotations

import os
from typing import Iterable

from ..models import IMAGE_EXTS, KIND_IMAGE, KIND_VIDEO, VIDEO_EXTS, Repo, WallpaperItem
from .base import Provider
from .github import detect_aspect, detect_category


class LocalProvider(Provider):
    """Imágenes de una carpeta del disco."""

    id = "local"

    def __init__(self, folder: str, repo: Repo | None = None):
        self.folder = os.path.abspath(os.path.expanduser(folder))
        self.repo = repo or Repo(
            provider="local",
            owner="",
            name=os.path.basename(self.folder) or "local",
            branch="",
            folder=self.folder,
            license="",
            license_verified=False,
            tags=[],
            categories=[],
            author="local",
        )

    @property
    def name(self) -> str:
        return self.repo.name

    def list_items(self) -> list[WallpaperItem]:
        items: list[WallpaperItem] = []
        root = self.folder
        if not os.path.isdir(root):
            return items
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in sorted(filenames):
                ext = os.path.splitext(filename)[1].lower()
                if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                    continue
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, root)
                folder = os.path.dirname(rel)
                stem = os.path.splitext(filename)[0]
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                category = detect_category(rel)
                item = WallpaperItem(
                    provider="local",
                    repo_slug=root,
                    repo_owner="",
                    repo_name=self.repo.name,
                    repo_branch="",
                    path=full,
                    name=stem,
                    folder=folder,
                    kind=KIND_VIDEO if ext in VIDEO_EXTS else "image",
                    tags=_unique([category] + [p.lower() for p in stem.replace("-", " ").split()]),
                    ext=ext,
                    url=full,
                    page_url=full,
                    blob_url=full,
                    license="",
                    license_verified=False,
                    author="local",
                    bytes=size,
                    aspect=detect_aspect(stem),
                )
                items.append(item)
        return items

    def media_url(self, item: WallpaperItem) -> str:
        return item.path

    def page_url(self, item: WallpaperItem) -> str:
        return item.path


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
