"""Print aggregate import counts without exposing partner values."""

from __future__ import annotations

import argparse

from .iek import load_iek
from .se import load_se


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ekt_adapters.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load")
    load.add_argument("data_dir")
    args = parser.parse_args(argv)
    if args.command == "load":
        failed = False
        for supplier, loader in (("SE", load_se), ("IEK", load_iek)):
            try:
                result = loader(args.data_dir)
            except Exception as error:
                # A workbook exception may contain cell contents; never echo it.
                print(f"{supplier}: ERROR {type(error).__name__}")
                failed = True
                continue
            print(
                f"{supplier}: sales_monthly={len(result.sales_monthly)} "
                f"sales_lines={len(result.sales_lines)} "
                f"stock_opening={len(result.stock_opening)} "
                f"inbound={len(result.inbound)} skus={len(result.skus)}"
            )
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
