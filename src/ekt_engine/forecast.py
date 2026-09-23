from __future__ import annotations

from datetime import date
from statistics import mean, pstdev


def _future_months(as_of: date, count: int = 12) -> list[str]:
    year, month = as_of.year, as_of.month
    result = []
    for _ in range(count):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def make_forecasts(
    restored: dict[str, dict[str, float]],
    profiles: dict[str, dict[int, float]],
    as_of: date,
    growth_overrides: dict[str, float],
) -> tuple[dict[str, dict[str, float]], dict[str, float], dict[str, float]]:
    forecasts: dict[str, dict[str, float]] = {}
    sigmas: dict[str, float] = {}
    levels: dict[str, float] = {}
    future = _future_months(as_of)
    for sku, values in restored.items():
        ordered = sorted(values)[-12:]
        deseasonalized = [
            values[month] / profiles[sku][int(month[-2:])] for month in ordered
        ]
        level = mean(deseasonalized) if deseasonalized else 0.0
        growth = 1.0 + growth_overrides.get(sku, 0.0)
        forecasts[sku] = {
            month: level * profiles[sku][int(month[-2:])] * growth for month in future
        }
        residuals = [
            values[month] - level * profiles[sku][int(month[-2:])] for month in ordered
        ]
        sigmas[sku] = max(1.0, pstdev(residuals) if len(residuals) > 1 else level**0.5)
        levels[sku] = level
    return forecasts, sigmas, levels
