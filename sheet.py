import re
from urllib.parse import urlsplit

import gspread
from google.oauth2.service_account import Credentials


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SPREADSHEET_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _extract_id(url_or_id: str) -> str:
    value = url_or_id.strip()
    if not value:
        raise ValueError("A Google Spreadsheet URL or ID is required.")

    if "/" in value:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.netloc.lower() != "docs.google.com":
            raise ValueError("The spreadsheet URL must use https://docs.google.com.")
        match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)(?:/|$)", parsed.path)
        if not match:
            raise ValueError("The URL does not contain a valid spreadsheet ID.")
        value = match.group(1)

    if not _SPREADSHEET_ID.fullmatch(value):
        raise ValueError("The spreadsheet ID contains invalid characters.")
    return value


class SheetWriter:
    """Append deduplicated Play Store links to a worksheet's first column."""

    def __init__(self, url: str, key_path: str, tab_index: int = 0):
        if tab_index < 0:
            raise ValueError("Worksheet index must be zero or greater.")

        spreadsheet_id = _extract_id(url)
        credentials = Credentials.from_service_account_file(key_path, scopes=SCOPES)
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.get_worksheet(tab_index)
        if worksheet is None:
            raise ValueError(f"Worksheet index {tab_index} does not exist.")
        self.ws = worksheet

        values = self.ws.get(f"A1:A{self.ws.row_count}") or []
        column = [str(row[0]).strip() if row and row[0] is not None else "" for row in values]
        self.existing = {value for value in column if value}
        self.next_row = max(len(column) + 1, 2)

    def _ensure_capacity(self, target_row: int) -> None:
        if target_row > self.ws.row_count:
            self.ws.add_rows(target_row - self.ws.row_count + 100)

    def append(self, links: list[str]) -> int:
        pending: list[str] = []
        pending_set: set[str] = set()
        for link in links:
            if not isinstance(link, str):
                continue
            normalized = link.strip()
            if normalized and normalized not in self.existing and normalized not in pending_set:
                pending.append(normalized)
                pending_set.add(normalized)

        if not pending:
            return 0

        end_row = self.next_row + len(pending) - 1
        self._ensure_capacity(end_row)
        self.ws.update(
            range_name=f"A{self.next_row}:A{end_row}",
            values=[[link] for link in pending],
            value_input_option="RAW",
        )
        self.existing.update(pending)
        self.next_row = end_row + 1
        return len(pending)
