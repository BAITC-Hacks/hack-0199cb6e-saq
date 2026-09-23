def clean_history(rows: list[dict]) -> tuple[dict[str, dict[str, float]], dict[str, list[str]]]:
    history: dict[str, dict[str, float]] = {}
    reasons: dict[str, list[str]] = {}
    for row in rows:
        sku = row["sku_id"]
        qty = float(row["qty"])
        history.setdefault(sku, {})[row["month"]] = max(0.0, qty)
        if qty < 0:
            reasons.setdefault(sku, []).append("RETURNS_CLIPPED")
    return history, reasons

