"""Lectura de la cabecera de una imagen para conocer su resolución.

No descarga la imagen entera: pide sólo los primeros bytes con una petición
de rango (Range) y lee el tamaño en la cabecera JPEG/PNG/WebP/GIF/BMP.
"""

from __future__ import annotations

import struct
from typing import Optional

from .net import HttpClient, HttpError

# Cabeceras: 32 KB bastan para PNG/WebP/GIF; los JPEG necesitan algo más
# porque el marcador SOF puede aparecer tarde.
RANGE_PNG = 64
RANGE_JPEG = 131072


def image_size_from_bytes(data: bytes) -> tuple[int, int] | None:
    """Devuelve (ancho, alto) leyendo la cabecera, o None si no se entiende."""
    if not data:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png_size(data)
    if data[:3] == b"\xff\xd8\xff":
        return _jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return _gif_size(data)
    if data[:2] == b"BM":
        return _bmp_size(data)
    return None


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    index = 2
    length = len(data)
    while index < length - 9:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xD9:  # EOI
            break
        if index + 4 > length:
            break
        seg_len = struct.unpack(">H", data[index + 2:index + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if index + 9 <= length:
                height, width = struct.unpack(">HH", data[index + 5:index + 9])
                return int(width), int(height)
            break
        index += 2 + seg_len
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8 ":
        index = data.find(b"\x9d\x01\x2a")
        if index < 0 or index + 7 > len(data):
            return None
        width, height = struct.unpack("<HH", data[index + 3:index + 7])
        return int(width & 0x3FFF), int(height & 0x3FFF)
    if chunk == b"VP8L":
        if len(data) < 25:
            return None
        bits = struct.unpack("<I", data[21:25])[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk == b"VP8X":
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


def _gif_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10:
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return int(width), int(height)


def _bmp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 26:
        return None
    width, height = struct.unpack("<ii", data[18:26])
    return int(abs(width)), int(abs(height))


def probe_resolution(
    http: HttpClient, url: str, ext: str = ""
) -> tuple[int, int] | None:
    """Pide la cabecera por rango y devuelve la resolución si se puede leer."""
    span = RANGE_JPEG if ext.lower() in (".jpg", ".jpeg") else RANGE_PNG
    try:
        data, _meta = http.get_bytes(url, start=0, end=span - 1)
    except (HttpError, OSError):
        return None
    return image_size_from_bytes(data)
