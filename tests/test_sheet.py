import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_sheet_module():
    gspread = types.ModuleType("gspread")
    gspread.authorize = MagicMock()

    google = types.ModuleType("google")
    google.__path__ = []
    oauth2 = types.ModuleType("google.oauth2")
    oauth2.__path__ = []
    service_account = types.ModuleType("google.oauth2.service_account")
    service_account.Credentials = MagicMock()

    modules = {
        "gspread": gspread,
        "google": google,
        "google.oauth2": oauth2,
        "google.oauth2.service_account": service_account,
    }
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("sheet_under_test", PROJECT_ROOT / "sheet.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, gspread, service_account.Credentials


class SpreadsheetIdTests(unittest.TestCase):
    def test_accepts_google_spreadsheet_urls_and_ids(self):
        sheet, _, _ = load_sheet_module()
        self.assertEqual(sheet._extract_id("spreadsheet_123"), "spreadsheet_123")
        self.assertEqual(
            sheet._extract_id("https://docs.google.com/spreadsheets/d/spreadsheet_123/edit?gid=0"),
            "spreadsheet_123",
        )

    def test_rejects_urls_from_untrusted_hosts(self):
        sheet, _, _ = load_sheet_module()
        with self.assertRaises(ValueError):
            sheet._extract_id("https://docs.google.com.evil.example/spreadsheets/d/abc")
        with self.assertRaises(ValueError):
            sheet._extract_id("http://docs.google.com/spreadsheets/d/abc")


class SheetWriterTests(unittest.TestCase):
    def test_appends_only_new_unique_values_as_raw_cells(self):
        sheet, gspread, credentials = load_sheet_module()
        worksheet = MagicMock()
        worksheet.row_count = 3
        worksheet.get.return_value = [["URL"], ["existing-link"], [""]]
        spreadsheet = MagicMock()
        spreadsheet.get_worksheet.return_value = worksheet
        gspread.authorize.return_value.open_by_key.return_value = spreadsheet

        writer = sheet.SheetWriter("spreadsheet_123", "key.json")
        added = writer.append(["existing-link", "new-link", "new-link", None])

        self.assertEqual(added, 1)
        credentials.from_service_account_file.assert_called_once()
        worksheet.update.assert_called_once_with(
            range_name="A4:A4",
            values=[["new-link"]],
            value_input_option="RAW",
        )


if __name__ == "__main__":
    unittest.main()
