from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Record, ValidationError

ZERO = Decimal("0.00")


def monthly_summary(records: list[Record], months=()) -> list[dict]:
    grouped = {month: {"income": ZERO, "expense": ZERO} for month in months}
    for record in records:
        bucket = grouped.setdefault(record.ym, {"income": ZERO, "expense": ZERO})
        bucket["income" if record.kind == "收入" else "expense"] += record.amount
    result = []
    for month, bucket in sorted(grouped.items()):
        income, expense = bucket["income"], bucket["expense"]
        previous = result[-1]["expense"] if result else ZERO
        result.append({
            "ym": month, "income": income, "expense": expense, "net": income - expense,
            "savings_rate": float((income - expense) / income * 100) if income else 0.0,
            "mom": float((expense - previous) / previous * 100) if previous else None,
        })
    return result


def category_breakdown(records: list[Record], month: str | None = None) -> list[dict]:
    totals = defaultdict(lambda: ZERO)
    for record in records:
        if record.kind == "支出" and (month is None or record.ym == month):
            totals[record.category] += record.amount
    total = sum(totals.values(), ZERO)
    return [
        {"category": category, "amount": amount, "share": float(amount / total * 100) if total else 0.0}
        for category, amount in sorted(totals.items(), key=lambda entry: (-entry[1], entry[0]))
    ]


def budget_status(records: list[Record], budgets: dict, month: str) -> list[dict]:
    actual = {row["category"]: row["amount"] for row in category_breakdown(records, month)}
    result = []
    for category, value in budgets.items():
        try:
            budget = Decimal(str(value))
            if not budget.is_finite() or budget < 0:
                raise InvalidOperation
            budget = budget.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"{category} 預算必須是非負數") from exc
        spent = actual.get(category, ZERO)
        result.append({
            "category": category, "budget": budget, "actual": spent,
            "remaining": budget - spent, "over": spent > budget,
            "ratio": float(spent / budget * 100) if budget else None,
        })
    return result


def forecast_next_expense(records: list[Record]) -> Decimal:
    months = monthly_summary(records)[-3:]
    if not months:
        return ZERO
    return (sum((row["expense"] for row in months), ZERO) / len(months)).quantize(Decimal("0.01"))


def export_chart(records: list[Record], path: str | Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    months = monthly_summary(records)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(figsize=(10, 4.8), layout="constrained")
    positions = list(range(len(months)))
    axes.bar([position - 0.2 for position in positions],
             [float(row["income"]) for row in months], width=0.4, color="#167D63", label="Income")
    axes.bar([position + 0.2 for position in positions],
             [float(row["expense"]) for row in months], width=0.4, color="#C44A56", label="Expense")
    axes.set_xticks(positions, [row["ym"] for row in months], rotation=30)
    axes.set_ylabel("TWD")
    axes.set_title("Monthly income and expenses")
    axes.legend()
    axes.spines[["top", "right"]].set_visible(False)
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path