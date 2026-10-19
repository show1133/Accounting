from __future__ import annotations

import datetime as dt
from pathlib import Path
import re
from typing import Iterable

from .models import Record, ValidationError

DATE = r"(?:(?P<year>\d{3,4})[/.-])?(?P<month>\d{1,2})[/.-](?P<day>\d{1,2})"
LINE = re.compile(
    r"^\s*" + DATE
    + r"\s+(?:(?:\d{3,4}[/.-])?\d{1,2}[/.-]\d{1,2}\s+)?"
    + r"(?P<item>.+?)\s+(?:NT\$\s*|TWD\s*)?"
    + r"(?P<amount>-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\s*$",
    re.IGNORECASE,
)
# Paying the card bill is a transfer, not income; refunds (退款) are still kept.
SUMMARY_WORDS = ("本期應繳", "最低應繳", "循環利息", "上期結欠", "本期合計", "繳款截止", "信用額度",
                 "繳款", "扣繳")


def categorize(item: str, config: dict) -> str:
    # OCR inserts spaces between characters, so compare without whitespace.
    text = re.sub(r"\s+", "", item).casefold()
    for name, keywords in config.get("statement_keywords", {}).items():
        if any(key and key in text for key in (re.sub(r"\s+", "", k).casefold() for k in keywords)):
            return name
    return "其他"


def parse_lines(lines: Iterable[str], config: dict, default_year: int | None = None,
                skipped: list[str] | None = None) -> list[Record]:
    default_year = default_year or dt.date.today().year
    result = []
    for line in lines:
        if any(word in re.sub(r"\s+", "", line) for word in SUMMARY_WORDS):
            continue
        match = LINE.match(line)
        if not match:
            continue
        year = int(match["year"]) if match["year"] else default_year
        if year < 1911:
            year += 1911
        item = match["item"].strip()
        amount = match["amount"].replace(",", "")
        category = categorize(item, config)
        try:
            date = dt.date(year, int(match["month"]), int(match["day"]))
            result.append(Record(
                id=0, date=date, category=category, item=item,
                amount=amount.lstrip("-"), kind="收入" if amount.startswith("-") else "支出",
                payment="信用卡",
            ))
        except (ValueError, ValidationError) as exc:
            if skipped is not None:
                skipped.append(line.strip())
                continue
            raise ValidationError(f"無法匯入帳單列：{line.strip()}（{exc}）") from exc
    return result


def parse_pdf(path: str | Path, config: dict, default_year: int | None = None,
              skipped: list[str] | None = None) -> list[Record]:
    import pdfplumber

    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").splitlines())
    if not "".join(lines).strip():
        from . import ocr

        if not ocr.available():
            raise ValidationError("PDF 為掃描影像，且本機沒有可用的繁體中文 OCR（需 Windows 10/11 與 requirements 中的 winrt 套件）")
        lines = ocr.pdf_lines(path)
        if skipped is None:
            skipped = []
    return parse_lines(lines, config, default_year, skipped)


def dedupe(rows: list[Record], existing: list[Record]) -> list[Record]:
    seen = {(row.date, row.amount, row.item) for row in existing}
    unique = []
    for row in rows:
        key = (row.date, row.amount, row.item)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique