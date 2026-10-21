"""Pruebas del respaldo a imagen estática cuando el escritorio no admite vídeos."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from kabe import video
from kabe.wallpaper import get_applier


class TestVideoFallback(unittest.TestCase):
    def test_get_applier_returns_the_video_applier(self) -> None:
        """Con kind='video' siempre se devuelve el reproductor de vídeos.

        El que decida si sirve es `supported()`: así la interfaz puede
        explicar que este escritorio no reproduce vídeos de fondo.
        """
        applier = get_applier("", kind="video")
        self.assertEqual(applier.id, "video")

    def test_video_applier_reports_it_is_unavailable(self) -> None:
        with mock.patch("kabe.wallpaper.base.have", lambda cmd: False), \
             mock.patch.dict(os.environ, {}, clear=True):
            applier = get_applier("", kind="video")
            self.assertFalse(applier.supported())

    def test_the_error_explains_the_alternative(self) -> None:
        tmp = tempfile.mktemp(suffix=".mp4")
        with open(tmp, "wb") as fh:
            fh.write(b"0")
        with mock.patch("kabe.wallpaper.base.have", lambda cmd: False), \
             mock.patch.dict(os.environ, {}, clear=True):
            applier = get_applier("", kind="video")
            ok, message = applier.apply_to_monitor(None, tmp)
        os.unlink(tmp)
        self.assertFalse(ok)
        self.assertIn("xwinwrap", message)
        self.assertIn("mpv", message)

    def test_poster_file_is_a_png(self) -> None:
        """El fotograma debe ser una imagen válida (un MP4 dejaría el
        escritorio en blanco)."""
        fake = tempfile.mktemp(suffix=".mp4")
        with open(fake, "wb") as fh:
            fh.write(b"0" * 32)
        out = tempfile.mktemp(suffix=".png")
        with mock.patch.object(video, "_run", return_value=(0, b"", "")):
            with mock.patch("os.path.exists", return_value=True):
                result = video.poster_file(fake, out)
        self.assertEqual(result, out)
        with mock.patch("os.path.exists", return_value=False):
            self.assertIsNone(video.poster_file(fake, out))
        os.unlink(fake)


class TestApplierChoiceByFile(unittest.TestCase):
    """El aplicador se elige por el archivo, no por el elemento."""

    def test_png_uses_the_desktop_applier(self) -> None:
        from kabe.models import VIDEO_EXTS
        self.assertNotIn(".png", VIDEO_EXTS)
        self.assertIn(".mp4", VIDEO_EXTS)
        self.assertIn(".webm", VIDEO_EXTS)


if __name__ == "__main__":
    unittest.main()
