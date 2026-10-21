"""Vídeos de fondo (live wallpapers).

Kabe indexa también los vídeos de los repositorios y puede aplicarlos como
fondo animado. Para la miniatura no descarga el vídeo entero: usa `ffmpeg`
para extraer un fotograma directamente de la URL (basta con leer unos
pocos segundos por HTTP).

Si `ffmpeg` no está instalado, el vídeo se muestra con una tarjeta propia
en lugar de una miniatura.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

TIMEOUT = 25


def _run(cmd: list[str], timeout: int = TIMEOUT) -> tuple[int, bytes, str]:
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, b"", str(exc)
    return (
        proc.returncode,
        proc.stdout,
        proc.stderr.decode("utf-8", "replace").strip(),
    )


def have_ffmpeg() -> bool:
    from .util import have
    return have("ffmpeg")


def probe_video(path_or_url: str) -> dict:
    """Duración y resolución de un vídeo (ffprobe)."""
    code, out, _err = _run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path_or_url,
    ])
    if code != 0:
        return {}
    try:
        data = json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        return {}
    info: dict = {}
    duration = data.get("format", {}).get("duration")
    if duration:
        try:
            info["duration"] = int(float(duration))
        except (TypeError, ValueError):
            pass
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            info["width"] = int(stream.get("width") or 0)
            info["height"] = int(stream.get("height") or 0)
            break
    return info


def poster_bytes(path_or_url: str, at_seconds: float = 1.0) -> Optional[bytes]:
    """Un fotograma del vídeo como PNG (o None si no se puede)."""
    code, out, _err = _run([
        "ffmpeg", "-v", "quiet", "-ss", f"{at_seconds:.2f}", "-i", path_or_url,
        "-frames:v", "1", "-vf", "scale=320:-1", "-f", "image2pipe",
        "-vcodec", "png", "-",
    ])
    if code != 0 or not out:
        return None
    return out


def format_duration(seconds: int) -> str:
    """'1:23' o '0:07'."""
    if seconds <= 0:
        return "0:00"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"
