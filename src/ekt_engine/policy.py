from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from math import ceil, sqrt

from ekt_core.config import EngineParams


def _demand_over_days(forecast: dict[str, float], start: date, days: int) -> float:
    total = 0.0
    for offset in range(1, days + 1):
        day = start + timedelta(days=offset)
        key = f"{day.year:04d}-{day.month:02d}"
        total += forecast[key] / monthrange(day.year, day.month)[1]
    return total


def apply_policy(
    dataset,
    forecasts: dict[str, dict[str, float]],
    sigmas: dict[str, float],
    params: EngineParams,
) -> list[dict]:
    stocks = {row["sku_id"]: row for row in dataset.stock_current}
    results = []
    for sku in dataset.skus:
        sku_id = sku["sku_id"]
        supplier = sku["supplier_id"]
        lead = params.lead_time_days[supplier]
        horizon = lead + params.review_days
        demand = _demand_over_days(forecasts[sku_id], dataset.as_of, horizon)
        safety = params.service_level_z.get(sku.get("abc") or "C", 1.04) * sigmas[sku_id] * sqrt(horizon / 30.4375)
        stock_row = stocks[sku_id]
        stock = sum(float(stock_row.get(key, 0)) for key in ("free", "retail", "showcase", "tz"))
        inbound = sum(
            float(row["qty"])
            for row in dataset.inbound
            if row["sku_id"] == sku_id and row["eta"] <= dataset.as_of + timedelta(days=horizon)
        )
        q0 = demand + safety - stock - inbound
        raw = max(0.0, q0)
        multiple = float(sku.get("order_multiple", 1) or 1)
        minimum = float(sku.get("min_order_qty", 1) or 1)
        purchase = max(minimum, ceil(raw / multiple) * multiple) if raw > 0 else 0.0
        final = purchase * float(sku.get("purchase_factor", 1) or 1)
        results.append(
            {
                "sku": sku_id,
                "supplier": supplier,
                "channel_id": sku["default_channel_id"],
                "qty_recommended": final,
                "demand": demand,
                "safety_stock": safety,
                "stock_now": stock,
                "inbound": inbound,
                "raw_qty": raw,
                "rounding": final - raw,
                "order_multiple": multiple,
            }
        )
    return results

