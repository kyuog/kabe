"""Maqueta del escritorio real.

La idea memorable de Kabe: antes de aplicar nada, se ve cómo queda el fondo
en tus monitores, con su disposición y sus tamaños reales. Las esquinas
redondeadas repiten el radio del logo (23 % del lado).
"""

from __future__ import annotations

import math
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402

from ..models import Monitor, MonitorLayout  # noqa: E402
from . import style  # noqa: E402


class MonitorPreview(Gtk.DrawingArea):
    """Dibuja la disposición de los monitores con el fondo elegido."""

    def __init__(self) -> None:
        super().__init__()
        self.layout: MonitorLayout = MonitorLayout()
        self.pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self.active: Optional[str] = None
        self.set_size_request(240, 140)
        self.connect("draw", self._draw)

    # ------------------------------------------------------------------ API
    def set_layout(self, layout: MonitorLayout) -> None:
        self.layout = layout
        self.queue_draw()

    def set_image(self, pixbuf: Optional[GdkPixbuf.Pixbuf]) -> None:
        self.pixbuf = pixbuf
        self.queue_draw()

    def set_active(self, monitor_name: str) -> None:
        self.active = monitor_name
        self.queue_draw()

    # ---------------------------------------------------------------- dibujo
    def _draw(self, _widget, cr) -> bool:
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()

        monitors = [m for m in self.layout if m.width and m.height]
        if not monitors:
            self._draw_placeholder(cr, width, height)
            return False

        min_x = min(m.x for m in monitors)
        min_y = min(m.y for m in monitors)
        total_w = max(m.x + m.effective_width for m in monitors) - min_x
        total_h = max(m.y + m.effective_height for m in monitors) - min_y
        if total_w <= 0 or total_h <= 0:
            return False

        margin = 10.0
        scale = min(
            (width - margin * 2) / total_w,
            (height - margin * 2) / total_h,
        )
        if scale <= 0:
            return False
        draw_w = total_w * scale
        draw_h = total_h * scale
        offset_x = (width - draw_w) / 2
        offset_y = (height - draw_h) / 2

        for monitor in monitors:
            x = offset_x + (monitor.x - min_x) * scale
            y = offset_y + (monitor.y - min_y) * scale
            w = monitor.effective_width * scale
            h = monitor.effective_height * scale
            radius = min(w, h) * style.LOGO_RADIUS_RATIO
            self._draw_monitor(cr, monitor, x, y, w, h, radius)
        return False

    def _draw_monitor(self, cr, monitor: Monitor, x, y, w, h, radius) -> None:
        # Sombra suave: sólo un halo, sin tarjeta decorativa.
        cr.save()
        cr.set_source_rgba(0, 0, 0, 0.18)
        _rounded_rect(cr, x + 2, y + 3, w, h, radius)
        cr.fill()
        cr.restore()

        cr.save()
        _rounded_rect(cr, x, y, w, h, radius)
        cr.clip()

        if self.pixbuf is not None:
            pw = self.pixbuf.get_width()
            ph = self.pixbuf.get_height()
            if pw > 0 and ph > 0:
                # "cover": recorta para llenar el monitor sin deformar.
                scale = max(w / pw, h / ph)
                iw = pw * scale
                ih = ph * scale
                Gdk.cairo_set_source_pixbuf(
                    cr, self.pixbuf, x + (w - iw) / 2, y + (h - ih) / 2
                )
                cr.paint()
        else:
            cr.set_source_rgb(0.10, 0.12, 0.20)
            cr.paint()
        cr.restore()

        active = self.active == monitor.name
        cr.save()
        cr.set_line_width(3.0 if active else 1.5)
        if active:
            cr.set_source_rgb(*_hex_rgb(style.AMBER))
        else:
            cr.set_source_rgba(0.55, 0.60, 0.70, 0.55)
        _rounded_rect(cr, x, y, w, h, radius)
        cr.stroke()
        cr.restore()

        # Etiqueta: nombre del monitor y resolución.
        label = monitor.name
        if monitor.width:
            label = f"{monitor.name}  {monitor.width}×{monitor.height}"
        cr.save()
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgba(1, 1, 1, 0.92)
        text_w = cr.text_extents(label)[4]
        tx = x + 6
        ty = y + h - 6
        cr.set_source_rgba(0.06, 0.08, 0.15, 0.55)
        _rounded_rect(cr, tx - 4, ty - 12, text_w + 8, 15, 5)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.move_to(tx, ty)
        cr.show_text(label)
        cr.restore()

    def _draw_placeholder(self, cr, width: int, height: int) -> None:
        cr.save()
        cr.set_source_rgba(0.5, 0.55, 0.65, 0.55)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        text = "Sin monitores detectados"
        text_w = cr.text_extents(text)[4]
        cr.move_to((width - text_w) / 2, height / 2)
        cr.show_text(text)
        cr.restore()


def _rounded_rect(cr, x, y, w, h, radius) -> None:
    """Rectángulo con esquinas redondeadas (mismo radio que el logo)."""
    r = max(0.0, min(radius, min(w, h) / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, math.pi * 1.5)
    cr.close_path()


def _hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
