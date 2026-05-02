"""Shared helpers for the A-share quant research pipeline."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = Path("data/quant.db")
DEFAULT_LEGACY_CSV_DIR = Path("/data/akshare/Akshare/stock_data")


@dataclass(frozen=True)
class StockMeta:
    code: str
    name: str
    market: str
    is_st: bool
    eligible: bool


def to_float(value: object) -> float | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def normalize_date(value: object) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def compact_date(value: str) -> str:
    return normalize_date(value).replace("-", "")


def market_of(code: str) -> str:
    if code.startswith(("300", "301")):
        return "ChiNext"
    if code.startswith("688"):
        return "STAR"
    if code.startswith(("8", "4", "920")):
        return "BSE"
    if code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return "Mainboard"
    return "Other"


def is_st_name(name: str) -> bool:
    upper = name.upper()
    return "ST" in upper or "PT" in upper or "退" in name


def make_meta(code: str, name: str) -> StockMeta:
    market = market_of(code)
    is_st = is_st_name(name)
    eligible = market in {"Mainboard", "ChiNext", "STAR"} and not is_st
    return StockMeta(code=code, name=name, market=market, is_st=is_st, eligible=eligible)


def parse_meta_from_filename(path: Path) -> StockMeta | None:
    stem = path.name.removesuffix("_daily.csv")
    parts = stem.split("_", 1)
    if len(parts) != 2:
        return None
    return make_meta(parts[0], parts[1])


def limit_threshold(market: str, is_st: bool) -> float:
    if is_st:
        return 4.8
    if market in {"ChiNext", "STAR"}:
        return 19.5
    if market == "BSE":
        return 29.5
    return 9.8


def is_limit_up(pct: float, market: str, is_st: bool) -> bool:
    return pct >= limit_threshold(market, is_st)


def is_limit_down(pct: float, market: str, is_st: bool) -> bool:
    return pct <= -limit_threshold(market, is_st)


def read_legacy_csv(path: Path) -> tuple[list[dict[str, object]], str | None]:
    required = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            fieldnames = set(reader.fieldnames or [])
            if not required.issubset(fieldnames):
                return [], "missing required columns"
            rows: list[dict[str, object]] = []
            for row in reader:
                date = normalize_date(row.get("日期", ""))
                values = {
                    "date": date,
                    "open": to_float(row.get("开盘")),
                    "close": to_float(row.get("收盘")),
                    "high": to_float(row.get("最高")),
                    "low": to_float(row.get("最低")),
                    "volume": to_float(row.get("成交量")),
                    "amount": to_float(row.get("成交额")),
                    "amplitude": to_float(row.get("振幅")),
                    "pct_chg": to_float(row.get("涨跌幅")),
                    "change_amount": to_float(row.get("涨跌额")),
                    "turnover": to_float(row.get("换手率")),
                }
                if not date or any(value is None for value in values.values()):
                    continue
                rows.append(values)
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"read error: {exc}"

    rows.sort(key=lambda item: str(item["date"]))
    if not rows:
        return [], "empty after parsing"
    return rows, None


def chunked(items: list[tuple], size: int) -> Iterable[list[tuple]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]
