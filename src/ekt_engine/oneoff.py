from collections import defaultdict
from statistics import median

from ekt_core.config import EngineParams


def exclude_oneoffs(
    history: dict[str, dict[str, float]], lines: list[dict], params: EngineParams
) -> tuple[dict[str, dict[str, float]], list[dict], dict[str, list[str]]]:
    by_sku: dict[str, list[dict]] = defaultdict(list)
    for line in lines:
        if line.get("doc_type") == "Расходная накладная" and line.get("qty", 0) > 0:
            by_sku[line["sku_id"]].append(line)

    cleaned = {sku: months.copy() for sku, months in history.items()}
    detected: list[dict] = []
    reasons: dict[str, list[str]] = defaultdict(list)
    for sku, sku_lines in by_sku.items():
        quantities = [float(row["qty"]) for row in sku_lines]
        med = median(quantities)
        candidates = [
            row for row in sku_lines if float(row["qty"]) >= params.oneoff_median_mult * med
        ]
        candidate_months = {row["ts"][:7] for row in candidates}
        clients = defaultdict(set)
        for row in candidates:
            clients[row.get("client_hash")].add(row["ts"][:7])
        regular = len(candidate_months) >= params.oneoff_recurrence_months or any(
            len(months) >= 3 for client, months in clients.items() if client
        )
        if candidates and regular:
            reasons[sku].append("REGULAR_LARGE_BUYER")
            continue
        candidates_by_month: dict[str, list[dict]] = defaultdict(list)
        for row in candidates:
            candidates_by_month[row["ts"][:7]].append(row)

        normal_months = {
            month: qty
            for month, qty in history.get(sku, {}).items()
            if month not in candidates_by_month
        }
        if not normal_months:
            # There is no reliable normal demand level to replace an outlier with.
            continue
        for month, month_candidates in candidates_by_month.items():
            same_season = [
                qty
                for normal_month, qty in normal_months.items()
                if normal_month[-2:] == month[-2:]
            ]
            # TODO(spec): replace the §2.3 line cap with a normal-month baseline.
            typical_month = median(same_season or list(normal_months.values()))
            month_lines = [row for row in sku_lines if row["ts"][:7] == month]
            candidate_ids = {id(row) for row in month_candidates}
            regular_lines_total = sum(
                float(row["qty"]) for row in month_lines if id(row) not in candidate_ids
            )
            candidate_total = sum(float(row["qty"]) for row in month_candidates)
            replacement = min(
                candidate_total, max(0.0, typical_month - regular_lines_total)
            )
            excess = candidate_total - replacement
            before = cleaned.get(sku, {}).get(month, 0.0)
            transaction_total = regular_lines_total + candidate_total
            transaction_regular = transaction_total - excess
            removed = min(excess, max(0.0, before - transaction_regular))
            if month in cleaned.get(sku, {}):
                cleaned[sku][month] = max(0.0, before - removed)
            for row in month_candidates:
                share = float(row["qty"]) / candidate_total
                detected.append(
                    {**row, "excess": excess * share, "removed": removed * share}
                )
            if removed > 0:
                reasons[sku].append("ONE_OFF_EXCLUDED")
            if removed < excess:
                reasons[sku].append("ONE_OFF_NOT_IN_MONTHLY")
    return cleaned, detected, dict(reasons)
