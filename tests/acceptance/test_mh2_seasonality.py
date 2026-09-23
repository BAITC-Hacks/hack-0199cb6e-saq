from ekt_core import make_dataset
from ekt_engine import run


def test_mh2_august_forecast_reflects_seasonality():
    forecast = run(make_dataset()).forecasts["SYN_SEASONAL"]
    assert forecast["2027-08"] >= 1.3 * forecast["2027-02"]
    assert len({round(value, 3) for value in forecast.values()}) > 1

