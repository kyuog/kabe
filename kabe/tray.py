"""Entrada de bandeja (bandeja del sistema).

Modo "solo bandeja": la ventana no existe, el proceso se queda dormido con
un icono, la rotación sigue funcionando y sólo se consume unos pocos MB.
"""

from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .i18n import _  # noqa: E402


class Tray:
    """Icono de Kabe en la bandeja del sistema."""

    def __init__(
        self,
        on_open: Callable[[], None],
        on_next: Callable[[], None],
        on_toggle_rotation: Callable[[], bool],
        on_quit: Callable[[], None],
        icon_name: str = "kabe",
    ) -> None:
        self.on_open = on_open
        self.on_next = on_next
        self.on_quit = on_quit
        self.icon = Gtk.StatusIcon.new_from_icon_name(icon_name)
        self.icon.set_tooltip_text(_("Kabe — fondos de pantalla"))
        self._rotation_item: Optional[Gtk.CheckMenuItem] = None
        self._build_menu(on_toggle_rotation)
        self.icon.connect("activate", lambda _i: self.on_open())
        self.icon.connect("popup-menu", self._popup)

    def _build_menu(self, on_toggle_rotation: Callable[[], bool]) -> None:
        menu = Gtk.Menu()
        item_open = Gtk.MenuItem.new_with_label(_("Abrir Kabe"))
        item_open.connect("activate", lambda _i: self.on_open())
        menu.append(item_open)

        item_next = Gtk.MenuItem.new_with_label(_("Siguiente fondo"))
        item_next.connect("activate", lambda _i: self.on_next())
        menu.append(item_next)

        self._rotation_item = Gtk.CheckMenuItem.new_with_label(_("Rotación automática"))
        self._rotation_item.connect("toggled", self._on_rotation_toggled)
        menu.append(self._rotation_item)

        menu.append(Gtk.SeparatorMenuItem())
        item_quit = Gtk.MenuItem.new_with_label(_("Salir"))
        item_quit.connect("activate", lambda _i: self.on_quit())
        menu.append(item_quit)
        menu.show_all()
        self.menu = menu
        self._on_toggle_rotation = on_toggle_rotation

    def _on_rotation_toggled(self, widget: Gtk.CheckMenuItem) -> None:
        active = self._on_toggle_rotation()
        widget.set_active(active)

    def _popup(self, _icon, button: int, activate_time: int) -> None:
        self.menu.popup(None, None, None, None, button, activate_time)

    def set_rotation_active(self, active: bool) -> None:
        if self._rotation_item:
            self._rotation_item.set_active(active)

    def set_icon_name(self, name: str) -> None:
        self.icon.set_from_icon_name(name)

    def hide(self) -> None:
        self.icon.set_visible(False)

    def show(self) -> None:
        self.icon.set_visible(True)
