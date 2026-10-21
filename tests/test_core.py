"""Pruebas de la red, del catálogo de repos y de la identidad visual."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from kabe import repos as repos_mod
from kabe import probe
from kabe.net import HttpClient, HttpError
from kabe.ui import style


class TestProbeHeaders(unittest.TestCase):
    def test_png(self) -> None:
        header = b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" \
            + (3840).to_bytes(4, "big") + (2160).to_bytes(4, "big")
        self.assertEqual(probe.image_size_from_bytes(header), (3840, 2160))

    def test_jpeg(self) -> None:
        data = b"\xff\xd8\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" \
            + b"\x00" * 9 + b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" \
            + (2160).to_bytes(2, "big") + (3840).to_bytes(2, "big") + b"\x03"
        self.assertEqual(probe.image_size_from_bytes(data), (3840, 2160))

    def test_webp(self) -> None:
        vp8 = b"RIFF" + (100).to_bytes(4, "little") + b"WEBPVP8 " \
            + (10).to_bytes(4, "little") + b"\x00\x00" + b"\x9d\x01\x2a" \
            + (1920 | 0x8000).to_bytes(2, "little") + (1080 | 0x8000).to_bytes(2, "little")
        self.assertEqual(probe.image_size_from_bytes(vp8), (1920, 1080))

    def test_gif(self) -> None:
        data = b"GIF89a" + (800).to_bytes(2, "little") + (600).to_bytes(2, "little")
        self.assertEqual(probe.image_size_from_bytes(data), (800, 600))

    def test_unknown(self) -> None:
        self.assertIsNone(probe.image_size_from_bytes(b"no soy una imagen"))


class TestHttpClient(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.client = HttpClient()
        self.client._cache_dir = self.tmp

    def test_etag_is_reused(self) -> None:
        calls: list[dict] = []

        class FakeResponse:
            headers = {"Content-Encoding": "identity", "ETag": "W/\"abc\"",
                       "X-RateLimit-Remaining": "57", "X-RateLimit-Limit": "60",
                       "X-RateLimit-Reset": "0"}

            def __init__(self) -> None:
                self._body = json.dumps({"tree": []}).encode("utf-8")

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(req, timeout=None):
            calls.append(dict(req.headers))
            return FakeResponse()

        with mock.patch.object(HttpClient, "_opener") as opener:
            opener.return_value.open.side_effect = fake_open
            data, cached = self.client.get_json("https://api.github.com/x")
            self.assertEqual(data, {"tree": []})
            self.assertFalse(cached)
            self.assertNotIn("If-None-Match", calls[0])

            # Segunda llamada: debe reusar el ETag guardado.
            self.client.get_json("https://api.github.com/x")
            self.assertTrue(
                any(key.lower() == "if-none-match" for key in calls[1]),
                f"cabeceras: {calls[1]}",
            )

    def test_rate_limit_is_tracked(self) -> None:
        client = HttpClient()
        client._update_rate_limit({
            "X-RateLimit-Remaining": "12", "X-RateLimit-Limit": "60",
            "X-RateLimit-Reset": "0",
        })
        self.assertEqual(client.rate_limit.remaining, 12)
        self.assertEqual(client.rate_limit.limit, 60)

    def test_error_message_is_actionable(self) -> None:
        error = HttpError(
            "Límite de la API alcanzado. Añade un token de GitHub en Preferencias "
            "o espera a que se reinicie el cupo.", 403
        )
        self.assertIn("token", error.message)


class TestRepoCatalog(unittest.TestCase):
    def test_parse_github_url(self) -> None:
        self.assertEqual(
            repos_mod.parse_github_url("https://github.com/dharmx/walls"),
            ("dharmx", "walls"),
        )

    def test_parse_github_url_with_trailing_path(self) -> None:
        self.assertEqual(
            repos_mod.parse_github_url("https://github.com/dharmx/walls/tree/main/anime"),
            ("dharmx", "walls"),
        )

    def test_parse_invalid(self) -> None:
        self.assertIsNone(repos_mod.parse_github_url("https://example.com/walls"))
        self.assertIsNone(repos_mod.parse_github_url(""))

    def test_package_catalog_is_valid(self) -> None:
        catalog = repos_mod.load_repos()
        self.assertGreaterEqual(len(catalog), 6)
        for repo in catalog:
            self.assertTrue(repo.owner)
            self.assertTrue(repo.name)
            self.assertTrue(repo.branch)
            if not repo.license_verified:
                self.assertEqual(repo.license_label, "licencia no verificada")

    def test_add_user_repo_rejects_duplicates(self) -> None:
        tmp = tempfile.mkdtemp()
        with mock.patch.object(repos_mod, "USER_REPOS", os.path.join(tmp, "repos.json")):
            repo, error = repos_mod.add_user_repo("https://github.com/ejemplo/fondos")
            self.assertIsNotNone(repo)
            self.assertEqual(error, "")
            again, error2 = repos_mod.add_user_repo("https://github.com/ejemplo/fondos")
            self.assertIsNone(again)
            self.assertIn("Ya tienes", error2)


class TestPalette(unittest.TestCase):
    def test_amber_on_indigo_is_wcag_aa(self) -> None:
        ratio = style.contrast_ratio(style.AMBER, style.INDIGO)
        self.assertGreaterEqual(ratio, 4.5, f"contraste {ratio:.2f}")

    def test_indigo_on_neblina_is_wcag_aa(self) -> None:
        ratio = style.contrast_ratio(style.INDIGO, style.NEBLINA)
        self.assertGreaterEqual(ratio, 4.5, f"contraste {ratio:.2f}")

    def test_neblina_on_indigo_is_wcag_aa(self) -> None:
        ratio = style.contrast_ratio(style.NEBLINA, style.INDIGO)
        self.assertGreaterEqual(ratio, 4.5, f"contraste {ratio:.2f}")

    def test_only_three_brand_colors(self) -> None:
        self.assertEqual(style.INDIGO, "#232A4D")
        self.assertEqual(style.NEBLINA, "#E8F1F2")
        self.assertEqual(style.AMBER, "#F2A541")


class TestThumbnailCache(unittest.TestCase):
    def test_prune_removes_oldest(self) -> None:
        from kabe.thumbs import prune_directory
        tmp = tempfile.mkdtemp()
        for index in range(4):
            path = os.path.join(tmp, f"thumb{index}.jpg")
            with open(path, "wb") as fh:
                fh.write(b"x" * 400 * 1024)
            os.utime(path, (1000 + index, 1000 + index))
        freed = prune_directory(tmp, 1)  # límite: 1 MB
        self.assertGreater(freed, 0)
        self.assertLessEqual(len(os.listdir(tmp)), 2)


if __name__ == "__main__":
    unittest.main()
