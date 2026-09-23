"""Systeme Electric workbook loader for the current pipeline schema."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from ._common import (
    code, dataset, discover, find_header, monthly_rows, new_sku, number,
    normalized, rows, transaction_rows,
)
from .xlsx_safe import open_workbook

DEFAULT_INBOUND_ETA_DAYS = 14
ABC = {"1": "A", "2": "B", "3": "C", "5": "B", "7": "N"}


def _one(files: list[tuple[Path, str]], kind: str, *, required: bool = False) -> Path | None:
    matches = [path for path, profile in files if profile == kind]
    if len(matches) > 1:
        raise ValueError(f"AMBIGUOUS_PROFILE: {kind}")
    if not matches and required:
        raise ValueError(f"MISSING_PROFILE: {kind}")
    return matches[0] if matches else None


def _master(
    path: Path, skus: dict[str, dict], as_of: date
) -> tuple[dict[str, dict], list[dict]]:
    current: dict[str, dict] = {}
    inbound: list[dict] = []
    workbook = open_workbook(path, need_comments=True)
    try:
        sheet, header_row, headers = find_header(workbook)
        incoming = next((key for key in headers if key.startswith("сэ в пути")), None)
        stock_columns = {
            "free": "свободный остаток", "reserved": "зарезервировано",
            "retail": "розничный склад", "showcase": "витрина",
            "tz": "остаток тз", "rc": "рц ект рыскулова",
        }
        seen: set[str] = set()
        for cells in sheet.iter_rows(min_row=header_row + 1):
            first = cells[0].value if cells else None
            if normalized(first) == "итого":
                continue
            sku_id = code(cells[headers["код 1с"]].value)
            if not sku_id or sku_id in seen:
                continue
            seen.add(sku_id)
            sku = skus.setdefault(sku_id, new_sku(sku_id, "SE"))
            sku["name"] = str(cells[headers["наименование"]].value or sku["name"])
            if "артикул поставщика" in headers:
                sku["supplier_article"] = cells[headers["артикул поставщика"]].value
            category = str(cells[headers["категория 2026"]].value or "")
            sku["abc"] = ABC.get(category, sku["abc"])
            sku["abc_source"] = "data"
            current[sku_id] = {
                "sku_id": sku_id, "as_of": as_of,
                **{
                    field: number(cells[headers[title]].value)
                    if title in headers else 0.0
                    for field, title in stock_columns.items()
                },
                "is_estimate": False,
            }
            if incoming is None:
                continue
            quantity = number(cells[headers[incoming]].value)
            if quantity is None or quantity <= 0:
                continue
            comment = cells[headers[incoming]].comment
            eta_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\b", comment.text) if comment else None
            eta = as_of + timedelta(days=DEFAULT_INBOUND_ETA_DAYS)
            source = "default"
            if eta_match:
                eta = date(as_of.year, int(eta_match.group(2)), int(eta_match.group(1)))
                if eta < as_of - timedelta(days=30):
                    eta = eta.replace(year=eta.year + 1)
                source = "comment"
            inbound.append({
                "sku_id": sku_id, "doc_id": f"SE-TRANSIT-{sku_id}",
                "channel_id": "SE-MAIN", "order_date": None,
                "eta": eta, "qty": quantity, "source": source,
            })
    finally:
        workbook.close()
    return current, inbound


def load_se(data_dir: str | Path):
    """Read SE xlsx files below DATA_DIR without printing partner values."""
    files = discover(data_dir)
    sales_path = _one(files, "sales_se", required=True)
    stock_path = _one(files, "stock_se", required=True)
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
            sku = skus.setdefault(sku_id, new_sku(sku_id, "SE", name))
            if "ед.изм" in headers:
                sku["uom_sales"] = str(values[headers["ед.изм"]] or "шт")
            if "артикул" in headers:
                sku["supplier_article"] = values[headers["артикул"]]

    moq_path = _one(files, "moq_se")
    if moq_path:
        seen_moq: set[str] = set()
        for headers, values in rows(moq_path):
            sku_id = code(values[headers["номенклатура.код"]])
            if not sku_id or sku_id in seen_moq:
                continue
            seen_moq.add(sku_id)
            sku = skus.setdefault(sku_id, new_sku(sku_id, "SE"))
            multiple = number(values[headers["кратность"]]) or 1.0
            sku["order_multiple"] = sku["min_order_qty"] = multiple

    master_path = _one(files, "master_se")
    if master_path:
        for headers, values in rows(master_path):
            sku_id = code(values[headers["код 1с"]])
            if sku_id:
                skus.setdefault(sku_id, new_sku(sku_id, "SE"))

    transactions = []
    for path, kind in files:
        if kind == "lines":
            transactions.extend(
                row for row in transaction_rows(path) if row["sku_id"] in skus
            )
    if not transactions:
        raise ValueError("MISSING_TRANSACTIONS: SE")
    as_of = max(date.fromisoformat(row["ts"][:10]) for row in transactions)

    current, inbound = _master(master_path, skus, as_of) if master_path else ({}, [])
    return dataset(
        "SE", skus, sales, opening, transactions, as_of,
        current=current, inbound=inbound,
    )
