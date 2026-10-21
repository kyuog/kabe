"""Pruebas del soporte de vídeos (live wallpapers)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from kabe import video
from kabe.db import Database, SearchFilters
from kabe.models import KIND_VIDEO, Repo, WallpaperItem
from kabe.wallpaper import base


class TestVideoModel(unittest.TestCase):
    def test_duration_label(self) -> None:
        item = WallpaperItem(kind=KIND_VIDEO, duration=83)
        self.assertEqual(item.duration_label, "1:23")
        self.assertTrue(item.is_video)

    def test_empty_duration(self) -> None:
        self.assertEqual(video.format_duration(0), "0:00")
        self.assertEqual(video.format_duration(7), "0:07")

    def test_video_resolution_label(self) -> None:
        item = WallpaperItem(kind=KIND_VIDEO, width=1920, height=1080)
        self.assertEqual(item.resolution_label, "FHD")


class TestVideoIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "index.sqlite3"))
        repo = Repo(owner="owner", name="repo")
        repo_id = self.db.upsert_repo(repo)
        self.db.replace_items(repo_id, [
            WallpaperItem(provider="github", repo_slug="owner/repo",
                          path="animated/clip.mp4", name="clip", kind=KIND_VIDEO,
                          ext=".mp4", duration=12),
            WallpaperItem(provider="github", repo_slug="owner/repo",
                          path="static/photo.png", name="photo", kind="image",
                          ext=".png"),
        ])

    def tearDown(self) -> None:
        self.db.close()

    def test_kind_filter(self) -> None:
        items, total = self.db.search(SearchFilters(kind="video"))
        self.assertEqual(total, 1)
        self.assertEqual(items[0].name, "clip")

    def test_images_filter(self) -> None:
        _items, total = self.db.search(SearchFilters(kind="image"))
        self.assertEqual(total, 1)

    def test_video_metadata_is_stored(self) -> None:
        item = self.db.search(SearchFilters(kind="video"))[0][0]
        self.assertEqual(item.kind, "video")
        self.assertEqual(item.duration, 12)

    def test_update_video_info(self) -> None:
        item = self.db.search(SearchFilters(kind="video"))[0][0]
        self.db.update_video_info(item.id, 1920, 1080, 30)
        fresh = self.db.get_item(item.id)
        self.assertEqual((fresh.width, fresh.height), (1920, 1080))
        self.assertEqual(fresh.duration, 30)
        self.assertEqual(fresh.aspect, "16:9")


class TestVideoApplier(unittest.TestCase):
    def test_without_tools_the_error_explains_what_to_install(self) -> None:
        applier = base.VideoApplier()
        tmp = tempfile.mktemp(suffix=".mp4")
        with open(tmp, "wb") as fh:
            fh.write(b"0")
        with mock.patch.object(base, "have", lambda cmd: False), \
             mock.patch.dict(os.environ, {}, clear=True):
            ok, message = applier.apply_to_monitor(None, tmp)
        os.unlink(tmp)
        self.assertFalse(ok)
        self.assertIn("mpvpaper", message)
        self.assertIn("xwinwrap", message)

    def test_mpvpaper_on_sway(self) -> None:
        applier = base.VideoApplier()
        with mock.patch.object(base, "have", lambda cmd: cmd == "mpvpaper"), \
             mock.patch.dict(os.environ, {"SWAYSOCK": "/run/sway.sock"}, clear=False):
            self.assertTrue(applier.supported())
            self.assertEqual(applier._command(), ["mpvpaper"])

    def test_xwinwrap_on_x11(self) -> None:
        applier = base.VideoApplier()
        with mock.patch.object(base, "have", lambda cmd: cmd in ("xwinwrap", "mpv")), \
             mock.patch.dict(os.environ, {}, clear=True):
            command = applier._command()
        self.assertIsNotNone(command)
        self.assertEqual(command[0], "xwinwrap")
        self.assertIn("mpv", command)

    def test_the_player_is_started_in_the_background(self) -> None:
        applier = base.VideoApplier()
        tmp = tempfile.mktemp(suffix=".mp4")
        with open(tmp, "wb") as fh:
            fh.write(b"0")
        with mock.patch.object(base, "have", lambda cmd: cmd == "mpvpaper"), \
             mock.patch.dict(os.environ, {"SWAYSOCK": "/run/sway.sock"}, clear=False), \
             mock.patch.object(base.subprocess, "Popen") as popen:
            ok, _err = applier.apply_to_monitor(None, tmp)
        self.assertTrue(ok)
        self.assertTrue(popen.called)
        os.unlink(tmp)


class TestVideoTools(unittest.TestCase):
    def test_probe_video_without_ffprobe(self) -> None:
        with mock.patch.object(video, "_run", return_value=(1, b"", "no ffprobe")):
            self.assertEqual(video.probe_video("/tmp/x.mp4"), {})

    def test_poster_bytes_without_ffmpeg(self) -> None:
        with mock.patch.object(video, "_run", return_value=(1, b"", "no ffmpeg")):
            self.assertIsNone(video.poster_bytes("/tmp/x.mp4"))


if __name__ == "__main__":
    unittest.main()
