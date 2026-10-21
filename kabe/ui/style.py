"""Identidad visual de Kabe.

La app respeta el tema GTK del sistema (claro u oscuro) y aplica la paleta
de Kabe sólo en sus propios elementos: barra superior, acentos, maqueta de
monitores y diálogo "Acerca de".

Paleta de marca (tres colores, nada más):
    Índigo   #232A4D  color principal, fondos de marca, texto sobre claro
    Neblina  #E8F1F2  superficies claras, texto sobre oscuro
    Ámbar    #F2A541  acento único, con mucha moderación
"""

from __future__ import annotations

import os
from typing import Optional

INDIGO = "#232A4D"
NEBLINA = "#E8F1F2"
AMBER = "#F2A541"

# Derivados del índigo (aclarado/oscurecido) y de la neblina.
INDIGO_SOFT = "#39416B"
INDIGO_DEEP = "#171C36"
NEBLINA_DIM = "#CFDDDF"
NEBLINA_DARK = "#1A1F33"

# Radio de esquina de la marca (23 % del lado) → en una maqueta de 120 px
# son ~28 px; el logo usa rx=58 sobre 256.
LOGO_RADIUS_RATIO = 0.23


def is_dark_theme() -> bool:
    """¿El tema GTK actual es oscuro?"""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except (ImportError, ValueError):
        return False
    settings = Gtk.Settings.get_default()
    if settings is None:
        return False
    try:
        if settings.get_property("gtk-application-prefer-dark-theme"):
            return True
    except Exception:
        pass
    try:
        theme = settings.get_property("gtk-theme-name") or ""
    except Exception:
        theme = ""
    theme = theme.lower()
    return "dark" in theme or theme in ("adwaita-dark", "yaru-dark", "highcontrast")


def relative_luminance(hex_color: str) -> float:
    """Luminancia WCAG de un color #RRGGBB."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    channels = []
    for i in range(0, 6, 2):
        value = int(hex_color[i:i + 2], 16) / 255.0
        if value <= 0.03928:
            channels.append(value / 12.92)
        else:
            channels.append(((value + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color_a: str, color_b: str) -> float:
    """Ratio de contraste WCAG entre dos colores."""
    lum_a = relative_luminance(color_a)
    lum_b = relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def css_text(dark: bool | None = None) -> str:
    """CSS mínimo para los elementos propios de Kabe."""
    if dark is None:
        dark = is_dark_theme()
    if dark:
        topbar_bg = INDIGO
        topbar_fg = NEBLINA
        surface = NEBLINA_DARK
        surface_fg = NEBLINA
        muted = "#9AA6B8"
        border = "#39416B"
    else:
        topbar_bg = NEBLINA
        topbar_fg = INDIGO
        surface = "#FFFFFF"
        surface_fg = INDIGO
        muted = "#5A6480"
        border = NEBLINA_DIM
    return f"""
/* Barra superior: la marca se ve sin robarle sitio a la imagen. */
.kabe-topbar {{
    background-color: {topbar_bg};
    color: {topbar_fg};
    padding: 6px 10px;
    border-bottom: 1px solid {border};
}}
.kabe-brand {{
    color: {topbar_fg};
    font-weight: 700;
    font-size: 15px;
}}
.kabe-brand-mark {{
    color: {topbar_fg};
    opacity: 0.92;
}}
.kabe-topbar entry {{
    background-color: {surface};
    color: {surface_fg};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 5px 10px;
    min-height: 22px;
}}
.kabe-topbar button {{
    color: {topbar_fg};
    background-image: none;
    background-color: rgba(255,255,255,0.08);
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 4px 10px;
}}
.kabe-topbar button:hover {{
    background-color: rgba(255,255,255,0.18);
}}
/* Botón principal: ámbar, y sólo el principal. */
.kabe-primary {{
    background-color: {AMBER};
    color: {INDIGO};
    border: none;
    border-radius: 10px;
    padding: 6px 14px;
    font-weight: 600;
}}
.kabe-primary:hover {{ background-color: #F6B35C; }}
.kabe-primary:disabled {{ background-color: rgba(242,165,65,0.35); color: rgba(35,42,77,0.6); }}
/* Tarjetas de detalle y paneles propios. */
.kabe-surface {{
    background-color: {surface};
    color: {surface_fg};
    border: 1px solid {border};
    border-radius: 12px;
    padding: 10px;
}}
.kabe-muted {{ color: {muted}; font-size: 11px; }}
.kabe-chip {{
    background-color: {NEBLINA_DIM if not dark else INDIGO_SOFT};
    color: {INDIGO if not dark else NEBLINA};
    border-radius: 8px;
    padding: 1px 7px;
    font-size: 11px;
}}
.kabe-accent {{
    color: {AMBER};
}}
/* Maqueta de monitores: mismo radio que el logo. */
.kabe-monitor {{
    border: 2px solid {border};
    border-radius: 14px;
    background-color: {INDIGO_DEEP};
}}
.kabe-monitor-active {{
    border: 2px solid {AMBER};
    border-radius: 14px;
    background-color: {INDIGO_DEEP};
}}
.kabe-monitor-label {{
    color: {muted};
    font-size: 10px;
}}
.kabe-statusbar {{
    background-color: {surface};
    color: {muted};
    border-top: 1px solid {border};
    padding: 4px 10px;
    font-size: 11px;
}}
.kabe-empty {{
    color: {muted};
    font-size: 14px;
}}
"""


def install_css() -> None:
    """Aplica el CSS de Kabe al tema actual."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk
    except (ImportError, ValueError):
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(css_text())
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    Gtk.StyleContext.remove_provider_for_screen(screen, provider)  # type: ignore[arg-type]
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def logo_pixbuf(size: int = 128):
    """El logo de Kabe como pixbuf (desde el SVG del proyecto)."""
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError):
        return None
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in (
        os.path.join(here, "kabe-icon.svg"),
        os.path.join(here, "..", "kabe-icon.svg"),
    ):
        path = os.path.normpath(candidate)
        if os.path.exists(path):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
            except Exception:
                continue
    return None


def app_icon_name() -> str:
    """Nombre de icono en el tema (si el paquete lo instaló)."""
    return "kabe"
