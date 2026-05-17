#!/usr/bin/env python3
"""Integration tests for popularity-related market data via AkShare."""

from __future__ import annotations

from collections.abc import Callable
from http.client import RemoteDisconnected
from typing import TypeVar

import akshare as ak
import pytest
import requests
import urllib3


pytestmark = [pytest.mark.integration, pytest.mark.network]
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


def _has_column_containing(columns: list[object], token: str) -> bool:
    return any(token in str(column) for column in columns)


def test_popularity_fetch() -> None:
    """AkShare A-share spot data should expose code/name plus at least one attention indicator."""
    df = _fetch_or_skip("A-share spot", ak.stock_zh_a_spot_em)

    assert df is not None and not df.empty
    assert _has_column_containing(list(df.columns), "代码")
    assert _has_column_containing(list(df.columns), "名称")

    attention_tokens = ("人气", "涨速", "量比", "5分钟")
    assert any(_has_column_containing(list(df.columns), token) for token in attention_tokens), (
        "spot schema does not expose any expected attention indicator; "
        f"columns={list(df.columns)}"
    )


def test_historical_data_with_turnover() -> None:
    """Daily historical data should include turnover information."""
    df = _fetch_or_skip(
        "daily price 000001",
        ak.stock_zh_a_hist,
        symbol="000001",
        period="daily",
        start_date="20250101",
        end_date="20260102",
        adjust="qfq",
    )

    assert df is not None and not df.empty
    assert _has_column_containing(list(df.columns), "换手")
