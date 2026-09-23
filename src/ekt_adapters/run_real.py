"""Calculate and export recommendations from locally loaded partner workbooks."""

from __future__ import annotations

import argparse
from copy import copy
from pathlib import Path

from ekt_engine.export import CSV_COLUMNS, export_csv
from ekt_engine.pipeline import run

from .iek import load_iek
from .se import load_se

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "var" / "recommendations_real.csv"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_csv_row(row: dict) -> dict:
    result = row.copy()
    for key in CSV_COLUMNS:
        value = result.get(key)
        if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
            result[key] = "'" + value
    return result


def calculate(data_dir: str | Path, output: str | Path = DEFAULT_OUTPUT) -> list[dict]:
    """Run each supplier independently and print only aggregate counts."""
    recommendations: list[dict] = []
    summaries: list[dict] = []
    for supplier, loader in (("SE", load_se), ("IEK", load_iek)):
        dataset = loader(data_dir)
        forecastable = {row["sku_id"] for row in dataset.sales_monthly}
        run_dataset = copy(dataset)
        run_dataset.skus = [
            row for row in dataset.skus if row["sku_id"] in forecastable
        ]
        result = run(run_dataset)
        calculated = {row["sku"]: row for row in result.recommendations}
        if len(calculated) != len(result.recommendations):
            raise ValueError("DUPLICATE_RECOMMENDATION")
        supplier_rows = []
        for sku in dataset.skus:
            sku_id = sku["sku_id"]
            if sku_id in calculated:
                supplier_rows.append(calculated[sku_id])
            elif sku_id not in forecastable:
                supplier_rows.append({
                    "sku": sku_id,
                    "supplier": supplier,
                    "qty_recommended": 0,
                    "reason": "NO_HISTORY_INSUFFICIENT_DATA",
                    "urgency": "none",
                    "reason_codes": ["NO_HISTORY_INSUFFICIENT_DATA"],
                })
            else:
                raise ValueError("MISSING_RECOMMENDATION")
        excluded_lines = [
            row for row in result.one_off_lines
            if row["removed"] > 0 and row["sku_id"] in forecastable
        ]
        summaries.append({
            "supplier": supplier,
            "skus": len(dataset.skus),
            "without_history": len(dataset.skus) - len(run_dataset.skus),
            "recommendations": len(supplier_rows),
            "positive": sum(
                row["qty_recommended"] > 0 for row in supplier_rows
            ),
            "one_off_excluded_skus": len({
                row["sku_id"] for row in excluded_lines
            }),
            "one_off_excluded_lines": len(excluded_lines),
            "stockout_restored_skus": sum(
                "STOCKOUT_RESTORED" in row["reason_codes"]
                for row in result.recommendations
            ),
        })
        recommendations.extend(_safe_csv_row(row) for row in supplier_rows)

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    export_csv(recommendations, destination)
    for summary in summaries:
        print(
            f"{summary['supplier']}: skus={summary['skus']} "
            f"without_history={summary['without_history']} "
            f"recommendations={summary['recommendations']} "
            f"positive={summary['positive']} "
            f"one_off_excluded_skus={summary['one_off_excluded_skus']} "
            f"one_off_excluded_lines={summary['one_off_excluded_lines']} "
            f"stockout_restored_skus={summary['stockout_restored_skus']}"
        )
    print(f"total: recommendations={len(recommendations)} csv={destination}")
    return recommendations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ekt_adapters.run_real")
    parser.add_argument("data_dir")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        calculate(args.data_dir, args.output)
    except Exception as error:
        # Exceptions from spreadsheets may contain cell values; never echo them.
        print(f"ERROR: {type(error).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
