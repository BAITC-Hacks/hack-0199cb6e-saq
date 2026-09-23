from ekt_core import make_dataset
from ekt_engine import run


def test_mh3_stockout_demand_is_restored():
    result = run(make_dataset())
    row = result.by_sku("SYN_STOCKOUT")
    assert "STOCKOUT_RESTORED" in row["reason_codes"]
    assert result.restored_history["SYN_STOCKOUT"]["2026-05"] == 100.0
    assert result.restored_history["SYN_STOCKOUT"]["2026-06"] > 0

