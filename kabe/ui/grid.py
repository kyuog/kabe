"""Cuadrícula de galería con carga bajo demanda.

Diseño: lienzo virtualizado (Gtk.Fixed).

El lienzo tiene el alto real de todo el catálogo, así que la barra de
desplazamiento funciona sola. Encima se colocan únicamente las miniaturas
visibles, en un número fijo de celdas que se **mueven** de sitio al
desplazar (nunca se vuelven a colgar en otro contenedor: GTK3 no vuelve a
medir los hijos que se añaden a un contenedor ya dimensionado y las
miniaturas se quedarían en 1×1 px).
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk  # noqa: E402

from ..i18n import gettext_ as _  # noqa: E402
from ..models import WallpaperItem  # noqa: E402
from .thumbnail import RoundedImage  # noqa: E402


class ThumbnailCell(Gtk.Overlay):
    """Una miniatura en la cuadrícula."""

    CELL_WIDTH = 168
    CELL_HEIGHT = 105

    __gsignals__ = {
        "activated": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "favorite-toggled": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, on_activate=None, on_favorite=None) -> None:
        super().__init__()
        self.item: Optional[WallpaperItem] = None
        self._thumb_key = ""
        self._source = None
        self._on_activate = on_activate
        self._on_favorite = on_favorite

        self.rounded = RoundedImage()
        self.rounded.set_size_request(self.CELL_WIDTH, self.CELL_HEIGHT)
        self.rounded.connect("button-press-event", self._on_press)
        self.rounded.connect("key-press-event", self._on_key)
        self.add(self.rounded)

        # Distintivo de vídeo (esquina superior izquierda).
        self.play = Gtk.Label(label="▶")
        self.play.get_style_context().add_class("kabe-chip")
        self.play.set_no_show_all(True)
        self.add_overlay(self.play)
        self.play.set_halign(Gtk.Align.START)
        self.play.set_valign(Gtk.Align.START)
        self.play.set_margin_top(8)
        self.play.set_margin_start(8)

        # Etiqueta de resolución o duración (esquina inferior derecha).
        self.chip = Gtk.Label(label="")
        self.chip.get_style_context().add_class("kabe-chip")
        chip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        chip_box.pack_start(self.chip, False, False, 0)
        self.add_overlay(chip_box)
        chip_box.set_halign(Gtk.Align.END)
        chip_box.set_valign(Gtk.Align.END)
        chip_box.set_margin_bottom(8)
        chip_box.set_margin_end(8)

        # Botón de favorito (esquina superior derecha).
        self.fav = Gtk.Button()
        self.fav.set_relief(Gtk.ReliefStyle.NONE)
        self.fav.set_focus_on_click(False)
        self.fav.set_size_request(28, 28)
        self.fav.set_tooltip_text(_("Guardar en favoritos"))
        self.fav.add(self._star_label("☆"))
        self.fav.connect("clicked", lambda _b: self._favorite())
        self.add_overlay(self.fav)
        self.fav.set_halign(Gtk.Align.END)
        self.fav.set_valign(Gtk.Align.START)
        self.fav.set_margin_top(6)
        self.fav.set_margin_end(6)

    @staticmethod
    def _star_label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_justify(Gtk.Justification.CENTER)
        return label

    # --------------------------------------------------------------- eventos
    def _on_press(self, _widget, event) -> bool:
        if event.button == 1:
            self._activate()
            return True
        return False

    def _on_key(self, _widget, event) -> bool:
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self._activate()
            return True
        return False

    def _activate(self) -> None:
        if self._on_activate and self.item:
            self._on_activate(self.item)

    def _favorite(self) -> None:
        if self._on_favorite and self.item:
            self._on_favorite(self.item)

    # ------------------------------------------------------------------ API
    def bind(self, item: WallpaperItem, thumb_key: str) -> None:
        """Asocia una imagen a la celda."""
        self.item = item
        self._thumb_key = thumb_key
        self._source = None
        self.rounded.set_pixbuf(None)
        self.rounded.set_placeholder("video" if item.is_video else "image")
        if item.is_video:
            self.play.show()
            self.chip.set_text(item.duration_label or _("vídeo"))
        else:
            self.play.hide()
            self.chip.set_text(item.resolution_label if item.width else "")
        self.fav.get_child().set_text("★" if item.is_favorite else "☆")
        self.fav.set_tooltip_text(
            _("Quitar de favoritos") if item.is_favorite else _("Guardar en favoritos")
        )

    def set_pixbuf(self, pixbuf) -> None:
        """Muestra la miniatura (ya recortada) en la tarjeta."""
        self._source = pixbuf
        self._render()

    def set_selected(self, selected: bool) -> None:
        self.rounded.set_selected(selected)

    def set_width(self, width: int) -> None:
        """Fija el ancho de la tarjeta (y recorta la miniatura a esa medida)."""
        if width <= 0:
            return
        height = max(1, int(width * self.CELL_HEIGHT / self.CELL_WIDTH))
        self.rounded.set_size_request(width, height)
        self.set_size_request(width, height)
        self._render()

    def relayout(self) -> None:
        """Vuelve a recortar la miniatura al tamaño actual de la celda."""
        if self._source is not None:
            self._render()

    def _render(self) -> None:
        if self._source is None:
            return
        width = self.rounded.get_allocated_width()
        if width <= 1:
            width = self.CELL_WIDTH
        height = max(1, int(width * self.CELL_HEIGHT / self.CELL_WIDTH))
        cropped = _cover(self._source, width, height)
        self.rounded.set_pixbuf(cropped if cropped is not None else self._source)

    def thumb_key(self) -> str:
        return self._thumb_key


class LazyGrid(Gtk.ScrolledWindow):
    """Cuadrícula virtualizada: sólo existen las miniaturas visibles."""

    def __init__(
        self,
        cell_size: int = 170,
        on_activate: Optional[Callable[[WallpaperItem], None]] = None,
        on_favorite: Optional[Callable[[WallpaperItem], None]] = None,
        on_visible: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_overlay_scrolling(False)
        self.set_shadow_type(Gtk.ShadowType.NONE)

        self._cell_size = cell_size
        self._gap = 10
        self._row_height = ThumbnailCell.CELL_HEIGHT + 26
        self._cols = 1
        self._cell_width = cell_size
        self._items: list[WallpaperItem] = []
        self._cells: list[ThumbnailCell] = []      # todas las creadas
        self._placed: dict[int, ThumbnailCell] = {}  # índice visible → celda
        self._on_activate = on_activate
        self._on_favorite = on_favorite
        self._on_visible = on_visible
        self._pending_update = False
        self._selected_item: Optional[WallpaperItem] = None

        self.canvas = Gtk.Fixed()
        self.add(self.canvas)

        self.get_vadjustment().connect("value-changed", self._on_scroll)
        self.connect("size-allocate", self._on_size_allocate)

    # ------------------------------------------------------------------ API
    def set_items(self, items: Sequence[WallpaperItem]) -> None:
        self._items = list(items)
        self.get_vadjustment().set_value(0)
        self._layout()

    def items(self) -> list[WallpaperItem]:
        return self._items

    def visible_indices(self) -> list[int]:
        return sorted(self._placed.keys())

    def cell_for(self, index: int) -> Optional[ThumbnailCell]:
        return self._placed.get(index)

    def select(self, item: Optional[WallpaperItem]) -> None:
        """Marca visualmente la celda seleccionada (borde ámbar)."""
        self._selected_item = item
        for cell in self._cells:
            cell.set_selected(item is not None and cell.item is item)

    def scroll_to_index(self, index: int) -> None:
        row = index // max(1, self._cols)
        self.get_vadjustment().set_value(row * self._row_height)

    # ------------------------------------------------------------- medidas
    def _on_size_allocate(self, _widget, allocation) -> None:
        width = allocation.width
        scrollbar = self.get_vscrollbar()
        if scrollbar is not None:
            width = max(200, width - scrollbar.get_allocated_width())
        cols = max(1, int((width + self._gap) // (self._cell_size + self._gap)))
        cell_width = max(110, (width - self._gap * (cols - 1)) // cols)
        changed = cols != self._cols or cell_width != self._cell_width
        self._cols = cols
        self._cell_width = cell_width
        if changed:
            for cell in self._cells:
                cell.set_width(self._cell_width)
        self._layout()

    # ------------------------------------------------------------- layout
    def _layout(self) -> None:
        """Coloca las miniaturas visibles en el lienzo."""
        total = len(self._items)
        rows = (total + self._cols - 1) // self._cols if total else 1
        content_height = max(self._row_height, rows * self._row_height)
        width = self._cell_width * self._cols + self._gap * max(0, self._cols - 1)
        self.canvas.set_size_request(max(1, width), content_height)

        adj = self.get_vadjustment()
        viewport = max(self._row_height, self.get_allocated_height())
        first_row = int(adj.get_value() // self._row_height)
        last_row = int((adj.get_value() + viewport) // self._row_height)
        first_row = max(0, min(first_row, max(0, rows - 1)))
        last_row = max(first_row, min(last_row, max(0, rows - 1)))

        needed = (last_row - first_row + 1) * self._cols
        while len(self._cells) < needed:
            cell = ThumbnailCell(self._on_activate, self._on_favorite)
            cell.set_width(self._cell_width)
            self.canvas.put(cell, 0, 0)
            cell.show_all()
            self._cells.append(cell)

        self._placed.clear()
        used = 0
        for row in range(first_row, last_row + 1):
            for col in range(self._cols):
                index = row * self._cols + col
                if index >= total:
                    break
                cell = self._cells[used]
                used += 1
                if cell.item is not self._items[index]:
                    cell.bind(self._items[index], thumb_key(self._items[index]))
                    cell.set_pixbuf(None)
                cell.set_selected(
                    self._selected_item is not None and cell.item is self._selected_item
                )
                x = col * (self._cell_width + self._gap)
                y = row * self._row_height
                self.canvas.move(cell, x, y)
                if not cell.get_visible():
                    cell.show_all()
                self._placed[index] = cell
        # Las sobrantes se esconden.
        for cell in self._cells[used:]:
            if cell.get_visible():
                cell.hide()
        if self._on_visible:
            self._on_visible()

    # ------------------------------------------------------------- scroll
    def _on_scroll(self, _adj) -> None:
        if self._pending_update:
            return
        self._pending_update = True
        GLib.idle_add(self._flush_scroll)

    def _flush_scroll(self) -> bool:
        self._pending_update = False
        self._layout()
        return False


def thumb_key(item: WallpaperItem) -> str:
    """Clave de caché de la miniatura de un elemento."""
    return f"{item.provider}:{item.repo_slug}:{item.path}"


def _cover(pixbuf, width: int, height: int):
    """Recorta la imagen para que llene el marco sin deformarla."""
    pw = pixbuf.get_width()
    ph = pixbuf.get_height()
    if pw <= 0 or ph <= 0:
        return None
    if pw == width and ph == height:
        return pixbuf
    scale = max(width / pw, height / ph)
    new_w = max(width, int(pw * scale + 0.5))
    new_h = max(height, int(ph * scale + 0.5))
    scaled = pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
    if scaled is None:
        return None
    offset_x = max(0, (new_w - width) // 2)
    offset_y = max(0, (new_h - height) // 2)
    try:
        return scaled.new_subpixbuf(offset_x, offset_y, width, height)
    except Exception:
        return scaled
