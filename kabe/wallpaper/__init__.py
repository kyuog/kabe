"""Selección del aplicador de fondo adecuado al entorno actual."""

from __future__ import annotations

from typing import Optional, Sequence

from ..models import Monitor
from .base import (
    Applier,
    FehApplier,
    GSettingsApplier,
    HyprpaperApplier,
    LxdeApplier,
    LxqtApplier,
    MateApplier,
    NitrogenApplier,
    PlasmaApplier,
    SwaybgApplier,
    SwwwApplier,
    VideoApplier,
    XfceApplier,
)
from .env import detect_desktop, detect_session_type, detect_window_manager

__all__ = [
    "Applier",
    "build_appliers",
    "get_applier",
    "XfceApplier",
    "GSettingsApplier",
    "MateApplier",
    "PlasmaApplier",
    "LxqtApplier",
    "LxdeApplier",
    "FehApplier",
    "NitrogenApplier",
    "SwwwApplier",
    "HyprpaperApplier",
    "SwaybgApplier",
    "VideoApplier",
]


def build_appliers() -> list[Applier]:
    """Todos los aplicadores, en orden de preferencia para el entorno actual."""
    desktop = detect_desktop()
    session = detect_session_type()
    wm = detect_window_manager()

    by_desktop = {
        "xfce": XfceApplier(),
        "kde": PlasmaApplier(),
        "cinnamon": GSettingsApplier("org.cinnamon.desktop.background", "Cinnamon"),
        "mate": MateApplier(),
        "lxqt": LxqtApplier(),
        "lxde": LxdeApplier(),
        "budgie": GSettingsApplier("org.gnome.desktop.background", "Budgie"),
        "deepin": GSettingsApplier("com.deepin.wrap.gnome.desktop.background", "Deepin"),
        "pantheon": GSettingsApplier("org.gnome.desktop.background", "Pantheon"),
        "elementary": GSettingsApplier("org.gnome.desktop.background", "elementary"),
        "unity": GSettingsApplier("org.gnome.desktop.background", "Unity"),
        "gnome": GSettingsApplier("org.gnome.desktop.background", "GNOME"),
    }

    ordered: list[Applier] = []
    if desktop in by_desktop:
        ordered.append(by_desktop[desktop])

    if session == "wayland":
        if wm == "hyprland":
            ordered.append(HyprpaperApplier())
        elif wm == "sway":
            ordered.append(SwaybgApplier())
        ordered.append(SwwwApplier())
    if wm == "hyprland":
        ordered.append(HyprpaperApplier())
    if wm == "sway":
        ordered.append(SwaybgApplier())

    ordered.append(FehApplier())
    ordered.append(NitrogenApplier())
    return ordered


def all_appliers() -> dict[str, Applier]:
    """Todos los aplicadores que existen, indexados por su id.

    Sirve para que la elección manual del usuario (Preferencias) gane siempre:
    si pide XFCE, se usa XFCE aunque la detección diga otra cosa.
    """
    return {
        "xfce": XfceApplier(),
        "gnome": GSettingsApplier("org.gnome.desktop.background", "GNOME"),
        "cinnamon": GSettingsApplier("org.cinnamon.desktop.background", "Cinnamon"),
        "mate": MateApplier(),
        "budgie": GSettingsApplier("org.gnome.desktop.background", "Budgie"),
        "deepin": GSettingsApplier("com.deepin.wrap.gnome.desktop.background", "Deepin"),
        "kde": PlasmaApplier(),
        "lxqt": LxqtApplier(),
        "lxde": LxdeApplier(),
        "feh": FehApplier(),
        "nitrogen": NitrogenApplier(),
        "swww": SwwwApplier(),
        "hyprpaper": HyprpaperApplier(),
        "swaybg": SwaybgApplier(),
        "video": VideoApplier(),
    }


def get_applier(preferred: str = "", kind: str = "image") -> Applier:
    """Devuelve el mejor aplicador disponible.

    `preferred` fuerza uno concreto (id), aunque la detección automática
    ponga otro. Si no está disponible, se cae al feh, que funciona en
    cualquier X11. Para vídeos se busca el reproductor de fondos animados
    (mpvpaper / xwinwrap+mpv).
    """
    if kind == "video":
        video = VideoApplier()
        if video.supported():
            return video
    registry = all_appliers()
    if preferred and preferred in registry:
        chosen = registry[preferred]
        if chosen.supported():
            return chosen
    candidates = build_appliers()
    for applier in candidates:
        if applier.supported():
            return applier
    return FehApplier()


def apply_wallpaper(
    applier: Applier,
    image_path: str,
    monitors: Sequence[Monitor],
    style: str = "scaled",
    to_all: bool = True,
) -> tuple[bool, str]:
    """Aplica el fondo y devuelve (ok, mensaje de error)."""
    if not monitors:
        return False, "No hay monitores: revisa la detección en Preferencias."
    if to_all:
        return applier.apply_to_all(image_path, monitors, style)
    return applier.apply_to_monitor(monitors[0], image_path, style)
