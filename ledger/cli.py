from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from . import analytics, excel_export, statement, storage
from .github_sync import GitHubSync, SyncError
from .models import Record, ValidationError

console = Console(markup=False)
logger = logging.getLogger("ledger")


class RedactSecrets(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        token = os.getenv("GITHUB_TOKEN", "")
        record.msg = message.replace(token, "***") if token else message
        record.args = ()
        return True


def setup_logging() -> None:
    if logger.handlers:
        return
    directory = storage.ROOT / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "ledger.log", maxBytes=1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    handler.addFilter(RedactSecrets())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def show_table(title: str, columns: list[str], rows) -> None:
    table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*(str(value) for value in row))
    console.print(table)


def show_records(records: list[Record]) -> None:
    show_table("帳務明細", ["編號", "日期", "類別", "項目", "收支", "金額", "支付方式", "備註"],
               [[row.id, row.date, row.category, row.item, row.kind, f"{row.amount:,.2f}", row.payment, row.note]
                for row in sorted(records, key=lambda record: (record.date, record.id))])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="日常帳務管理：記帳、帳單、報表、GitHub 同步")
    commands = parser.add_subparsers(dest="command")
    add = commands.add_parser("add", help="新增帳務")
    add.add_argument("--date", default=dt.date.today().isoformat())
    add.add_argument("--category", required=True)
    add.add_argument("--item", required=True)
    add.add_argument("--amount", required=True)
    add.add_argument("--kind", "--type", choices=["收入", "支出"], default="支出")
    add.add_argument("--payment", "--pay", default="現金")
    add.add_argument("--note", default="")
    listing = commands.add_parser("list", help="查詢帳務")
    listing.add_argument("--month")
    listing.add_argument("--category")
    listing.add_argument("--keyword", default="")
    delete = commands.add_parser("delete", help="刪除帳務")
    delete.add_argument("--id", type=int, required=True)
    delete.add_argument("--yes", action="store_true", help="確認刪除")
    for name in ("category", "month"):
        manage = commands.add_parser(name, help="管理類別" if name == "category" else "管理月份")
        manage.add_argument("action", choices=["add", "remove", "list"])
        manage.add_argument("value", nargs="?")
    budget = commands.add_parser("budget", help="設定每月類別預算")
    budget.add_argument("--category", required=True)
    budget.add_argument("--amount", required=True)
    importing = commands.add_parser("import", help="預覽並匯入 PDF 帳單或網頁 JSON")
    source = importing.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path)
    source.add_argument("--json", type=Path)
    importing.add_argument("--year", type=int, default=dt.date.today().year)
    importing.add_argument("--yes", action="store_true", help="確認匯入全部")
    analyze = commands.add_parser("analyze", help="月度收支與預算分析")
    analyze.add_argument("--chart", action="store_true")
    exporting = commands.add_parser("export", help="Excel 與 CSV 匯出")
    exporting.add_argument("--excel", type=Path)
    exporting.add_argument("--csv", type=Path)
    sync = commands.add_parser("sync", help="GitHub 帳本上下載")
    sync.add_argument("--pull", action="store_true", help="下載遠端帳本，預設為上傳")
    sync.add_argument("--dry-run", action="store_true", help="不連線、不上傳")
    sync.add_argument("--force", action="store_true", help="明確允許取代既有帳本")
    sync.add_argument("--allow-public", action="store_true", help="允許公開個人帳務")
    return parser


def confirm(message: str) -> str:
    if not sys.stdin.isatty():
        raise ValidationError("非互動環境請明確加入 --yes")
    return input(message).strip()


def execute(args) -> None:
    config = storage.load_config()
    records = storage.load_records()
    if args.command == "add":
        record = Record(id=storage.next_id(records), date=args.date, category=args.category,
                        item=args.item, amount=args.amount, kind=args.kind,
                        payment=args.payment, note=args.note)
        storage.save_records(records + [record])
        console.print(f"已新增第 {record.id} 筆帳務")
    elif args.command == "list":
        if args.month:
            storage.validate_month(args.month)
        matches = [row for row in records if (not args.month or row.ym == args.month)
                   and (not args.category or row.category == args.category)
                   and args.keyword.casefold() in (row.item + " " + row.note).casefold()]
        show_records(matches)
        console.print(f"共 {len(matches)} 筆，淨額 {sum((row.signed_amount for row in matches), Decimal('0')):,.2f}")
    elif args.command == "delete":
        target = next((row for row in records if row.id == args.id), None)
        if target is None:
            raise ValidationError("找不到此帳務編號")
        show_records([target])
        if args.yes or confirm("確認刪除？[y/N] ").lower() == "y":
            storage.save_records([row for row in records if row.id != args.id])
            console.print("已刪除，原帳本已備份")
    elif args.command in ("category", "month"):
        key = "categories" if args.command == "category" else "months"
        values = config[key]
        if args.action == "list":
            known = {row.ym if key == "months" else row.category for row in records}
            console.print("\n".join(sorted(set(values) | known)) or "尚無資料")
            return
        if not args.value or not args.value.strip():
            raise ValidationError("請提供月份或類別名稱")
        value = args.value.strip()
        if key == "months":
            storage.validate_month(value)
        if args.action == "add" and value not in values:
            values.append(value)
        elif args.action == "remove":
            if any((row.ym if key == "months" else row.category) == value for row in records):
                raise ValidationError("仍有帳務使用此項目，不可移除")
            if value in values:
                values.remove(value)
            if key == "categories":
                config["budgets"].pop(value, None)
        storage.save_config(config)
        console.print("設定已儲存")
    elif args.command == "budget":
        analytics.budget_status([], {args.category: args.amount}, dt.date.today().strftime("%Y-%m"))
        config["budgets"][args.category] = str(Decimal(args.amount).quantize(Decimal("0.01")))
        storage.save_config(config)
        console.print("月預算已儲存")
    elif args.command == "import":
        if args.pdf:
            skipped: list[str] = []
            rows = statement.parse_pdf(args.pdf, config, args.year, skipped)
            if skipped:
                console.print(f"有 {len(skipped)} 行日期或金額無效（常見於 OCR 誤讀），已略過，請對照紙本帳單手動補登")
        else:
            rows = storage.records_from_web_export(json.loads(args.json.read_text(encoding="utf-8-sig")))
        rows = statement.dedupe(rows, records)
        if not rows:
            console.print("沒有可匯入的新帳務；帳單格式不符時請先檢查文字內容")
            return
        show_table("待匯入帳務", ["序號", "日期", "項目", "類別", "收支", "金額"],
                   [[index, row.date, row.item, row.category, row.kind, row.amount]
                    for index, row in enumerate(rows, start=1)])
        answer = "y" if args.yes else confirm("匯入 y=全部、n=取消，或序號如 1,3,5：").lower()
        if answer in ("n", ""):
            return
        if answer == "y":
            selected = rows
        else:
            try:
                indices = {int(value.strip()) for value in answer.split(",")}
            except ValueError as exc:
                raise ValidationError("請輸入有效序號") from exc
            if not indices or min(indices) < 1 or max(indices) > len(rows):
                raise ValidationError("序號超出範圍")
            selected = [row for index, row in enumerate(rows, start=1) if index in indices]
        first_id = storage.next_id(records)
        for offset, row in enumerate(selected):
            row.id = first_id + offset
        storage.save_records(records + selected)
        console.print(f"已匯入 {len(selected)} 筆")
    elif args.command == "analyze":
        monthly = analytics.monthly_summary(records, config["months"])
        show_table("月度收支", ["月份", "收入", "支出", "結餘", "儲蓄率", "支出環比"],
                   [[row["ym"], f'{row["income"]:,.2f}', f'{row["expense"]:,.2f}',
                     f'{row["net"]:,.2f}', f'{row["savings_rate"]:.1f}%',
                     f'{row["mom"]:+.1f}%' if row["mom"] is not None else "—"] for row in monthly])
        show_table("全期支出類別", ["類別", "金額", "占比"],
                   [[row["category"], f'{row["amount"]:,.2f}', f'{row["share"]:.1f}%']
                    for row in analytics.category_breakdown(records)])
        if records:
            month = max(row.ym for row in records)
            show_table(f"{month} 預算", ["類別", "預算", "實支", "剩餘", "狀態"],
                       [[row["category"], row["budget"], row["actual"], row["remaining"], "超支" if row["over"] else "正常"]
                        for row in analytics.budget_status(records, config["budgets"], month)])
        console.print(f"下期支出參考（最近三個有紀錄月份平均）：{analytics.forecast_next_expense(records):,.2f}")
        if args.chart:
            console.print(str(analytics.export_chart(records, storage.ROOT / "reports" / "monthly.png")))
    elif args.command == "export":
        if not args.excel and not args.csv:
            args.excel = storage.ROOT / "reports" / "ledger.xlsx"
        if args.excel:
            console.print(str(excel_export.export_excel(records, args.excel, config["budgets"], config["months"])))
        if args.csv:
            console.print(str(storage.export_csv(records, args.csv)))
    elif args.command == "sync":
        if args.pull and args.dry_run:
            raise ValidationError("--dry-run 只適用於上傳")
        client = GitHubSync()
        console.print(client.pull(force=args.force) if args.pull else
                      client.push(records, dry_run=args.dry_run, force=args.force, allow_public=args.allow_public))
    logger.info("Completed command: %s", args.command)


def interactive(parser) -> None:
    while True:
        console.print("\n日常帳務管理\n1 新增帳務  2 帳務明細  3 刪除帳務  4 月份與類別\n5 帳單匯入  6 財務分析  7 匯出報表  8 GitHub 同步  9 預算  0 結束")
        choice = input("選擇：").strip()
        if choice == "0":
            return
        arguments = []
        if choice == "1":
            arguments = ["add", "--date", input("日期 YYYY-MM-DD（空白=今天）：").strip() or dt.date.today().isoformat(),
                         "--category", input("類別：").strip(), "--item", input("項目：").strip(),
                         "--amount", input("金額：").strip(), "--kind", input("收入/支出（空白=支出）：").strip() or "支出",
                         "--payment", input("支付方式（空白=現金）：").strip() or "現金",
                         "--note", input("備註：").strip()]
        elif choice == "2":
            arguments = ["list"]
            month = input("查詢月份 YYYY-MM（空白=全部）：").strip()
            if month:
                arguments.extend(["--month", month])
        elif choice == "3":
            arguments = ["delete", "--id", input("刪除編號：").strip()]
        elif choice == "4":
            arguments = [input("category=類別 / month=月份：").strip(),
                         input("add=新增 / remove=移除 / list=列出：").strip()]
            if arguments[1] != "list":
                arguments.append(input("名稱或月份：").strip())
        elif choice == "5":
            path = input("PDF 或 JSON 檔案路徑：").strip().strip('"')
            arguments = ["import", "--json" if path.lower().endswith(".json") else "--pdf", path]
        elif choice == "6":
            arguments = ["analyze"]
        elif choice == "7":
            arguments = ["export", "--excel", "reports/ledger.xlsx", "--csv", "reports/ledger.csv"]
        elif choice == "8":
            mode = input("1 試跑 / 2 上傳 / 3 下載：").strip()
            if mode not in ("1", "2", "3"):
                continue
            arguments = ["sync"] + ({"1": ["--dry-run"], "2": [], "3": ["--pull"]}[mode])
        elif choice == "9":
            arguments = ["budget", "--category", input("類別：").strip(), "--amount", input("每月預算：").strip()]
        else:
            continue
        try:
            execute(parser.parse_args(arguments))
        except SystemExit:
            continue
        except (ValueError, OSError, SyncError) as exc:
            show_error(exc)


def show_error(exc: Exception) -> None:
    message = str(exc)
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        message = message.replace(token, "***")
    console.print("錯誤：" + message)
    logger.error("%s", message)


def main(argv=None) -> int:
    load_dotenv(storage.ROOT / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        setup_logging()
        if args.command is None:
            if not sys.stdin.isatty():
                parser.print_help()
                return 0
            storage.load_config()
            storage.load_records()
            interactive(parser)
        else:
            execute(args)
        return 0
    except (KeyboardInterrupt, EOFError):
        console.print("\n已取消")
        return 130
    except (ValueError, OSError, SyncError) as exc:
        show_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())