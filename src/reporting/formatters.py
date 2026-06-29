"""Formatting helpers shared by report pages."""

from __future__ import annotations

import math


SOURCE_LABELS = {
    "eastmoney_zt_pool": "东方财富涨停池",
    "eastmoney_hot_rank": "东方财富人气榜",
    "eastmoney_hot_rank_direct": "东方财富人气榜",
    "eastmoney_hot_rank_detail_em": "东方财富人气榜历史",
    "eastmoney_hot_rank_detail_em_all": "东方财富人气榜全量历史",
    "akshare_stock_hot_rank_em": "AkShare人气榜",
    "ths_pywencai_hot_rank": "同花顺问财人气榜",
    "ths": "同花顺热榜",
    "xueqiu": "雪球热榜",
}


def fmt_num(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "-"
        return f"{value:.{digits}f}"
    return str(value)


def fmt_pct(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value * 100:.{digits}f}%"
    return str(value)


def display_source(value: object) -> str:
    if value is None:
        return "-"
    return SOURCE_LABELS.get(str(value), str(value))


def fmt_market_time(value: object) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    if not text:
        return "-"
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"
    if len(digits) == 4:
        return f"{digits[:2]}:{digits[2:]}"
    return text


def format_table_cell(key: str, value: object) -> str:
    if key == "source":
        return display_source(value)
    if key in {"first_limit_time", "last_limit_time"}:
        return fmt_market_time(value)
    if key == "seal_amount_yi":
        return fmt_num(value)
    if key.endswith("_rate"):
        return fmt_pct(value)
    return fmt_num(value)
