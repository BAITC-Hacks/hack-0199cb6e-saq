import csv
from pathlib import Path


CSV_COLUMNS = ["sku", "supplier", "qty_recommended", "reason", "urgency"]


def export_csv(rows: list[dict], path: str | Path) -> Path:
    destination = Path(path)
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return destination

