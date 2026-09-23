from datetime import date
from pathlib import Path

import pytest

from ekt_adapters import _common
from ekt_adapters import cli
from ekt_adapters._common import code, dataset, header_map, month, number, timestamp


def test_month_headers_and_code_are_lossless():
    assert month("янв. 2024") == "2024-01"
    assert month("Январь 2024 г.") == "2024-01"
    assert month("Категория 2026") is None
    assert code(" 030200192_\xa0") == "030200192_"
    assert code("щт23054819") == "щт23054819"
    assert code(30200192) == "30200192"
    assert code(30200192.0) == "30200192"
    with pytest.raises(ValueError, match="CODE_NOT_TEXT"):
        code(30200192.5)


def test_numbers_dates_and_private_headers():
    assert number("1\xa0234,5") == 1234.5
    assert number(None) == 0.0
    assert number(" #N/A\xa0") == 0.0
    assert number("#N/A", empty=None) is None
    assert timestamp("22.09.2026 9:00:00").isoformat() == "2026-09-22T09:00:00"
    with pytest.raises(ValueError, match="CLIENT_ID_RAW"):
        header_map(("Дата", "Контрагент", "Количество"))
    assert "клиент_hash" in header_map(("Клиент_hash",))


def test_partial_month_is_excluded_and_current_stock_estimated():
    sku = {
        "sku_id": "030200192_", "supplier_id": "SE", "name": "Synthetic",
        "abc": "C", "lifecycle": "active", "purchase_factor": 1,
        "min_order_qty": 1, "order_multiple": 1, "default_channel_id": "SE-MAIN",
    }
    result = dataset(
        "SE", {sku["sku_id"]: sku},
        [
            {"sku_id": sku["sku_id"], "month": "2026-08", "qty": 100.0},
            {"sku_id": sku["sku_id"], "month": "2026-09", "qty": 25.0},
        ],
        [{"sku_id": sku["sku_id"], "month": "2026-09", "qty": 50.0}],
        [{"sku_id": sku["sku_id"], "ts": "2026-09-22 09:00:00", "qty": 25.0}],
        date(2026, 9, 22),
    )
    assert [row["month"] for row in result.sales_monthly] == ["2026-08"]
    assert result.stock_current[0]["free"] == 25.0


def test_unknown_month_heading_is_rejected(monkeypatch):
    monkeypatch.setattr(
        _common, "rows",
        lambda _: iter([(
            {"номенклатура": 0, "номенклатура.код": 1, "марз 2026": 2},
            ("Synthetic", "030200192_", 10),
        )]),
    )
    with pytest.raises(ValueError, match="HDR_UNKNOWN_MONTH"):
        _common.monthly_rows(Path("synthetic.xlsx"), stock=False)


def test_transaction_filters_documents_and_empty_quantities(monkeypatch):
    headings = {
        "дата": 0, "номер": 1, "документ": 2, "код": 3,
        "номенклатура": 4, "ед.": 5, "склад": 6, "количество": 7,
    }
    monkeypatch.setattr(
        _common, "rows",
        lambda _: iter([
            (headings, ("22.09.2026 9:00:00", 1, "Расходная накладная",
                        "030200192_", "Synthetic", "шт", "Алматы", "1,5")),
            (headings, ("22.09.2026 9:00:00", 2, "Заказ покупателя",
                        "030200192_", "Synthetic", "шт", "Алматы", 999)),
            (headings, ("22.09.2026 9:00:00", 3, "Расходная накладная",
                        "030200192_", "Synthetic", "шт", "Алматы", None)),
        ]),
    )
    result = _common.transaction_rows(Path("synthetic.xlsx"))
    assert len(result) == 1
    assert result[0]["sku_id"] == "030200192_"
    assert result[0]["doc_key"] == "2026-1"
    assert result[0]["qty"] == 1.5


def test_cli_outputs_only_counts(monkeypatch, capsys):
    class SyntheticResult:
        skus = [{"sku_id": "SECRET_CODE_"}]
        sales_monthly = [{"qty": 987654.0}]
        sales_lines = [{"qty": 987654.0}]
        stock_opening = []
        inbound = []

    monkeypatch.setattr(cli, "load_se", lambda _: SyntheticResult())
    monkeypatch.setattr(cli, "load_iek", lambda _: SyntheticResult())
    assert cli.main(["load", "synthetic-dir"]) == 0
    output = capsys.readouterr().out
    assert "SE: sales_monthly=1 sales_lines=1" in output
    assert "IEK: sales_monthly=1 sales_lines=1" in output
    assert "SECRET_CODE_" not in output
    assert "987654" not in output


def test_cli_reports_each_supplier_without_traceback(monkeypatch, capsys):
    class SyntheticResult:
        skus = [{}]
        sales_monthly = []
        sales_lines = []
        stock_opening = []
        inbound = []

    def failed_loader(_):
        raise ValueError("sensitive synthetic cell value")

    monkeypatch.setattr(cli, "load_se", failed_loader)
    monkeypatch.setattr(cli, "load_iek", lambda _: SyntheticResult())
    assert cli.main(["load", "synthetic-dir"]) == 1
    output = capsys.readouterr().out
    assert "SE: ERROR ValueError" in output
    assert "IEK: sales_monthly=0 sales_lines=0" in output
    assert "Traceback" not in output
    assert "sensitive synthetic cell value" not in output
