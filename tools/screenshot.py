#!/usr/bin/env python3
"""Captura la ventana de Kabe (para desarrollo y documentación).

    python3 tools/screenshot.py salida.png
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

DISPLAY = os.environ.get("DISPLAY", ":0.0")


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kabe.png"
    env = dict(os.environ, DISPLAY=DISPLAY)
    out = subprocess.run(
        ["xdotool", "search", "--name", "^Kabe$"], env=env,
        stdout=subprocess.PIPE, check=False,
    ).stdout.decode().split()
    if not out:
        print("no hay ninguna ventana de Kabe abierta", file=sys.stderr)
        return 1
    window = out[-1]
    subprocess.run(["xdotool", "windowactivate", window], env=env, check=False)
    subprocess.run(["xdotool", "windowraise", window], env=env, check=False)
    # El ratón debe estar sobre la ventana: si no, el gestor de ventanas
    # vuelve a subir la terminal que tiene el foco.
    subprocess.run(["xdotool", "mousemove", "700", "300"], env=env, check=False)
    time.sleep(2.0)
    subprocess.run(["import", "-window", "root", target], env=env, check=False)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
