"""Hilos de trabajo.

Kabe no bloquea la interfaz: las descargas, las miniaturas, la lectura de
cabeceras y la actualización del índice ocurren en hilos aparte y vuelven a
la interfaz con GLib.idle_add (que es el único sitio donde se puede tocar
GTK).
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional


class WorkerPool:
    """Pool de hilos con cola. Cada tarea es una función sin argumentos."""

    def __init__(self, size: int = 2, name: str = "kabe-worker"):
        self._queue: "queue.Queue[Optional[Callable[[], None]]]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._size = max(1, size)
        self._name = name
        self._stopped = False

    def start(self) -> None:
        if self._threads:
            return
        for index in range(self._size):
            thread = threading.Thread(target=self._loop, name=f"{self._name}-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                job()
            except Exception:  # pragma: no cover - un fallo no debe matar el pool
                pass
            finally:
                self._queue.task_done()

    def submit(self, job: Callable[[], None]) -> None:
        if self._stopped:
            return
        self.start()
        self._queue.put(job)

    def stop(self) -> None:
        self._stopped = True
        for _ in self._threads:
            self._queue.put(None)
        self._threads.clear()


def run_async(
    func: Callable[..., Any],
    on_done: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
    *args,
    **kwargs,
) -> threading.Thread:
    """Ejecuta una función en un hilo y entrega el resultado en el bucle GTK."""

    def _worker() -> None:
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            if on_error:
                _idle(on_error, exc)
            return
        if on_done:
            _idle(on_done, result)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def _idle(callback: Callable[..., Any], *args) -> None:
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib
        GLib.idle_add(_wrap, callback, *args, priority=GLib.PRIORITY_DEFAULT_IDLE)
    except (ImportError, ValueError):  # pragma: no cover
        callback(*args)


def _wrap(callback: Callable[..., Any], *args) -> bool:
    callback(*args)
    return False
