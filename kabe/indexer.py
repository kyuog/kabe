"""Indexador: mantiene el catálogo de fondos al día.

Por cada repositorio hace UNA petición al API de Git Trees (con ETag para no
gastar cuota) y guarda el resultado en el índice SQLite. Nunca clona nada.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import repos as repos_mod
from .db import Database
from .models import Repo
from .net import HttpClient, HttpError
from .providers.github import GitHubProvider
from .providers.local import LocalProvider

ProgressFn = Callable[[str, int, int], None]


@dataclass
class SyncReport:
    """Resultado de una sincronización."""

    repos_ok: int = 0
    repos_failed: int = 0
    repos_cached: int = 0
    items_total: int = 0
    errors: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.repos_failed == 0 and not self.errors


class Indexer:
    """Sincroniza repos.json (paquete + usuario) con el índice local."""

    def __init__(self, db: Database, http: HttpClient, ttl_hours: int = 12):
        self.db = db
        self.http = http
        self.ttl_hours = ttl_hours
        self.cancel = threading.Event()

    def stop(self) -> None:
        self.cancel.set()

    # ------------------------------------------------------------------ API
    def sync(self, progress: Optional[ProgressFn] = None, force: bool = False,
             network: bool = False) -> SyncReport:
        """Sincroniza el catálogo.

        `force`  reconstruye el índice aunque los datos estén al día.
        `network` fuerza la petición a GitHub (por defecto se reutiliza la
        copia en disco del árbol, que no gasta cuota).
        """
        report = SyncReport()
        catalog = repos_mod.load_repos()
        total = len(catalog)
        for index, repo in enumerate(catalog):
            if self.cancel.is_set():
                break
            if progress:
                progress(repo.slug, index, total)
            try:
                count = self.sync_repo(repo, force=force, network=network)
            except HttpError as exc:
                report.repos_failed += 1
                report.errors.append(f"{repo.slug}: {exc.message}")
                continue
            except Exception as exc:  # pragma: no cover
                report.repos_failed += 1
                report.errors.append(f"{repo.slug}: {exc}")
                continue
            if count is None:
                report.repos_cached += 1
            else:
                report.repos_ok += 1
                report.items_total += count
        self.db.clean_orphans()
        self.db.mark_duplicates()
        if force:
            self.db.compact()
        return report

    def sync_repo(self, repo: Repo, force: bool = False,
                  network: bool = False) -> Optional[int]:
        """Sincroniza un repo. Devuelve el nº de imágenes o None si estaba al día."""
        if repo.provider == "local":
            return self._sync_local(repo)

        row = self.db.find_repo(repo.owner, repo.name, repo.folder)
        fresh = (
            row is not None
            and row.tree_fetched_at
            and (time.time() - row.tree_fetched_at) < self.ttl_hours * 3600
            and self.db.item_count(row.id) > 0
        )
        if fresh and not force:
            return None

        repo_id = self.db.upsert_repo(repo)
        provider = GitHubProvider(repo, self.http, cancel=self.cancel)
        # Si la copia del árbol en disco es reciente, no gastamos petición.
        max_age = 0.0 if network else self.ttl_hours * 3600
        items = provider.list_items(max_age_seconds=max_age)
        if provider.truncated:
            # El árbol no cabe en una respuesta: el repo es enorme. Se avisa
            # en el informe, pero se conserva lo indexado hasta ahora.
            pass
        self.db.replace_items(repo_id, items)
        self.db.set_repo_tree(
            repo_id,
            repo.tree_sha,
            repo.tree_etag,
            int(time.time()),
            len(items),
        )
        return len(items)

    def _sync_local(self, repo: Repo) -> int:
        repo_id = self.db.upsert_repo(repo)
        provider = LocalProvider(repo.folder, repo)
        items = provider.list_items()
        self.db.replace_items(repo_id, items)
        self.db.set_repo_tree(repo_id, "", "", int(time.time()), len(items))
        return len(items)

    # ------------------------------------------------------------- categorías
    def categories(self) -> list[str]:
        """Categorías presentes en el índice."""
        rows = self.db.conn.execute(
            "SELECT DISTINCT category FROM items WHERE category != ''"
        ).fetchall()
        return sorted(row["category"] for row in rows)


CATEGORY_VOCAB = {
    "anime", "ciudades", "naturaleza", "minimal", "arte", "cultura", "sistema", "mixto",
}
