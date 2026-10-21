#!/usr/bin/env python3
"""Prepara la web de Kabe en dist/site.

    python3 tools/build_site.py

Copia el HTML, el logo, las capturas y los paquetes de descarga a
dist/site/, listo para subirlo a cualquier hosting estático (GitHub Pages,
Netlify, un nginx…). Cuando tengas el dominio, sólo hay que subir esta
carpeta.
"""

from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "site")


def copy(src: str, dst: str) -> bool:
    if not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    copied = []

    for name in ("index.html", "favicon.svg", "vercel.json"):
        if copy(os.path.join(ROOT, "site", name), os.path.join(OUT, name)):
            copied.append(name)
    if copy(os.path.join(ROOT, "kabe-icon.svg"), os.path.join(OUT, "kabe.svg")):
        copied.append("kabe.svg")
    if copy(os.path.join(ROOT, "kabe-logo.svg"), os.path.join(OUT, "kabe-logo.svg")):
        copied.append("kabe-logo.svg")

    for name in ("screenshot-main.png", "screenshot-preview.png",
                 "screenshot-search.png"):
        if copy(os.path.join(ROOT, "docs", name), os.path.join(OUT, name)):
            copied.append(name)

    # Paquetes de descarga: primero la carpeta releases/ (versionada en el
    # repositorio, para que Vercel también los sirva) y luego dist/.
    downloads = os.path.join(OUT, "descargas")
    os.makedirs(downloads, exist_ok=True)
    for folder in (os.path.join(ROOT, "releases"), os.path.join(ROOT, "dist")):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.endswith((".deb", ".AppImage")):
                shutil.copyfile(os.path.join(folder, name),
                                os.path.join(downloads, name))
                copied.append(f"descargas/{name}")
        if folder.endswith("releases") and os.path.exists(
                os.path.join(folder, "install.sh")):
            shutil.copyfile(os.path.join(folder, "install.sh"),
                            os.path.join(downloads, "install.sh"))
            os.chmod(os.path.join(downloads, "install.sh"), 0o755)
            copied.append("descargas/install.sh")

    if copy(os.path.join(ROOT, "README.md"), os.path.join(OUT, "README.md")):
        copied.append("README.md")

    print(f"Web preparada en {OUT}")
    for name in copied:
        print(f"  {name}")
    print("\nSube el contenido de esa carpeta a tu hosting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
