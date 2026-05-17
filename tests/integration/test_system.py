#!/usr/bin/env python3
"""Integration tests for the external data and local parquet query stack."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from http.client import RemoteDisconnected
from pathlib import Path
from typing import TypeVar

import akshare as ak
import duckdb
import pandas as pd
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


@pytest.fixture(scope="module")
def sample_stock_df() -> pd.DataFrame:
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    df = _fetch_or_skip(
        "daily price 000001",
        ak.stock_zh_a_hist,
        symbol="000001",
        period="daily",
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        adjust="qfq",
    )

    assert df is not None and not df.empty
    return df


def _find_column(df: pd.DataFrame, token: str) -> str:
    for column in df.columns:
        if token in str(column):
            return str(column)
    raise AssertionError(f"missing expected column containing {token!r}; columns={list(df.columns)}")


def _standardize_stock_df(df: pd.DataFrame) -> pd.DataFrame:
    date_col = _find_column(df, "日期")
    close_col = _find_column(df, "收盘")
    volume_col = _find_column(df, "成交量")

    return pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "code": "000001",
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "volume": pd.to_numeric(df[volume_col], errors="coerce"),
        }
    ).dropna(subset=["date", "close"])


def _write_sample_parquet(df: pd.DataFrame, directory: Path) -> Path:
    output = directory / "test_000001.parquet"
    _standardize_stock_df(df).to_parquet(output, engine="pyarrow", compression="snappy", index=False)
    return output


def test_akshare_connection() -> None:
    df = _fetch_or_skip("A-share spot", ak.stock_zh_a_spot_em)
    assert df is not None and not df.empty


def test_single_stock_fetch(sample_stock_df: pd.DataFrame) -> None:
    assert len(sample_stock_df) > 0
    assert any("日期" in str(column) for column in sample_stock_df.columns)


def test_parquet_write_read(sample_stock_df: pd.DataFrame, tmp_path: Path) -> None:
    test_file = _write_sample_parquet(sample_stock_df, tmp_path)

    df_read = pd.read_parquet(test_file)

    assert len(df_read) == len(_standardize_stock_df(sample_stock_df))
    assert {"date", "code", "close", "volume"}.issubset(df_read.columns)


def test_duckdb_query(sample_stock_df: pd.DataFrame, tmp_path: Path) -> None:
    test_file = _write_sample_parquet(sample_stock_df, tmp_path)

    query = f"""
    SELECT date, code, close, volume
    FROM read_parquet('{test_file.as_posix()}')
    ORDER BY date DESC
    LIMIT 5
    """

    result = duckdb.connect().execute(query).df()

    assert not result.empty
    assert list(result.columns) == ["date", "code", "close", "volume"]
