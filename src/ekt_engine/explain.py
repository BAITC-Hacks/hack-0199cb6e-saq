def add_explanations(rows: list[dict], reasons: dict[str, list[str]]) -> list[dict]:
    for row in rows:
        sku_reasons = list(dict.fromkeys(reasons.get(row["sku"], [])))
        sku_reasons.insert(0, "BASE_DEMAND")
        if row["inbound"]:
            sku_reasons.append("INBOUND")
        row["reason_codes"] = sku_reasons
        row["urgency"] = (
            "critical"
            if row["stock_now"] < row["demand"] / 2
            else "medium" if row["qty_recommended"] > 0 else "none"
        )
        qty = round(row["qty_recommended"])
        demand = round(row["demand"])
        available = round(row["stock_now"] + row["inbound"])
        row["reason_short"] = {
            "ru": f"Заказать {qty} шт: спрос {demand}, доступно {available}.",
            "kk": f"{qty} дана тапсырыс: сұраныс {demand}, қолжетімді {available}.",
        }
        floor = max(0.0, -(row["demand"] + row["safety_stock"] - row["stock_now"] - row["inbound"]))
        row["waterfall"] = {
            "base": row["demand"],
            "safety_stock": row["safety_stock"],
            "stock_now": -row["stock_now"],
            "inbound": -row["inbound"],
            "floor": floor,
            "rounding": row["rounding"],
        }
        row["reason"] = row["reason_short"]["ru"]
    return rows

