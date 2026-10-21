"""Aplicadores de fondo de pantalla.

Cada clase sabe poner un fondo en un entorno concreto (XFCE, GNOME, KDE…) o
en un gestor de ventanas (feh, swww, hyprpaper…). La app elige el
aplicador adecuado según el escritorio detectado y siempre puede recurrir a
feh como último recurso.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional, Sequence

from ..models import Monitor
from ..util import have

TIMEOUT = 20


def run_cmd(cmd: Sequence[str], timeout: int = TIMEOUT) -> tuple[int, str, str]:
    """Ejecuta un comando: (código, stdout, stderr)."""
    try:
        proc = subprocess.run(
            list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "tiempo de espera agotado"
    except OSError as exc:
        return 127, "", str(exc)
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace").strip(),
        proc.stderr.decode("utf-8", "replace").strip(),
    )


def file_uri(path: str) -> str:
    return "file://" + os.path.abspath(path)


class Applier:
    """Interfaz común de los aplicadores."""

    id: str = ""
    name: str = ""
    per_monitor: bool = True

    def supported(self) -> bool:
        return True

    # ------------------------------------------------------------ aplicación
    def apply_to_monitor(
        self, monitor: Monitor, image_path: str, style: str = "scaled"
    ) -> tuple[bool, str]:
        raise NotImplementedError

    def apply_to_all(
        self, image_path: str, monitors: Sequence[Monitor], style: str = "scaled"
    ) -> tuple[bool, str]:
        """Por defecto, se aplica al monitor principal y se propaga al resto
        cuando el entorno no distingue entre pantallas."""
        if not monitors:
            return False, "No hay monitores detectados."
        return self.apply_to_monitor(monitors[0], image_path, style)

    # ------------------------------------------------------------ utilidades
    def describe(self) -> str:
        return self.name


# --------------------------------------------------------------------- XFCE
XFCE_STYLES = {
    "tiled": 0,
    "scaled": 1,
    "stretched": 2,
    "centered": 3,
    "zoomed": 4,
    "shrunk": 5,
}


class XfceApplier(Applier):
    """XFCE (prioridad: MX Linux). Usa xfconf-query sobre xfce4-desktop."""

    id = "xfce"
    name = "XFCE"

    def supported(self) -> bool:
        return have("xfconf-query")

    def _set(self, prop: str, value: str, kind: str = "string") -> tuple[bool, str]:
        # --create: XFCE sólo tiene creadas las propiedades que ya usó;
        # las demás (image-style, image-show…) hay que crearlas, y para eso
        # xfconf-query exige indicar el tipo del valor.
        code, _out, err = run_cmd([
            "xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", value,
            "--create", "--type", kind,
        ])
        if code != 0:
            return False, err or f"xfconf-query falló en {prop}"
        return True, ""

    def _monitor_ids(self) -> list[str]:
        """Identificadores de monitor que XFCE ya tiene configurados."""
        code, out, _err = run_cmd(["xfconf-query", "-c", "xfce4-desktop", "-l"])
        if code != 0:
            return []
        import re
        ids: list[str] = []
        for line in out.splitlines():
            match = re.match(r"^/backdrop/screen\d+/monitor([^/]+)/", line.strip())
            if match and match.group(1) not in ids:
                ids.append(match.group(1))
        return ids

    def _ids_for(self, monitor: Monitor, ids: list[str]) -> list[str]:
        if not ids:
            # Todavía no hay propiedades: se usa el nombre del conector
            # (HDMI-1, DP-2…) y el identificador antiguo por compatibilidad.
            candidates = [monitor.name, "monitor0"]
            return [c for c in candidates if c]
        name = (monitor.name or "").strip()
        if name and name in ids:
            return [name]
        legacy = f"monitor{monitor.name}"
        if legacy in ids:
            return [legacy]
        # Coincidencia sin guiones (HDMI-1 vs HDMI1)
        flat = name.replace("-", "").replace("_", "")
        for candidate in ids:
            if candidate.replace("-", "").replace("_", "") == flat:
                return [candidate]
        return [ids[0]]

    def apply_to_monitor(
        self, monitor: Monitor, image_path: str, style: str = "scaled"
    ) -> tuple[bool, str]:
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        uri = file_uri(image_path)
        style_code = XFCE_STYLES.get(style, XFCE_STYLES["scaled"])
        ids = self._monitor_ids()
        targets = self._ids_for(monitor, ids)
        errors: list[str] = []
        for mid in targets:
            for workspace in range(4):
                base = f"/backdrop/screen0/monitor{mid}/workspace{workspace}"
                for prop, value, kind in (
                    ("image-show", "true", "bool"),
                    ("color-style", "0", "int"),
                    ("image-style", str(style_code), "int"),
                    ("last-image", uri, "string"),
                ):
                    ok, err = self._set(f"{base}/{prop}", value, kind)
                    if not ok:
                        errors.append(err)
        if errors:
            return False, errors[0]
        return True, ""

    def apply_to_all(
        self, image_path: str, monitors: Sequence[Monitor], style: str = "scaled"
    ) -> tuple[bool, str]:
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        uri = file_uri(image_path)
        style_code = XFCE_STYLES.get(style, XFCE_STYLES["scaled"])
        ids = self._monitor_ids()
        if ids:
            targets = ids
        else:
            targets = [m.name for m in monitors if m.name] or ["monitor0"]
        errors: list[str] = []
        for mid in targets:
            for workspace in range(4):
                base = f"/backdrop/screen0/monitor{mid}/workspace{workspace}"
                for prop, value, kind in (
                    ("image-show", "true", "bool"),
                    ("color-style", "0", "int"),
                    ("image-style", str(style_code), "int"),
                    ("last-image", uri, "string"),
                ):
                    ok, err = self._set(f"{base}/{prop}", value, kind)
                    if not ok:
                        errors.append(err)
        if errors:
            return False, errors[0]
        return True, ""


# -------------------------------------------------------------------- GNOME
class GSettingsApplier(Applier):
    """GNOME, Budgie, Cinnamon, Deepin y MATE: todos basado en gsettings."""

    schema = "org.gnome.desktop.background"
    dark_schema = ""

    def __init__(self, schema: str = "org.gnome.desktop.background", name: str = "GNOME",
                 dark_schema: str = "", filename_key: bool = False):
        self.schema = schema
        self.dark_schema = dark_schema
        self.name = name
        self.filename_key = filename_key

    def supported(self) -> bool:
        return have("gsettings")

    def _has_key(self, schema: str, key: str) -> bool:
        """¿Existe esa clave en el esquema? (gsettings range sale con error si no)"""
        code, _out, _err = run_cmd(["gsettings", "range", schema, key])
        return code == 0

    def apply_to_monitor(
        self, monitor: Monitor, image_path: str, style: str = "scaled"
    ) -> tuple[bool, str]:
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        uri = file_uri(image_path)
        value = os.path.abspath(image_path) if self.filename_key else uri
        errors: list[str] = []
        for key in ("picture-uri", "picture-filename"):
            if not self._has_key(self.schema, key):
                continue
            code, _out, err = run_cmd(["gsettings", "set", self.schema, key, value])
            if code != 0:
                errors.append(err or f"gsettings: {key}")
        if self.dark_schema:
            for key in ("picture-uri", "picture-filename"):
                if not self._has_key(self.dark_schema, key):
                    continue
                code, _out, err = run_cmd(
                    ["gsettings", "set", self.dark_schema, key, value]
                )
                if code != 0:
                    errors.append(err or f"gsettings: {key}")
        if errors:
            return False, errors[0]
        return True, ""


class MateApplier(GSettingsApplier):
    def __init__(self):
        super().__init__("org.mate.background", "MATE", filename_key=True)

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        ok, err = super().apply_to_monitor(monitor, image_path, style)
        if ok:
            run_cmd(["gsettings", "set", "org.mate.background", "picture-options", "zoom"])
        return ok, err


# ---------------------------------------------------------------------- KDE
class PlasmaApplier(Applier):
    """KDE Plasma 5 y 6."""

    id = "kde"
    name = "KDE Plasma"

    def supported(self) -> bool:
        return have("plasma-apply-wallpaperimage") or have("qdbus") or have("qdbus6")

    def apply_to_monitor(
        self, monitor: Monitor, image_path: str, style: str = "scaled"
    ) -> tuple[bool, str]:
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        if have("plasma-apply-wallpaperimage"):
            code, _out, err = run_cmd(["plasma-apply-wallpaperimage", image_path])
            if code == 0:
                return True, ""
            if err:
                return False, err
        return self._via_qdbus(image_path)

    def _via_qdbus(self, image_path: str) -> tuple[bool, str]:
        last = "No se pudo hablar con Plasma."
        for dbus, service in (("qdbus6", "org.kde.plasmashell"), ("qdbus", "org.kde.plasmashell")):
            if not have(dbus):
                continue
            script = (
                "var d=desktops();"
                f"for(i=0;i<d.length;i++){{"
                "d[i].wallpaperPlugin='org.kde.image';"
                "d[i].currentConfigGroup=Array('Wallpaper','org.kde.image','General');"
                f"d[i].writeConfig('Image','file://{image_path}');"
                "d[i].writeConfig('FillMode', 2);"
                "}"
            )
            code, _out, err = run_cmd(
                [dbus, service, "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script]
            )
            if code == 0:
                return True, ""
            last = err
        return False, last

    def apply_to_all(self, image_path, monitors, style="scaled"):
        return self.apply_to_monitor(monitors[0] if monitors else Monitor(), image_path, style)


# -------------------------------------------------------------------- LXQt
class LxqtApplier(Applier):
    id = "lxqt"
    name = "LXQt"

    def supported(self) -> bool:
        return have("pcmanfm-qt")

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        code, _out, err = run_cmd(["pcmanfm-qt", f"--set-wallpaper={image_path}"])
        if code != 0:
            return False, err or "pcmanfm-qt no pudo aplicar el fondo."
        return True, ""


# -------------------------------------------------------------------- LXDE
class LxdeApplier(Applier):
    id = "lxde"
    name = "LXDE"

    def supported(self) -> bool:
        return have("pcmanfm")

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        code, _out, err = run_cmd(["pcmanfm", f"--set-wallpaper={image_path}"])
        if code != 0:
            return False, err or "pcmanfm no pudo aplicar el fondo."
        return True, ""


# ----------------------------------------------- gestores de ventanas (WM)
class FehApplier(Applier):
    """feh: funciona en cualquier X11 y es el último recurso."""

    id = "feh"
    name = "feh"

    def supported(self) -> bool:
        return have("feh")

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        cmd = ["feh", "--no-fehbg"]
        if monitor.width and monitor.height:
            cmd += ["--bg-fill", f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}"]
        else:
            cmd += ["--bg-fill"]
        cmd.append(image_path)
        code, _out, err = run_cmd(cmd)
        if code != 0:
            return False, err or "feh no pudo aplicar el fondo."
        return True, ""

    def apply_to_all(self, image_path, monitors, style="scaled"):
        if not monitors:
            return False, "No hay monitores detectados."
        cmd = ["feh", "--no-fehbg"]
        for monitor in monitors:
            cmd += ["--bg-fill", f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}"]
        cmd.append(image_path)
        code, _out, err = run_cmd(cmd)
        if code != 0:
            return False, err or "feh no pudo aplicar el fondo."
        return True, ""


class NitrogenApplier(Applier):
    id = "nitrogen"
    name = "nitrogen"

    def supported(self) -> bool:
        return have("nitrogen")

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        mode = "zoom" if style in ("zoomed", "scaled") else "centered"
        code, _out, err = run_cmd(["nitrogen", f"--set-zoom-{mode}", image_path])
        if code != 0:
            return False, err or "nitrogen no pudo aplicar el fondo."
        return True, ""


class SwwwApplier(Applier):
    """swww (Wayland) — requiere el demonio swww-daemon en marcha."""

    id = "swww"
    name = "swww"

    def supported(self) -> bool:
        return have("swww")

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        cmd = ["swww", "img", "load", image_path]
        if monitor.name:
            cmd += ["--outputs", monitor.name]
        code, _out, err = run_cmd(cmd)
        if code != 0:
            return False, err or "swww no pudo aplicar el fondo (¿está swww-daemon en marcha?)."
        return True, ""


class HyprpaperApplier(Applier):
    id = "hyprpaper"
    name = "hyprpaper"

    def supported(self) -> bool:
        return have("hyprpaper") or have("hyprctl")

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        if have("hyprctl"):
            code, _out, err = run_cmd(
                ["hyprctl", "hyprpaper", "wallpaper", f",{image_path}", "kabe"]
            )
            if code == 0:
                return True, ""
            if err:
                return False, err
        return False, "hyprctl no pudo cambiar el fondo."


class SwaybgApplier(Applier):
    id = "swaybg"
    name = "swaybg"

    def supported(self) -> bool:
        return have("swaybg")

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "La imagen no existe en disco."
        cmd = ["swaybg", "-m", "-i", image_path]
        if monitor.name:
            cmd += ["-o", monitor.name]
        code, _out, err = run_cmd(cmd)
        if code != 0:
            return False, err or "swaybg no pudo aplicar el fondo."
        return True, ""


class VideoApplier(Applier):
    """Fondos animados.

    Sway: mpvpaper (crea una capa con el vídeo en bucle).
    X11:  xwinwrap + mpv a pantalla completa.
    """

    id = "video"
    name = "Vídeo"

    def supported(self) -> bool:
        if have("mpvpaper") and os.environ.get("SWAYSOCK"):
            return True
        return have("xwinwrap") and have("mpv")

    def _command(self) -> list[str] | None:
        if have("mpvpaper") and os.environ.get("SWAYSOCK"):
            return ["mpvpaper"]
        if have("xwinwrap") and have("mpv"):
            return [
                "xwinwrap", "-d", "0", "--", "mpv",
                "--loop", "--no-audio", "--fs", "--really-quiet",
            ]
        return None

    def apply_to_monitor(self, monitor, image_path, style="scaled"):
        if not os.path.exists(image_path):
            return False, "El vídeo no existe en disco."
        command = self._command()
        if command is None:
            if have("mpvpaper") and not os.environ.get("SWAYSOCK"):
                return False, (
                    "mpvpaper está instalado, pero sólo funciona en Sway (Wayland). "
                    "En X11 necesitas xwinwrap con mpv."
                )
            return False, (
                "Para aplicar un vídeo necesitas mpvpaper (Sway) o xwinwrap con mpv (X11). "
                "Instala uno de los dos y vuelve a intentarlo."
            )
        cmd = command + [image_path]
        try:
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            return False, f"No se pudo iniciar el reproductor: {exc}"
        return True, ""
