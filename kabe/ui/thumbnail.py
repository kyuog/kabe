"""Tarjeta de miniatura con las esquinas redondeadas del logo.

El logo de Kabe es un cuadrado con el radio al 23 % del lado. Esa misma
proporción se repite en cada miniatura y en la maqueta de monitores: es lo
único que hace que la galería se reconozca como Kabe y no como una lista de
imágenes.

El dibujo se hace con cairo sobre un Gtk.DrawingArea porque el CSS de GTK3
no puede recortar las esquinas de una imagen.
"""

from __future__ import annotations

import math
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GObject, Gtk  # noqa: E402

from . import style  # noqa: E402


class RoundedImage(Gtk.DrawingArea):
    """Miniatura con esquinas redondeadas, sombra mínima y borde de selección."""

    def __init__(self, radius_ratio: float = style.LOGO_RADIUS_RATIO) -> None:
        super().__init__()
        self.pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self.radius_ratio = radius_ratio
        self.selected = False
        self.hovered = False
        self.set_has_tooltip(True)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.set_can_focus(True)
        self.connect("draw", self._draw)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)

    # ------------------------------------------------------------------ API
    def set_pixbuf(self, pixbuf: Optional[GdkPixbuf.Pixbuf]) -> None:
        self.pixbuf = pixbuf
        self.queue_draw()

    def set_selected(self, selected: bool) -> None:
        if self.selected != selected:
            self.selected = selected
            self.queue_draw()

    def set_hovered(self, hovered: bool) -> None:
        if self.hovered != hovered:
            self.hovered = hovered
            self.queue_draw()

    # ---------------------------------------------------------------- dibujo
    def _draw(self, _widget, cr) -> bool:
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 1 or height <= 1:
            return False
        radius = min(min(width, height) * self.radius_ratio, 26.0)

        # Sombra: un halo suave, nada de tarjetas con sombra gris.
        if self.hovered or self.selected:
            cr.save()
            cr.set_source_rgba(0.06, 0.09, 0.18, 0.35 if self.hovered else 0.5)
            _rounded_rect(cr, 1.5, 3.0, width - 3, height - 3, radius)
            cr.fill()
            cr.restore()

        cr.save()
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.clip()
        if self.pixbuf is not None:
            _draw_cover(cr, self.pixbuf, width, height)
        else:
            cr.set_source_rgba(0.5, 0.55, 0.65, 0.18)
            cr.paint()
        cr.restore()

        # Borde: ámbar sólo en la selección; neutro al pasar el ratón.
        cr.save()
        if self.selected:
            cr.set_line_width(3.0)
            cr.set_source_rgb(*_hex_rgb(style.AMBER))
        elif self.hovered:
            cr.set_line_width(1.5)
            cr.set_source_rgba(0.85, 0.88, 0.94, 0.55)
        else:
            cr.set_line_width(1.0)
            cr.set_source_rgba(0.55, 0.60, 0.70, 0.35)
        _rounded_rect(cr, 1, 1, width - 2, height - 2, radius)
        cr.stroke()
        cr.restore()
        return False

    # --------------------------------------------------------------- eventos
    def _on_enter(self, _widget, _event) -> bool:
        self.set_hovered(True)
        return False

    def _on_leave(self, _widget, _event) -> bool:
        self.set_hovered(False)
        return False


def _rounded_rect(cr, x, y, width, height, radius) -> None:
    r = max(0.0, min(radius, min(width, height) / 2))
    cr.new_sub_path()
    cr.arc(x + width - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + width - r, y + height - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + height - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, math.pi * 1.5)
    cr.close_path()


def _draw_cover(cr, pixbuf, width: int, height: int) -> None:
    """Dibuja la imagen llenando el marco sin deformarla."""
    pw = pixbuf.get_width()
    ph = pixbuf.get_height()
    if pw <= 0 or ph <= 0:
        return
    scale = max(width / pw, height / ph)
    iw = pw * scale
    ih = ph * scale
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, (width - iw) / 2, (height - ih) / 2)
    cr.paint()


def _hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
