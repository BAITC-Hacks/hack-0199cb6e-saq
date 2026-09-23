from __future__ import annotations

from dataclasses import dataclass

from ekt_core.config import EngineParams

from .cleaning import clean_history
from .explain import add_explanations
from .forecast import make_forecasts
from .oneoff import exclude_oneoffs
from .policy import apply_policy
from .seasonality import seasonality_profiles
from .stockout import restore_stockouts


@dataclass
class RunResult:
    recommendations: list[dict]
    forecasts: dict[str, dict[str, float]]
    cleaned_history: dict[str, dict[str, float]]
    restored_history: dict[str, dict[str, float]]
    availability: dict[str, dict[str, float]]
    one_off_lines: list[dict]

    def by_sku(self, sku: str) -> dict:
        return next(row for row in self.recommendations if row["sku"] == sku)


def run(dataset, params: EngineParams | None = None) -> RunResult:
    params = params or EngineParams()
    history, clean_reasons = clean_history(dataset.sales_monthly)
    cleaned, one_off_lines, oneoff_reasons = exclude_oneoffs(
        history, dataset.sales_lines, params
    )
    restored, availability, stockout_reasons = restore_stockouts(
        cleaned, dataset.stock_opening, params
    )
    profiles = seasonality_profiles(restored, params)
    forecasts, sigmas, _levels = make_forecasts(
        restored, profiles, dataset.as_of, dataset.growth_overrides
    )
    recommendations = apply_policy(dataset, forecasts, sigmas, params)
    reasons: dict[str, list[str]] = {}
    for source in (clean_reasons, oneoff_reasons, stockout_reasons):
        for sku, codes in source.items():
            reasons.setdefault(sku, []).extend(codes)
    add_explanations(recommendations, reasons)
    return RunResult(
        recommendations=recommendations,
        forecasts=forecasts,
        cleaned_history=cleaned,
        restored_history=restored,
        availability=availability,
        one_off_lines=one_off_lines,
    )

