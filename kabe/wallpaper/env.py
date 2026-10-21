"""Detección del escritorio y del gestor de ventanas."""

from __future__ import annotations

import os


def _env_values() -> list[str]:
    values: list[str] = []
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        raw = os.environ.get(var, "")
        for part in raw.split(":"):
            part = part.strip().lower()
            if part:
                values.append(part)
    return values


def detect_desktop() -> str:
    """Devuelve un identificador de escritorio: xfce, gnome, kde, cinnamon…"""
    values = _env_values()
    for value in values:
        if "xfce" in value:
            return "xfce"
    for value in values:
        if "kde" in value or "plasma" in value:
            return "kde"
    for value in values:
        if "cinnamon" in value:
            return "cinnamon"
    for value in values:
        if "mate" in value:
            return "mate"
    for value in values:
        if "lxqt" in value:
            return "lxqt"
    for value in values:
        if "lxde" in value:
            return "lxde"
    for value in values:
        if "budgie" in value:
            return "budgie"
    for value in values:
        if "deepin" in value:
            return "deepin"
    for value in values:
        if "pantheon" in value:
            return "pantheon"
    for value in values:
        if "elementary" in value:
            return "elementary"
    for value in values:
        if "unity" in value:
            return "unity"
    for value in values:
        if "gnome" in value:
            return "gnome"
    return ""


def detect_session_type() -> str:
    kind = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if kind in ("x11", "wayland"):
        return kind
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return ""


def detect_window_manager() -> str:
    """sway, hyprland, i3, xfwm4… si se puede saber."""
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if os.environ.get("SWAYSOCK"):
        return "sway"
    if os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("i3") >= 0:
        return "i3"
    return ""


def describe_environment() -> str:
    """Texto corto para la interfaz: 'XFCE · X11'."""
    desktop = detect_desktop()
    session = detect_session_type()
    wm = detect_window_manager()
    parts = []
    if desktop:
        parts.append(desktop.upper())
    if wm:
        parts.append(wm)
    if session:
        parts.append(session.upper())
    return " · ".join(parts) if parts else "escritorio desconocido"
