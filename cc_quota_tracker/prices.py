"""單價表：隨版本發佈的資料檔（prices.json），來源是供應商公開的定價，執行時不連網、不下載（ADR-0013）。

每個模型有 input、output、cache 寫入（5 分鐘、1 小時）、cache 讀取五種單價，單位是每百萬 token 的美元。
有的模型依 prompt 長度分兩種單價（longPromptOver）：單價表只記不超過門檻的那一種，超過的那部分金額是未知。
對話紀錄裡的模型識別碼可能帶日期後綴（claude-haiku-4-5-20251001）：查不到時去掉後綴再查一次。"""
import json
import re
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Tuple

from .usage_ledger import TOKEN_FIELDS

PRICE_FILE = Path(__file__).with_name("prices.json")  # 打包時放在同一個位置（packaging/cc-quota-tracker.spec）
_DATE_SUFFIX = re.compile(r"-\d{8}$")


class ModelPrice(NamedTuple):
    rates: Tuple[float, ...]  # 每百萬 token 的美元，依 TOKEN_FIELDS 的順序
    long_prompt_over: Optional[int]  # prompt 超過這麼多 token 時單價不同（單價表不含那一種）；None 是不分


class PriceTable(NamedTuple):
    version: Optional[str]  # 單價表的版本日期；讀不到時是 None
    models: Dict[str, ModelPrice]
    readable: bool


def load(path: Optional[Path] = None) -> PriceTable:
    """讀不到、讀不懂、任何一個模型的單價不齊，都當成整份讀不到：單價表是隨版本發佈的，壞掉就是發佈出了錯。"""
    try:
        raw = json.loads((path or PRICE_FILE).read_text(encoding="utf-8"))
        version, entries = raw["version"], raw["models"]
        if not (isinstance(version, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", version) and isinstance(entries, dict)):
            raise ValueError("price table header")
        models = {model: _entry(entry) for model, entry in entries.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return PriceTable(None, {}, False)
    return PriceTable(version, models, True)


def _entry(entry) -> ModelPrice:
    rates = [entry[field] for field in TOKEN_FIELDS]
    if not all(isinstance(r, (int, float)) and not isinstance(r, bool) and r >= 0 for r in rates):
        raise ValueError("price table rates")
    over = entry.get("longPromptOver")
    if over is not None and not (isinstance(over, int) and not isinstance(over, bool) and over > 0):
        raise ValueError("price table longPromptOver")
    return ModelPrice(tuple(rates), over)


def lookup(table: PriceTable, model: str) -> Optional[ModelPrice]:
    return table.models.get(model) or table.models.get(_DATE_SUFFIX.sub("", model))
