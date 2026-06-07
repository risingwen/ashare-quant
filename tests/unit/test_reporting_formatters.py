from __future__ import annotations

from reporting.formatters import display_source, fmt_market_time, fmt_num, fmt_pct, format_table_cell


def test_source_labels_are_human_readable() -> None:
    assert display_source("eastmoney_zt_pool") == "东方财富涨停池"
    assert display_source("eastmoney_hot_rank_direct") == "东方财富人气榜"
    assert display_source("custom_source") == "custom_source"


def test_market_time_formatting() -> None:
    assert fmt_market_time("092502") == "09:25:02"
    assert fmt_market_time("0930") == "09:30"
    assert fmt_market_time(None) == "-"


def test_number_and_percent_formatting() -> None:
    assert fmt_num(1.2345) == "1.23"
    assert fmt_num(True) == "yes"
    assert fmt_pct(0.1234) == "12.34%"


def test_table_cell_dispatch() -> None:
    assert format_table_cell("source", "eastmoney_zt_pool") == "东方财富涨停池"
    assert format_table_cell("first_limit_time", "145701") == "14:57:01"
    assert format_table_cell("win_rate", 0.5) == "50.00%"

