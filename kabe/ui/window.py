"""Ventana principal de Kabe.

Estructura:

    ┌ barra superior: marca · búsqueda · orden · sorpréndeme · menú ┐
    │ filtros │ cuadrícula (carga bajo demanda) │ detalle + maqueta │
    └ estado: cuántos fondos, qué monitores, progreso de descarga ──┘
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

from ..db import SearchFilters  # noqa: E402
from ..i18n import _  # noqa: E402
from ..models import Monitor, MonitorLayout, WallpaperItem  # noqa: E402
from ..net import HttpError  # noqa: E402
from .. import paths  # noqa: E402
from .. import wallpaper as wallpaper_mod  # noqa: E402
from ..util import trim_memory  # noqa: E402
from . import style  # noqa: E402
from .grid import LazyGrid, thumb_key  # noqa: E402
from .monitor_preview import MonitorPreview  # noqa: E402

SORT_LABELS = {
    "relevance": "Relevancia",
    "recent": "Más recientes",
    "resolution": "Resolución",
    "random": "Aleatorio",
    "name": "Nombre",
}


def sort_options() -> list[tuple[str, str]]:
    """Opciones de orden (traducidas en el momento de construir la interfaz)."""
    return [(key, _(label)) for key, label in SORT_LABELS.items()]


RESOLUTION_OPTIONS = [
    ("", "Cualquiera"),
    ("3840", "4K y más (3840 px)"),
    ("5120", "5K y más (5120 px)"),
    ("1920", "Full HD y más"),
    ("1280", "HD y más"),
]

ASPECT_OPTIONS = [
    ("", "Cualquiera"),
    ("16:9", "16:9"),
    ("16:10", "16:10"),
    ("21:9", "21:9 ultrawide"),
    ("4:3", "4:3"),
    ("3:2", "3:2"),
]

ORIENTATION_OPTIONS = [
    ("", "Cualquiera"),
    ("landscape", "Apaisado"),
    ("portrait", "Vertical"),
    ("square", "Cuadrado"),
]


def resolution_options() -> list[tuple[str, str]]:
    return [("", _("Cualquiera")),
            ("3840", _("4K o más")),
            ("5120", _("5K o más")),
            ("1920", _("Full HD o más")),
            ("1280", _("HD o más"))]


def aspect_options() -> list[tuple[str, str]]:
    return [("", _("Cualquiera")), ("16:9", "16:9"), ("16:10", "16:10"),
            ("21:9", "21:9"), ("4:3", "4:3"), ("3:2", "3:2")]


def orientation_options() -> list[tuple[str, str]]:
    return [("", _("Cualquiera")), ("landscape", _("Apaisado")),
            ("portrait", _("Vertical")), ("square", _("Cuadrado"))]


def _shorten(text: str, limit: int) -> str:
    """Recorta un texto para la interfaz: 'linuxdotexe/nordic…'."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class KabeWindow(Gtk.ApplicationWindow):
    """La ventana de Kabe."""

    def __init__(self, app) -> None:
        super().__init__(application=app, title=_("Kabe"))
        ctx = app.ctx
        self.app = app
        self.ctx = ctx
        self.config = ctx.config
        self.selected: Optional[WallpaperItem] = None
        self._search_timer: Optional[int] = None
        self._pending_thumbs: set[str] = set()
        self._downloading = False
        self._last_results: list[WallpaperItem] = []

        self.set_default_size(self.config.window_width, self.config.window_height)
        screen = Gdk.Screen.get_default()
        if screen is not None:
            width = min(self.config.window_width, screen.get_width() - 80)
            height = min(self.config.window_height, screen.get_height() - 120)
            self.set_default_size(max(720, width), max(480, height))
        self.set_size_request(360, 320)
        self.connect("delete-event", self._on_delete)
        self.connect("key-press-event", self._on_key_press)

        self._build_ui()
        self._install_actions()
        self._install_accels()
        self.monitor_preview.set_layout(self.ctx.layout)
        self.reload_repo_filter()
        self.reload_items()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        root.pack_start(self._build_topbar(), False, False, 0)

        main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main_paned.set_position(228)
        main_paned.set_wide_handle(True)
        root.pack_start(main_paned, True, True, 0)

        main_paned.add1(self._build_sidebar())

        right = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        right.set_wide_handle(True)
        right.set_position(560)
        main_paned.add2(right)

        self.grid = LazyGrid(
            cell_size=170,
            on_activate=self._on_item_activated,
            on_favorite=self._on_item_favorite,
            on_visible=self._load_visible_thumbs,
        )
        self.grid_empty = Gtk.Label(label="")
        self.grid_empty.set_line_wrap(True)
        self.grid_empty.set_justify(Gtk.Justification.CENTER)
        self.grid_empty.get_style_context().add_class("kabe-empty")
        self.grid_empty.set_no_show_all(True)
        overlay = Gtk.Overlay()
        overlay.add(self.grid)
        overlay.add_overlay(self.grid_empty)
        self.grid_empty.set_halign(Gtk.Align.CENTER)
        self.grid_empty.set_valign(Gtk.Align.CENTER)
        right.add1(overlay)
        right.add2(self._build_detail())

        root.pack_start(self._build_statusbar(), False, False, 0)

    # ----------------------------------------------------------- barra superior
    def _build_topbar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.get_style_context().add_class("kabe-topbar")

        logo = style.logo_pixbuf(24)
        if logo is not None:
            image = Gtk.Image.new_from_pixbuf(logo)
            bar.pack_start(image, False, False, 0)
        brand = Gtk.Label(label="kabe")
        brand.get_style_context().add_class("kabe-brand")
        bar.pack_start(brand, False, False, 0)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(_("Buscar fondos, temas o categorías"))
        self.search.set_hexpand(True)
        self.search.set_width_chars(28)
        self.search.connect("search-changed", self._on_search_changed)
        self.search.connect("activate", self._on_search_activate)
        bar.pack_start(self.search, True, True, 0)

        self.sort_combo = Gtk.ComboBoxText()
        for key, label in sort_options():
            self.sort_combo.append(key, label)
        self.sort_combo.set_active(0)
        self.sort_combo.connect("changed", lambda _c: self.reload_items())
        self.sort_combo.set_tooltip_text(_("Ordenar por"))
        bar.pack_start(self.sort_combo, False, False, 0)

        self.surprise = Gtk.Button(label=_("Sorpréndeme"))
        self.surprise.set_tooltip_text(_("Muestra un fondo al azar"))
        self.surprise.connect("clicked", self._on_surprise)
        bar.pack_start(self.surprise, False, False, 0)

        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_tooltip_text(_("Menú"))
        menu = Gtk.Menu()
        self._menu_item_refresh = Gtk.MenuItem.new_with_label(_("Actualizar índice"))
        self._menu_item_refresh.connect("activate", lambda _i: self.app.refresh_index(force=True))
        menu.append(self._menu_item_refresh)
        self._menu_item_repo = Gtk.MenuItem.new_with_label(_("Añadir repositorio"))
        self._menu_item_repo.connect("activate", lambda _i: self.app.open_add_repo())
        menu.append(self._menu_item_repo)
        self._menu_item_rotation = Gtk.CheckMenuItem.new_with_label(_("Rotación automática"))
        self._menu_item_rotation.connect("toggled", self._on_rotation_toggled)
        menu.append(self._menu_item_rotation)
        menu.append(Gtk.SeparatorMenuItem())
        item_prefs = Gtk.MenuItem.new_with_label(_("Preferencias"))
        item_prefs.connect("activate", lambda _i: self.app.open_preferences())
        menu.append(item_prefs)
        item_about = Gtk.MenuItem.new_with_label(_("Acerca de Kabe"))
        item_about.connect("activate", lambda _i: self.app.open_about())
        menu.append(item_about)
        menu.show_all()
        self.menu_button.set_popup(menu)
        bar.pack_end(self.menu_button, False, False, 0)

        return bar

    # --------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> Gtk.Widget:
        outer = Gtk.ScrolledWindow()
        outer.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.set_size_request(200, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_start(10)
        box.set_margin_end(6)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        outer.add(box)

        self.kind_combo = self._add_combo(box, _("Tipo"), [
            ("", _("Imágenes y vídeos")),
            ("image", _("Sólo imágenes")),
            ("video", _("Sólo vídeos")),
        ])
        self.kind_combo.connect("changed", lambda _c: self.reload_items())
        self.category_combo = self._add_combo(box, _("Categoría"), [])
        self.repo_combo = self._add_combo(box, _("Repositorio"), [])
        self.min_res_combo = self._add_combo(box, _("Resolución mínima"), resolution_options())
        self.aspect_combo = self._add_combo(box, _("Relación de aspecto"), aspect_options())
        self.orientation_combo = self._add_combo(box, _("Orientación"), orientation_options())

        for combo in (self.category_combo, self.repo_combo, self.min_res_combo,
                      self.aspect_combo, self.orientation_combo):
            combo.connect("changed", lambda _c: self.reload_items())

        self.only_favorites = self._add_check(box, _("Sólo favoritos"))
        self.only_downloaded = self._add_check(box, _("Sólo descargados"))
        self.match_monitor = self._add_check(box, _("Cubrir el monitor"))
        self.match_monitor.set_active(self.config.match_monitor)
        self.match_monitor.connect("toggled", self._on_match_toggled)

        self.show_all_check = self._add_check(box, _("Mostrar todo"))
        self.show_all_check.set_tooltip_text(
            _("Ignora el filtro de resolución del monitor")
        )
        self.show_all_check.connect("toggled", self._on_match_toggled)

        return outer

    def _add_combo(self, box: Gtk.Box, title: str, options) -> Gtk.ComboBoxText:
        label = Gtk.Label(label=title)
        label.set_xalign(0.0)
        label.get_style_context().add_class("kabe-muted")
        box.pack_start(label, False, False, 0)
        combo = Gtk.ComboBoxText()
        for key, text in options:
            combo.append(key, text)
        combo.set_active(0)
        box.pack_start(combo, False, False, 0)
        return combo

    def _add_check(self, box: Gtk.Box, title: str) -> Gtk.CheckButton:
        check = Gtk.CheckButton(label=title)
        check.set_active(False)
        box.pack_start(check, False, False, 0)
        return check

    # ---------------------------------------------------------------- detalle
    def _build_detail(self) -> Gtk.Widget:
        outer = Gtk.ScrolledWindow()
        outer.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.set_size_request(300, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        outer.add(box)

        self.preview_image = Gtk.Image()
        self.preview_image.set_size_request(280, 160)
        box.pack_start(self.preview_image, False, False, 0)

        self.detail_title = Gtk.Label(label="")
        self.detail_title.set_xalign(0.0)
        self.detail_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.detail_title.set_line_wrap(True)
        box.pack_start(self.detail_title, False, False, 0)

        self.detail_meta = Gtk.Label(label="")
        self.detail_meta.set_xalign(0.0)
        self.detail_meta.set_line_wrap(True)
        self.detail_meta.get_style_context().add_class("kabe-muted")
        box.pack_start(self.detail_meta, False, False, 0)

        self.detail_source = Gtk.Label(label="")
        self.detail_source.set_xalign(0.0)
        self.detail_source.set_line_wrap(True)
        self.detail_source.get_style_context().add_class("kabe-muted")
        box.pack_start(self.detail_source, False, False, 0)

        preview_title = Gtk.Label(label=_("Vista previa del escritorio"))
        preview_title.set_xalign(0.0)
        preview_title.get_style_context().add_class("kabe-muted")
        box.pack_start(preview_title, False, False, 0)

        self.monitor_preview = MonitorPreview()
        box.pack_start(self.monitor_preview, False, False, 0)

        self.apply_one = Gtk.Button(label=_("Aplicar a este monitor"))
        self.apply_one.get_style_context().add_class("kabe-primary")
        self.apply_one.connect("clicked", lambda _b: self._apply_selected(to_all=False))
        box.pack_start(self.apply_one, False, False, 0)

        self.apply_all = Gtk.Button(label=_("Aplicar a todos"))
        self.apply_all.connect("clicked", lambda _b: self._apply_selected(to_all=True))
        box.pack_start(self.apply_all, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.fav_button = Gtk.Button(label=_("Guardar en favoritos"))
        self.fav_button.connect("clicked", lambda _b: self._toggle_favorite(self.selected))
        row.pack_start(self.fav_button, True, True, 0)
        self.download_button = Gtk.Button(label=_("Descargar"))
        self.download_button.connect("clicked", lambda _b: self._download_selected())
        row.pack_start(self.download_button, True, True, 0)
        box.pack_start(row, False, False, 0)

        similar = Gtk.Button(label=_("Otro parecido"))
        similar.set_tooltip_text(_("Busca fondos del mismo estilo"))
        similar.connect("clicked", lambda _b: self._show_similar())
        box.pack_start(similar, False, False, 0)

        self.empty_label = Gtk.Label(label="")
        self.empty_label.set_line_wrap(True)
        self.empty_label.get_style_context().add_class("kabe-empty")
        box.pack_start(self.empty_label, False, False, 0)

        self._update_detail()
        return outer

    # -------------------------------------------------------------- estado
    def _build_statusbar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.get_style_context().add_class("kabe-statusbar")

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0.0)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        bar.pack_start(self.status_label, True, True, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_size_request(140, -1)
        self.progress.set_show_text(True)
        self.progress.set_no_show_all(True)
        bar.pack_end(self.progress, False, False, 0)
        return bar

    # ------------------------------------------------------------- acciones
    def _install_actions(self) -> None:
        actions = [
            ("search", lambda *a: self.search.grab_focus()),
            ("refresh", lambda *a: self.app.refresh_index(force=True)),
            ("favorite", lambda *a: self._toggle_favorite(self.selected)),
            ("download", lambda *a: self._download_selected()),
            ("apply", lambda *a: self._apply_selected(to_all=False)),
            ("apply-all", lambda *a: self._apply_selected(to_all=True)),
            ("surprise", lambda *a: self._on_surprise(None)),
            ("preferences", lambda *a: self.app.open_preferences()),
            ("about", lambda *a: self.app.open_about()),
            ("add-repo", lambda *a: self.app.open_add_repo()),
            ("quit", lambda *a: self.app.quit()),
        ]
        for name, handler in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def _install_accels(self) -> None:
        accels = {
            "<Control>f": "win.search",
            "<Control>r": "win.refresh",
            "<Control>s": "win.favorite",
            "<Control>d": "win.download",
            "<Control>Return": "win.apply",
            "<Control><Shift>a": "win.apply-all",
            "<Control>n": "win.surprise",
            "<Control>q": "app.quit",
        }
        app = self.get_application()
        if app is None:
            return
        for accel, target in accels.items():
            try:
                app.set_accels_for_action(target, [accel])
            except Exception:  # pragma: no cover
                continue

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape and self.search.get_text():
            self.search.set_text("")
            return True
        return False

    # ------------------------------------------------------------- búsqueda
    def _on_search_changed(self, _entry) -> None:
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(280, self._do_search)

    def _on_search_activate(self, _entry) -> None:
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = None
        self.reload_items()

    def _do_search(self) -> bool:
        self._search_timer = None
        self.reload_items()
        return False

    def _current_filters(self) -> SearchFilters:
        monitor = self.ctx.primary_monitor()
        return SearchFilters(
            query=self.search.get_text().strip(),
            category=self.category_combo.get_active_id() or "",
            kind=self.kind_combo.get_active_id() or "",
            repo=self.repo_combo.get_active_id() or "",
            min_width=int(self.min_res_combo.get_active_id() or 0),
            aspect=self.aspect_combo.get_active_id() or "",
            orientation=self.orientation_combo.get_active_id() or "",
            only_favorites=self.only_favorites.get_active(),
            only_downloaded=self.only_downloaded.get_active(),
            match_monitor=(self.match_monitor.get_active()
                           and not self.show_all_check.get_active()),
            monitor_width=monitor.width if monitor else 0,
            monitor_height=monitor.height if monitor else 0,
            monitor_ratio=monitor.ratio if monitor else 0.0,
        )

    def reload_items(self) -> None:
        filters = self._current_filters()
        sort = self.sort_combo.get_active_id() or "relevance"
        try:
            items, total = self.ctx.db.search(filters, sort=sort, limit=240)
        except Exception as exc:  # pragma: no cover
            self._set_status(_("No se pudo consultar el índice: %s") % exc)
            return
        self._last_results = items
        self.grid.set_items(items)
        self._load_visible_thumbs()
        self._update_status(len(items), total)
        self._update_empty_state(items)

    def _update_empty_state(self, items: list[WallpaperItem]) -> None:
        """Mensaje claro cuando la galería no tiene nada que mostrar."""
        if items:
            self.grid_empty.hide()
            return
        if getattr(self.app, "_indexing", False):
            message = _("Actualizando el índice de repositorios…")
        elif self.search.get_text().strip():
            message = _(
                "Ningún fondo coincide con «%s». Prueba con menos palabras "
                "o quita algún filtro."
            ) % self.search.get_text().strip()
        elif self.ctx.db.total_items() == 0:
            message = _(
                "Todavía no hay fondos en el índice.\n"
                "Elige «Actualizar índice» en el menú para descargarlos."
            )
        else:
            message = _("Ningún fondo cumple los filtros activos. Prueba a mostrar todo.")
        self.grid_empty.set_text(message)
        self.grid_empty.show()

    def reload_repo_filter(self) -> None:
        repos = self.ctx.db.list_repos()
        self.repo_combo.remove_all()
        self.repo_combo.append("", _("Todos"))
        for repo in repos:
            # El texto se recorta para que el desplegable no ensanche la barra
            # lateral (el identificador completo sigue siendo el valor).
            self.repo_combo.append(repo.slug, _shorten(repo.slug, 18))
        self.repo_combo.set_active(0)

        categories = self.ctx.indexer.categories()
        self.category_combo.remove_all()
        self.category_combo.append("", _("Todas"))
        for category in categories:
            self.category_combo.append(category, category.capitalize())
        self.category_combo.set_active(0)

    # ------------------------------------------------------------ miniaturas
    def _load_visible_thumbs(self) -> None:
        """Pide las miniaturas de las celdas visibles. La descarga y el
        escalado ocurren en un hilo; la vuelta al GTK se hace con idle_add."""
        for index in self.grid.visible_indices():
            cell = self.grid.cell_for(index)
            if cell is None or cell.item is None:
                continue
            item = cell.item
            key = thumb_key(item)
            if key in self._pending_thumbs:
                continue
            pixbuf = self.ctx.thumbs.get_cached(key)
            if pixbuf is not None:
                cell.set_pixbuf(pixbuf)
                continue
            self._pending_thumbs.add(key)
            self.ctx.thumb_pool.submit(lambda it=item, k=key: self._build_thumb(it, k))
        self._probe_visible_resolutions()

    def _build_thumb(self, item: WallpaperItem, key: str):
        """Descarga (o escala) la imagen y genera la miniatura (hilo).

        En los vídeos no se descarga el archivo entero: ffmpeg extrae un
        fotograma directamente de la URL.
        """
        try:
            if item.is_video:
                path = self._video_poster(item, key)
            elif item.provider == "local":
                path = self.ctx.thumbs.save_from_file(key, item.path)
            else:
                source = self._source_path(item)
                if not os.path.exists(source):
                    self.ctx.http.download(item.url, source)
                path = self.ctx.thumbs.save_from_file(key, source)
            pixbuf = self.ctx.thumbs.get_cached(key)
        except (HttpError, OSError):
            path, pixbuf = None, None
        # Decodificar un PNG de 4K reserva decenas de MB: se devuelven al
        # sistema para que el consumo se quede en el nivel real.
        trim_memory()
        GLib.idle_add(self._set_cell_thumb, key, path, pixbuf)
        return path

    def _video_poster(self, item: WallpaperItem, key: str):
        """Extrae un fotograma del vídeo para usarlo como miniatura."""
        from ..video import poster_bytes
        data = poster_bytes(item.path if item.provider == "local" else item.url)
        if not data:
            return None
        return self.ctx.thumbs.save_from_bytes(key, data)

    def _set_cell_thumb(self, key: str, path, pixbuf) -> bool:
        """Vuelve al hilo principal y pinta la miniatura en su celda."""
        self._pending_thumbs.discard(key)
        if pixbuf is None and path:
            pixbuf = self.ctx.thumbs.load_from_disk(key)
        if pixbuf is None:
            return False
        for index in self.grid.visible_indices():
            cell = self.grid.cell_for(index)
            if cell is None or cell.item is None:
                continue
            if thumb_key(cell.item) == key:
                cell.set_pixbuf(pixbuf)


        return False

    def _probe_visible_resolutions(self) -> None:
        """Lee la cabecera de las imágenes visibles para saber su resolución."""
        for index in self.grid.visible_indices():
            cell = self.grid.cell_for(index)
            if cell is None or cell.item is None:
                continue
            item = cell.item
            if item.resolution_status != "unknown" or not item.width:
                continue
            if item.id is None:
                continue
            self.ctx.task_pool.submit(lambda it=item: self._probe_one(it))

    def _probe_one(self, item: WallpaperItem) -> None:
        if item.is_video:
            from ..video import probe_video
            info = probe_video(item.path if item.provider == "local" else item.url)
            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)
            duration = int(info.get("duration") or 0)
            if item.id is not None and (width or duration):
                self.ctx.db.update_video_info(item.id, width, height, duration)
            GLib.idle_add(self._refresh_resolution_labels)
            return
        from ..probe import probe_resolution
        cached = self.ctx.db.cached_resolution(item.url)
        if cached:
            width, height, ok = cached
        else:
            size = probe_resolution(self.ctx.http, item.url, item.ext)
            if size:
                width, height = size
                ok = True
            else:
                width, height, ok = 0, 0, False
            self.ctx.db.store_resolution(item.url, width, height, ok)
        if not ok:
            return
        self.ctx.db.update_resolution(item.id, width, height, True)
        GLib.idle_add(self._refresh_resolution_labels)

    def _refresh_resolution_labels(self) -> bool:
        for index in self.grid.visible_indices():
            cell = self.grid.cell_for(index)
            if cell is None or cell.item is None or cell.item.id is None:
                continue
            fresh = self.ctx.db.get_item(cell.item.id)
            if fresh:
                cell.item.width = fresh.width
                cell.item.height = fresh.height
                cell.chip.set_text(fresh.resolution_label if fresh.width else "")
        self._update_status()
        return False

    # ------------------------------------------------------------- selección
    def _on_item_activated(self, item: WallpaperItem) -> None:
        self.select_item(item)

    def select_item(self, item: WallpaperItem) -> None:
        self.selected = item
        self.grid.select(item)
        self._update_detail()
        key = thumb_key(item)
        pixbuf = self.ctx.thumbs.get_cached(key)
        if pixbuf is None and self.ctx.thumbs.has_disk(key):
            self.ctx.thumb_pool.submit(
                lambda: self._set_preview_pixbuf(self.ctx.thumbs.load_from_disk(key))
            )
        elif pixbuf is not None:
            self._set_preview_pixbuf(pixbuf)
        else:
            self.ctx.thumb_pool.submit(
                lambda it=item, k=key: self._set_preview_pixbuf(self._build_thumb(it, k) and
                                                                 self.ctx.thumbs.get_cached(k))
            )
        monitor = self.ctx.primary_monitor()
        if monitor:
            self.monitor_preview.set_active(monitor.name)

    def _set_preview_pixbuf(self, pixbuf) -> None:
        if pixbuf is None:
            return
        self.preview_image.set_from_pixbuf(pixbuf)
        self.monitor_preview.set_image(pixbuf)

    def _update_detail(self) -> None:
        item = self.selected
        if item is None:
            self.detail_title.set_text("")
            self.detail_meta.set_text("")
            self.detail_source.set_text("")
            self.preview_image.clear()
            self.monitor_preview.set_image(None)
            for button in (self.apply_one, self.apply_all, self.fav_button,
                           self.download_button):
                button.set_sensitive(False)
            return
        for button in (self.apply_one, self.apply_all, self.fav_button,
                       self.download_button):
            button.set_sensitive(True)
        self.detail_title.set_text(item.name.replace("_", " ").replace("-", " "))
        parts = []
        if item.is_video:
            parts.append(_("Vídeo"))
            if item.duration:
                parts.append(item.duration_label)
        if item.width:
            parts.append(f"{item.width}×{item.height}")
            parts.append(item.resolution_label)
        if item.aspect:
            parts.append(item.aspect)
        if item.bytes:
            from ..util import human_size
            parts.append(human_size(item.bytes))
        self.detail_meta.set_text(" · ".join(parts))
        source = item.repo_slug or item.provider
        license_label = item.license if item.license_verified else _("licencia no verificada")
        self.detail_source.set_text(f"{source} · {license_label}")
        self.fav_button.set_label(
            _("Quitar de favoritos") if item.is_favorite else _("Guardar en favoritos")
        )

    def _update_status(self, shown: Optional[int] = None, total: Optional[int] = None) -> None:
        layout = self.ctx.layout
        monitors = layout.monitors
        if monitors:
            desc = ", ".join(f"{m.name} {m.resolution_label}" for m in monitors[:3])
            if len(monitors) > 3:
                desc += f" (+{len(monitors) - 3})"
            env = f" · {len(monitors)} monitor{'es' if len(monitors) > 1 else ''}: {desc}"
        else:
            env = " · " + _("sin monitores detectados")
        if shown is None:
            shown = len(self._last_results)
        if total is None:
            total = self.ctx.db.total_items()
        self.status_label.set_text(_("%(shown)d de %(total)d fondos%(env)s") % {
            "shown": shown, "total": total, "env": env,
        })

    def _set_status(self, message: str) -> None:
        self.status_label.set_text(message)

    # --------------------------------------------------------------- filtros
    def _on_match_toggled(self, _widget) -> None:
        self.config.match_monitor = self.match_monitor.get_active()
        self.reload_items()

    def _on_rotation_toggled(self, widget: Gtk.CheckMenuItem) -> None:
        self.config.rotation_enabled = widget.get_active()
        self.config.save()
        self.app.set_rotation(self.config.rotation_enabled)

    def _on_surprise(self, _button) -> None:
        items = self._last_results or []
        if not items:
            self._set_status(_("No hay fondos que mostrar todavía. Actualiza el índice."))
            return
        item = items[int(time.time() * 1000) % len(items)]
        index = items.index(item)
        self.grid.scroll_to_index(index)
        self.select_item(item)

    def _show_similar(self) -> None:
        item = self.selected
        if item is None:
            return
        tags = [t for t in item.tags if t not in ("mixto",)][:2]
        if not tags:
            self._set_status(_("No hay suficientes etiquetas para buscar parecidos."))
            return
        self.search.set_text(tags[0])
        self.reload_items()

    # ------------------------------------------------------------ favoritos
    def _on_item_favorite(self, item: WallpaperItem) -> None:
        self._toggle_favorite(item)

    def _toggle_favorite(self, item: Optional[WallpaperItem]) -> None:
        if item is None or item.id is None:
            return
        state = self.ctx.db.toggle_favorite(item.id)
        item.is_favorite = state
        if self.selected is item:
            self._update_detail()
        for index in self.grid.visible_indices():
            cell = self.grid.cell_for(index)
            if cell and cell.item and cell.item.id == item.id:
                cell.item.is_favorite = state
                cell.fav.get_child().set_text("★" if state else "☆")
        self._set_status(
            _("Guardado en favoritos") if state else _("Quitado de favoritos")
        )

    # ------------------------------------------------------------ descargas
    def _source_path(self, item: WallpaperItem) -> str:
        name = os.path.basename(item.path) or "imagen"
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")[:80]
        from ..util import short_hash
        folder = os.path.join(str(paths.sources_dir()), short_hash(item.url, 12))
        return os.path.join(folder, safe or "imagen.jpg")

    def _download_selected(self) -> None:
        item = self.selected
        if item is None:
            return
        self._download_item(item)

    def _download_item(self, item: WallpaperItem) -> None:
        if self._downloading:
            self._set_status(_("Ya hay una descarga en curso."))
            return
        if item.provider == "local":
            self._set_status(_("Este fondo ya está en tu disco."))
            return
        target = os.path.join(str(paths.downloads_dir()), self._download_name(item))
        if os.path.exists(target):
            self.ctx.db.mark_downloaded(item.id, target, os.path.getsize(target))
            self._set_status(_("Ya estaba descargado."))
            return
        self._downloading = True
        self.progress.set_fraction(0.0)
        self.progress.set_text(_("Descargando…"))
        self.progress.show()

        def _progress(done: int, total: int) -> None:
            GLib.idle_add(self._update_progress, done, total)

        def _worker() -> None:
            try:
                size = self.ctx.http.download(item.url, target, progress=_progress)
            except (HttpError, OSError) as exc:
                GLib.idle_add(self._download_finished, False, str(exc))
                return
            GLib.idle_add(self._download_finished, True, size)

        self.ctx.task_pool.submit(_worker)

    def _download_name(self, item: WallpaperItem) -> str:
        from ..util import short_hash
        base = os.path.basename(item.path) or "fondo"
        base = "".join(ch for ch in base if ch.isalnum() or ch in "._-")[:60]
        return f"{short_hash(item.url, 8)}-{base}"

    def _update_progress(self, done: int, total: int) -> bool:
        if total:
            self.progress.set_fraction(min(1.0, done / total))
            self.progress.set_text(f"{int(done / 1024)}/{int(total / 1024)} KB")
        else:
            self.progress.set_fraction(0.0)
            self.progress.set_text(f"{int(done / 1024)} KB")
        return False

    def _download_finished(self, ok: bool, info) -> bool:
        self._downloading = False
        self.progress.hide()
        item = self.selected
        if not ok:
            self._set_status(_("No se pudo descargar: %s") % info)
            return False
        if item is not None and item.id is not None:
            target = os.path.join(str(paths.downloads_dir()), self._download_name(item))
            self.ctx.db.mark_downloaded(item.id, target, int(info))
        self._set_status(_("Descarga completada."))
        return False

    # --------------------------------------------------------------- aplicar
    def _apply_selected(self, to_all: bool = False) -> None:
        item = self.selected
        if item is None:
            self._set_status(_("Selecciona un fondo primero."))
            return
        self._apply_item(item, to_all)

    def _apply_item(self, item: WallpaperItem, to_all: bool) -> None:
        if item.provider == "local":
            self._apply_local(item.path, item, to_all)
            return
        if item.is_video:
            self._apply_video(item, to_all)
            return
        source = self._source_path(item)
        if os.path.exists(source):
            self._apply_local(source, item, to_all)
            return
        self._set_status(_("Descargando el fondo antes de aplicarlo…"))
        self.progress.set_fraction(0.0)
        self.progress.set_text(_("Descargando…"))
        self.progress.show()

        def _progress(done: int, total: int) -> None:
            GLib.idle_add(self._update_progress, done, total)

        def _worker() -> None:
            try:
                self.ctx.http.download(item.url, source, progress=_progress)
            except (HttpError, OSError) as exc:
                GLib.idle_add(self._apply_failed, str(exc))
                return
            GLib.idle_add(self._apply_local, source, item, to_all)

        self.ctx.task_pool.submit(_worker)

    def _apply_video(self, item: WallpaperItem, to_all: bool) -> None:
        """Los vídeos se descargan enteros y se aplican con mpvpaper o
        xwinwrap+mpv."""
        source = self._source_path(item)
        if os.path.exists(source):
            self._apply_local(source, item, to_all)
            return
        self._set_status(_("Descargando el vídeo…"))
        self.progress.set_fraction(0.0)
        self.progress.set_text(_("Descargando…"))
        self.progress.show()

        def _progress(done: int, total: int) -> None:
            GLib.idle_add(self._update_progress, done, total)

        def _worker() -> None:
            try:
                self.ctx.http.download(item.url, source, progress=_progress)
            except (HttpError, OSError) as exc:
                GLib.idle_add(self._apply_failed, str(exc))
                return
            GLib.idle_add(self._apply_local, source, item, to_all)

        self.ctx.task_pool.submit(_worker)

    def _apply_failed(self, message: str) -> bool:
        self.progress.hide()
        self._set_status(_("No se pudo aplicar el fondo: %s") % message)
        return False

    def _apply_local(self, path: str, item: WallpaperItem, to_all: bool) -> bool:
        self.progress.hide()
        applier = self.ctx.applier
        if item.is_video:
            applier = wallpaper_mod.get_applier(
                getattr(self.config, "wallpaper_backend", ""), kind="video"
            )
        layout = self.ctx.layout
        try:
            ok, message = wallpaper_mod.apply_wallpaper(
                applier, path, layout.monitors, self.config_style(), to_all
            )
        except Exception as exc:  # pragma: no cover
            ok, message = False, str(exc)
        if not ok:
            self._set_status(_("No se pudo aplicar el fondo: %s") % message)
            return False
        if item.id is not None:
            self.ctx.db.add_history(item.id, ",".join(m.name for m in layout.monitors), True)
        target = _("todos los monitores") if to_all else (
            layout.primary.name if layout.primary else _("el monitor principal")
        )
        self._set_status(_("Fondo aplicado en %s.") % target)
        return False

    def config_style(self) -> str:
        return getattr(self.config, "wallpaper_style", "scaled") or "scaled"

    # ------------------------------------------------------------- lifecycle
    def _on_delete(self, _widget, _event) -> bool:
        if self.config.close_to_tray and self.app.tray is not None:
            self.hide()
            return True
        return False

    def on_visibility_changed(self) -> None:
        if self.get_visible():
            self.reload_items()
