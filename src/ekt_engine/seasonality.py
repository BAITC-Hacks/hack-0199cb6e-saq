from collections import defaultdict
from statistics import mean

from ekt_core.config import EngineParams


def seasonality_profiles(
    restored: dict[str, dict[str, float]], params: EngineParams
) -> dict[str, dict[int, float]]:
    profiles: dict[str, dict[int, float]] = {}
    for sku, values in restored.items():
        by_month: dict[int, list[float]] = defaultdict(list)
        for month, qty in values.items():
            by_month[int(month[-2:])].append(qty)
        raw = {month: mean(by_month.get(month, [1.0])) for month in range(1, 13)}
        center = mean(raw.values()) or 1.0
        clipped = {
            month: min(params.season_clip[1], max(params.season_clip[0], value / center))
            for month, value in raw.items()
        }
        norm = mean(clipped.values()) or 1.0
        profiles[sku] = {month: value / norm for month, value in clipped.items()}
    return profiles

