"""Validate an xlsx archive before handing it to openpyxl."""

from pathlib import Path
from zipfile import BadZipFile, ZipFile

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


def open_workbook(path: str | Path, need_comments: bool = False):
    source = Path(path)
    if source.suffix.lower() != ".xlsx":
        raise ValueError("Only .xlsx files are accepted")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("XLSX_FILE_TOO_LARGE")
    try:
        with source.open("rb") as stream:
            if stream.read(4) != b"PK\x03\x04":
                raise ValueError("XLSX_BAD_SIGNATURE")
        with ZipFile(source) as archive:
            entries = archive.infolist()
            names = {entry.filename.lower() for entry in entries}
            if "[content_types].xml" not in names:
                raise ValueError("XLSX_MISSING_CONTENT_TYPES")
            if "xl/vbaproject.bin" in names:
                raise ValueError("XLSX_MACROS_FORBIDDEN")
            if len(entries) > MAX_ZIP_ENTRIES:
                raise ValueError("XLSX_TOO_MANY_ENTRIES")
            if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("XLSX_UNCOMPRESSED_TOO_LARGE")
            if any(
                entry.file_size / max(entry.compress_size, 1) > MAX_COMPRESSION_RATIO
                for entry in entries
            ):
                raise ValueError("XLSX_COMPRESSION_RATIO")
    except BadZipFile as error:
        raise ValueError("XLSX_BAD_ARCHIVE") from error

    from openpyxl import load_workbook

    return load_workbook(
        source, data_only=True, keep_links=False, read_only=not need_comments
    )
