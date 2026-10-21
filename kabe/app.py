"""Aplicación Kabe: contexto compartido, ciclo de vida GTK y bandeja."""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, __version__  # noqa: E402
from . import i18n, monitors, paths  # noqa: E402
from . import wallpaper as wallpaper_mod  # noqa: E402
from .config import Config  # noqa: E402
from .db import Database  # noqa: E402
from .i18n import _  # noqa: E402
from .indexer import Indexer  # noqa: E402
from .models import Monitor, MonitorLayout  # noqa: E402
from .net import HttpClient  # noqa: E402
from .rotation import RotationManager  # noqa: E402
from .thumbs import Thumbnailer  # noqa: E402
from .tray import Tray  # noqa: E402
from .ui import style  # noqa: E402
from .ui.dialogs import AboutDialog, AddRepoDialog, PreferencesDialog  # noqa: E402
from .ui.window import KabeWindow  # noqa: E402
from .workers import WorkerPool  # noqa: E402


class AppContext:
    """Estado compartido: configuración, índice, red, cachés y monitores.

    Todo lo pesado (base de datos, miniaturas, indexador) se crea bajo
    demanda: en modo sólo bandeja no se carga nada que no haga falta.
    """

    def __init__(self) -> None:
        self.config = Config.load()
        i18n.init(self.config.language)
        paths.ensure_dirs()
        self.http = HttpClient(self.config.github_token)
        self.layout: MonitorLayout = monitors.detect_monitors(
            getattr(self.config, "manual_resolution", "")
        )
        self.applier = wallpaper_mod.get_applier(
            getattr(self.config, "wallpaper_backend", "")
        )
        self._db: Optional[Database] = None
        self._thumbs: Optional[Thumbnailer] = None
        self._indexer: Optional[Indexer] = None
        self.thumb_pool = WorkerPool(1, "kabe-thumb")
        self.task_pool = WorkerPool(2, "kabe-task")

    # ------------------------------------------------------ objetos perezosos
    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database()
        return self._db

    @property
    def thumbs(self) -> Thumbnailer:
        if self._thumbs is None:
            self._thumbs = Thumbnailer(
                size=self.config.thumb_size,
                memory_limit=self.config.thumb_memory_limit,
            )
        return self._thumbs

    @property
    def indexer(self) -> Indexer:
        if self._indexer is None:
            self._indexer = Indexer(self.db, self.http, self.config.index_ttl_hours)
        return self._indexer

    # ------------------------------------------------------------- monitores
    def primary_monitor(self) -> Optional[Monitor]:
        return self.layout.primary

    def refresh_layout(self) -> MonitorLayout:
        self.layout = monitors.detect_monitors(
            getattr(self.config, "manual_resolution", "")
        )
        return self.layout

    # --------------------------------------------------------- preferencias
    def apply_preferences(self) -> None:
        """Aplica los cambios de Preferencias (token, estilo, backend…)."""
        self.http.token = (self.config.github_token or "").strip()
        self.applier = wallpaper_mod.get_applier(
            getattr(self.config, "wallpaper_backend", "")
        )
        if self._indexer is not None:
            self._indexer.ttl_hours = self.config.index_ttl_hours
        if self._thumbs is not None:
            self._thumbs.size = self.config.thumb_size
            self._thumbs.memory_limit = self.config.thumb_memory_limit
        self.refresh_layout()

    # ----------------------------------------------------------------- índices
    def prune_cache(self) -> int:
        """Recorta la caché de miniaturas al límite configurado."""
        freed = self.thumbs.enforce_disk_limit(self.config.cache_limit_mb)
        try:
            from .thumbs import prune_directory
            freed += prune_directory(str(paths.sources_dir()), self.config.cache_limit_mb)
        except OSError:
            pass
        return freed

    def shutdown(self) -> None:
        self.thumb_pool.stop()
        self.task_pool.stop()
        if self._indexer is not None:
            self._indexer.stop()
        if self._db is not None:
            self._db.close()


class KabeApp(Gtk.Application):
    """La aplicación GTK de Kabe."""

    def __init__(self, start_in_tray: bool = False) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self._t0 = time.time()
        self.ctx = AppContext()
        self.window: Optional[KabeWindow] = None
        self.tray: Optional[Tray] = None
        self.rotation: Optional[RotationManager] = None
        self._tray_only = start_in_tray or self.ctx.config.start_in_tray
        self._indexing = False

    # ------------------------------------------------------------ ciclo de vida
    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        style.install_css()
        self._build_tray()
        self._build_rotation()
        self._start_rotation(self.ctx.config.rotation_enabled)
        if self._tray_only:
            # Modo sólo bandeja: ni ventana ni GTK cargado en pantalla.
            # La aplicación se mantiene viva por el icono de la bandeja.
            self.hold()
            return
        GLib.idle_add(self._refresh_index_background)

    def do_activate(self) -> None:
        if self._tray_only:
            return
        self._ensure_window()
        self.window.present()
        if os.environ.get("KABE_DEBUG"):
            import time
            print(f"[kabe] ventana lista en {time.time() - self._t0:.2f} s", flush=True)

    def _ensure_window(self) -> None:
        if self.window is None:
            self.window = KabeWindow(self)
            self.window.show_all()
            self.window.reload_items()
            self.window.reload_repo_filter()

    def do_shutdown(self) -> None:
        self.ctx.shutdown()
        Gtk.Application.do_shutdown(self)

    # ---------------------------------------------------------------- bandeja
    def _build_tray(self) -> None:
        try:
            self.tray = Tray(
                on_open=self._open_window,
                on_next=self._rotation_next,
                on_toggle_rotation=self._toggle_rotation,
                on_quit=self.quit,
                icon_name=style.app_icon_name(),
            )
            self.tray.set_rotation_active(self.ctx.config.rotation_enabled)
        except Exception:  # pragma: no cover - sin bandeja no es un error fatal
            self.tray = None

    def _open_window(self) -> None:
        self._ensure_window()
        self.window.present()

    # --------------------------------------------------------------- rotación
    def _build_rotation(self) -> None:
        self.rotation = RotationManager(
            lambda: self.ctx.db,
            self.ctx.config,
            self._rotation_apply,
            self._rotation_error,
        )

    def _start_rotation(self, active: bool) -> None:
        if self.rotation is None:
            return
        if active:
            self.rotation.start()
        else:
            self.rotation.stop()

    def set_rotation(self, active: bool) -> None:
        self.ctx.config.rotation_enabled = active
        self.ctx.config.save()
        self._start_rotation(active)
        if self.tray:
            self.tray.set_rotation_active(active)

    def _toggle_rotation(self) -> bool:
        active = not self.ctx.config.rotation_enabled
        self.set_rotation(active)
        return active

    def _rotation_next(self) -> None:
        if self.rotation:
            self.rotation.apply_now()

    def _rotation_apply(self, item) -> None:
        GLib.idle_add(self._apply_rotation_item, item)

    def _apply_rotation_item(self, item) -> bool:
        window = self.window
        if window is None:
            return False
        window.select_item(item)
        window._apply_item(item, self.ctx.config.rotation_apply_all)
        return False

    def _rotation_error(self, message: str) -> None:
        GLib.idle_add(self._set_status, message)

    def _set_status(self, message: str) -> bool:
        if self.window is not None:
            window = self.window
            window._set_status(message)
        return False

    # ----------------------------------------------------------------- índice
    def refresh_index(self, force: bool = False) -> None:
        """Actualiza el índice en segundo plano."""
        if self._indexing:
            return
        self._indexing = True
        status = _("Actualizando el índice de repositorios…")
        if self.window:
            self.window._set_status(status)

        def _worker() -> None:
            report = self.ctx.indexer.sync(force=force)
            GLib.idle_add(self._index_finished, report)

        threading.Thread(target=_worker, name="kabe-index", daemon=True).start()

    def _refresh_index_background(self) -> bool:
        self.refresh_index(force=False)
        return False

    def _index_finished(self, report) -> bool:
        self._indexing = False
        if self.window:
            self.window.reload_repo_filter()
            self.window.reload_items()
        if report.errors:
            message = _("Actualización con problemas: %s") % "; ".join(report.errors[:2])
        else:
            message = _("Índice actualizado: %d fondos") % self.ctx.db.total_items()
        self._set_status(message)
        self.ctx.prune_cache()
        return False

    # -------------------------------------------------------------- diálogos
    def open_preferences(self) -> None:
        dialog = PreferencesDialog(self.window, self.ctx, on_saved=self._on_prefs_saved)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _on_prefs_saved(self) -> None:
        if self.window:
            self.window.monitor_preview.set_layout(self.ctx.layout)
            self.window.reload_items()
        self._set_status(_("Preferencias guardadas."))

    def open_about(self) -> None:
        dialog = AboutDialog(self.window)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def open_add_repo(self) -> None:
        from . import repos as repos_mod

        def _add(url: str) -> tuple[bool, str]:
            repo, error = repos_mod.add_user_repo(url)
            if repo is None:
                return False, error
            self.refresh_index(force=False)
            if self.window:
                self.window.reload_repo_filter()
            return True, _("Repositorio añadido. Actualizando el índice…")

        dialog = AddRepoDialog(self.window, _add)
        dialog.show_all()
        dialog.run()
        dialog.destroy()
