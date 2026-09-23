"""Run the real viewer against disposable synthetic data, never partner data."""

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ekt_api.viewer import create_app


def main() -> None:
    with TemporaryDirectory(prefix="ekt-viewer-synthetic-") as directory:
        csv_path = Path(directory) / "recommendations.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.writer(destination, delimiter=";")
            writer.writerow(["sku", "supplier", "qty_recommended", "reason", "urgency"])
            writer.writerows(
                [
                    [
                        "0001_",
                        "SE",
                        "24",
                        "Синтетика: покрытие спроса на срок поставки.",
                        "high",
                    ],
                    [
                        "SYN_PACK",
                        "ИЭК",
                        "12",
                        "Синтетика: партия с учётом кратности.",
                        "medium",
                    ],
                    [
                        "SYN_URGENT",
                        "IEK",
                        "48",
                        "Синтетика: ожидается дефицит до поставки.",
                        "critical",
                    ],
                    ["SYN_ZERO", "SE", "0", "Синтетика: запаса достаточно.", "none"],
                ]
            )
        uvicorn.run(create_app(csv_path), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
