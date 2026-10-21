#!/usr/bin/env python3
"""Genera los iconos de Kabe a partir de kabe-icon.svg.

    python3 tools/make_icons.py

Crea:
    share/icons/hicolor/<tamaño>x<tamaño>/apps/kabe.png
    share/icons/hicolor/scalable/apps/kabe.svg
    share/icons/hicolor/symbolic/apps/kabe-symbolic.svg

Usa GdkPixbuf (ya presente en cualquier escritorio GTK) para rasterizar:
no hace falta ImageMagick, Inkscape ni cairosvg.
"""

from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render() -> int:
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError) as exc:
        print(f"No se puede rasterizar sin GdkPixbuf: {exc}", file=sys.stderr)
        return 1

    source = os.path.join(ROOT, "kabe-icon.svg")
    if not os.path.exists(source):
        print(f"Falta {source}", file=sys.stderr)
        return 1

    out_root = os.path.join(ROOT, "share", "icons", "hicolor")
    for size in SIZES:
        folder = os.path.join(out_root, f"{size}x{size}", "apps")
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, "kabe.png")
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(source, size, size, True)
        pixbuf.savev(target, "png", [], [])
        print(f"  {target} ({pixbuf.get_width()}×{pixbuf.get_height()})")

    scalable = os.path.join(out_root, "scalable", "apps")
    os.makedirs(scalable, exist_ok=True)
    shutil.copyfile(source, os.path.join(scalable, "kabe.svg"))

    symbolic = os.path.join(out_root, "symbolic", "apps")
    os.makedirs(symbolic, exist_ok=True)
    src_symbolic = os.path.join(ROOT, "icons", "kabe-symbolic.svg")
    if os.path.exists(src_symbolic):
        shutil.copyfile(src_symbolic, os.path.join(symbolic, "kabe-symbolic.svg"))

    # Copia del logo horizontal para el diálogo "Acerca de" y el README.
    logo_dir = os.path.join(ROOT, "share", "icons", "hicolor", "scalable", "apps")
    logo_src = os.path.join(ROOT, "kabe-logo.svg")
    if os.path.exists(logo_src):
        shutil.copyfile(logo_src, os.path.join(logo_dir, "kabe-logo.svg"))
    return 0


if __name__ == "__main__":
    sys.exit(render())
