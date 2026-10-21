"""Diálogos: Acerca de, Preferencias y Añadir repositorio."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .. import APP_ID, __version__  # noqa: E402
from ..i18n import _  # noqa: E402
from . import style  # noqa: E402

BACKEND_OPTIONS = [
    ("", "Automático (detectar escritorio)"),
    ("xfce", "XFCE (xfconf-query)"),
    ("gnome", "GNOME (gsettings)"),
    ("kde", "KDE Plasma"),
    ("cinnamon", "Cinnamon (gsettings)"),
    ("mate", "MATE (gsettings)"),
    ("lxqt", "LXQt (pcmanfm-qt)"),
    ("lxde", "LXDE (pcmanfm)"),
    ("budgie", "Budgie (gsettings)"),
    ("deepin", "Deepin (gsettings)"),
    ("feh", "feh (cualquier X11)"),
    ("nitrogen", "nitrogen"),
    ("swww", "swww (Wayland)"),
    ("hyprpaper", "hyprpaper (Hyprland)"),
    ("swaybg", "swaybg (Sway)"),
]


def style_options() -> list[tuple[str, str]]:
    """Estilos de fondo traducibles."""
    return [
        ("scaled", _("Escalado (encaja sin recortar)")),
        ("zoomed", _("Zoom (llena el monitor recortando)")),
        ("centered", _("Centrado")),
        ("stretched", _("Estirado")),
        ("shrunk", _("Encogido")),
    ]


def backend_options() -> list[tuple[str, str]]:
    """Aplicadores disponibles, traducidos."""
    labels = {
        "": _("Automático (detectar escritorio)"),
        "xfce": "XFCE (xfconf-query)",
        "gnome": "GNOME (gsettings)",
        "kde": "KDE Plasma",
        "cinnamon": "Cinnamon (gsettings)",
        "mate": "MATE (gsettings)",
        "lxqt": "LXQt (pcmanfm-qt)",
        "lxde": "LXDE (pcmanfm)",
        "budgie": "Budgie (gsettings)",
        "deepin": "Deepin (gsettings)",
        "feh": _("feh (cualquier X11)"),
        "nitrogen": "nitrogen",
        "swww": "swww (Wayland)",
        "hyprpaper": "hyprpaper (Hyprland)",
        "swaybg": "swaybg (Sway)",
    }
    return [(key, labels[key]) for key, _text in BACKEND_OPTIONS]


class AboutDialog(Gtk.AboutDialog):
    """Pantalla «Acerca de Kabe» con el logo."""

    def __init__(self, parent=None) -> None:
        super().__init__(transient_for=parent, modal=True)
        self.set_program_name("Kabe")
        self.set_version(__version__)
        pixbuf = style.logo_pixbuf(128)
        if pixbuf is not None:
            self.set_logo(pixbuf)
        self.set_comments(_(
            "壁 · pared. Descubre, descarga y aplica fondos de pantalla en alta "
            "resolución para tu escritorio Linux."
        ))
        self.set_website("https://github.com/kabe-app/kabe")
        self.set_license_type(Gtk.License.GPL_3_0)
        self.set_copyright("© 2026 Kabe")
        self.set_website_label(_("Sitio web"))
        self.set_authors(["Kabe"])
        self.set_transient_for(parent)


class PreferencesDialog(Gtk.Dialog):
    """Preferencias: token, caché, estilo de fondo y detección de monitores."""

    def __init__(self, parent, ctx, on_saved=None) -> None:
        super().__init__(title=_("Preferencias"), transient_for=parent, modal=True)
        self.ctx = ctx
        self.on_saved = on_saved
        self.set_border_width(12)
        self.add_buttons(
            _("Cancelar"), Gtk.ResponseType.CANCEL,
            _("Guardar"), Gtk.ResponseType.OK,
        )
        self.set_default_size(460, -1)

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(8)
        grid.set_border_width(6)
        self.get_content_area().add(grid)

        row = 0
        self.token_entry = Gtk.Entry()
        self.token_entry.set_placeholder_text(_("Opcional: token personal de GitHub"))
        self.token_entry.set_visibility(False)
        self.token_entry.set_text(ctx.config.github_token)
        grid.attach(_label(_("Token de GitHub")), 0, row, 1, 1)
        grid.attach(self.token_entry, 1, row, 1, 1)
        row += 1

        self.token_hint = Gtk.Label(
            label=_("Sin token: 60 peticiones por hora. Con token: 5000. "
                    "El token sólo se guarda en ~/.config/kabe/config.json.")
        )
        self.token_hint.set_line_wrap(True)
        self.token_hint.get_style_context().add_class("kabe-muted")
        grid.attach(self.token_hint, 1, row, 1, 1)
        row += 1

        self.style_combo = Gtk.ComboBoxText()
        for key, text in style_options():
            self.style_combo.append(key, text)
        self.style_combo.set_active_id(getattr(ctx.config, "wallpaper_style", "scaled") or "scaled")
        grid.attach(_label(_("Estilo del fondo")), 0, row, 1, 1)
        grid.attach(self.style_combo, 1, row, 1, 1)
        row += 1

        self.backend_combo = Gtk.ComboBoxText()
        for key, text in backend_options():
            self.backend_combo.append(key, text)
        self.backend_combo.set_active_id(getattr(ctx.config, "wallpaper_backend", "") or "")
        grid.attach(_label(_("Aplicar con")), 0, row, 1, 1)
        grid.attach(self.backend_combo, 1, row, 1, 1)
        row += 1

        self.manual_entry = Gtk.Entry()
        self.manual_entry.set_placeholder_text("1920x1080")
        self.manual_entry.set_text(getattr(ctx.config, "manual_resolution", "") or "")
        grid.attach(_label(_("Resolución manual")), 0, row, 1, 1)
        grid.attach(self.manual_entry, 1, row, 1, 1)
        row += 1

        self.ttl_spin = Gtk.SpinButton.new_with_range(1, 168, 1)
        self.ttl_spin.set_value(ctx.config.index_ttl_hours)
        grid.attach(_label(_("Actualizar índice cada (horas)")), 0, row, 1, 1)
        grid.attach(self.ttl_spin, 1, row, 1, 1)
        row += 1

        self.cache_spin = Gtk.SpinButton.new_with_range(64, 16384, 64)
        self.cache_spin.set_value(ctx.config.cache_limit_mb)
        grid.attach(_label(_("Caché en disco (MB)")), 0, row, 1, 1)
        grid.attach(self.cache_spin, 1, row, 1, 1)
        row += 1

        self.close_to_tray = Gtk.CheckButton(label=_("Cerrar la ventana va a la bandeja"))
        self.close_to_tray.set_active(ctx.config.close_to_tray)
        grid.attach(self.close_to_tray, 0, row, 2, 1)
        row += 1

        self.start_in_tray = Gtk.CheckButton(label=_("Empezar sólo en la bandeja"))
        self.start_in_tray.set_active(ctx.config.start_in_tray)
        grid.attach(self.start_in_tray, 0, row, 2, 1)

        self.connect("response", self._on_response)

    def _on_response(self, _dialog, response: int) -> None:
        if response != Gtk.ResponseType.OK:
            return
        config = self.ctx.config
        config.github_token = self.token_entry.get_text().strip()
        config.wallpaper_style = self.style_combo.get_active_id() or "scaled"
        config.wallpaper_backend = self.backend_combo.get_active_id() or ""
        config.manual_resolution = self.manual_entry.get_text().strip()
        config.index_ttl_hours = int(self.ttl_spin.get_value())
        config.cache_limit_mb = int(self.cache_spin.get_value())
        config.close_to_tray = self.close_to_tray.get_active()
        config.start_in_tray = self.start_in_tray.get_active()
        config.save()
        self.ctx.apply_preferences()
        if self.on_saved:
            self.on_saved()


class AddRepoDialog(Gtk.Dialog):
    """Añadir un repositorio de GitHub escribiendo su URL."""

    def __init__(self, parent, on_add) -> None:
        super().__init__(title=_("Añadir repositorio"), transient_for=parent, modal=True)
        self.on_add = on_add
        self.set_border_width(12)
        self.set_default_size(460, -1)
        self.add_buttons(
            _("Cancelar"), Gtk.ResponseType.CANCEL,
            _("Añadir"), Gtk.ResponseType.OK,
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.get_content_area().add(box)

        hint = Gtk.Label(
            label=_("Pega la dirección del repositorio de GitHub. "
                    "Kabe indexará sus imágenes sin descargar el repositorio completo.")
        )
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("kabe-muted")
        box.pack_start(hint, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("https://github.com/propietario/repositorio")
        self.entry.set_activates_default(True)
        box.pack_start(self.entry, False, False, 0)

        self.message = Gtk.Label(label="")
        self.message.set_line_wrap(True)
        box.pack_start(self.message, False, False, 0)

        self.set_default_response(Gtk.ResponseType.OK)
        self.connect("response", self._on_response)

    def _on_response(self, _dialog, response: int) -> None:
        if response != Gtk.ResponseType.OK:
            return
        url = self.entry.get_text().strip()
        ok, message = self.on_add(url)
        if not ok:
            self.message.set_text(message)
            self.message.get_style_context().add_class("kabe-accent")


def _label(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.set_xalign(0.0)
    return label
