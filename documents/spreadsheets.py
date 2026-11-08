"""Safe, deliberately small XLSX reader/editor for the internal document area."""

from copy import copy
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - turns a deployment omission into a clear UI error.
    load_workbook = None


MAX_EDITABLE_ROWS = 500
MAX_EDITABLE_COLUMNS = 50
MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


class SpreadsheetError(ValidationError):
    pass


def _require_editor_dependency():
    if load_workbook is None:
        raise SpreadsheetError("Der Tabellen-Editor ist noch nicht auf dem Server installiert.")


def _read_workbook_bytes(document):
    if not document.is_editable_spreadsheet:
        raise SpreadsheetError("Nur Excel-Dateien im Format .xlsx können im Browser bearbeitet werden.")
    if not default_storage.exists(document.file.name):
        raise SpreadsheetError("Die Excel-Datei wurde nicht gefunden.")

    with default_storage.open(document.file.name, "rb") as source:
        content = source.read()

    try:
        with ZipFile(BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_XLSX_UNCOMPRESSED_BYTES:
                raise SpreadsheetError("Die entpackte Excel-Datei ist für den Browser-Editor zu gross.")
    except BadZipFile as exc:
        raise SpreadsheetError("Die Datei ist keine gültige .xlsx-Datei.") from exc
    return content


def _load_workbook(content):
    try:
        return load_workbook(BytesIO(content), data_only=False)
    except Exception as exc:
        raise SpreadsheetError("Die Excel-Datei konnte nicht geöffnet werden.") from exc


def _open_workbook(document):
    _require_editor_dependency()
    return _load_workbook(_read_workbook_bytes(document))


def _cell_text(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")
    return str(value)


def _infer_cell_value(text):
    """Turn an edited cell's raw text back into a typed value where possible.

    Without this, every saved cell would come back as a plain string, silently
    turning numbers/dates/booleans into text on the very first save (Excel
    formulas and sorting elsewhere in the workbook would then break).
    """
    if text == "":
        return None
    if len(text) > 1 and text.startswith("="):
        return text  # openpyxl infers the formula type itself from the leading "="
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    for parser in (int, float, datetime.fromisoformat):
        try:
            return parser(text)
        except ValueError:
            continue
    return text


def get_editor_data(document, requested_sheet=None):
    workbook = _open_workbook(document)
    sheet_names = workbook.sheetnames
    sheet_name = requested_sheet if requested_sheet in sheet_names else workbook.active.title
    sheet = workbook[sheet_name]
    rows = max(sheet.max_row, 20)
    columns = max(sheet.max_column, 10)
    if rows > MAX_EDITABLE_ROWS or columns > MAX_EDITABLE_COLUMNS:
        raise SpreadsheetError(
            f"Diese Tabelle hat {rows} Zeilen und {columns} Spalten. Der Browser-Editor unterstützt maximal "
            f"{MAX_EDITABLE_ROWS} Zeilen und {MAX_EDITABLE_COLUMNS} Spalten pro Arbeitsblatt."
        )

    grid = []
    for row in range(1, rows + 1):
        grid_row = []
        for column in range(1, columns + 1):
            cell = sheet.cell(row=row, column=column)
            grid_row.append(
                {
                    "value": _cell_text(cell.value),
                    "bold": bool(cell.font.bold),
                    "font_size": cell.font.sz or 11,
                }
            )
        grid.append(grid_row)

    return {
        "sheet_names": sheet_names,
        "sheet_name": sheet_name,
        "rows": rows,
        "columns": columns,
        "grid": grid,
    }


def save_editor_data(document, *, sheet_name, cells, formats, expected_revision, user):
    if not isinstance(cells, list) or len(cells) > MAX_EDITABLE_ROWS:
        raise SpreadsheetError("Die übermittelten Tabellenzeilen sind ungültig.")
    if not isinstance(expected_revision, int) or expected_revision != document.spreadsheet_revision:
        raise SpreadsheetError("Die Datei wurde inzwischen geändert. Bitte lade den Editor neu.")

    _require_editor_dependency()
    original_content = _read_workbook_bytes(document)
    workbook = _load_workbook(original_content)
    if sheet_name not in workbook.sheetnames:
        raise SpreadsheetError("Das gewählte Arbeitsblatt existiert nicht mehr.")

    sheet = workbook[sheet_name]
    for row_number, row in enumerate(cells, start=1):
        if not isinstance(row, list) or len(row) > MAX_EDITABLE_COLUMNS:
            raise SpreadsheetError("Die übermittelten Tabellenspalten sind ungültig.")
        for column_number, value in enumerate(row, start=1):
            if not isinstance(value, str) or len(value) > 10_000:
                raise SpreadsheetError("Ein Tabellenwert ist ungültig oder zu lang.")
            cell = sheet.cell(row=row_number, column=column_number)
            if value == _cell_text(cell.value):
                continue  # untouched cell: leave its original type/format alone
            cell.value = _infer_cell_value(value)

    if not isinstance(formats, list) or len(formats) > MAX_EDITABLE_ROWS * MAX_EDITABLE_COLUMNS:
        raise SpreadsheetError("Die übermittelten Zellformatierungen sind ungültig.")
    for item in formats:
        if not isinstance(item, dict):
            raise SpreadsheetError("Eine Zellformatierung ist ungültig.")
        row = item.get("row")
        column = item.get("column")
        bold = item.get("bold")
        if (
            not isinstance(row, int)
            or not isinstance(column, int)
            or not isinstance(bold, bool)
            or row < 1
            or column < 1
            or row > len(cells)
            or column > MAX_EDITABLE_COLUMNS
        ):
            raise SpreadsheetError("Eine Zellformatierung ist ungültig.")
        cell = sheet.cell(row=row, column=column)
        font = copy(cell.font)
        font.bold = bold
        cell.font = font

    output = BytesIO()
    try:
        workbook.save(output)
    except Exception as exc:
        raise SpreadsheetError("Die Excel-Datei konnte nicht gespeichert werden.") from exc

    next_revision = document.spreadsheet_revision + 1
    old_file_basename = Path(document.file_name).name
    revision_name = f"protected/spreadsheet-revisions/document-{document.pk}-revision-{next_revision}-{old_file_basename}"
    saved_revision_name = default_storage.save(revision_name, ContentFile(original_content))
    new_file_name = ""
    try:
        new_file_name = default_storage.save(
            f"protected/spreadsheets/document-{document.pk}-{old_file_basename}", ContentFile(output.getvalue())
        )
        return saved_revision_name, new_file_name, next_revision
    except Exception:
        if new_file_name and default_storage.exists(new_file_name):
            default_storage.delete(new_file_name)
        if default_storage.exists(saved_revision_name):
            default_storage.delete(saved_revision_name)
        raise
