from __future__ import annotations

import copy
import csv
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import tempfile

from .models import Record, ValidationError

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LEDGER_FILE = DATA_DIR / "ledger.json"
BACKUP_DIR = DATA_DIR / "backup"
CONFIG_FILE = ROOT / "config.json"
KEEP_BACKUPS = 5
DEFAULT_CONFIG = {
    "categories": ["餐飲", "交通", "居住", "購物", "醫療", "娛樂", "教育", "保險", "薪資", "其他"],
    "months": [],
    "budgets": {},
    "statement_keywords": {
        "交通": ["中油", "台塑石油", "加油", "高鐵", "台鐵", "捷運", "停車", "悠遊卡", "一卡通",
                 "計程車", "大車隊", "Uber", "遠通", "ETC", "客運"],
        "餐飲": ["全聯", "餐廳", "咖啡", "超商", "7-ELEVEN", "全家", "萊爾富", "OK便利", "超市",
                 "麥當勞", "肯德基", "摩斯", "星巴克", "路易莎", "八方雲集", "早餐", "便當",
                 "小吃", "食品", "餐", "飲料", "Foodpanda", "Uber Eats"],
        "購物": ["蝦皮", "momo", "PChome", "家樂福", "好市多", "COSTCO", "IKEA", "屈臣氏", "康是美",
                 "寶雅", "大創", "美德耐", "博客來", "商場", "百貨", "淘寶", "購物"],
        "醫療": ["醫院", "診所", "藥局", "牙醫", "醫療"],
        "娛樂": ["Netflix", "Spotify", "YouTube", "Disney", "KKBOX", "Steam", "影城", "威秀", "Apple.com"],
        "居住": ["台電", "電費", "自來水", "瓦斯", "中華電信", "台灣大哥大", "遠傳", "管理費"],
        "保險": ["保險", "人壽", "產險"],
    },
}


def atomic_json(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def records_from_payload(payload) -> list[Record]:
    if not isinstance(payload, list):
        raise ValidationError("帳本 JSON 最外層必須是陣列")
    records = []
    used_ids = set()
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise ValidationError(f"第 {index} 筆帳務必須是物件")
        record = Record.from_dict(row)
        if record.id == 0:
            record.id = max(used_ids, default=0) + 1
        if record.id in used_ids:
            raise ValidationError(f"帳本有重複編號：{record.id}")
        used_ids.add(record.id)
        records.append(record)
    return records


def records_from_web_export(payload) -> list[Record]:
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list):
        raise ValidationError("JSON 需為帳務陣列，或網頁「複製 JSON」產生的物件")
    rows = []
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise ValidationError(f"第 {index} 筆帳務必須是物件")
        if row.get("demo") is True:
            continue
        # Web page ids are timestamps (sometimes fractional); ids are reassigned on import.
        rows.append(Record.from_dict({**row, "id": 0}))
    return rows


def load_records() -> list[Record]:
    if not LEDGER_FILE.exists():
        atomic_json(LEDGER_FILE, [])
    with LEDGER_FILE.open(encoding="utf-8-sig") as stream:
        return records_from_payload(json.load(stream))


def save_records(records: list[Record]) -> None:
    payload = [record.to_dict() for record in records]
    records_from_payload(payload)
    if LEDGER_FILE.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(LEDGER_FILE, BACKUP_DIR / f"ledger-{stamp}.json")
    atomic_json(LEDGER_FILE, payload)
    if BACKUP_DIR.exists():
        backups = sorted(BACKUP_DIR.glob("ledger-*.json"), reverse=True)
        for old in backups[KEEP_BACKUPS:]:
            old.unlink()


def next_id(records: list[Record]) -> int:
    return max((record.id for record in records), default=0) + 1


def validate_month(value: str) -> str:
    try:
        parsed = dt.date.fromisoformat(value + "-01")
    except (ValueError, TypeError) as exc:
        raise ValidationError("月份必須為 YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != value:
        raise ValidationError("月份必須為 YYYY-MM")
    return value


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        atomic_json(CONFIG_FILE, DEFAULT_CONFIG)
    with CONFIG_FILE.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValidationError("設定檔必須是 JSON 物件")
    result = copy.deepcopy(DEFAULT_CONFIG)
    result.update(config)
    keywords = result["statement_keywords"]
    if isinstance(keywords, dict):
        # Merge newly shipped default keywords without dropping user-added ones.
        for category, defaults in DEFAULT_CONFIG["statement_keywords"].items():
            existing = keywords.setdefault(category, [])
            if isinstance(existing, list):
                existing.extend(k for k in defaults if k not in existing)
    if not isinstance(result["categories"], list) or not all(
        isinstance(category, str) and category.strip() for category in result["categories"]
    ):
        raise ValidationError("categories 必須是非空白類別文字的陣列")
    if not isinstance(result["months"], list):
        raise ValidationError("months 必須是月份陣列")
    for month in result["months"]:
        validate_month(month)
    if not isinstance(result["budgets"], dict) or not isinstance(result["statement_keywords"], dict):
        raise ValidationError("budgets 和 statement_keywords 必須是物件")
    return result


def save_config(config: dict) -> None:
    atomic_json(CONFIG_FILE, config)


def export_csv(records: list[Record], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["日期", "月份", "類別", "項目", "收支", "金額", "支付方式", "備註"])
        for record in sorted(records, key=lambda row: (row.date, row.id)):
            text_values = [record.category, record.item, record.payment, record.note]
            category, item, payment, note = [
                "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
                for value in text_values
            ]
            writer.writerow([record.date.isoformat(), record.ym, category, item,
                             record.kind, str(record.amount), payment, note])
    return path