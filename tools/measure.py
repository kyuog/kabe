#!/usr/bin/env python3
"""Mide el consumo de memoria y el tiempo de arranque de Kabe.

    python3 tools/measure.py

Arranca la aplicación en modo ventana o en modo bandeja, espera a que se
estabilice y muestra el RSS (memoria residente) del proceso.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rss_kb(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def measure(mode: str, seconds: float = 12.0) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "kabe"]
    if mode == "tray":
        cmd.append("--tray")
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    peak = 0
    try:
        deadline = time.time() + seconds
        while time.time() < deadline:
            time.sleep(0.25)
            peak = max(peak, rss_kb(proc.pid))
            if proc.poll() is not None:
                break
    finally:
        elapsed = time.time() - start
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return {
        "mode": mode,
        "rss_mb": peak / 1024.0,
        "seconds": elapsed,
    }


def main() -> int:
    print("Kabe — medición de recursos")
    print("-" * 46)
    for mode in ("ventana", "tray"):
        result = measure(mode)
        print(f"{result['mode']:>8}: RSS máximo {result['rss_mb']:.1f} MB"
              f"   ({result['seconds']:.1f} s de observación)")
    print("-" * 46)
    print("Objetivo: < 80 MB en uso normal, < 40 MB en reposo (bandeja).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
