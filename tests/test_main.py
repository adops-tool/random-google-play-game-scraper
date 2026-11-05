import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main


class InstallParsingTests(unittest.TestCase):
    def test_parses_store_install_counts(self):
        self.assertEqual(main.parse_installs("1,234+"), 1234)
        self.assertEqual(main.parse_installs(" 500 "), 500)
        self.assertEqual(main.parse_installs("unknown"), 0)
        self.assertEqual(main.parse_installs(None), 0)

    def test_requires_game_genre_and_configured_install_range(self):
        with patch.object(main.settings, "MIN_INSTALLS", 500), patch.object(
            main.settings, "MAX_INSTALLS", 2000
        ):
            self.assertTrue(main.is_wanted({"genre": "Casual game", "installs": "500+"}))
            self.assertFalse(main.is_wanted({"genre": "Tools", "installs": "1000+"}))
            self.assertFalse(main.is_wanted({"genreId": "GAME_PUZZLE", "installs": "2001+"}))
            self.assertFalse(main.is_wanted({"genreId": "GAME_PUZZLE", "installs": "499+"}))


class ListingParsingTests(unittest.TestCase):
    def test_extracts_unique_non_stopword_tokens(self):
        details = {
            "title": "Dragon Quest: Dragon Island",
            "summary": "Explore the island and discover treasure.",
        }
        self.assertEqual(main.tokens_of(details), ("dragon", "quest", "island", "explore", "treasure"))

    def test_non_string_listing_fields_are_ignored(self):
        self.assertEqual(main.tokens_of({"title": 42, "summary": None}), ())

    def test_accepts_only_google_play_urls_with_valid_package_ids(self):
        valid = "https://play.google.com/store/apps/details?id=com.example.game"
        self.assertEqual(main._app_id_from_url(valid), "com.example.game")
        self.assertIsNone(main._app_id_from_url("http://play.google.com/store/apps/details?id=com.example.game"))
        self.assertIsNone(main._app_id_from_url("https://evil.example/store/apps/details?id=com.example.game"))
        self.assertIsNone(main._app_id_from_url("https://play.google.com/store/apps/details?id=invalid"))
        self.assertIsNone(main._app_id_from_url(None))

    def test_seed_queries_are_non_empty(self):
        self.assertTrue(main.random_query().strip())


class PersistenceTests(unittest.TestCase):
    def test_load_and_append_validate_and_deduplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output" / "games.txt"
            main.append_links(path, ["com.example.game", "com.example.game", "bad id"])
            self.assertEqual(main.load_existing(path), {"com.example.game"})
            self.assertEqual(path.read_text(encoding="utf-8").splitlines(), [
                "https://play.google.com/store/apps/details?id=com.example.game"
            ])

    def test_missing_output_file_is_an_empty_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(main.load_existing(Path(directory) / "missing.txt"), set())


class ConcurrencyTests(unittest.TestCase):
    def test_bounded_executor_returns_all_items(self):
        with patch.object(main.settings, "WORKERS", 2):
            with main._pool() as executor:
                results = [future.result() for _, future in main._completed_futures(
                    executor, lambda value: value * 2, range(8)
                )]
        self.assertCountEqual(results, [value * 2 for value in range(8)])


class MainRunTests(unittest.TestCase):
    def test_single_cycle_flushes_final_buffer(self):
        details = {"title": "Puzzle Quest", "genre": "Puzzle game", "installs": "1000000"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "games.txt"
            with (
                patch.object(main.settings, "OUTPUT_FILE", str(output)),
                patch.object(main.settings, "SPIDER_ENABLED", False),
                patch.object(main, "discover_by_search", return_value=["com.example.game"]),
                patch.object(main, "iter_games", return_value=iter([("com.example.game", details)])),
                redirect_stdout(io.StringIO()),
            ):
                main.main(max_cycles=1, use_sheets=False)

            self.assertEqual(main.load_existing(output), {"com.example.game"})


if __name__ == "__main__":
    unittest.main()
