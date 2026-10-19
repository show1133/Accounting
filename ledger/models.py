from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class ValidationError(ValueError):
    pass


@dataclass
class Record:
    id: int
    date: dt.date | str
    category: str
    item: str
    amount: Decimal | str | int | float
    kind: str = "支出"
    payment: str = "現金"
    note: str = ""

    def __post_init__(self):
        try:
            if isinstance(self.date, dt.datetime):
                self.date = self.date.date()
            elif not isinstance(self.date, dt.date):
                self.date = dt.date.fromisoformat(self.date)
        except (ValueError, TypeError) as exc:
            raise ValidationError("日期必須為 YYYY-MM-DD") from exc
        if self.date > dt.date.today():
            raise ValidationError("不可登錄未來日期")
        try:
            amount = Decimal(str(self.amount))
            if not amount.is_finite() or amount <= 0:
                raise InvalidOperation
            self.amount = amount.quantize(Decimal("0.01"))
            if self.amount <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("金額必須是大於零的有效數字") from exc
        if isinstance(self.id, bool) or not isinstance(self.id, int) or self.id < 0:
            raise ValidationError("編號必須是非負整數")
        if self.kind not in ("收入", "支出"):
            raise ValidationError("收支類型必須是收入或支出")
        for field in ("category", "item", "payment", "note"):
            value = getattr(self, field)
            if not isinstance(value, str):
                raise ValidationError(f"{field} 必須是文字")
            setattr(self, field, value.strip())
        if not self.category or not self.item:
            raise ValidationError("類別與項目不可空白")

    @property
    def ym(self) -> str:
        return self.date.strftime("%Y-%m")

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.kind == "收入" else -self.amount

    @classmethod
    def from_dict(cls, data: dict) -> Record:
        return cls(
            id=data.get("id", 0), date=data.get("date", ""),
            category=data.get("category", data.get("cat", "")),
            item=data.get("item", ""), amount=data.get("amount", ""),
            kind=data.get("kind", data.get("type", "支出")),
            payment=data.get("payment", data.get("pay", "現金")),
            note=data.get("note", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "date": self.date.isoformat(), "ym": self.ym,
            "category": self.category, "item": self.item,
            "amount": str(self.amount), "kind": self.kind,
            "payment": self.payment, "note": self.note,
        }