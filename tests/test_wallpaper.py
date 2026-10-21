"""Pruebas de los aplicadores de fondo (con comandos simulados)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

from kabe.models import Monitor
from kabe.wallpaper import base, env


class FakeRunner:
    """Sustituye a subprocess.run y guarda las órdenes ejecutadas."""

    def __init__(self, fail_on: str = "") -> None:
        self.commands: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, cmd, stdout=None, stderr=None, timeout=None, check=False):
        self.commands.append(list(cmd))
        if self.fail_on and any(self.fail_on in part for part in cmd):
            return 1, "", "error simulado"
        return 0, "", ""


class ApplierTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.image = os.path.join(self.tmp, "fondo.png")
        with open(self.image, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        self.monitor = Monitor(name="HDMI-1", width=1920, height=1080,
                               x=0, y=0, primary=True)
        self.monitors = [self.monitor]

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestXfce(ApplierTestCase):
    def test_writes_every_monitor_and_workspace(self) -> None:
        runner = FakeRunner()
        applier = base.XfceApplier()
        with mock.patch.object(base, "run_cmd", runner):
            applier._monitor_ids = lambda: ["HDMI-1"]
            ok, err = applier.apply_to_monitor(self.monitor, self.image, "zoomed")
        self.assertTrue(ok, err)
        written = {}
        for cmd in runner.commands:
            if "-p" in cmd and "-s" in cmd:
                written[cmd[cmd.index("-p") + 1]] = cmd[cmd.index("-s") + 1]
        self.assertEqual(written["/backdrop/screen0/monitorHDMI-1/workspace0/last-image"],
                         "file://" + self.image)
        # Estilo "zoomed" = 4 en XFCE, y los cuatro espacios de trabajo.
        self.assertEqual(written["/backdrop/screen0/monitorHDMI-1/workspace0/image-style"], "4")
        self.assertIn("/backdrop/screen0/monitorHDMI-1/workspace3/last-image", written)

    def test_uses_existing_monitor_ids(self) -> None:
        runner = FakeRunner()
        applier = base.XfceApplier()
        with mock.patch.object(base, "run_cmd", runner):
            applier._monitor_ids = lambda: ["monitor0", "HDMI-1"]
            ok, _err = applier.apply_to_monitor(self.monitor, self.image)
        self.assertTrue(ok)
        targets = {cmd[cmd.index("-p") + 1] for cmd in runner.commands if "-p" in cmd}
        self.assertIn("/backdrop/screen0/monitorHDMI-1/workspace0/last-image", targets)

    def test_missing_image_is_reported(self) -> None:
        applier = base.XfceApplier()
        ok, message = applier.apply_to_monitor(self.monitor, "/no/existe.png")
        self.assertFalse(ok)
        self.assertIn("no existe", message.lower())

    def test_error_is_propagated(self) -> None:
        runner = FakeRunner(fail_on="xfconf-query")
        applier = base.XfceApplier()
        with mock.patch.object(base, "run_cmd", runner):
            ok, message = applier.apply_to_monitor(self.monitor, self.image)
        self.assertFalse(ok)
        self.assertTrue(message)


class TestGSettings(ApplierTestCase):
    def test_picture_uri(self) -> None:
        runner = FakeRunner()
        applier = base.GSettingsApplier("org.gnome.desktop.background", "GNOME")
        with mock.patch.object(base, "run_cmd", runner):
            ok, err = applier.apply_to_monitor(self.monitor, self.image)
        self.assertTrue(ok, err)
        sets = [cmd for cmd in runner.commands if cmd[:2] == ["gsettings", "set"]]
        self.assertTrue(any(cmd[3] == "picture-uri" for cmd in sets))
        self.assertTrue(all(cmd[4].startswith("file://") for cmd in sets))

    def test_mate_uses_filename(self) -> None:
        runner = FakeRunner()
        applier = base.MateApplier()
        with mock.patch.object(base, "run_cmd", runner):
            ok, _err = applier.apply_to_monitor(self.monitor, self.image)
        self.assertTrue(ok)
        sets = [cmd for cmd in runner.commands if cmd[:2] == ["gsettings", "set"]]
        self.assertTrue(any(cmd[3] == "picture-filename" for cmd in sets))


class TestFeh(ApplierTestCase):
    def test_fill_geometry(self) -> None:
        runner = FakeRunner()
        applier = base.FehApplier()
        with mock.patch.object(base, "run_cmd", runner):
            ok, err = applier.apply_to_monitor(self.monitor, self.image)
        self.assertTrue(ok, err)
        self.assertIn("--bg-fill", runner.commands[0])
        self.assertIn("1920x1080+0+0", runner.commands[0])

    def test_apply_to_all(self) -> None:
        runner = FakeRunner()
        applier = base.FehApplier()
        second = Monitor(name="DP-1", width=1280, height=1024, x=1920, y=0)
        with mock.patch.object(base, "run_cmd", runner):
            ok, _err = applier.apply_to_all(self.image, [self.monitor, second])
        self.assertTrue(ok)
        self.assertIn("1280x1024+1920+0", runner.commands[0])


class TestEnvironment(unittest.TestCase):
    def test_detect_xfce(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "XFCE"}, clear=False):
            self.assertEqual(env.detect_desktop(), "xfce")

    def test_detect_kde(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}, clear=False):
            self.assertEqual(env.detect_desktop(), "kde")

    def test_detect_cinnamon(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "X-Cinnamon"}, clear=False):
            self.assertEqual(env.detect_desktop(), "cinnamon")

    def test_describe(self) -> None:
        with mock.patch.dict(os.environ,
                             {"XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_TYPE": "x11"},
                             clear=False):
            self.assertIn("XFCE", env.describe_environment())


class TestApplierSelection(unittest.TestCase):
    def test_falls_back_to_feh(self) -> None:
        from kabe.wallpaper import get_applier
        with mock.patch.object(base.FehApplier, "supported", lambda self: True), \
             mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=False), \
             mock.patch.object(base, "have", lambda cmd: cmd == "feh"):
            applier = get_applier()
        self.assertEqual(applier.id, "feh")

    def test_preferred_backend(self) -> None:
        from kabe.wallpaper import get_applier
        with mock.patch.object(base, "have", lambda cmd: cmd in ("feh", "xfconf-query")):
            applier = get_applier("xfce")
        self.assertEqual(applier.id, "xfce")

    def test_preferred_backend_wins_over_the_detected_desktop(self) -> None:
        """La elección del usuario manda aunque la detección diga otra cosa."""
        from kabe.wallpaper import get_applier
        with mock.patch.object(base, "have", lambda cmd: cmd in ("feh", "xfconf-query")), \
             mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=False):
            applier = get_applier("xfce")
        self.assertEqual(applier.id, "xfce")


if __name__ == "__main__":
    unittest.main()
