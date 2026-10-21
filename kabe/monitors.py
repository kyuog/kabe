"""Detección de monitores.

X11: xrandr. Wayland: wlr-randr, hyprctl, swaymsg o kscreen-doctor.
Si nada responde se cae a la información de GDK y, como último recurso,
a la resolución manual que el usuario indique.

Todas las funciones de análisis son puras (reciben texto o JSON) para poder
probarse sin hardware.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Optional

from .models import Monitor, MonitorLayout
from .util import have

TIMEOUT = 6


# --------------------------------------------------------------------- utils
def _run(cmd: list[str]) -> tuple[int, str]:
    """Ejecuta un comando y devuelve (código, salida). Nunca lanza."""
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _session_type() -> str:
    kind = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if kind in ("x11", "wayland"):
        return kind
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return ""


# -------------------------------------------------------------------- xrandr
_XRANDR_HEADER = re.compile(r"^Screen\s+\d+:", re.IGNORECASE)
_XRANDR_OUTPUT = re.compile(
    r"^(?P<name>\S+)\s+(?P<status>connected|disconnected)\b(?P<rest>.*)$"
)
_XRANDR_GEOM = re.compile(r"(?P<w>\d+)x(?P<h>\d+)\+(?P<x>\d+)\+(?P<y>\d+)")
_XRANDR_MM = re.compile(r"(?P<w>\d+)mm\s*x\s*(?P<h>\d+)mm")
_XRANDR_MODE = re.compile(r"^\s+(?P<w>\d+)x(?P<h>\d+)\s+(?P<rates>.*)$")


def parse_xrandr(text: str) -> list[Monitor]:
    """Convierte la salida de `xrandr --query` en monitores."""
    monitors: list[Monitor] = []
    current: Monitor | None = None
    for line in text.splitlines():
        if _XRANDR_HEADER.match(line):
            continue
        out = _XRANDR_OUTPUT.match(line.strip())
        if out:
            if current is not None:
                monitors.append(current)
            current = Monitor(name=out.group("name"), backend="xrandr")
            rest = out.group("rest")
            current.connected = out.group("status") == "connected"
            current.primary = "primary" in rest.split("(")[0]
            geom = _XRANDR_GEOM.search(rest)
            if geom:
                current.width = int(geom.group("w"))
                current.height = int(geom.group("h"))
                current.x = int(geom.group("x"))
                current.y = int(geom.group("y"))
            mm = _XRANDR_MM.search(rest)
            if mm:
                current.physical_mm = (int(mm.group("w")), int(mm.group("h")))
            continue
        if current is not None:
            mode = _XRANDR_MODE.match(line)
            if mode:
                # La frecuencia actual de xrandr lleva un asterisco: "59.79*+"
                rates = mode.group("rates")
                marked = re.search(r"(\d+(?:\.\d+)?)\s*\*", rates)
                if marked:
                    current.refresh = float(marked.group(1))
    if current is not None:
        monitors.append(current)
    return [m for m in monitors if m.connected and m.width]


# ----------------------------------------------------------------- wlr-randr
def parse_wlr_randr(text: str) -> list[Monitor]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    monitors: list[Monitor] = []
    for out in data.get("outputs", []) or []:
        if not out.get("current_mode"):
            continue
        mode = out["current_mode"]
        pos = out.get("position") or {}
        scale = float(out.get("scale") or 1.0)
        transform = str(out.get("transform") or "")
        rot = {"90": 90, "180": 180, "270": 270, "flipped": 270}.get(transform, 0)
        mon = Monitor(
            name=out.get("name") or "",
            label=(out.get("make") or "") + " " + (out.get("model") or ""),
            backend="wlr-randr",
            width=int(mode.get("width") or 0),
            height=int(mode.get("height") or 0),
            refresh=float(mode.get("refresh") or 0.0),
            scale=scale,
            x=int(pos.get("x") or 0),
            y=int(pos.get("y") or 0),
            rotation=rot,
            primary=bool(out.get("primary")),
            connected=bool(out.get("enabled", True)),
            physical_mm=(int(out.get("physical_width") or 0), int(out.get("physical_height") or 0)),
        )
        monitors.append(mon)
    return [m for m in monitors if m.width]


# ------------------------------------------------------------------- hyprctl
def parse_hyprctl_monitors(text: str) -> list[Monitor]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    monitors: list[Monitor] = []
    for out in data or []:
        if not out.get("active"):
            continue
        transform = int(out.get("transform") or 0)
        monitors.append(Monitor(
            name=out.get("name") or "",
            label=out.get("description") or "",
            backend="hyprctl",
            width=int(out.get("width") or 0),
            height=int(out.get("height") or 0),
            refresh=float(out.get("refreshRate") or 0.0) / 1000.0,
            scale=float(out.get("scale") or 1.0),
            x=int(out.get("x") or 0),
            y=int(out.get("y") or 0),
            rotation=transform,
            primary=bool(out.get("focused")),
            connected=True,
        ))
    return [m for m in monitors if m.width]


# ------------------------------------------------------------------- swaymsg
def parse_sway_outputs(text: str) -> list[Monitor]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    monitors: list[Monitor] = []
    for out in data or []:
        if not out.get("active"):
            continue
        rect = out.get("rect") or {}
        mode = out.get("current_mode") or {}
        monitors.append(Monitor(
            name=out.get("name") or "",
            label=(out.get("make") or "") + " " + (out.get("model") or ""),
            backend="swaymsg",
            width=int(rect.get("width") or 0),
            height=int(rect.get("height") or 0),
            refresh=float(mode.get("refresh") or 0.0),
            scale=float(out.get("scale") or 1.0),
            x=int(rect.get("x") or 0),
            y=int(rect.get("y") or 0),
            primary=bool(out.get("focused")),
            connected=True,
        ))
    return [m for m in monitors if m.width]


# ------------------------------------------------------------- kscreen-doctor
def parse_kscreen(text: str) -> list[Monitor]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    monitors: list[Monitor] = []
    for out in data.get("outputs", []) or []:
        if not out.get("connected"):
            continue
        geom = out.get("geometry") or {}
        pos = out.get("pos") or {}
        monitors.append(Monitor(
            name=out.get("name") or "",
            label=out.get("model") or "",
            backend="kscreen-doctor",
            width=int(geom.get("width") or 0),
            height=int(geom.get("height") or 0),
            refresh=float(out.get("refreshRate") or 0.0),
            scale=float(out.get("scale") or 1.0),
            x=int(pos.get("x") or 0),
            y=int(pos.get("y") or 0),
            primary=bool(out.get("primary")),
            connected=True,
        ))
    return [m for m in monitors if m.width]


# ----------------------------------------------------------------------- GDK
def detect_monitors_gdk() -> list[Monitor]:
    """Información de GDK: siempre disponible, pero sin frecuencia ni escala
    en algunos backends."""
    try:
        import gi
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
    except (ImportError, ValueError):
        return []
    monitors: list[Monitor] = []
    try:
        display = Gdk.Display.get_default()
        if display is None:
            return []
        count = display.get_n_monitors()
        for index in range(count):
            mon = display.get_monitor(index)
            if mon is None:
                continue
            geom = mon.get_geometry()
            scale = 1.0
            try:
                scale = float(mon.get_scale_factor())
            except AttributeError:
                pass
            refresh = 0.0
            try:
                refresh = float(mon.get_refresh_rate())
            except AttributeError:
                pass
            model = mon.get_model() or ""
            manufacturer = mon.get_manufacturer() or ""
            monitors.append(Monitor(
                name=model or f"monitor-{index}",
                label=(manufacturer + " " + model).strip(),
                backend="gdk",
                width=geom.width,
                height=geom.height,
                refresh=refresh,
                scale=scale,
                x=geom.x,
                y=geom.y,
                primary=(index == 0),
                connected=True,
            ))
    except Exception:  # pragma: no cover - GDK puede fallar en sesiones raras
        return []
    return [m for m in monitors if m.width]


# ------------------------------------------------------------------ público
def detect_monitors(manual: str = "") -> MonitorLayout:
    """Detecta los monitores del sistema. `manual` es una alternativa del
    usuario con el formato '1920x1080' (o '1920x1080+3840x1080')."""
    layout = MonitorLayout()
    kind = _session_type()

    attempts: list[tuple[str, Any]] = []
    if kind == "wayland":
        attempts = [
            ("wlr-randr", _cmd_wlr_randr),
            ("hyprctl", _cmd_hyprctl),
            ("swaymsg", _cmd_swaymsg),
            ("kscreen-doctor", _cmd_kscreen),
        ]
    else:
        attempts = [
            ("xrandr", _cmd_xrandr),
            ("wlr-randr", _cmd_wlr_randr),
            ("hyprctl", _cmd_hyprctl),
            ("swaymsg", _cmd_swaymsg),
            ("kscreen-doctor", _cmd_kscreen),
        ]

    errors: list[str] = []
    for backend, runner in attempts:
        try:
            monitors = runner()
        except Exception as exc:  # pragma: no cover
            errors.append(f"{backend}: {exc}")
            continue
        if monitors:
            layout.monitors = monitors
            layout.backend = backend
            layout.error = ""
            return layout

    gdk_monitors = detect_monitors_gdk()
    if gdk_monitors:
        layout.monitors = gdk_monitors
        layout.backend = "gdk"
        return layout

    manual_monitors = parse_manual(manual)
    if manual_monitors:
        layout.monitors = manual_monitors
        layout.backend = "manual"
        return layout

    layout.backend = "ninguno"
    layout.error = (
        "No se han podido detectar los monitores. "
        "Indica la resolución manualmente en Preferencias."
    )
    return layout


def parse_manual(spec: str) -> list[Monitor]:
    """'1920x1080' o '1920x1080+3840x1080' → lista de monitores."""
    spec = (spec or "").strip()
    if not spec:
        return []
    monitors: list[Monitor] = []
    x = 0
    for chunk in spec.split("+"):
        chunk = chunk.strip()
        if "x" not in chunk:
            continue
        w, _, h = chunk.partition("x")
        try:
            width, height = int(w), int(h)
        except ValueError:
            continue
        if width <= 0 or height <= 0:
            continue
        monitors.append(Monitor(
            name=f"manual-{len(monitors) + 1}",
            label="Resolución manual",
            backend="manual",
            width=width,
            height=height,
            x=x,
            y=0,
            primary=(len(monitors) == 0),
        ))
        x += width
    return monitors


# ------------------------------------------------------------- ejecutores
def _cmd_xrandr() -> list[Monitor]:
    if not have("xrandr"):
        return []
    code, out = _run(["xrandr", "--query"])
    if code != 0:
        return []
    return parse_xrandr(out)


def _cmd_wlr_randr() -> list[Monitor]:
    if not have("wlr-randr"):
        return []
    code, out = _run(["wlr-randr"])
    if code != 0:
        return []
    return parse_wlr_randr(out)


def _cmd_hyprctl() -> list[Monitor]:
    if not have("hyprctl"):
        return []
    code, out = _run(["hyprctl", "monitors", "-j"])
    if code != 0:
        return []
    return parse_hyprctl_monitors(out)


def _cmd_swaymsg() -> list[Monitor]:
    if not have("swaymsg"):
        return []
    code, out = _run(["swaymsg", "-t", "get_outputs", "-r"])
    if code != 0:
        return []
    return parse_sway_outputs(out)


def _cmd_kscreen() -> list[Monitor]:
    if not have("kscreen-doctor"):
        return []
    code, out = _run(["kscreen-doctor", "-j"])
    if code != 0:
        return []
    return parse_kscreen(out)
