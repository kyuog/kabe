"""Catálogo de repositorios: carga, validación y sincronización con el índice.

`repos.json` vive junto al paquete (editable por el usuario) y se combina con
las fuentes que el usuario añade desde la interfaz, que se guardan en
~/.config/kabe/repos.json.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Iterable

from . import paths
from .models import Repo

PACKAGE_REPOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repos.json")
USER_REPOS = os.path.join(str(paths.config_dir()), "repos.json")

_GITHUB_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/\s]+)/(?P<name>[^/\s#?]+)(?:/.*)?$",
    re.IGNORECASE,
)


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Extrae (propietario, repositorio) de una URL de GitHub."""
    url = (url or "").strip()
    match = _GITHUB_RE.match(url)
    if not match:
        return None
    owner = match.group("owner")
    name = match.group("name").removesuffix(".git")
    if owner in ("", "sponsors", "orgs", "topics", "search"):
        return None
    return owner, name


def load_repos() -> list[Repo]:
    """Repos del paquete + repos del usuario (sin duplicados)."""
    repos: list[Repo] = []
    seen: set[tuple[str, str, str]] = set()

    for path in (PACKAGE_REPOS, USER_REPOS):
        for raw in _read_json(path):
            repo = repo_from_dict(raw)
            if repo is None:
                continue
            key = (repo.provider, repo.owner, repo.name, repo.folder)
            if key in seen:
                continue
            seen.add(key)
            repos.append(repo)
    return repos


def _read_json(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("repos", [])
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def repo_from_dict(raw: dict[str, Any]) -> Repo | None:
    provider = str(raw.get("provider") or "github")
    if provider == "local":
        folder = str(raw.get("folder") or "")
        if not folder:
            return None
        return Repo(
            provider="local",
            owner="",
            name=str(raw.get("name") or os.path.basename(folder)),
            branch="",
            folder=folder,
            license=str(raw.get("license") or ""),
            license_verified=bool(raw.get("license_verified", False)),
            tags=[str(t) for t in raw.get("tags", [])],
            categories=[str(c) for c in raw.get("categories", [])],
            author="local",
            enabled=bool(raw.get("enabled", True)),
            added_at=int(raw.get("added_at") or 0),
        )

    owner = str(raw.get("owner") or "")
    name = str(raw.get("name") or "")
    if not owner or not name:
        return None
    return Repo(
        provider="github",
        owner=owner,
        name=name,
        branch=str(raw.get("branch") or "main"),
        folder=str(raw.get("folder") or ""),
        license=str(raw.get("license") or ""),
        license_verified=bool(raw.get("license_verified", False)),
        tags=[str(t) for t in raw.get("tags", [])],
        categories=[str(c) for c in raw.get("categories", [])],
        author=str(raw.get("author") or owner),
        homepage=str(raw.get("homepage") or f"https://github.com/{owner}/{name}"),
        enabled=bool(raw.get("enabled", True)),
        added_at=int(raw.get("added_at") or 0),
    )


def add_user_repo(url: str, branch: str = "", folder: str = "") -> tuple[Repo | None, str]:
    """Añade un repositorio de GitHub a la configuración del usuario.

    Devuelve (repo, mensaje_de_error). El mensaje explica qué hacer.
    """
    parsed = parse_github_url(url)
    if not parsed:
        return None, "Esa dirección no parece un repositorio de GitHub. Usa el formato https://github.com/propietario/repositorio"
    owner, name = parsed

    existing = _read_json(USER_REPOS)
    for entry in existing:
        if entry.get("owner") == owner and entry.get("name") == name:
            return None, f"Ya tienes {owner}/{name} en la lista."

    entry = {
        "provider": "github",
        "owner": owner,
        "name": name,
        "branch": branch or "main",
        "folder": folder,
        "license": "",
        "license_verified": False,
        "categories": [],
        "tags": [],
        "added_at": int(time.time()),
        "note": "Añadido por el usuario; la licencia se verificará al actualizar el índice.",
    }
    existing.append(entry)
    _write_user_repos(existing)
    return repo_from_dict(entry), ""


def remove_user_repo(owner: str, name: str) -> bool:
    existing = _read_json(USER_REPOS)
    kept = [
        e for e in existing
        if not (e.get("owner") == owner and e.get("name") == name and e.get("provider") == "github")
    ]
    if len(kept) == len(existing):
        return False
    _write_user_repos(kept)
    return True


def _write_user_repos(entries: Iterable[dict[str, Any]]) -> None:
    paths.ensure_dirs()
    payload = {"version": 1, "repos": list(entries)}
    target = USER_REPOS
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, target)
