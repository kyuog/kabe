"""Cuadrícula de galería con carga bajo demanda.

Sólo existen las miniaturas visibles: las que salen de pantalla se sueltan y
vuelven al pool de reciclaje. Así la memoria se queda acotada aunque el
catálogo tenga miles de imágenes.

La estructura es sencilla a propósito: una caja vertical con una caja por
fila. Las filas que no se ven son cajas vacías con la altura de una fila,
así la barra de desplazamiento sabe cuánto contenido hay sin crear
miniaturas de más.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk  # noqa: E402

from ..models import WallpaperItem  # noqa: E402
from .thumbnail import RoundedImage  # noqa: E402


class ThumbnailCell(Gtk.Overlay):
    """Una miniatura en la cuadrícula."""

    CELL_WIDTH = 210
    CELL_HEIGHT = 132

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
        self.fav.set_tooltip_text("Guardar en favoritos")
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
        if item.is_video:
            self.play.show()
            self.chip.set_text(item.duration_label or "vídeo")
        else:
            self.play.hide()
            self.chip.set_text(item.resolution_label if item.width else "")
        self.fav.get_child().set_text("★" if item.is_favorite else "☆")
        self.fav.set_tooltip_text(
            "Quitar de favoritos" if item.is_favorite else "Guardar en favoritos"
        )

    def set_pixbuf(self, pixbuf) -> None:
        """Muestra la miniatura (ya recortada) en la tarjeta."""
        self._source = pixbuf
        self.rounded.set_pixbuf(pixbuf)

    def set_selected(self, selected: bool) -> None:
        self.rounded.set_selected(selected)

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
    """Cuadrícula virtualizada: crea celdas sólo para lo que se ve."""

    def __init__(
        self,
        cell_size: int = 210,
        on_activate: Optional[Callable[[WallpaperItem], None]] = None,
        on_favorite: Optional[Callable[[WallpaperItem], None]] = None,
    ) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_overlay_scrolling(False)
        self.set_shadow_type(Gtk.ShadowType.NONE)
        self.set_propagate_natural_width(False)
        self.set_propagate_natural_height(False)

        self._cell_size = cell_size
        self._gap = 10
        self._row_height = ThumbnailCell.CELL_HEIGHT + 30
        self._cols = 1
        self._cell_width = cell_size
        self._items: list[WallpaperItem] = []
        self._cells: dict[int, ThumbnailCell] = {}
        self._pool: list[ThumbnailCell] = []
        self._rows: dict[int, Gtk.Box] = {}
        self._on_activate = on_activate
        self._on_favorite = on_favorite
        self._pending_update = False
        self._selected_index: Optional[int] = None

        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(self.rows_box)

        self.get_vadjustment().connect("value-changed", self._on_scroll)
        self.connect("size-allocate", self._on_size_allocate)

    # ------------------------------------------------------------------ API
    def set_items(self, items: Sequence[WallpaperItem]) -> None:
        self._items = list(items)
        for cell in self._cells.values():
            self._detach(cell)
            self._pool.append(cell)
        self._cells.clear()
        self._selected_index = None
        self._clear_rows()
        self._update_viewport(force=True)

    def items(self) -> list[WallpaperItem]:
        return self._items

    def visible_indices(self) -> list[int]:
        return sorted(self._cells.keys())

    def cell_for(self, index: int) -> Optional[ThumbnailCell]:
        return self._cells.get(index)

    def select(self, item: Optional[WallpaperItem]) -> None:
        """Marca visualmente la celda seleccionada (borde ámbar)."""
        for index, cell in self._cells.items():
            cell.set_selected(item is not None and cell.item is item)
        if item is not None:
            for index, cell in self._cells.items():
                if cell.item is item:
                    self._selected_index = index
                    break

    def scroll_to_index(self, index: int) -> None:
        row = index // max(1, self._cols)
        adj = self.get_vadjustment()
        adj.set_value(row * self._row_height)

    # ------------------------------------------------------------- medidas
    def _on_size_allocate(self, _widget, allocation) -> None:
        width = allocation.width
        scrollbar = self.get_vscrollbar()
        if scrollbar is not None:
            width = max(200, width - scrollbar.get_allocated_width())
        cols = max(1, int((width + self._gap) // (self._cell_size + self._gap)))
        cell_width = max(120, (width - self._gap * (cols - 1)) // cols)
        changed = cols != self._cols or cell_width != self._cell_width
        self._cols = cols
        self._cell_width = cell_width
        self.rows_box.set_size_request(max(1, width), -1)
        self._update_viewport(force=changed)
        if changed:
            for cell in self._cells.values():
                cell.relayout()

    def _on_scroll(self, _adj) -> None:
        if self._pending_update:
            return
        self._pending_update = True
        GLib.idle_add(self._flush_scroll)

    def _flush_scroll(self) -> bool:
        self._pending_update = False
        self._update_viewport()
        return False

    def _visible_rows(self) -> tuple[int, int]:
        total = len(self._items)
        if total == 0:
            return 0, 0
        rows = (total + self._cols - 1) // self._cols
        adj = self.get_vadjustment()
        value = adj.get_value()
        page = adj.get_page_size() or self._row_height
        first = max(0, int(value // self._row_height) - 1)
        last = min(rows - 1, int((value + page) // self._row_height) + 1)
        return first, last

    # -------------------------------------------------------------viewport
    def _update_viewport(self, force: bool = False) -> None:
        total = len(self._items)
        rows = (total + self._cols - 1) // self._cols if total else 0
        first_row, last_row = self._visible_rows()

        if total == 0:
            self._clear_rows()
            return

        # Filas visibles: se vacían y se vuelven a llenar.
        for row in range(first_row, last_row + 1):
            rowbox = self._row_box(row)
            for child in rowbox.get_children():
                rowbox.remove(child)

        for row in range(first_row, last_row + 1):
            rowbox = self._row_box(row)
            start = row * self._cols
            for col in range(self._cols):
                index = start + col
                if index >= total:
                    break
                cell = self._cell_for(index)
                cell.set_size_request(self._cell_width, self._row_height)
                cell.set_selected(self.selected_item is cell.item)
                rowbox.pack_start(cell, False, False, 0)
                cell.show_all()

        # Filas que no se ven: cajas vacías con la altura de una fila.
        for row in range(rows):
            if first_row <= row <= last_row:
                continue
            self._row_box(row)

    @property
    def selected_item(self) -> Optional[WallpaperItem]:
        if self._selected_index is None:
            return None
        cell = self._cells.get(self._selected_index)
        return cell.item if cell else None

    def _row_box(self, row: int) -> Gtk.Box:
        rowbox = self._rows.get(row)
        if rowbox is None:
            rowbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=self._gap)
            rowbox.set_size_request(-1, self._row_height)
            self._rows[row] = rowbox
            self.rows_box.pack_start(rowbox, False, True, 0)
            rowbox.show_all()
        return rowbox

    def _cell_for(self, index: int) -> ThumbnailCell:
        cell = self._cells.get(index)
        if cell is None:
            cell = self._pool.pop() if self._pool else ThumbnailCell(
                self._on_activate, self._on_favorite
            )
            item = self._items[index]
            cell.bind(item, thumb_key(item))
            self._cells[index] = cell
        else:
            self._detach(cell)
        return cell

    def _detach(self, widget: Gtk.Widget) -> None:
        parent = widget.get_parent()
        if parent is not None:
            parent.remove(widget)

    def _clear_rows(self) -> None:
        for rowbox in self._rows.values():
            for child in rowbox.get_children():
                rowbox.remove(child)
            self.rows_box.remove(rowbox)
        self._rows.clear()


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
