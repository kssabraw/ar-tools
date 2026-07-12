"""Google Sheets/Drive API client for the Deliverables Sheet Sync module.

Direct Sheets API access (NOT the Apps Script webhook in `google_docs.py`,
which is create-only) — this module needs to read existing sheets, append rows,
and copy the master template. Authenticates as the shared service account
(`settings.google_service_account_key`, the same key GSC uses) with the
**write** scopes; the GSC credential (read-only Search Console) is unchanged.

All functions here are synchronous (googleapiclient is sync) — call them from
async jobs via ``asyncio.to_thread``. Every function raises on failure; callers
own the best-effort discipline.

Access model (PRD §7): the sheets live in an agency Shared Drive the service
account is a member of, so copies created there are instantly writable with no
per-client sharing. All Drive calls pass ``supportsAllDrives=True``.
"""

from __future__ import annotations

import logging

from services.gsc_service import _load_key

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsError(RuntimeError):
    """Raised when the Sheets/Drive API is unconfigured or a call fails."""


def a1_tab(title: str) -> str:
    """Quote a worksheet title for A1 notation ('' doubles embedded quotes, so
    a tab named e.g. Kyle's notes can't break the range)."""
    return "'" + title.replace("'", "''") + "'"


def _credentials():
    from google.oauth2 import service_account  # noqa: PLC0415

    return service_account.Credentials.from_service_account_info(_load_key(), scopes=SCOPES)


def build_sheets_client():
    """Authenticated Sheets API client (lazy Google imports)."""
    from googleapiclient.discovery import build  # noqa: PLC0415

    return build("sheets", "v4", credentials=_credentials(), cache_discovery=False)


def build_drive_client():
    """Authenticated Drive API client (lazy Google imports)."""
    from googleapiclient.discovery import build  # noqa: PLC0415

    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def list_tabs(sheet_id: str) -> list[str]:
    """The spreadsheet's worksheet titles, in order."""
    meta = (
        build_sheets_client()
        .spreadsheets()
        .get(spreadsheetId=sheet_id, fields="sheets(properties(title))")
        .execute()
    )
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def read_values(sheet_id: str, a1_range: str) -> list[list[str]]:
    """Cell values for an A1 range (formatted strings; trailing blanks trimmed
    by the API)."""
    resp = (
        build_sheets_client()
        .spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=a1_range)
        .execute()
    )
    return resp.get("values", [])


def read_dropdown_values(sheet_id: str, tab: str, cell: str = "A2") -> list[str]:
    """The data-validation list on `cell` (the column-A dropdown), or [] when
    the cell has no ONE_OF_LIST validation. Used so the mapper matches each
    sheet's REAL dropdown vocabulary instead of a hardcoded list (PRD §4)."""
    resp = (
        build_sheets_client()
        .spreadsheets()
        .get(
            spreadsheetId=sheet_id,
            ranges=[f"{a1_tab(tab)}!{cell}"],
            includeGridData=True,
            fields="sheets(data(rowData(values(dataValidation))))",
        )
        .execute()
    )
    try:
        cell_data = resp["sheets"][0]["data"][0]["rowData"][0]["values"][0]
        cond = cell_data["dataValidation"]["condition"]
        if cond.get("type") != "ONE_OF_LIST":
            return []
        return [v.get("userEnteredValue", "") for v in cond.get("values", []) if v.get("userEnteredValue")]
    except (KeyError, IndexError):
        return []


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def append_row(sheet_id: str, tab: str, row: list[str]) -> dict:
    """Append one row to the bottom of a tab's data. USER_ENTERED so a
    =HYPERLINK(...) formula renders as a titled link (matching the VA's style).
    Only writes the cells given (A..D) — the client-owned Status/Notes columns
    to the right stay untouched."""
    return (
        build_sheets_client()
        .spreadsheets()
        .values()
        .append(
            spreadsheetId=sheet_id,
            range=f"{a1_tab(tab)}!A:D",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        )
        .execute()
    )


def copy_template(template_id: str, name: str, folder_id: str) -> dict:
    """Drive files.copy of the master template into the Shared-Drive folder.
    Returns {id, name, webViewLink}. The copy inherits the template's tabs,
    dropdown validation, and formatting (why the template must be NATIVE)."""
    return (
        build_drive_client()
        .files()
        .copy(
            fileId=template_id,
            body={"name": name, "parents": [folder_id]},
            fields="id,name,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
