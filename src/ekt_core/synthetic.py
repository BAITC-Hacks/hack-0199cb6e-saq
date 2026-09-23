from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import cos, pi
from random import Random


@dataclass
class CanonicalDataset:
    as_of: date
    skus: list[dict]
    sales_monthly: list[dict]
    sales_lines: list[dict]
    stock_opening: list[dict]
    stock_current: list[dict]
    inbound: list[dict]
    season_prior: list[dict]
    growth_overrides: dict[str, float]
    truth: list[dict]


def _months(start_year: int, start_month: int, count: int) -> list[str]:
    result = []
    year, month = start_year, start_month
    for _ in range(count):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def _sku(
    sku_id: str,
    supplier: str,
    *,
    abc: str = "B",
    stock: float = 0,
    multiple: float = 1,
) -> tuple[dict, dict]:
    channel = "SE-MAIN" if supplier == "SE" else "IEK-PP"
    return (
        {
            "sku_id": sku_id,
            "supplier_id": supplier,
            "name": sku_id.replace("_", " ").title(),
            "abc": abc,
            "lifecycle": "active",
            "purchase_factor": 1.0,
            "min_order_qty": multiple,
            "order_multiple": multiple,
            "default_channel_id": channel,
        },
        {
            "sku_id": sku_id,
            "as_of": date(2026, 9, 22),
            "free": stock,
            "retail": 0.0,
            "showcase": 0.0,
            "tz": 0.0,
            "rc": 0.0,
        },
    )


def make_dataset(seed: int = 42, n_se: int = 60, n_iek: int = 140) -> CanonicalDataset:
    """Return deterministic synthetic canonical tables; no partner data is read."""
    del n_se, n_iek  # fixed acceptance fixture is intentionally small
    rng = Random(seed)
    months = _months(2024, 1, 32)
    sku_specs = [
        ("SYN_SEASONAL", "SE", "B", 20.0, 1.0),
        ("SYN_STOCKOUT", "IEK", "A", 0.0, 1.0),
        ("SYN_ONEOFF", "SE", "B", 100.0, 1.0),
        ("SYN_REGULAR_BIG", "IEK", "B", 500.0, 1.0),
        ("SYN_INTRANSIT", "IEK", "C", 100.0, 1.0),
        ("SYN_STEADY_SE", "SE", "A", 80.0, 10.0),
    ]
    skus, stock_current = [], []
    for sku_id, supplier, abc, stock, multiple in sku_specs:
        sku_row, stock_row = _sku(
            sku_id, supplier, abc=abc, stock=stock, multiple=multiple
        )
        skus.append(sku_row)
        stock_current.append(stock_row)

    sales_monthly: list[dict] = []
    truth: list[dict] = []
    sales_lines: list[dict] = []
    stock_opening: list[dict] = []

    for sku in skus:
        sku_id = sku["sku_id"]
        for index, month in enumerate(months):
            month_num = int(month[-2:])
            if sku_id == "SYN_SEASONAL":
                factor = 1.0 + 0.5 * cos(2 * pi * (month_num - 8) / 12)
                true_demand = 120.0 * factor
            elif sku_id == "SYN_INTRANSIT":
                true_demand = 300.0
            elif sku_id == "SYN_ONEOFF":
                true_demand = 1000.0
            elif sku_id == "SYN_REGULAR_BIG":
                true_demand = 4000.0
            else:
                true_demand = 100.0 if sku_id == "SYN_STOCKOUT" else 180.0

            observed = true_demand
            if sku_id == "SYN_STOCKOUT" and month in {"2026-06", "2026-07"}:
                observed = 0.0
            elif sku_id == "SYN_STOCKOUT" and month == "2026-05":
                observed = 50.0
            if sku_id == "SYN_ONEOFF" and month == "2026-04":
                observed += 50_000.0

            sales_monthly.append({"sku_id": sku_id, "month": month, "qty": observed})
            truth.append({"sku_id": sku_id, "month": month, "true_demand": true_demand})

            opening = 200.0
            if sku_id == "SYN_STOCKOUT":
                if month in {"2026-06", "2026-07", "2026-08"}:
                    opening = 0.0
                elif month == "2026-05":
                    opening = 200.0
            stock_opening.append({"sku_id": sku_id, "month": month, "qty": opening})

            if sku_id == "SYN_ONEOFF":
                for line_no in range(20):
                    sales_lines.append(
                        {
                            "sku_id": sku_id,
                            "ts": f"{month}-15",
                            "doc_key": f"{month}-{line_no}",
                            "doc_type": "Расходная накладная",
                            "qty": 50.0,
                            "client_hash": f"client-{line_no}",
                        }
                    )
            elif sku_id == "SYN_REGULAR_BIG":
                sales_lines.append(
                    {
                        "sku_id": sku_id,
                        "ts": f"{month}-10",
                        "doc_key": f"{month}-big",
                        "doc_type": "Расходная накладная",
                        "qty": 3000.0,
                        "client_hash": "regular-client",
                    }
                )
                for line_no in range(10):
                    sales_lines.append(
                        {
                            "sku_id": sku_id,
                            "ts": f"{month}-15",
                            "doc_key": f"{month}-{line_no}",
                            "doc_type": "Расходная накладная",
                            "qty": 100.0,
                            "client_hash": f"other-{line_no}",
                        }
                    )
            else:
                jitter = 1.0 + rng.uniform(-0.02, 0.02)
                sales_lines.append(
                    {
                        "sku_id": sku_id,
                        "ts": f"{month}-15",
                        "doc_key": f"{month}-base",
                        "doc_type": "Расходная накладная",
                        "qty": max(1.0, observed * jitter),
                        "client_hash": "synthetic-client",
                    }
                )

    # One line is reflected in monthly totals, another simulates LOOP-like tx-only data.
    sales_lines.extend(
        [
            {
                "sku_id": "SYN_ONEOFF",
                "ts": "2026-04-20",
                "doc_key": "2026-04-oneoff",
                "doc_type": "Расходная накладная",
                "qty": 50_000.0,
                "client_hash": "oneoff-client",
            },
            {
                "sku_id": "SYN_ONEOFF",
                "ts": "2026-03-20",
                "doc_key": "2026-03-tx-only",
                "doc_type": "Расходная накладная",
                "qty": 40_000.0,
                "client_hash": "tx-only-client",
            },
        ]
    )

    inbound = [
        {
            "sku_id": "SYN_INTRANSIT",
            "doc_id": "SYN-IN-1",
            "channel_id": "IEK-PP",
            "eta": date(2026, 10, 5),
            "qty": 120.0,
        }
    ]
    season_prior = []
    for supplier in ("SE", "IEK"):
        for month in range(1, 13):
            season_prior.append(
                {"supplier_id": supplier, "month_num": month, "coef": 1.0}
            )
    return CanonicalDataset(
        as_of=date(2026, 9, 22),
        skus=skus,
        sales_monthly=sales_monthly,
        sales_lines=sales_lines,
        stock_opening=stock_opening,
        stock_current=stock_current,
        inbound=inbound,
        season_prior=season_prior,
        growth_overrides={},
        truth=truth,
    )

