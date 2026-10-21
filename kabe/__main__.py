"""Punto de entrada de Kabe: `kabe`."""

from __future__ import annotations

import argparse
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kabe",
        description="壁 Kabe — descubre y aplica fondos de pantalla en Linux.",
    )
    parser.add_argument("--version", action="store_true", help="muestra la versión y sale")
    parser.add_argument("--tray", action="store_true",
                        help="empieza sólo en la bandeja del sistema")
    parser.add_argument("--refresh", action="store_true",
                        help="actualiza el índice y sale")
    parser.add_argument("--apply", metavar="ARCHIVO",
                        help="aplica una imagen local como fondo y sale")
    parser.add_argument("--search", metavar="TEXTO",
                        help="abre Kabe con una búsqueda ya escrita")
    parser.add_argument("--list-monitors", action="store_true",
                        help="muestra los monitores detectados y sale")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        from . import __version__
        print(f"kabe {__version__}")
        return 0

    if args.list_monitors:
        from .monitors import detect_monitors
        layout = detect_monitors()
        print(f"backend: {layout.backend}")
        for monitor in layout:
            refresh = f" @ {monitor.refresh:.0f}Hz" if monitor.refresh else ""
            print(f"  {monitor.name}: {monitor.resolution_label}{refresh}"
                  f"{' (principal)' if monitor.primary else ''}")
        return 0

    if args.apply:
        from .wallpaper import apply_wallpaper, get_applier
        from .monitors import detect_monitors
        path = os.path.abspath(os.path.expanduser(args.apply))
        if not os.path.exists(path):
            print(f"kabe: no existe el archivo {path}", file=sys.stderr)
            return 1
        layout = detect_monitors()
        applier = get_applier()
        ok, message = apply_wallpaper(applier, path, layout.monitors, "scaled", True)
        if ok:
            print(f"Fondo aplicado con {applier.name}.")
            return 0
        print(f"kabe: {message}", file=sys.stderr)
        return 1

    if args.refresh:
        from .config import Config
        from .db import Database
        from .indexer import Indexer
        from .net import HttpClient
        config = Config.load()
        db = Database()
        http = HttpClient(config.github_token)
        indexer = Indexer(db, http, config.index_ttl_hours)
        report = indexer.sync(force=True)
        for error in report.errors:
            print(f"kabe: {error}", file=sys.stderr)
        print(f"{db.total_items()} fondos indexados en {report.repos_ok} repositorios.")
        return 0

    # Modo gráfico.
    from .app import KabeApp
    app = KabeApp(start_in_tray=args.tray)
    if args.search:
        def _set_search() -> bool:
            if app.window is not None:
                app.window.search.set_text(args.search)
                app.window.reload_items()
            return False
        GLib_idle(_set_search)
    return app.run([])


def GLib_idle(func) -> None:
    try:
        from gi.repository import GLib
        GLib.idle_add(func)
    except (ImportError, ValueError):  # pragma: no cover
        pass


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
