import csv

from ekt_core import make_dataset
from ekt_engine import export_csv, run


def test_mh5_explanations_groups_and_csv_contract(tmp_path):
    result = run(make_dataset())
    assert {row["supplier"] for row in result.recommendations} == {"SE", "IEK"}
    for row in result.recommendations:
        assert any(char.isdigit() for char in row["reason_short"]["ru"])
        assert any(char.isdigit() for char in row["reason_short"]["kk"])
        assert abs(sum(row["waterfall"].values()) - row["qty_recommended"]) < 1e-6
        assert row["channel_id"]

    output = export_csv(result.recommendations, tmp_path / "recommendations.csv")
    with output.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ["sku", "supplier", "qty_recommended", "reason", "urgency"]
        assert len(list(reader)) == len(result.recommendations)
