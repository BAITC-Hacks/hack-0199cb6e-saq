"""IEK workbook loader for the current pipeline schema."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from ._common import (
    code, dataset, discover, find_header, monthly_rows, new_sku, number,
    normalized, rows, transaction_rows,
)
from .xlsx_safe import open_workbook

ORDER_MONTHS = {
    name: index for index, name in enumerate(
        ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
         "августа", "сентября", "октября", "ноября", "декабря"), 1
    )
}
ORDER_HEADER = re.compile(
    r"^(?:(?P<channel>рф|пп)\s+)?(?P<doc>ут-\d+)\s+от\s+"
    r"(?P<day>\d{1,2})\s+(?P<month>[а-я]+)\s+(?P<year>\d{4})\s*г\.?\s*"
    r"\(поступление до (?P<eta>\d{2}\.\d{2}\.\d{4})\)",
    re.I,
)


def _one(files: list[tuple[Path, str]], kind: str, *, required: bool = False) -> Path | None:
    matches = [path for path, profile in files if profile == kind]
    if len(matches) > 1:
        raise ValueError(f"AMBIGUOUS_PROFILE: {kind}")
    if not matches and required:
        raise ValueError(f"MISSING_PROFILE: {kind}")
    return matches[0] if matches else None


def _inbound(path: Path, skus: dict[str, dict]) -> list[dict]:
    result = []
    workbook = open_workbook(path)
    try:
        sheet, header_row, headers = find_header(workbook)
        documents = []
        for title, column in headers.items():
            match = ORDER_HEADER.match(title)
            if not match:
                continue
            order_date = date(
                int(match["year"]), ORDER_MONTHS[match["month"]], int(match["day"])
            )
            eta = datetime.strptime(match["eta"], "%d.%m.%Y").date()
            channel = {"рф": "IEK-RF", "пп": "IEK-PP"}.get(match["channel"], "IEK-UT")
            documents.append((column, match["doc"].upper(), channel, order_date, eta))
        seen: set[str] = set()
        for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
            if not values or normalized(values[0]) == "итого":
                continue
            sku_id = code(values[headers["код 1с"]])
            if not sku_id or sku_id in seen:
                continue
            seen.add(sku_id)
            sku = skus.setdefault(sku_id, new_sku(sku_id, "IEK"))
            sku["name"] = str(values[headers["наименование"]] or sku["name"])
            sku["supplier_article"] = values[headers["артикул иэк"]]
            latest_order: date | None = None
            for column, doc_id, channel, order_date, eta in documents:
                qty = number(values[column])
                if qty is None or qty <= 0:
                    continue
                result.append({
                    "sku_id": sku_id, "doc_id": doc_id, "channel_id": channel,
                    "order_date": order_date, "eta": eta, "qty": qty,
                    "source": "doc",
                })
                if latest_order is None or order_date >= latest_order:
                    sku["default_channel_id"] = channel
                    latest_order = order_date
    finally:
        workbook.close()
    return result


def load_iek(data_dir: str | Path):
    """Read IEK xlsx files below DATA_DIR without printing partner values."""
    files = discover(data_dir)
    sales_path = _one(files, "sales_iek", required=True)
    stock_path = _one(files, "stock_iek", required=True)
    assert sales_path is not None and stock_path is not None
    sales = monthly_rows(sales_path, stock=False)
    opening = monthly_rows(stock_path, stock=True)
    skus: dict[str, dict] = {}
    for path in (sales_path, stock_path):
        for headers, values in rows(path):
            sku_id = code(values[headers["номенклатура.код"]])
            if not sku_id:
                continue
            name = str(values[headers["номенклатура"]] or "")
            sku = skus.setdefault(sku_id, new_sku(sku_id, "IEK", name))
            if "ед." in headers:
                sku["uom_sales"] = str(values[headers["ед."]] or "шт")

    moq_path = _one(files, "moq_iek")
    if moq_path:
        seen_moq: set[str] = set()
        for headers, values in rows(moq_path):
            sku_id = code(values[headers["код 1с"]])
            if not sku_id or sku_id in seen_moq:
                continue
            seen_moq.add(sku_id)
            sku = skus.setdefault(sku_id, new_sku(sku_id, "IEK"))
            multiple = number(values[headers["мин. разр. к отгр."]]) or 1.0
            sku["min_order_qty"] = sku["order_multiple"] = multiple
            sku["supplier_article"] = values[headers["артикул поставщика"]]

    path_file = _one(files, "master_iek")
    inbound = _inbound(path_file, skus) if path_file else []
    transactions = []
    for path, kind in files:
        if kind == "lines":
            transactions.extend(
                row for row in transaction_rows(path) if row["sku_id"] in skus
            )
    if not transactions:
        raise ValueError("MISSING_TRANSACTIONS: IEK")
    as_of = max(date.fromisoformat(row["ts"][:10]) for row in transactions)
    return dataset("IEK", skus, sales, opening, transactions, as_of, inbound=inbound)
