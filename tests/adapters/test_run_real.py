from __future__ import annotations

import csv
from types import SimpleNamespace

from ekt_adapters import run_real


def test_runner_exports_aggregates_and_escapes_formula_cells(monkeypatch, tmp_path, capsys):
    se = SimpleNamespace(
        skus=[{"sku_id": "=synthetic"}, {"sku_id": "safe"}, {"sku_id": "@missing"}],
        sales_monthly=[{"sku_id": "=synthetic"}, {"sku_id": "safe"}],
        supplier="SE",
    )
    iek = SimpleNamespace(
        skus=[{"sku_id": "iek"}],
        sales_monthly=[{"sku_id": "iek"}], supplier="IEK",
    )
    monkeypatch.setattr(run_real, "load_se", lambda _: se)
    monkeypatch.setattr(run_real, "load_iek", lambda _: iek)
    engine_skus = []

    def fake_run(dataset):
        engine_skus.append([row["sku_id"] for row in dataset.skus])
        if dataset.supplier == "SE":
            return SimpleNamespace(
                recommendations=[
                    {"sku": "=synthetic", "supplier": "SE", "qty_recommended": 10,
                     "reason": "@synthetic", "urgency": "medium",
                     "reason_codes": ["ONE_OFF_EXCLUDED", "STOCKOUT_RESTORED"]},
                    {"sku": "safe", "supplier": "SE", "qty_recommended": 0,
                     "reason": "synthetic", "urgency": "none", "reason_codes": []},
                ],
                one_off_lines=[
                    {"sku_id": "=synthetic", "removed": 10},
                    {"sku_id": "safe", "removed": 0},
                ],
            )
        return SimpleNamespace(
            recommendations=[
                {"sku": "iek", "supplier": "IEK", "qty_recommended": 5,
                 "reason": "synthetic", "urgency": "medium", "reason_codes": []},
            ],
            one_off_lines=[],
        )

    monkeypatch.setattr(run_real, "run", fake_run)
    output = tmp_path / "recommendations_real.csv"
    assert run_real.main(["synthetic-dir", "--output", str(output)]) == 0
    printed = capsys.readouterr().out
    assert "SE: skus=3 without_history=1 recommendations=3 positive=1 one_off_excluded_skus=1" in printed
    assert "IEK: skus=1 without_history=0 recommendations=1 positive=1 one_off_excluded_skus=0" in printed
    assert engine_skus == [["=synthetic", "safe"], ["iek"]]
    assert "=synthetic" not in printed
    assert "@synthetic" not in printed
    with output.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    assert rows[0]["sku"] == "'=synthetic"
    assert rows[0]["reason"] == "'@synthetic"
    assert rows[2]["sku"] == "'@missing"
    assert rows[2]["qty_recommended"] == "0"
    assert rows[2]["reason"] == "NO_HISTORY_INSUFFICIENT_DATA"
