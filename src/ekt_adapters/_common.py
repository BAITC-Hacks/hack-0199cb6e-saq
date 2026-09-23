"""Column-based parsing shared by the two partner adapters."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from ekt_core.synthetic import CanonicalDataset

from .xlsx_safe import open_workbook

MONTH_NAMES = {
    "янв": 1, "январь": 1, "февр": 2, "февраль": 2,
    "март": 3, "апр": 4, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "авг": 8, "август": 8, "сент": 9,
    "сентябрь": 9, "окт": 10, "октябрь": 10,
    "нояб": 11, "ноябрь": 11, "дек": 12, "декабрь": 12,
}
MONTH_HEADER = re.compile(r"^([а-яё]+)\.?\s+(20\d{2})(?:\s+г\.?)?$", re.I)
PRIVATE_HEADER = re.compile(
    r"^(?:контрагент|клиент|покупатель|бин|иин|телефон|e-?mail|адрес)(?!.*hash)",
    re.I,
)
DERIVED_HEADERS = (
    "итого", "продажи ", "ср мес", "сумма последние", "кэф", "запас",
)


def normalized(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).lower()


def code(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if not isinstance(value, str):
        raise ValueError("CODE_NOT_TEXT: 1C codes must be stored as Excel text")
    return value.strip(" \t\r\n\xa0")


def number(value: object, *, empty: float | None = 0.0) -> float | None:
    if value is None or str(value).replace("\xa0", " ").strip().upper() in {"", "#N/A"}:
        return empty
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))


def timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return datetime.strptime(str(value).strip(), "%d.%m.%Y %H:%M:%S")


def month(value: object) -> str | None:
    match = MONTH_HEADER.fullmatch(normalized(value))
    if not match:
        return None
    month_number = MONTH_NAMES.get(match.group(1))
    if month_number is None:
        return None
    return f"{match.group(2)}-{month_number:02d}"


def header_map(values: tuple) -> dict[str, int]:
    headers = {normalized(value): index for index, value in enumerate(values) if value is not None}
    if any(PRIVATE_HEADER.search(name) for name in headers):
        raise ValueError("CLIENT_ID_RAW")
    return headers


def find_header(workbook) -> tuple[object, int, dict[str, int]]:
    for sheet in workbook.worksheets:
        if sheet.sheet_state != "visible":
            continue
        for row_number, values in enumerate(sheet.iter_rows(min_row=1, max_row=5, values_only=True), 1):
            headers = header_map(values)
            if {"дата", "номер", "документ", "код", "количество"} <= headers.keys():
                return sheet, row_number, headers
            if "номенклатура.код" in headers or "код 1с" in headers:
                return sheet, row_number, headers
    raise ValueError("UNKNOWN_XLSX_PROFILE")


def profile(headers: dict[str, int], sheet) -> str:
    if {"дата", "номер", "документ", "код", "количество"} <= headers.keys():
        return "lines"
    if {"код 1с", "категория 2026", "свободный остаток"} <= headers.keys():
        return "master_se"
    if {"код 1с", "артикул иэк"} <= headers.keys() and any(
        "поступление до" in name for name in headers
    ):
        return "master_iek"
    if "мин. разр. к отгр." in headers:
        return "moq_iek"
    monthly = [name for name in headers if month(name)]
    if monthly:
        if "ед.изм" in headers:
            return "stock_se"
        if "ед." in headers and any(
            normalized(value) == "нач. остаток"
            for row in sheet.iter_rows(min_row=2, max_row=3, values_only=True)
            for value in row
        ):
            return "stock_iek"
        if "артикул" in headers and "кратность" in headers:
            return "sales_se"
        if "номенклатура.код" in headers:
            return "sales_iek"
    if {"номенклатура.код", "артикул", "кратность"} <= headers.keys():
        return "moq_se"
    return "unknown"


def discover(directory: str | Path) -> list[tuple[Path, str]]:
    root = Path(directory)
    if not root.is_dir():
        raise ValueError("DATA_DIR must be an existing directory")
    found = []
    for path in sorted(root.rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        workbook = open_workbook(path)
        try:
            sheet, _, headers = find_header(workbook)
            kind = profile(headers, sheet)
            if kind != "unknown":
                found.append((path, kind))
        except ValueError as error:
            if str(error) != "UNKNOWN_XLSX_PROFILE":
                raise
        finally:
            workbook.close()
    return found


def rows(path: Path):
    workbook = open_workbook(path)
    try:
        sheet, header_row, headers = find_header(workbook)
        for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
            if not values or normalized(values[0]) in {"итого", "количество", "нач. остаток"}:
                continue
            yield headers, values
    finally:
        workbook.close()


def monthly_rows(path: Path, *, stock: bool) -> list[dict]:
    result = []
    for headers, values in rows(path):
        sku = code(values[headers["номенклатура.код"]])
        if not sku or normalized(values[headers.get("номенклатура", 0)]) in {
            "итого", "количество", "нач. остаток"
        }:
            continue
        for title, column in headers.items():
            period = month(title)
            if period is not None:
                result.append({"sku_id": sku, "month": period, "qty": number(values[column])})
            elif re.search(r"20\d{2}", title) and not title.startswith(DERIVED_HEADERS):
                raise ValueError("HDR_UNKNOWN_MONTH")
    return result


def transaction_rows(path: Path) -> list[dict]:
    result = []
    for headers, values in rows(path):
        if normalized(values[headers["дата"]]) == "итого":
            continue
        document = str(values[headers["документ"]] or "")
        if not document.startswith("Расходная накладная"):
            continue
        qty = number(values[headers["количество"]], empty=None)
        if qty is None:
            continue
        ts = timestamp(values[headers["дата"]])
        if ts.date() < date(2025, 1, 1):
            continue
        sku = code(values[headers["код"]])
        if not sku:
            continue
        result.append({
            "sku_id": sku, "ts": ts.isoformat(sep=" "),
            "doc_key": f"{ts.year}-{values[headers['номер']]}",
            "doc_type": "Расходная накладная", "qty": qty,
            "uom": str(values[headers["ед."]] or "") if "ед." in headers else "",
            "warehouse": str(values[headers["склад"]] or "") if "склад" in headers else "",
            "client_hash": None, "price": None,
        })
    return result


def new_sku(sku_id: str, supplier: str, name: str = "") -> dict:
    channel = "SE-MAIN" if supplier == "SE" else "IEK-PP"
    return {
        "sku_id": sku_id, "supplier_id": supplier, "supplier_article": None,
        "name": name or sku_id, "uom_sales": "шт", "uom_purchase": "шт",
        "purchase_factor": 1.0, "min_order_qty": 1.0, "order_multiple": 1.0,
        "abc": "C", "abc_source": "computed", "lifecycle": "active",
        "default_channel_id": channel,
    }


def dataset(
    supplier: str, skus: dict[str, dict], monthly_sales: list[dict],
    opening: list[dict], transactions: list[dict], as_of: date,
    *, current: dict[str, dict] | None = None, inbound: list[dict] | None = None,
) -> CanonicalDataset:
    # TODO(spec): pipeline currently requires string months/timestamps, not Period/datetime.
    current_month = as_of.strftime("%Y-%m")
    history = [row for row in monthly_sales if row["month"] < current_month]
    opening_by_sku = {
        row["sku_id"]: row["qty"] for row in opening if row["month"] == current_month
    }
    current = current or {}
    stock_current = []
    for sku_id in skus:
        if sku_id in current:
            stock_current.append(current[sku_id])
            continue
        sold = sum(
            row["qty"] for row in transactions
            if row["sku_id"] == sku_id and row["ts"][:7] == current_month
        )
        stock_current.append({
            "sku_id": sku_id, "as_of": as_of,
            "free": max(0.0, opening_by_sku.get(sku_id, 0.0) - sold),
            "reserved": 0.0, "retail": 0.0, "showcase": 0.0,
            "tz": 0.0, "rc": 0.0, "is_estimate": True,
        })
    return CanonicalDataset(
        as_of=as_of, skus=list(skus.values()), sales_monthly=history,
        sales_lines=transactions, stock_opening=opening,
        stock_current=stock_current, inbound=inbound or [],
        # TODO(spec): ingest the two season workbooks when their profile lands.
        season_prior=[
            {"supplier_id": supplier, "month_num": month_num, "coef": 1.0}
            for month_num in range(1, 13)
        ], growth_overrides={}, truth=[],
    )
