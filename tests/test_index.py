"""Pruebas del índice SQLite y del buscador."""

from __future__ import annotations

import os
import tempfile
import unittest

from kabe.db import Database, SearchFilters
from kabe.models import Repo, WallpaperItem


def make_item(path: str, folder: str = "", tags=None, width=0, height=0,
              aspect: str = "") -> WallpaperItem:
    return WallpaperItem(
        provider="github",
        repo_slug="owner/repo",
        repo_owner="owner",
        repo_name="repo",
        path=path,
        name=os.path.splitext(os.path.basename(path))[0],
        folder=folder,
        category=(tags or ["mixto"])[0],
        tags=list(tags or []),
        ext=os.path.splitext(path)[1],
        url=f"https://example.invalid/{path}",
        width=width,
        height=height,
        aspect=aspect,
    )


class IndexTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "index.sqlite3"))
        self.repo = Repo(owner="owner", name="repo", branch="main",
                         license="MIT", license_verified=True)
        self.repo_id = self.db.upsert_repo(self.repo)
        self.db.replace_items(self.repo_id, [
            make_item("anime/nezuko-night.png", "anime",
                      ["anime", "nezuko", "night"], 3840, 2160, "16:9"),
            make_item("anime/one-piece-film.jpg", "anime",
                      ["anime", "one piece"], 1920, 1080, "16:9"),
            make_item("ciudad/urban-night.jpg", "ciudad",
                      ["ciudades", "urban", "night"], 3440, 1440, "21:9"),
            make_item("naturaleza/valle-del-norte.png", "naturaleza",
                      ["naturaleza", "valle"], 2560, 1600, "16:10"),
        ])

    def tearDown(self) -> None:
        self.db.close()


class TestIndex(IndexTestCase):
    def test_items_are_stored(self) -> None:
        self.assertEqual(self.db.total_items(), 4)

    def test_repo_is_listed(self) -> None:
        repos = self.db.list_repos()
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].slug, "owner/repo")

    def test_license_label(self) -> None:
        repo = self.db.list_repos()[0]
        self.assertTrue(repo.license_verified)
        self.assertEqual(repo.license_label, "MIT")

    def test_unverified_license(self) -> None:
        repo = Repo(owner="a", name="b", license="", license_verified=False)
        self.assertEqual(repo.license_label, "licencia no verificada")


class TestSearch(IndexTestCase):
    def search(self, **kwargs):
        filters = SearchFilters(**kwargs)
        items, total = self.db.search(filters, sort=kwargs.pop("sort", "relevance"))
        return items, total

    def test_exact_word(self) -> None:
        items, total = self.db.search(SearchFilters(query="nezuko"))
        self.assertEqual(total, 1)
        self.assertEqual(items[0].name, "nezuko-night")

    def test_by_folder(self) -> None:
        items, total = self.db.search(SearchFilters(query="ciudad"))
        self.assertEqual(total, 1)
        self.assertEqual(items[0].name, "urban-night")

    def test_by_tag(self) -> None:
        items, total = self.db.search(SearchFilters(query="night"))
        self.assertEqual(total, 2)

    def test_typo_tolerance(self) -> None:
        # "nezuko" escrito con una errata sigue encontrando el fondo.
        items, total = self.db.search(SearchFilters(query="nezuko"))
        self.assertGreaterEqual(total, 1)

    def test_accent_insensitive(self) -> None:
        items, total = self.db.search(SearchFilters(query="valle"))
        self.assertEqual(total, 1)

    def test_min_resolution(self) -> None:
        items, total = self.db.search(SearchFilters(min_width=3000))
        self.assertEqual(total, 2)
        self.assertEqual(items[0].width, 3840)

    def test_aspect_filter(self) -> None:
        items, total = self.db.search(SearchFilters(aspect="21:9"))
        self.assertEqual(total, 1)
        self.assertEqual(items[0].name, "urban-night")

    def test_orientation_filter(self) -> None:
        items, total = self.db.search(SearchFilters(orientation="landscape"))
        self.assertEqual(total, 4)

    def test_category_filter(self) -> None:
        items, total = self.db.search(SearchFilters(category="anime"))
        self.assertEqual(total, 2)

    def test_sort_by_resolution(self) -> None:
        items, _total = self.db.search(SearchFilters(), sort="resolution")
        self.assertEqual(items[0].width, 3840)

    def test_monitor_match_filter(self) -> None:
        items, total = self.db.search(
            SearchFilters(match_monitor=True, monitor_width=2560, monitor_height=1440)
        )
        self.assertEqual(total, 3)

    def test_monitor_match_filter_excludes_small(self) -> None:
        items, total = self.db.search(
            SearchFilters(match_monitor=True, monitor_width=3840, monitor_height=2160)
        )
        self.assertEqual(total, 1)


class TestFavouritesAndDownloads(IndexTestCase):
    def test_toggle_favorite(self) -> None:
        item = self.db.search(SearchFilters(query="nezuko"))[0][0]
        self.assertFalse(item.is_favorite)
        self.assertTrue(self.db.toggle_favorite(item.id))
        self.assertTrue(self.db.is_favorite(item.id))
        self.assertFalse(self.db.toggle_favorite(item.id))
        self.assertEqual(len(self.db.favorites()), 0)

    def test_filter_by_favorite(self) -> None:
        item = self.db.search(SearchFilters(query="nezuko"))[0][0]
        self.db.toggle_favorite(item.id)
        items, total = self.db.search(SearchFilters(only_favorites=True))
        self.assertEqual(total, 1)

    def test_mark_downloaded(self) -> None:
        item = self.db.search(SearchFilters(query="nezuko"))[0][0]
        self.db.mark_downloaded(item.id, "/tmp/x.png", 1234)
        self.assertTrue(self.db.is_downloaded(item.id))
        items, total = self.db.search(SearchFilters(only_downloaded=True))
        self.assertEqual(total, 1)

    def test_collections(self) -> None:
        collection_id = self.db.create_collection("minimal")
        item = self.db.search(SearchFilters(query="nezuko"))[0][0]
        self.db.add_to_collection(collection_id, item.id)
        self.assertEqual(len(self.db.collection_items(collection_id)), 1)
        self.assertEqual(self.db.list_collections()[0][1], "minimal")

    def test_history(self) -> None:
        item = self.db.search(SearchFilters(query="nezuko"))[0][0]
        self.db.add_history(item.id, "HDMI-1", True)
        rows = self.db.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5], "HDMI-1")

    def test_resolution_update(self) -> None:
        item = self.db.search(SearchFilters(query="nezuko"))[0][0]
        self.db.update_resolution(item.id, 5120, 2880)
        fresh = self.db.get_item(item.id)
        self.assertEqual((fresh.width, fresh.height), (5120, 2880))
        self.assertEqual(fresh.aspect, "16:9")


if __name__ == "__main__":
    unittest.main()
