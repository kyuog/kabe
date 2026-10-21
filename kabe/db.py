"""Índice local de Kabe: SQLite con FTS5 (tokens exactos + trigramas).

Un solo archivo en ~/.cache/kabe/index.sqlite3. El índice guarda rutas,
nombres de carpeta, nombres de archivo y etiquetas de cada repo, de modo que
"anime/nezuko-night.png" se encuentra con anime, nezuko, night, nezuko night…
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional, Sequence

from . import paths
from .models import RESOLUTION_UNKNOWN, Repo, WallpaperItem
from .util import normalize

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS repos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    provider         TEXT    NOT NULL DEFAULT 'github',
    owner            TEXT    NOT NULL DEFAULT '',
    name             TEXT    NOT NULL DEFAULT '',
    branch           TEXT    NOT NULL DEFAULT 'main',
    folder           TEXT    NOT NULL DEFAULT '',
    license          TEXT    NOT NULL DEFAULT '',
    license_verified INTEGER NOT NULL DEFAULT 0,
    tags             TEXT    NOT NULL DEFAULT '',
    categories       TEXT    NOT NULL DEFAULT '',
    author           TEXT    NOT NULL DEFAULT '',
    homepage         TEXT    NOT NULL DEFAULT '',
    enabled          INTEGER NOT NULL DEFAULT 1,
    added_at         INTEGER NOT NULL DEFAULT 0,
    tree_sha         TEXT    NOT NULL DEFAULT '',
    tree_etag        TEXT    NOT NULL DEFAULT '',
    tree_fetched_at  INTEGER NOT NULL DEFAULT 0,
    item_count       INTEGER NOT NULL DEFAULT 0,
    UNIQUE(provider, owner, name, folder)
);

CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT    NOT NULL DEFAULT 'github',
    repo_id           INTEGER,
    repo_slug         TEXT    NOT NULL DEFAULT '',
    repo_owner        TEXT    NOT NULL DEFAULT '',
    repo_name         TEXT    NOT NULL DEFAULT '',
    repo_branch       TEXT    NOT NULL DEFAULT 'main',
    path              TEXT    NOT NULL,
    name              TEXT    NOT NULL DEFAULT '',
    folder            TEXT    NOT NULL DEFAULT '',
    category          TEXT    NOT NULL DEFAULT '',
    kind              TEXT    NOT NULL DEFAULT 'image',
    duplicate_of      INTEGER NOT NULL DEFAULT 0,
    duration          INTEGER NOT NULL DEFAULT 0,
    tags              TEXT    NOT NULL DEFAULT '',
    ext               TEXT    NOT NULL DEFAULT '',
    url               TEXT    NOT NULL DEFAULT '',
    page_url          TEXT    NOT NULL DEFAULT '',
    blob_url          TEXT    NOT NULL DEFAULT '',
    license           TEXT    NOT NULL DEFAULT '',
    license_verified  INTEGER NOT NULL DEFAULT 0,
    author            TEXT    NOT NULL DEFAULT '',
    bytes             INTEGER NOT NULL DEFAULT 0,
    width             INTEGER NOT NULL DEFAULT 0,
    height            INTEGER NOT NULL DEFAULT 0,
    aspect_cache      TEXT    NOT NULL DEFAULT '',
    res_status        TEXT    NOT NULL DEFAULT 'unknown',
    res_checked_at    INTEGER NOT NULL DEFAULT 0,
    blob_sha          TEXT    NOT NULL DEFAULT '',
    added_at          INTEGER NOT NULL DEFAULT 0,
    UNIQUE(provider, repo_id, path)
);
CREATE INDEX IF NOT EXISTS idx_items_repo   ON items(repo_id);
CREATE INDEX IF NOT EXISTS idx_items_folder ON items(folder);
CREATE INDEX IF NOT EXISTS idx_items_res    ON items(width, height);
CREATE INDEX IF NOT EXISTS idx_items_name   ON items(name);

CREATE TABLE IF NOT EXISTS favorites (
    item_id    INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS downloads (
    item_id       INTEGER PRIMARY KEY,
    path          TEXT NOT NULL DEFAULT '',
    bytes         INTEGER NOT NULL DEFAULT 0,
    downloaded_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL,
    item_id       INTEGER NOT NULL,
    added_at      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (collection_id, item_id)
);

CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER,
    applied_at INTEGER NOT NULL DEFAULT 0,
    monitor    TEXT NOT NULL DEFAULT '',
    ok         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS res_cache (
    url        TEXT PRIMARY KEY,
    width      INTEGER NOT NULL DEFAULT 0,
    height     INTEGER NOT NULL DEFAULT 0,
    ok         INTEGER NOT NULL DEFAULT 0,
    checked_at INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    tokens,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE VIRTUAL TABLE IF NOT EXISTS items_tri USING fts5(
    tokens,
    tokenize = "trigram"
);
"""


@dataclass
class SearchFilters:
    """Filtros combinables de la galería."""

    query: str = ""
    category: str = ""
    repo: str = ""
    min_width: int = 0
    min_height: int = 0
    aspect: str = ""
    orientation: str = ""
    only_favorites: bool = False
    only_downloaded: bool = False
    kind: str = ""              # "" (todos) | image | video
    match_monitor: bool = False
    monitor_width: int = 0
    monitor_height: int = 0
    monitor_ratio: float = 0.0
    tags: list[str] = field(default_factory=list)


class Database:
    """Acceso al índice. Seguro para usar desde varios hilos (una conexión
    por hilo mediante threading.local)."""

    def __init__(self, path: str | None = None):
        self.path = path or str(paths.db_file())
        self._local = threading.local()
        self._write_lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------- conexión
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _init_schema(self) -> None:
        with self._write_lock:
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()

    def _migrate(self) -> None:
        """Añade columnas nuevas a bases de datos de versiones anteriores."""
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(items)")}
        if "category" not in columns:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN category TEXT NOT NULL DEFAULT ''"
            )
        if "aspect_cache" not in columns:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN aspect_cache TEXT NOT NULL DEFAULT ''"
            )
        if "kind" not in columns:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN kind TEXT NOT NULL DEFAULT 'image'"
            )
        if "duration" not in columns:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN duration INTEGER NOT NULL DEFAULT 0"
            )
        if "duplicate_of" not in columns:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN duplicate_of INTEGER NOT NULL DEFAULT 0"
            )

    # ----------------------------------------------------------------- meta
    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value)
            )
            self.conn.commit()

    # ---------------------------------------------------------------- repos
    def upsert_repo(self, repo: Repo) -> int:
        """Inserta o actualiza un repositorio y devuelve su id real.

        Ojo: `lastrowid` no sirve aquí, porque un UPSERT que sólo actualiza
        lo deja a 0. Si se devolviera ese 0, los fondos se guardarían con un
        repo_id inexistente y aparecerían duplicados en la galería.
        """
        with self._write_lock:
            self.conn.execute(
                """
                INSERT INTO repos(provider, owner, name, branch, folder, license,
                                  license_verified, tags, categories, author, homepage,
                                  enabled, added_at, tree_sha, tree_etag, tree_fetched_at,
                                  item_count)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider, owner, name, folder) DO UPDATE SET
                    branch=excluded.branch, license=excluded.license,
                    license_verified=excluded.license_verified, tags=excluded.tags,
                    categories=excluded.categories, homepage=excluded.homepage,
                    enabled=excluded.enabled, tree_sha=excluded.tree_sha,
                    tree_etag=excluded.tree_etag,
                    tree_fetched_at=excluded.tree_fetched_at,
                    item_count=excluded.item_count
                """,
                (
                    repo.provider, repo.owner, repo.name, repo.branch, repo.folder,
                    repo.license, int(repo.license_verified),
                    " ".join(repo.tags), " ".join(repo.categories), repo.author,
                    repo.homepage, int(repo.enabled), repo.added_at or int(time.time()),
                    repo.tree_sha, repo.tree_etag, repo.tree_fetched_at, repo.item_count,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT id FROM repos WHERE provider=? AND owner=? AND name=? AND folder=?",
                (repo.provider, repo.owner, repo.name, repo.folder),
            ).fetchone()
        if row is None:  # pragma: no cover - sólo si alguien borra la fila a la vez
            raise sqlite3.IntegrityError(
                f"No se pudo guardar el repositorio {repo.owner}/{repo.name}"
            )
        return int(row["id"])

    def mark_duplicates(self) -> int:
        """Marca las imágenes repetidas (el mismo archivo en otro repo o
        bajo otro nombre). La galería muestra sólo una copia de cada una."""
        with self._write_lock:
            self.conn.execute("UPDATE items SET duplicate_of = 0")
            cur = self.conn.execute(
                """UPDATE items SET duplicate_of = (
                       SELECT MIN(i2.id) FROM items i2
                       WHERE i2.blob_sha != '' AND i2.blob_sha = items.blob_sha
                   )
                   WHERE blob_sha != ''
                     AND id != (SELECT MIN(i3.id) FROM items i3
                                WHERE i3.blob_sha = items.blob_sha)"""
            )
            count = self.conn.execute(
                "SELECT COUNT(*) c FROM items WHERE duplicate_of != 0"
            ).fetchone()["c"]
            self.conn.commit()
        return int(count)

    def clean_orphans(self) -> int:
        """Borra fondos cuyo repositorio ya no existe y elimina duplicados.

        Un repo_id huérfano (o un UPSERT mal resuelto) dejaba dos filas con
        la misma ruta: la misma imagen aparecía dos veces en la galería.
        """
        with self._write_lock:
            cur = self.conn.execute(
                "DELETE FROM items WHERE repo_id IS NOT NULL "
                "AND repo_id NOT IN (SELECT id FROM repos)"
            )
            removed = cur.rowcount or 0
            # Duplicados exactos: se queda la fila más reciente.
            self.conn.execute(
                "DELETE FROM items WHERE id NOT IN "
                "(SELECT MAX(id) FROM items GROUP BY provider, path)"
            )
            removed += self.conn.execute("SELECT changes()").fetchone()[0]
            self.conn.commit()
        if removed:
            self._rebuild_fts()
        return removed

    def list_repos(self, enabled_only: bool = False) -> list[Repo]:
        sql = "SELECT * FROM repos"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY owner, name"
        return [self._row_to_repo(r) for r in self.conn.execute(sql)]

    def get_repo(self, repo_id: int) -> Repo | None:
        row = self.conn.execute("SELECT * FROM repos WHERE id=?", (repo_id,)).fetchone()
        return self._row_to_repo(row) if row else None

    def find_repo(self, owner: str, name: str, folder: str = "") -> Repo | None:
        row = self.conn.execute(
            "SELECT * FROM repos WHERE provider='github' AND owner=? AND name=? AND folder=?",
            (owner, name, folder),
        ).fetchone()
        return self._row_to_repo(row) if row else None

    def set_repo_tree(self, repo_id: int, sha: str, etag: str, fetched_at: int, count: int) -> None:
        with self._write_lock:
            self.conn.execute(
                "UPDATE repos SET tree_sha=?, tree_etag=?, tree_fetched_at=?, item_count=? WHERE id=?",
                (sha, etag, fetched_at, count, repo_id),
            )
            self.conn.commit()

    def delete_repo(self, repo_id: int) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM items WHERE repo_id=?", (repo_id,))
            self.conn.execute("DELETE FROM repos WHERE id=?", (repo_id,))
            self.conn.commit()
        self._rebuild_fts()

    @staticmethod
    def _row_to_repo(row: sqlite3.Row) -> Repo:
        return Repo(
            id=row["id"], provider=row["provider"], owner=row["owner"], name=row["name"],
            branch=row["branch"], folder=row["folder"], license=row["license"],
            license_verified=bool(row["license_verified"]),
            tags=row["tags"].split() if row["tags"] else [],
            categories=row["categories"].split() if row["categories"] else [],
            author=row["author"], homepage=row["homepage"], enabled=bool(row["enabled"]),
            added_at=row["added_at"], tree_sha=row["tree_sha"], tree_etag=row["tree_etag"],
            tree_fetched_at=row["tree_fetched_at"], item_count=row["item_count"],
        )

    # ---------------------------------------------------------------- items
    def replace_items(self, repo_id: int, items: Sequence[WallpaperItem]) -> int:
        """Sustituye el catálogo de un repo y reconstruye su índice FTS."""
        with self._write_lock:
            self.conn.execute("DELETE FROM items WHERE repo_id=?", (repo_id,))
            ids = []
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO items(provider, repo_id, repo_slug, repo_owner,
                    repo_name, repo_branch, path, name, folder, category, kind, duration,
                    tags, ext, url, page_url, blob_url, license, license_verified, author,
                    bytes, width, height, aspect_cache, res_status, res_checked_at,
                    blob_sha, added_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        it.provider, repo_id, it.repo_slug, it.repo_owner, it.repo_name,
                        it.repo_branch, it.path, it.name, it.folder, it.category,
                        it.kind, it.duration, " ".join(it.tags), it.ext, it.url,
                        it.page_url, it.blob_url, it.license, int(it.license_verified),
                        it.author, it.bytes, it.width, it.height, it.aspect,
                        it.resolution_status, it.resolution_checked_at, it.blob_sha,
                        it.added_at,
                    )
                    for it in items
                ],
            )
            self.conn.commit()
        self._rebuild_fts()
        return len(items)

    def _rebuild_fts(self) -> None:
        """Reconstruye las tablas FTS desde `items` (índice pequeño: cabe en RAM).

        La tabla de tokens guarda ruta, carpetas, nombre y etiquetas; la de
        trigramas sólo el nombre, que es donde se cometen los errores de
        tipeo, y así ocupa cuatro veces menos.
        """
        with self._write_lock:
            self.conn.execute("DELETE FROM items_fts")
            self.conn.execute("DELETE FROM items_tri")
            rows = self.conn.execute(
                "SELECT id, name, folder, path, tags FROM items"
            ).fetchall()
            fts_rows = []
            tri_rows = []
            for row in rows:
                tokens = _token_blob(row)
                fts_rows.append((row["id"], tokens))
                tri_rows.append((row["id"], normalize(row["name"] or "")))
            self.conn.executemany("INSERT INTO items_fts(rowid, tokens) VALUES(?,?)", fts_rows)
            self.conn.executemany("INSERT INTO items_tri(rowid, tokens) VALUES(?,?)", tri_rows)
            self.conn.commit()

    def compact(self) -> None:
        """Reclaiming el espacio libre del fichero SQLite (VACUUM)."""
        with self._write_lock:
            try:
                self.conn.execute("VACUUM")
            except sqlite3.Error:
                pass

    def item_count(self, repo_id: int | None = None) -> int:
        if repo_id is None:
            row = self.conn.execute("SELECT COUNT(*) c FROM items").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM items WHERE repo_id=?", (repo_id,)
            ).fetchone()
        return int(row["c"])

    def total_items(self) -> int:
        return self.item_count()

    def get_item(self, item_id: int) -> WallpaperItem | None:
        row = self.conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def update_resolution(self, item_id: int, width: int, height: int, ok: bool = True) -> None:
        aspect = ""
        if ok and width and height:
            from math import gcd
            g = gcd(width, height)
            if g and (width // g) <= 32 and (height // g) <= 32:
                aspect = f"{width // g}:{height // g}"
        with self._write_lock:
            self.conn.execute(
                "UPDATE items SET width=?, height=?, aspect_cache=?, res_status=?, "
                "res_checked_at=? WHERE id=?",
                (width, height, aspect, "known" if ok else "failed", int(time.time()), item_id),
            )
            self.conn.commit()

    def update_video_info(self, item_id: int, width: int, height: int,
                          duration: int) -> None:
        """Guarda la resolución y la duración de un vídeo."""
        aspect = ""
        if width and height:
            from math import gcd
            g = gcd(width, height)
            if g and (width // g) <= 32 and (height // g) <= 32:
                aspect = f"{width // g}:{height // g}"
        with self._write_lock:
            self.conn.execute(
                "UPDATE items SET width=?, height=?, duration=?, aspect_cache=?, "
                "res_status='known', res_checked_at=? WHERE id=?",
                (width, height, duration, aspect, int(time.time()), item_id),
            )
            self.conn.commit()

    def set_item_bytes(self, item_id: int, size: int) -> None:
        with self._write_lock:
            self.conn.execute("UPDATE items SET bytes=? WHERE id=?", (size, item_id))
            self.conn.commit()

    def _row_to_item(self, row: sqlite3.Row) -> WallpaperItem:
        return WallpaperItem(
            id=row["id"], provider=row["provider"], repo_id=row["repo_id"],
            repo_slug=row["repo_slug"], repo_owner=row["repo_owner"],
            repo_name=row["repo_name"], repo_branch=row["repo_branch"],
            path=row["path"], name=row["name"], folder=row["folder"],
            category=row["category"],
            kind=row["kind"] or "image",
            duration=int(row["duration"] or 0),
            tags=row["tags"].split() if row["tags"] else [], ext=row["ext"],
            url=row["url"], page_url=row["page_url"], blob_url=row["blob_url"],
            license=row["license"], license_verified=bool(row["license_verified"]),
            author=row["author"], bytes=row["bytes"], width=row["width"],
            height=row["height"], aspect=row["aspect_cache"],
            resolution_status=row["res_status"], resolution_checked_at=row["res_checked_at"],
            blob_sha=row["blob_sha"],
            added_at=row["added_at"],
            is_favorite=self.is_favorite(row["id"]),
            is_downloaded=self.is_downloaded(row["id"]),
        )

    # -------------------------------------------------------------- búsqueda
    def search(
        self,
        filters: SearchFilters,
        sort: str = "relevance",
        limit: int = 120,
        offset: int = 0,
    ) -> tuple[list[WallpaperItem], int]:
        """Busca en el índice. Devuelve (página de resultados, total estimado)."""
        where: list[str] = []
        params: list[Any] = []

        if filters.repo:
            where.append("i.repo_slug = ?")
            params.append(filters.repo)
        else:
            # La misma imagen puede estar en varios repos o repetida bajo
            # otro nombre: en la galería se ve una sola vez.
            where.append("i.duplicate_of = 0")
        if filters.category:
            where.append("i.category = ?")
            params.append(filters.category)
        if filters.min_width:
            # Los fondos cuya resolución todavía no se conoce no se excluyen:
            # se van midiendo en segundo plano (ver kabe.probe).
            where.append("(i.width = 0 OR i.width >= ?)")
            params.append(filters.min_width)
        if filters.min_height:
            where.append("(i.height = 0 OR i.height >= ?)")
            params.append(filters.min_height)
        if filters.orientation:
            where.append(
                "(CASE WHEN i.width > i.height THEN 'landscape' "
                "WHEN i.height > i.width THEN 'portrait' ELSE 'square' END) = ?"
            )
            params.append(filters.orientation)
        if filters.aspect:
            where.append("i.aspect_cache = ?")
            params.append(filters.aspect)
        if filters.kind:
            where.append("i.kind = ?")
            params.append(filters.kind)
        if filters.only_favorites:
            where.append("i.id IN (SELECT item_id FROM favorites)")
        if filters.only_downloaded:
            where.append("i.id IN (SELECT item_id FROM downloads)")
        if filters.match_monitor and filters.monitor_width:
            where.append("(i.width = 0 OR (i.width >= ? AND i.height >= ?))")
            params.append(filters.monitor_width)
            params.append(filters.monitor_height)
        for tag in filters.tags:
            where.append("i.tags LIKE ?")
            params.append(f"%{tag}%")

        query = normalize(filters.query).strip()
        scored: list[tuple[float, sqlite3.Row]] = []

        if query:
            # 1) Coincidencia por tokens (tolerante a tildes por el tokenizador).
            ids = self._fts_ids(query)
            if ids:
                where.append("i.id IN (%s)" % ",".join("?" * len(ids)))
                params.extend(ids)
                scored = []
            else:
                where.append("1=0")

        sql_where = " AND ".join(where) if where else "1=1"
        base = f"FROM items i WHERE {sql_where}"

        if query and sort == "relevance":
            rows = self.conn.execute(
                f"SELECT i.* {base} ORDER BY i.name COLLATE NOCASE LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            rows = self._rank(query, rows)
            total = self.conn.execute(f"SELECT COUNT(*) c {base}", params).fetchone()["c"]
            return [self._row_to_item(r) for r in rows], int(total)

        order = {
            "recent": "i.id DESC",
            "resolution": "(i.width * i.height) DESC, i.name COLLATE NOCASE",
            "name": "i.name COLLATE NOCASE",
            "random": "RANDOM()",
        }.get(sort, "i.name COLLATE NOCASE")
        rows = self.conn.execute(
            f"SELECT i.* {base} ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        total = self.conn.execute(f"SELECT COUNT(*) c {base}", params).fetchone()["c"]
        return [self._row_to_item(r) for r in rows], int(total)

    def _fts_ids(self, query: str, limit: int = 4000) -> list[int]:
        """IDs que coinciden con la consulta: tokens exactos y, si no bastan,
        trigramas (que absorben errores de tipeo)."""
        terms = [t for t in query.split() if t]
        ids: list[int] = []
        if terms:
            match = " AND ".join(f'"{t}"*' for t in terms)
            try:
                rows = self.conn.execute(
                    "SELECT rowid FROM items_fts WHERE items_fts MATCH ? LIMIT ?",
                    (match, limit),
                ).fetchall()
                ids = [int(r["rowid"]) for r in rows]
            except sqlite3.OperationalError:
                ids = []
        if not ids and len(query) >= 3:
            try:
                rows = self.conn.execute(
                    "SELECT rowid FROM items_tri WHERE items_tri MATCH ? LIMIT ?",
                    (f'"{query}"', limit),
                ).fetchall()
                ids = [int(r["rowid"]) for r in rows]
            except sqlite3.OperationalError:
                ids = []
        return ids

    def _rank(self, query: str, rows: Sequence[sqlite3.Row]) -> list[sqlite3.Row]:
        """Ordena por parecido (distancia de edición) cuando hay texto."""
        target = normalize(query)
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            hay = normalize(f"{row['name']} {row['folder']} {row['tags']}")
            score = SequenceMatcher(None, target, hay[: len(hay) + 40]).ratio()
            # Coincidencia literal del término, arriba del todo.
            if target and target in hay:
                score += 0.5
            scored.append((score, row))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        return [row for _score, row in scored]

    def suggest(self, text: str, limit: int = 8) -> list[str]:
        """Sugerencias de nombres/carpetas (autocompletado)."""
        text = normalize(text).strip()
        if not text:
            return []
        rows = self.conn.execute(
            "SELECT DISTINCT name FROM items WHERE name LIKE ? LIMIT ?",
            (f"%{text}%", limit),
        ).fetchall()
        return [r["name"] for r in rows]

    # ------------------------------------------------------------ favoritos
    def is_favorite(self, item_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM favorites WHERE item_id=?", (item_id,)
        ).fetchone()
        return row is not None

    def toggle_favorite(self, item_id: int) -> bool:
        with self._write_lock:
            if self.is_favorite(item_id):
                self.conn.execute("DELETE FROM favorites WHERE item_id=?", (item_id,))
                state = False
            else:
                self.conn.execute(
                    "INSERT OR REPLACE INTO favorites(item_id, created_at) VALUES(?,?)",
                    (item_id, int(time.time())),
                )
                state = True
            self.conn.commit()
        return state

    def favorites(self, limit: int = 500) -> list[WallpaperItem]:
        rows = self.conn.execute(
            "SELECT i.* FROM items i JOIN favorites f ON f.item_id = i.id "
            "ORDER BY f.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    # ----------------------------------------------------------- descargas
    def is_downloaded(self, item_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM downloads WHERE item_id=?", (item_id,)
        ).fetchone()
        return row is not None

    def mark_downloaded(self, item_id: int, path: str, size: int) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO downloads(item_id, path, bytes, downloaded_at) "
                "VALUES(?,?,?,?)",
                (item_id, path, size, int(time.time())),
            )
            self.conn.execute("UPDATE items SET bytes=? WHERE id=?", (size, item_id))
            self.conn.commit()

    def download_path(self, item_id: int) -> str:
        row = self.conn.execute(
            "SELECT path FROM downloads WHERE item_id=?", (item_id,)
        ).fetchone()
        return row["path"] if row else ""

    def downloaded_items(self, limit: int = 500) -> list[WallpaperItem]:
        rows = self.conn.execute(
            "SELECT i.* FROM items i JOIN downloads d ON d.item_id = i.id "
            "ORDER BY d.downloaded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    # ---------------------------------------------------------- colecciones
    def list_collections(self) -> list[tuple[int, str, int]]:
        rows = self.conn.execute(
            "SELECT c.id, c.name, COUNT(ci.item_id) n FROM collections c "
            "LEFT JOIN collection_items ci ON ci.collection_id = c.id "
            "GROUP BY c.id ORDER BY c.name"
        ).fetchall()
        return [(int(r["id"]), r["name"], int(r["n"])) for r in rows]

    def create_collection(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("nombre vacío")
        with self._write_lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO collections(name, created_at) VALUES(?,?)",
                (name, int(time.time())),
            )
            self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM collections WHERE name=?", (name,)
        ).fetchone()
        return int(row["id"]) if row else 0

    def add_to_collection(self, collection_id: int, item_id: int) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO collection_items(collection_id, item_id, added_at) "
                "VALUES(?,?,?)",
                (collection_id, item_id, int(time.time())),
            )
            self.conn.commit()

    def remove_from_collection(self, collection_id: int, item_id: int) -> None:
        with self._write_lock:
            self.conn.execute(
                "DELETE FROM collection_items WHERE collection_id=? AND item_id=?",
                (collection_id, item_id),
            )
            self.conn.commit()

    def collection_items(self, collection_id: int) -> list[WallpaperItem]:
        rows = self.conn.execute(
            "SELECT i.* FROM items i JOIN collection_items ci ON ci.item_id = i.id "
            "WHERE ci.collection_id=? ORDER BY ci.added_at DESC",
            (collection_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def delete_collection(self, collection_id: int) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM collection_items WHERE collection_id=?", (collection_id,))
            self.conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))
            self.conn.commit()

    # -------------------------------------------------------------- historial
    def add_history(self, item_id: int | None, monitor: str, ok: bool = True) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO history(item_id, applied_at, monitor, ok) VALUES(?,?,?,?)",
                (item_id, int(time.time()), monitor, int(ok)),
            )
            self.conn.commit()

    def history(self, limit: int = 40) -> list[tuple[int, str, str, int, int, str]]:
        rows = self.conn.execute(
            "SELECT h.id, i.name, i.path, h.applied_at, h.ok, h.monitor FROM history h "
            "LEFT JOIN items i ON i.id = h.item_id ORDER BY h.applied_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            (int(r["id"]), r["name"] or "", r["path"] or "", int(r["applied_at"]),
             int(r["ok"]), r["monitor"] or "")
            for r in rows
        ]

    # ------------------------------------------------------ caché de tamaños
    def cached_resolution(self, url: str) -> tuple[int, int, bool] | None:
        row = self.conn.execute(
            "SELECT width, height, ok FROM res_cache WHERE url=?", (url,)
        ).fetchone()
        if not row:
            return None
        return int(row["width"]), int(row["height"]), bool(row["ok"])

    def store_resolution(self, url: str, width: int, height: int, ok: bool) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO res_cache(url, width, height, ok, checked_at) "
                "VALUES(?,?,?,?,?)",
                (url, width, height, int(ok), int(time.time())),
            )
            self.conn.commit()


def _token_blob(row: sqlite3.Row) -> str:
    """Texto normalizado que se indexa: nombre, carpetas, ruta y etiquetas."""
    parts = [row["name"] or "", row["folder"] or "", row["path"] or "", row["tags"] or ""]
    blob = " ".join(parts)
    blob = blob.replace("_", " ").replace("-", " ").replace("/", " ")
    return normalize(blob)
