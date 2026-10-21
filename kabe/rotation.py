"""Rotación automática de fondos.

Dos modos:
  - por intervalo (cada N minutos);
  - por hora del día (a las 08:00, 13:00, 18:00, 22:00…).

El temporizador es un hilo ligero que despierta cada 30 segundos; no mantiene
ninguna ventana de GTK abierta y usa muy poca memoria.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional

from .db import Database, SearchFilters
from .models import WallpaperItem


class RotationManager:
    """Decide cuándo y qué fondo aplicar."""

    def __init__(
        self,
        db: Database | Any,
        config,
        apply_callback: Callable[[WallpaperItem], None],
        error_callback: Optional[Callable[[str], None]] = None,
    ):
        # `db` puede ser una fábrica (lambda) para no abrir la base de datos
        # hasta que la rotación necesite consultarla.
        self._db_factory = db if callable(db) and not hasattr(db, "search") else (lambda: db)
        self.config = config
        self.apply_callback = apply_callback
        self.error_callback = error_callback
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_run = 0.0
        self._last_slot = ""

    @property
    def db(self) -> Database:
        return self._db_factory()

    # ------------------------------------------------------------- control
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="kabe-rotation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def apply_now(self) -> Optional[WallpaperItem]:
        """Aplica el siguiente fondo de la rotación (a mano, desde la bandeja)."""
        item = self.pick()
        if item is None:
            if self.error_callback:
                self.error_callback("No hay fondos en la lista de rotación.")
            return None
        self.apply_callback(item)
        return item

    # -------------------------------------------------------------- lógica
    def _loop(self) -> None:
        while not self._stop.wait(30):
            try:
                self._tick()
            except Exception:  # pragma: no cover
                continue

    def _tick(self) -> None:
        if not self.config.rotation_enabled:
            return
        now = time.time()
        if self.config.rotation_mode == "timeofday":
            slot = self._current_slot()
            if slot and slot != self._last_slot:
                self._last_slot = slot
                self._last_run = now
                item = self.pick()
                if item:
                    self.apply_callback(item)
            return
        interval = max(1, int(self.config.rotation_interval_min)) * 60
        if now - self._last_run >= interval:
            self._last_run = now
            item = self.pick()
            if item:
                self.apply_callback(item)

    def _current_slot(self) -> str:
        """Devuelve la hora programada actual (o cadena vacía)."""
        now = time.localtime()
        stamp = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        for raw in self.config.rotation_times:
            hh, _, mm = raw.partition(":")
            try:
                hour, minute = int(hh), int(mm)
            except ValueError:
                continue
            if hour == now.tm_hour and minute == now.tm_min:
                return stamp
        return ""

    # -------------------------------------------------------------- selección
    def pick(self) -> Optional[WallpaperItem]:
        """Elige el siguiente fondo: colección de rotación → favoritos → catálogo."""
        playlists = list(getattr(self.config, "rotation_playlists", []) or [])
        if playlists:
            for collection_id in playlists:
                items = self.db.collection_items(int(collection_id))
                if items:
                    return random.choice(items)
        favorites = self.db.favorites(limit=200)
        if favorites:
            return random.choice(favorites)
        items, _total = self.db.search(
            SearchFilters(), sort="random", limit=50
        )
        if not items:
            return None
        return random.choice(items)
