"""Proveedor de repositorios de GitHub.

No clona nada: pide el árbol completo al API de Git Trees (una petición por
repo) y descarga del raw.githubusercontent.com sólo lo que el usuario elige.
"""

from __future__ import annotations

import os
import posixpath
import threading
from typing import Iterable

from .. import net
from ..models import IMAGE_EXTS, KIND_IMAGE, KIND_VIDEO, VIDEO_EXTS, Repo, WallpaperItem
from ..util import keywords, normalize
from .base import Provider

# Palabras clave → categoría mostrada en la interfaz.
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("anime", ("anime", "waifu", "manga", "ghibli", "naruto", "onepiece", "dragonball",
               "pokemon", "genshin", "demon", "kiss", "yuri", "wallpaper-anime")),
    ("ciudades", ("city", "cities", "urban", "skyline", "street", "downtown",
                  "building", "buildings", "architecture", "cityscape", "tokyo",
                  "newyork", "new-york", "metropolis")),
    ("naturaleza", ("nature", "natural", "landscape", "forest", "mountain", "mountains",
                    "sea", "ocean", "water", "flower", "flowers", "trees", "sunset",
                    "sunrise", "river", "lake", "valley", "beach", "snow", "sky", "clouds")),
    ("minimal", ("minimal", "minimalist", "simple", "flat", "solid", "monochrome",
                 "monocolor", "monocolour", "plain", "wallpaper-minimal", "pastel",
                 "nord", "gruvbox", "catppuccin", "rose-pine", "rosepine", "nordic")),
    ("arte", ("art", "artwork", "abstract", "illustration", "digital", "painting",
              "paint", "ink", "graphic", "wallpaper-art", "surreal", "geometry")),
    ("cultura", ("culture", "japanese", "japan", "traditional", "retro", "vintage",
                 "cyberpunk", "vaporwave", "sci-fi", "fantasy", "aesthetic", "quotes",
                 "typography", "pattern", "patterns")),
    ("sistema", ("macos", "windows", "linux", "android", "iphone", "ios")),
]

RESOLUTION_HINTS = {
    "8k": 7680, "5k": 5120, "4k": 3840, "uhd": 3840, "2k": 2560, "qhd": 2560,
    "1440p": 2560, "1080p": 1920, "fhd": 1920, "hd": 1280, "ultrawide": 2560,
}


def detect_category(text: str) -> str:
    """Deduce la categoría a partir de una ruta o nombre."""
    low = normalize(text)
    for category, words in CATEGORY_RULES:
        for word in words:
            if word in low:
                return category
    return "mixto"


def detect_aspect(text: str) -> str:
    """Deduce la relación de aspecto a partir del nombre (p. ej. '21x9')."""
    import re
    low = normalize(text).replace(" ", "")
    match = re.search(r"(\d{1,2})[x×:](\d{1,2})", low)
    if match:
        a, b = int(match.group(1)), int(match.group(2))
        if 4 <= a <= 40 and 4 <= b <= 40:
            return f"{a}:{b}"
    if "ultrawide" in low or "21x9" in low or "3440" in low:
        return "21:9"
    if "portrait" in low or "vertical" in low:
        return "portrait"
    return ""


class GitHubProvider(Provider):
    """Catálogo de un repositorio de GitHub."""

    id = "github"

    def __init__(self, repo: Repo, http: net.HttpClient, cancel: threading.Event | None = None):
        self.repo = repo
        self.http = http
        self.cancel = cancel
        self.truncated = False

    @property
    def name(self) -> str:
        return f"{self.repo.owner}/{self.repo.name}"

    # ------------------------------------------------------------- catálogo
    def tree_url(self) -> str:
        owner = self.repo.owner
        name = self.repo.name
        branch = self.repo.branch or "main"
        return f"{net.GITHUB_API}/repos/{owner}/{name}/git/trees/{branch}?recursive=1"

    def list_items(self, max_age_seconds: float = 0.0) -> list[WallpaperItem]:
        """Catálogo del repo.

        Si `max_age_seconds` > 0 y la copia en disco del árbol es más nueva,
        se usa sin gastar una petición de la API.
        """
        url = self.tree_url()
        data = None
        if max_age_seconds > 0:
            age = self.http.cache_age(url)
            if age is not None and age < max_age_seconds:
                cached = self.http.cached_json(url)
                if isinstance(cached, dict):
                    data = cached
        if data is None:
            data, _from_cache = self.http.get_json(url, token=True, cancel=self.cancel)
        if not isinstance(data, dict):
            return []
        self.truncated = bool(data.get("truncated"))
        tree = data.get("tree") or []
        root = (self.repo.folder or "").strip("/")
        items: list[WallpaperItem] = []
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = entry.get("path") or ""
            if root and not (path == root or path.startswith(root + "/")):
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                continue
            rel = path[len(root) + 1:] if root and path.startswith(root + "/") else path
            items.append(self._make_item(rel, path, entry))
        return items

    def _make_item(self, rel_path: str, full_path: str, entry: dict) -> WallpaperItem:
        owner = self.repo.owner
        name = self.repo.name
        branch = self.repo.branch or "main"
        folder = posixpath.dirname(rel_path)
        base = posixpath.basename(rel_path)
        stem = os.path.splitext(base)[0]
        ext = os.path.splitext(base)[1].lower()

        raw_url = net.github_raw_url(owner, name, branch, full_path)
        page = f"https://github.com/{owner}/{name}/blob/{branch}/{full_path}"

        tags = list(self.repo.tags)
        tags.extend(keywords(stem))
        top = folder.split("/")[0] if folder else ""
        if top:
            tags.append(top)
        category = detect_category(folder or stem) if folder else detect_category(stem)
        if category == "mixto" and self.repo.categories:
            category = self.repo.categories[0]

        size = int(entry.get("size") or 0)
        is_video = ext in VIDEO_EXTS
        item = WallpaperItem(
            provider="github",
            repo_slug=f"{owner}/{name}",
            repo_owner=owner,
            repo_name=name,
            repo_branch=branch,
            path=full_path,
            name=stem,
            folder=folder,
            category=category,
            kind=KIND_VIDEO if is_video else KIND_IMAGE,
            tags=_unique([t for t in tags if t])[:24],
            ext=ext,
            url=raw_url,
            page_url=page,
            blob_url=raw_url,
            license=self.repo.license,
            license_verified=self.repo.license_verified,
            author=self.repo.author or owner,
            bytes=size,
            blob_sha=entry.get("sha") or "",
            aspect=detect_aspect(stem),
        )
        item.tags = _unique([t for t in item.tags if t])
        if category:
            item.tags = [category] + [t for t in item.tags if t != category]
        item.category = category
        return item

    # ---------------------------------------------------------------- urls
    def media_url(self, item: WallpaperItem) -> str:
        return item.url

    def page_url(self, item: WallpaperItem) -> str:
        return item.page_url

    def license_of(self, item: WallpaperItem) -> str:
        return self.repo.license_label


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        low = item.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(item)
    return out
