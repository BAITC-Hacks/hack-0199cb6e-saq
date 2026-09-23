from copy import deepcopy

from ekt_core import make_dataset
from ekt_engine import run


def test_mh4_oneoff_is_excluded_but_regular_large_buyer_is_not():
    result = run(make_dataset())
    oneoff = result.by_sku("SYN_ONEOFF")
    regular = result.by_sku("SYN_REGULAR_BIG")
    assert "ONE_OFF_EXCLUDED" in oneoff["reason_codes"]
    assert "ONE_OFF_NOT_IN_MONTHLY" in oneoff["reason_codes"]
    assert any(row["sku_id"] == "SYN_ONEOFF" for row in result.one_off_lines)
    assert "REGULAR_LARGE_BUYER" in regular["reason_codes"]
    assert not any(row["sku_id"] == "SYN_REGULAR_BIG" for row in result.one_off_lines)
    assert result.cleaned_history["SYN_ONEOFF"]["2026-04"] == 1000.0
    assert result.cleaned_history["SYN_ONEOFF"]["2026-03"] == 1000.0
    changed = deepcopy(make_dataset())
    next(
        row for row in changed.sales_monthly
        if row["sku_id"] == "SYN_ONEOFF" and row["month"] == "2026-08"
    )["qty"] += 500.0
    changed.sales_lines.append(
        {
            "sku_id": "SYN_ONEOFF",
            "ts": "2026-08-20",
            "doc_key": "synthetic-tenfold",
            "doc_type": "Расходная накладная",
            "qty": 500.0,
            "client_hash": "synthetic-oneoff-client",
        }
    )
    after = run(changed)
    regular_before = result.cleaned_history["SYN_ONEOFF"]["2026-08"]
    regular_after = after.cleaned_history["SYN_ONEOFF"]["2026-08"]
    assert regular_before == 1000.0
    assert regular_after == regular_before
    assert next(
        row for row in after.one_off_lines if row["doc_key"] == "synthetic-tenfold"
    )["removed"] == 500.0
