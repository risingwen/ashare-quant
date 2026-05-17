#!/usr/bin/env python3
"""Integration tests for Eastmoney hot-rank data via AkShare."""

from __future__ import annotations

import logging
from collections.abc import Callable
from http.client import RemoteDisconnected
from typing import TypeVar

import akshare as ak
import pandas as pd
import pytest
import requests
import urllib3


pytestmark = [pytest.mark.integration, pytest.mark.network]

logger = logging.getLogger(__name__)
T = TypeVar("T")

NETWORK_ERRORS = (
    requests.exceptions.RequestException,
    urllib3.exceptions.HTTPError,
    RemoteDisconnected,
    ConnectionError,
    TimeoutError,
)


def _fetch_or_skip(label: str, func: Callable[..., T], *args: object, **kwargs: object) -> T:
    try:
        return func(*args, **kwargs)
    except NETWORK_ERRORS as exc:
        pytest.skip(f"{label} external source unavailable: {exc}")


def _market_symbol(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688")):
        return f"SH{code}"
    return f"SZ{code}"


def _find_column(df: pd.DataFrame, tokens: tuple[str, ...]) -> str:
    for column in df.columns:
        text = str(column).lower()
        if any(token.lower() in text for token in tokens):
            return str(column)
    raise AssertionError(f"missing expected column containing one of: {tokens}; columns={list(df.columns)}")


def test_hot_rank_single_stock() -> None:
    """At least one representative stock should return hot-rank history."""
    successful: list[tuple[str, pd.DataFrame]] = []
    failures: list[str] = []

    for code in ("000001", "600519", "000665"):
        symbol = _market_symbol(code)
        try:
            df = _fetch_or_skip(f"hot-rank {symbol}", ak.stock_hot_rank_detail_em, symbol=symbol)
        except Exception as exc:  # External source errors should be visible in the assertion message.
            failures.append(f"{symbol}: {exc}")
            continue

        if df is not None and not df.empty:
            successful.append((symbol, df))
        else:
            failures.append(f"{symbol}: empty response")

    assert successful, "all hot-rank requests failed: " + "; ".join(failures)
    for symbol, df in successful:
        logger.info("hot-rank rows for %s: %s", symbol, len(df))
        assert len(df.columns) >= 2


def test_hot_rank_merge_with_price() -> None:
    """Hot-rank rows should overlap with normal daily price rows by date."""
    code = "000001"
    price_df = _fetch_or_skip(
        "daily price 000001",
        ak.stock_zh_a_hist,
        symbol=code,
        period="daily",
        start_date="20250101",
        end_date="20260102",
        adjust="qfq",
    )
    hot_df = _fetch_or_skip("hot-rank 000001", ak.stock_hot_rank_detail_em, symbol=_market_symbol(code))

    assert price_df is not None and not price_df.empty
    assert hot_df is not None and not hot_df.empty

    price_date_col = _find_column(price_df, ("date", "日期"))
    hot_date_col = _find_column(hot_df, ("date", "日期", "时间"))

    price_dates = pd.to_datetime(price_df[price_date_col], errors="coerce").dropna()
    hot_dates = pd.to_datetime(hot_df[hot_date_col], errors="coerce").dropna()

    overlap = set(price_dates.dt.date).intersection(set(hot_dates.dt.date))
    assert overlap, "price data and hot-rank data have no overlapping dates"
