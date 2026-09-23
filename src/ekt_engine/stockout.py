from collections import defaultdict
from statistics import median

from ekt_core.config import EngineParams


def restore_stockouts(
    history: dict[str, dict[str, float]],
    stock_opening: list[dict],
    params: EngineParams,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, list[str]]]:
    stocks: dict[str, dict[str, float]] = defaultdict(dict)
    for row in stock_opening:
        stocks[row["sku_id"]][row["month"]] = float(row["qty"])

    restored = {sku: months.copy() for sku, months in history.items()}
    availability: dict[str, dict[str, float]] = defaultdict(dict)
    reasons: dict[str, list[str]] = defaultdict(list)
    for sku, values in history.items():
        ordered = sorted(values)
        normal = [values[m] for m in ordered if stocks[sku].get(m, 1) > 0 and values[m] > 0]
        level = median(normal[-12:]) if normal else 0.0
        for index, month in enumerate(ordered):
            next_open = stocks[sku].get(ordered[index + 1], stocks[sku].get(month, 1)) if index + 1 < len(ordered) else stocks[sku].get(month, 1)
            open_qty = stocks[sku].get(month, 1)
            if open_qty <= 0 and next_open <= 0 and values[month] <= 0.1 * level:
                avail = 0.0
            elif (open_qty <= 0) != (next_open <= 0):
                avail = 0.5
            else:
                avail = 1.0
            availability[sku][month] = avail
            if avail < params.stockout_min_avail:
                restored[sku][month] = level
            elif avail < 0.95:
                restored[sku][month] = min(values[month] / avail, 1.5 * level)
            if restored[sku][month] > values[month]:
                reasons[sku].append("STOCKOUT_RESTORED")
    return restored, dict(availability), dict(reasons)

