from copy import deepcopy

from ekt_core import EngineParams, make_dataset
from ekt_engine import run


def test_mh1_all_sources_change_recommendation():
    dataset = make_dataset()
    base = run(dataset).by_sku("SYN_INTRANSIT")["qty_recommended"]

    more_stock = deepcopy(dataset)
    next(row for row in more_stock.stock_current if row["sku_id"] == "SYN_INTRANSIT")["free"] += 200
    assert run(more_stock).by_sku("SYN_INTRANSIT")["qty_recommended"] < base

    no_inbound = deepcopy(dataset)
    no_inbound.inbound.clear()
    assert run(no_inbound).by_sku("SYN_INTRANSIT")["qty_recommended"] > base

    more_history = deepcopy(dataset)
    for row in more_history.sales_monthly:
        if row["sku_id"] == "SYN_INTRANSIT":
            row["qty"] *= 1.5
    assert run(more_history).by_sku("SYN_INTRANSIT")["qty_recommended"] > base

    higher_service = deepcopy(dataset)
    next(
        row for row in higher_service.skus if row["sku_id"] == "SYN_INTRANSIT"
    )["abc"] = "A"
    assert run(higher_service).by_sku("SYN_INTRANSIT")["qty_recommended"] > base

    growth = deepcopy(dataset)
    growth.growth_overrides["SYN_INTRANSIT"] = 0.20
    assert run(growth).by_sku("SYN_INTRANSIT")["qty_recommended"] > base

    longer = EngineParams(lead_time_days={"SE": 45, "IEK": 54})
    assert run(dataset, longer).by_sku("SYN_INTRANSIT")["qty_recommended"] > base

    rounded = deepcopy(dataset)
    next(row for row in rounded.skus if row["sku_id"] == "SYN_INTRANSIT")[
        "order_multiple"
    ] = 50
    assert run(rounded).by_sku("SYN_INTRANSIT")["qty_recommended"] % 50 == 0
