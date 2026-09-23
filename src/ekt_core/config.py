from dataclasses import dataclass, field


@dataclass(frozen=True)
class EngineParams:
    review_days: int = 14
    lead_time_days: dict[str, int] = field(
        default_factory=lambda: {"SE": 45, "IEK": 24}
    )
    service_level_z: dict[str, float] = field(
        default_factory=lambda: {"A": 1.65, "B": 1.28, "C": 1.04, "N": 0.0}
    )
    oneoff_median_mult: float = 10.0
    oneoff_recurrence_months: int = 4
    stockout_min_avail: float = 0.3
    season_clip: tuple[float, float] = (0.5, 2.0)

