from zipfile import ZipFile

import pytest

from ekt_adapters.xlsx_safe import open_workbook


def test_rejects_macro_payload_before_parsing(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/vbaProject.bin", b"synthetic")
    with pytest.raises(ValueError, match="XLSX_MACROS_FORBIDDEN"):
        open_workbook(path)


def test_rejects_non_xlsx_extension(tmp_path):
    with pytest.raises(ValueError, match="Only .xlsx"):
        open_workbook(tmp_path / "synthetic.xlsm")
