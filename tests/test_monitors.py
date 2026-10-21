"""Pruebas de la detección de monitores."""

from __future__ import annotations

import json
import unittest

from kabe import monitors
from kabe.models import Monitor


XRANDR_SAMPLE = """Screen 0: minimum 320 x 200, current 3840 x 1080, maximum 16384 x 16384
VGA-1 disconnected (normal left inverted right x axis y axis)
HDMI-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 600mm x 340mm
   1920x1080     60.00*+  50.00    59.94
   1680x1050     59.88
DP-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 0mm x 0mm
   1920x1080     60.00*+
DP-2 disconnected (normal left inverted right x axis y axis)
"""


class TestXrandr(unittest.TestCase):
    def setUp(self) -> None:
        self.monitors = monitors.parse_xrandr(XRANDR_SAMPLE)

    def test_only_connected_monitors(self) -> None:
        self.assertEqual(len(self.monitors), 2)

    def test_geometry(self) -> None:
        first = self.monitors[0]
        self.assertEqual(first.name, "HDMI-1")
        self.assertEqual((first.width, first.height), (1920, 1080))
        self.assertEqual((first.x, first.y), (0, 0))
        self.assertTrue(first.primary)

    def test_second_monitor_offset(self) -> None:
        second = self.monitors[1]
        self.assertEqual(second.name, "DP-1")
        self.assertEqual((second.x, second.y), (1920, 0))
        self.assertFalse(second.primary)

    def test_refresh_rate_of_current_mode(self) -> None:
        self.assertAlmostEqual(self.monitors[0].refresh, 60.0, places=2)

    def test_physical_size(self) -> None:
        self.assertEqual(self.monitors[0].physical_mm, (600, 340))


class TestWaylandBackends(unittest.TestCase):
    def test_wlr_randr(self) -> None:
        payload = json.dumps({
            "outputs": [
                {
                    "name": "eDP-1",
                    "make": "Chimei Innolux",
                    "model": "0x14D4",
                    "current_mode": {"width": 2880, "height": 1800, "refresh": 60.0},
                    "position": {"x": 0, "y": 0},
                    "scale": 2.0,
                    "enabled": True,
                    "primary": True,
                },
                {"name": "off", "current_mode": None, "enabled": False},
            ]
        })
        result = monitors.parse_wlr_randr(payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].width, 2880)
        self.assertEqual(result[0].scale, 2.0)
        self.assertEqual(result[0].effective_width, 5760)

    def test_hyprctl(self) -> None:
        payload = json.dumps([
            {
                "id": 0, "name": "DP-1", "description": "Dell Inc. U2717D",
                "width": 2560, "height": 1440, "refreshRate": 59940,
                "scale": 1.0, "x": 0, "y": 0, "transform": 0, "active": True,
            },
            {"id": 1, "name": "HDMI-A-1", "width": 1920, "height": 1080,
             "active": False},
        ])
        result = monitors.parse_hyprctl_monitors(payload)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].refresh, 59.94, places=2)
        self.assertEqual(result[0].resolution_label, "2560×1440")

    def test_swaymsg(self) -> None:
        payload = json.dumps([
            {
                "name": "eDP-1", "active": True, "scale": 1.0, "focused": True,
                "rect": {"x": 0, "y": 0, "width": 1920, "height": 1200},
                "current_mode": {"width": 1920, "height": 1200, "refresh": 60},
            }
        ])
        result = monitors.parse_sway_outputs(payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].height, 1200)

    def test_kscreen(self) -> None:
        payload = json.dumps({
            "outputs": [
                {
                    "name": "DP-1", "connected": True, "primary": True,
                    "geometry": {"x": 0, "y": 0, "width": 3840, "height": 2160},
                    "pos": {"x": 0, "y": 0}, "scale": 1.0, "refreshRate": 60.0,
                }
            ]
        })
        result = monitors.parse_kscreen(payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].width, 3840)


class TestManual(unittest.TestCase):
    def test_single_resolution(self) -> None:
        result = monitors.parse_manual("1920x1080")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].width, 1920)
        self.assertTrue(result[0].primary)

    def test_two_monitors(self) -> None:
        result = monitors.parse_manual("1920x1080+3840x1080")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1].x, 1920)

    def test_garbage(self) -> None:
        self.assertEqual(monitors.parse_manual("no es una resolución"), [])


class TestModel(unittest.TestCase):
    def test_orientation(self) -> None:
        self.assertEqual(Monitor(width=1920, height=1080).orientation, "landscape")
        self.assertEqual(Monitor(width=1080, height=1920).orientation, "portrait")
        self.assertEqual(Monitor(width=1000, height=1000).orientation, "square")

    def test_layout_bounds(self) -> None:
        layout = monitors.MonitorLayout(monitors=[
            Monitor(name="a", width=1920, height=1080, x=0, y=0),
            Monitor(name="b", width=1920, height=1080, x=1920, y=0),
        ])
        self.assertEqual(layout.total_width, 3840)
        self.assertEqual(layout.total_height, 1080)


if __name__ == "__main__":
    unittest.main()
