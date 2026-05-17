#!/usr/bin/env python3
"""Update daily bars, real popularity rankings, and limit-up pools into SQLite."""

from __future__ import annotations

import argparse
import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from quant_core import DEFAULT_DB_PATH, compact_date, make_meta, normalize_date, to_float
from quant_db import connect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update SQLite data via AkShare")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start-date", default="20210101")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1, help="Concurrent daily download workers")
    parser.add_argument("--skip-daily", action="store_true")
    parser.add_argument("--skip-popularity", action="store_true")
    parser.add_argument("--skip-limit-pool", action="store_true")
    parser.add_argument("--skip-lhb", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=None, help="Debug only: limit daily symbols")
    parser.add_argument("--daily-source", choices=["em", "sina", "mootdx"], default="mootdx", help="Daily data source: mootdx (TCP, no IP ban), sina, or em (eastmoney)")
    parser.add_argument("--backfill-history", action="store_true", help="Fetch data before each stock's first stored date")
    parser.add_argument("--socket-timeout", type=float, default=25.0, help="Default network socket timeout in seconds")
    parser.add_argument("--stock-batch-size", type=int, default=500, help="Commit to DB every N stocks; 0 = commit all at end")
    parser.add_argument("--date-chunk-days", type=int, default=0, help="Split date range into chunks of N calendar days; 0 = no split")
    return parser.parse_args()


def import_deps():
    try:
        import akshare as ak  # type: ignore
        import pandas as pd  # type: ignore
    except ImportError as exc:
        raise SystemExit("Missing dependency. Run: pip install -r requirements.txt") from exc
    return ak, pd


def next_day(date_text: str) -> str:
    return (datetime.strptime(compact_date(date_text), "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def prev_day(date_text: str) -> str:
    return (datetime.strptime(compact_date(date_text), "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")


def configure_socket_timeout(timeout_seconds: float) -> None:
    if timeout_seconds > 0:
        socket.setdefaulttimeout(timeout_seconds)


def call_with_retry(func: Callable, retries: int, sleep_seconds: float):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - AkShare endpoints raise heterogeneous errors
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_seconds * 5)
    raise RuntimeError(last_error)


def insert_issue(conn, run_id: str, item: str, reason: str) -> None:
    conn.execute(
        "INSERT INTO data_quality_issues(run_id, file, reason, created_at) VALUES (?, ?, ?, ?)",
        (run_id, item, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def fetch_cached_stock_list(conn) -> list[dict[str, str]]:
    rows = conn.execute("SELECT code, name FROM stocks ORDER BY code").fetchall()
    return [{"code": row["code"], "name": row["name"]} for row in rows]


def _call_with_hard_timeout(func: Callable, timeout_seconds: float):
    """Run func() in a thread; raise TimeoutError if it doesn't return in time.

    socket.setdefaulttimeout() does not cover requests/urllib3 connection pools
    used by some AkShare endpoints. This wrapper provides a hard wall-clock cap.

    The executor is shut down without waiting so a hung thread (e.g. a stalled
    TCP connection) does not block the caller after the timeout fires.

    WARNING: hung threads share the process's urllib3/requests connection pool,
    which may cause subsequent HTTP calls to also hang. For endpoints known to
    hang (e.g. stock_info_a_code_name), call this once and then prefer caches.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    exe = ThreadPoolExecutor(max_workers=1)
    future = exe.submit(func)
    try:
        result = future.result(timeout=timeout_seconds)
        exe.shutdown(wait=False)
        return result
    except FuturesTimeoutError:
        exe.shutdown(wait=False)
        raise TimeoutError(f"Call timed out after {timeout_seconds}s")


def fetch_stock_list(conn, ak, retries: int, sleep_seconds: float, prefer_cache: bool = False) -> list[dict[str, str]]:
    if prefer_cache:
        cached = fetch_cached_stock_list(conn)
        if cached:
            print(f"Using database stock cache: {len(cached)}; live stock-list skipped")
            return cached

    try:
        if hasattr(ak, "stock_info_a_code_name"):
            df = _call_with_hard_timeout(lambda: ak.stock_info_a_code_name(), timeout_seconds=30)
            stocks = [{"code": str(row["code"]).zfill(6), "name": str(row["name"])} for _, row in df.iterrows()]
        else:
            df = _call_with_hard_timeout(lambda: ak.stock_zh_a_spot_em(), timeout_seconds=30)
            stocks = [{"code": str(row["代码"]).zfill(6), "name": str(row["名称"])} for _, row in df.iterrows()]
        with conn:
            for item in stocks:
                meta = make_meta(item["code"], item["name"])
                conn.execute(
                    """
                    INSERT INTO stocks(code, name, market, is_st, eligible, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name=excluded.name,
                        market=excluded.market,
                        is_st=excluded.is_st,
                        eligible=excluded.eligible,
                        updated_at=excluded.updated_at
                    """,
                    (meta.code, meta.name, meta.market, int(meta.is_st), int(meta.eligible), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
        print(f"Fetched live stock list: {len(stocks)}")
        return stocks
    except Exception as exc:  # noqa: BLE001
        cached = fetch_cached_stock_list(conn)
        if not cached:
            raise SystemExit(f"Failed to fetch stock list and database has no cache: {exc}") from exc
        print(f"Using database stock cache: {len(cached)}; live stock-list error: {exc}")
        return cached


def resolve_effective_end_date(conn, ak, requested_end_date: str, retries: int, sleep_seconds: float) -> tuple[str, bool]:
    """Return the latest known trading date not after requested_end_date.

    The daily timer may fire on weekends or holidays. Without this guard the
    pipeline tries to download every stock for a non-trading date, which is
    slow and can trigger data-source hangs.
    """
    requested = normalize_date(requested_end_date)
    dates: list[str] = []

    if hasattr(ak, "tool_trade_date_hist_sina"):
        try:
            df = _call_with_hard_timeout(lambda: ak.tool_trade_date_hist_sina(), timeout_seconds=20)
            for column in df.columns:
                column_dates = []
                for value in df[column].dropna().tolist():
                    date_text = normalize_date(value)
                    if len(date_text) == 10 and date_text <= requested:
                        column_dates.append(date_text)
                if column_dates:
                    dates = column_dates
                    break
        except Exception as exc:  # noqa: BLE001
            print(f"Trade calendar lookup failed; using requested end date: {exc}")

    if dates:
        effective = max(dates)
        if effective < requested:
            print(f"Requested end date {requested} is not a trading day; using {effective}")
            return effective, True
        return requested, False

    latest = conn.execute("SELECT MAX(date) AS date FROM daily_bars WHERE date <= ?", (requested,)).fetchone()["date"]
    if latest and latest < requested:
        print(f"Trade calendar unavailable; database latest date is {latest}, requested {requested}")
    return requested, False


def df_to_daily_rows(df, code: str) -> list[tuple]:
    rows = []
    for _, row in df.iterrows():
        date = normalize_date(row.get("日期"))
        values = {
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
        rows.append(
            (
                code,
                date,
                values["open"],
                values["close"],
                values["high"],
                values["low"],
                values["volume"],
                values["amount"],
                values["amplitude"],
                values["pct_chg"],
                values["change_amount"],
                values["turnover"],
            )
        )
    return rows


def symbol_with_exchange(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def df_to_sina_daily_rows(df, code: str) -> list[tuple]:
    rows = []
    prev_close = None
    for _, row in df.iterrows():
        date = normalize_date(row.get("date"))
        open_price = to_float(row.get("open"))
        close = to_float(row.get("close"))
        high = to_float(row.get("high"))
        low = to_float(row.get("low"))
        volume = to_float(row.get("volume"))
        amount = to_float(row.get("amount"))
        turnover_raw = to_float(row.get("turnover"))
        if not date or None in {open_price, close, high, low, volume, amount}:
            continue
        pct_chg = 0.0 if prev_close in {None, 0} else (close - prev_close) / prev_close * 100
        change_amount = 0.0 if prev_close is None else close - prev_close
        amplitude = 0.0 if prev_close in {None, 0} else (high - low) / prev_close * 100
        turnover = (turnover_raw or 0.0) * 100 if turnover_raw is not None and turnover_raw < 1 else (turnover_raw or 0.0)
        rows.append((code, date, open_price, close, high, low, volume, amount, amplitude, pct_chg, change_amount, turnover))
        prev_close = close
    return rows


def fetch_daily_mootdx(code: str, start_date: str, end_date: str, db_prev_close: float | None = None) -> list[tuple]:
    """Fetch daily bars via mootdx TCP (no HTTP gateway, no IP ban risk).

    Supports SH, SZ and BSE (北交所) stocks. Market is auto-detected from
    the stock code using mootdx's get_stock_market() utility.

    Returns list of row tuples compatible with daily_bars schema.
    start_date / end_date format: YYYYMMDD or YYYY-MM-DD.
    """
    from mootdx.quotes import Quotes
    from mootdx.utils import get_stock_market

    start_dt = datetime.strptime(compact_date(start_date), "%Y%m%d").date()
    end_dt = datetime.strptime(compact_date(end_date), "%Y%m%d").date()

    # Auto-detect market: 0=SZ, 1=SH, 2=BJ
    market_id = get_stock_market(code, string=False)

    client = Quotes.factory(market="std", server="119.147.212.81", port=7709)
    rows: list[tuple] = []
    # mootdx returns newest-first with start/offset pagination; collect enough pages
    batch = 800
    page_start = 0
    all_bars: list[tuple] = []
    while True:
        df = client.bars(symbol=code, market=market_id, frequency=9, start=page_start, offset=batch)
        if df is None or df.empty:
            break
        # df index is datetime, columns: open close high low vol amount datetime ...
        for idx, row in df.iterrows():
            bar_date = idx.date() if hasattr(idx, "date") else None
            if bar_date is None:
                continue
            all_bars.append((bar_date, row))
        # Stop if earliest bar is already before start_date
        earliest = df.index[0].date() if hasattr(df.index[0], "date") else start_dt
        if earliest <= start_dt:
            break
        if len(df) < batch:
            break
        page_start += batch

    # Filter to requested date range and compute pct_chg from prev close
    filtered = sorted(
        [(d, r) for d, r in all_bars if start_dt <= d <= end_dt],
        key=lambda x: x[0],
    )
    prev_close = db_prev_close  # seed from DB so first-day pct_chg is correct
    for bar_date, row in filtered:
        date_str = bar_date.strftime("%Y-%m-%d")
        open_p = to_float(row.get("open"))
        close = to_float(row.get("close"))
        high = to_float(row.get("high"))
        low = to_float(row.get("low"))
        vol = to_float(row.get("vol") or row.get("volume"))
        amount = to_float(row.get("amount"))
        if None in {open_p, close, high, low, vol, amount}:
            prev_close = close
            continue
        if prev_close in {None, 0.0}:
            # 新股/复牌首日：退而使用 mootdx 自带的涨跌幅字段（pct_chg 或 price_chg_rate）
            src_pct = to_float(row.get("pct_chg") or row.get("price_chg_rate"))
            pct_chg = src_pct if src_pct is not None else 0.0
            change_amount = 0.0
            amplitude = 0.0
        else:
            pct_chg = (close - prev_close) / prev_close * 100
            change_amount = close - prev_close
            amplitude = (high - low) / prev_close * 100
        rows.append((code, date_str, open_p, close, high, low, vol, amount, amplitude, pct_chg, change_amount, 0.0))
        prev_close = close
    return rows


def fetch_daily_tencent(code: str, start_date: str, end_date: str) -> list[tuple]:
    """Fetch daily bars for BSE stocks via Tencent Finance API.

    Returns list of row tuples compatible with daily_bars schema.
    Tencent supports bj-prefix codes with full history.
    """
    import requests as _req

    start_compact = compact_date(start_date)
    end_compact = compact_date(end_date)
    start_fmt = f"{start_compact[:4]}-{start_compact[4:6]}-{start_compact[6:]}"
    end_fmt = f"{end_compact[:4]}-{end_compact[4:6]}-{end_compact[6:]}"

    # Tencent uses bj prefix for BSE stocks
    symbol = f"bj{code}"
    url = (
        f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
        f"?_var=kline_dayqfq&param={symbol},day,{start_fmt},{end_fmt},1000,qfq"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = _req.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    raw = resp.text
    json_str = raw.split("=", 1)[1] if "=" in raw else raw
    import json as _json
    data = _json.loads(json_str)
    stock_data = data.get("data", {}).get(symbol, {})
    # Tencent returns 'qfqday' for SH/SZ and 'day' for BSE stocks
    day_list = stock_data.get("qfqday") or stock_data.get("day") or []

    # Filter by requested date range (Tencent may return more data than requested)
    day_list = [item for item in day_list if start_fmt <= str(item[0]) <= end_fmt]

    rows: list[tuple] = []
    prev_close = None
    for item in day_list:
        # [date, open, close, high, low, vol(手), {}, turnover(%), amount(万元), '']
        if len(item) < 6:
            continue
        date_str = str(item[0])
        open_p = to_float(item[1])
        close = to_float(item[2])
        high = to_float(item[3])
        low = to_float(item[4])
        vol = to_float(item[5])
        amount_wan = to_float(item[8]) if len(item) > 8 else None
        amount = amount_wan * 10000 if amount_wan is not None else None
        turnover = to_float(item[7]) if len(item) > 7 else 0.0
        if None in {open_p, close, high, low, vol, amount}:
            prev_close = close
            continue
        pct_chg = 0.0 if prev_close in {None, 0.0} else (close - prev_close) / prev_close * 100
        change_amount = 0.0 if prev_close is None else close - prev_close
        amplitude = 0.0 if prev_close in {None, 0.0} else (high - low) / prev_close * 100
        rows.append((code, date_str, open_p, close, high, low, vol, amount, amplitude, pct_chg, change_amount, turnover or 0.0))
        prev_close = close
    return rows


def fetch_daily_akshare(code: str, start_date: str, end_date: str, db_prev_close: float | None = None) -> list[tuple]:
    """Fetch daily bars for BSE 9-prefix stocks via akshare (EastMoney).

    Only works for codes starting with '9' (北交所现行代码规则).
    akshare maps these to secid=0.9xxxxx which EastMoney correctly serves.
    Returns list of row tuples compatible with daily_bars schema.
    """
    import akshare as _ak

    start_compact = compact_date(start_date)
    end_compact = compact_date(end_date)
    df = _ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start_compact,
        end_date=end_compact,
        adjust="",  # 不复权，pct_chg 自行从原始价格计算
    )
    if df is None or df.empty:
        return []

    # 列名：日期 股票代码 开盘 收盘 最高 最低 成交量 成交额 振幅 涨跌幅 涨跌额 换手率
    rows: list[tuple] = []
    prev_close = db_prev_close  # seed from DB so first-day pct_chg is correct
    for _, row in df.iterrows():
        date_str = str(row["日期"])
        open_p  = to_float(row.get("开盘"))
        close   = to_float(row.get("收盘"))
        high    = to_float(row.get("最高"))
        low     = to_float(row.get("最低"))
        vol     = to_float(row.get("成交量"))
        amount  = to_float(row.get("成交额"))
        turnover= to_float(row.get("换手率")) or 0.0
        if None in {open_p, close, high, low, vol, amount}:
            prev_close = close
            continue
        # 如果 prev_close 仍为 None（真正新股首日），退而使用数据源自带的涨跌幅字段
        if prev_close in {None, 0.0}:
            src_pct = to_float(row.get("涨跌幅"))
            pct_chg = src_pct if src_pct is not None else 0.0
            change_amount = 0.0
            amplitude = 0.0 if prev_close in {None, 0.0} else (high - low) / prev_close * 100
        else:
            pct_chg       = (close - prev_close) / prev_close * 100
            change_amount = close - prev_close
            amplitude     = (high - low) / prev_close * 100
        rows.append((code, date_str, open_p, close, high, low, vol, amount, amplitude, pct_chg, change_amount, turnover))
        prev_close = close
    return rows


def fetch_daily_df(ak, code: str, start_date: str, end_date: str, source: str, market: str = "", conn=None, db_prev_close: float | None = None):
    """Route to the appropriate data source based on market and source flag.

    Returns (rows: list[tuple], source_label: str) where rows are ready for INSERT.
    - mootdx: SH/SZ via TCP direct connect; BSE 9-prefix via akshare EastMoney;
               BSE 8/4-prefix skipped (no accessible source).
    - em/sina: legacy akshare paths, backward compatible.
    conn: optional DB connection to look up prev_close before start_date (fixes new-stock first-day pct_chg=0 bug).
          NOTE: when called from a worker thread, pass db_prev_close directly instead to avoid SQLite thread-safety issues.
    """
    # Query DB for the close price of the trading day immediately before start_date,
    # so that the first bar in the fetched range has a correct pct_chg.
    if db_prev_close is None and conn is not None:
        row = conn.execute(
            "SELECT close FROM daily_bars WHERE code=? AND date<? ORDER BY date DESC LIMIT 1",
            (code, normalize_date(start_date)),
        ).fetchone()
        if row:
            db_prev_close = float(row[0]) if row[0] else None

    if source == "mootdx":
        if market == "BSE":
            if code.startswith("9"):
                return fetch_daily_akshare(code, start_date, end_date, db_prev_close=db_prev_close), "akshare"
            else:
                return None, "skip"
        return fetch_daily_mootdx(code, start_date, end_date, db_prev_close=db_prev_close), "mootdx"
    if source == "em":
        return ak.stock_zh_a_hist(symbol=code, period="daily", start_date=compact_date(start_date), end_date=compact_date(end_date), adjust="qfq"), "em"
    return ak.stock_zh_a_daily(symbol=symbol_with_exchange(code), start_date=compact_date(start_date), end_date=compact_date(end_date), adjust="qfq"), "sina"


def update_daily_bars(conn, ak, stocks: list[dict[str, str]], args: argparse.Namespace, run_id: str) -> None:
    insert_sql = """
    INSERT OR REPLACE INTO daily_bars(
        code, date, open, close, high, low, volume, amount, amplitude,
        pct_chg, change_amount, turnover, source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    created = 0
    updated = 0
    skipped = 0
    failed = 0
    selected = stocks[: args.max_symbols] if args.max_symbols else stocks

    # Pre-load market info for routing
    market_map: dict[str, str] = {}
    for row in conn.execute("SELECT code, market FROM stocks"):
        market_map[row["code"]] = row["market"]

    tasks = []
    for item in selected:
        code = item["code"]
        name = item["name"]
        if args.backfill_history:
            first = conn.execute("SELECT MIN(date) AS first_date FROM daily_bars WHERE code = ?", (code,)).fetchone()["first_date"]
            start_date = args.start_date
            end_date = prev_day(first) if first else args.end_date
            last = first
        else:
            last = conn.execute("SELECT MAX(date) AS last_date FROM daily_bars WHERE code = ?", (code,)).fetchone()["last_date"]
            start_date = next_day(last) if last else args.start_date
            end_date = args.end_date
        if start_date > end_date:
            skipped += 1
            continue
        # Pre-fetch prev_close in the main thread to avoid SQLite cross-thread access in workers.
        prev_close_row = conn.execute(
            "SELECT close FROM daily_bars WHERE code=? AND date<? ORDER BY date DESC LIMIT 1",
            (code, normalize_date(start_date)),
        ).fetchone()
        db_prev_close: float | None = float(prev_close_row[0]) if (prev_close_row and prev_close_row[0]) else None
        tasks.append({"code": code, "name": name, "last": last, "start_date": start_date, "end_date": end_date, "market": market_map.get(code, ""), "db_prev_close": db_prev_close})

    def fetch_one(task: dict[str, object]) -> tuple[dict[str, object], list[tuple] | None, str | None]:
        code = str(task["code"])
        start_date = str(task["start_date"])
        end_date = str(task["end_date"])
        market = str(task.get("market", ""))
        db_prev_close: float | None = task.get("db_prev_close")  # type: ignore[assignment]
        time.sleep(args.sleep)
        try:
            result, source_label = call_with_retry(
                lambda: _call_with_hard_timeout(
                    lambda: fetch_daily_df(ak, code, start_date, end_date, args.daily_source, market, db_prev_close=db_prev_close),
                    timeout_seconds=60,
                ),
                args.retries,
                args.sleep,
            )
        except Exception as exc:  # noqa: BLE001
            return task, None, str(exc)
        # mootdx (SH/SZ/BSE) returns rows directly; em/sina returns a DataFrame
        if source_label == "skip":
            return task, [], None
        if source_label in ("mootdx", "akshare"):
            rows = [r + (source_label,) for r in result]
            return task, rows, None
        df = result
        if df is None or df.empty:
            return task, [], None
        base_rows = df_to_daily_rows(df, code) if source_label == "em" else df_to_sina_daily_rows(df, code)
        rows = [r + (source_label,) for r in base_rows]
        return task, rows, None

    if not tasks:
        print(f"Daily update done. created={created}, updated={updated}, skipped={skipped}, failed={failed}")
        return

    workers = max(1, args.workers)
    batch_size = args.stock_batch_size if args.stock_batch_size > 0 else len(tasks)
    total = len(tasks)
    print(f"Daily tasks to fetch: {total}, workers={workers}, batch_size={batch_size}")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_one, task) for task in tasks]
        pending_rows: list[tuple] = []
        for completed, future in enumerate(as_completed(futures), start=1):
            task, rows, error = future.result()
            code = str(task["code"])
            name = str(task["name"])
            if completed <= 10 or completed % 100 == 0:
                print(f"[{completed}/{total}] daily {code} {name}: {task['start_date']} -> {task['end_date']}")
            if error:
                failed += 1
                with conn:
                    insert_issue(conn, run_id, f"daily:{code}", error)
            elif not rows:
                skipped += 1
            else:
                pending_rows.extend(rows)
                if task["last"]:
                    updated += 1
                else:
                    created += 1

            # Flush to DB every batch_size completions (or at the very end)
            if pending_rows and (completed % batch_size == 0 or completed == total):
                with conn:
                    conn.executemany(insert_sql, pending_rows)
                print(f"  -> batch committed: {len(pending_rows)} rows up to stock {completed}/{total} "
                      f"(created={created}, updated={updated}, failed={failed})")
                pending_rows = []

    print(f"Daily update done. created={created}, updated={updated}, skipped={skipped}, failed={failed}")


def row_value(row, names: list[str]) -> object | None:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def code_value(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        text = text[2:8]
    if text.endswith(".SH") or text.endswith(".SZ") or text.endswith(".BJ"):
        text = text[:6]
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text


def load_popularity_csv_fallback(pd, base_dir: Path, end_date: str) -> list[tuple[str, str, int, str, str, float | None, str]]:
    fallback_paths = [
        base_dir / "reports" / "hot_rank_multi_source_snapshot_latest.csv",
        base_dir / "reports" / "hot_rank_wencai_last30_normalized.csv",
    ]
    normalized_end_date = normalize_date(end_date)
    rows: list[tuple[str, str, int, str, str, float | None, str]] = []

    for path in fallback_paths:
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = pd.read_csv(path)
        if df is None or df.empty:
            continue

        if "date" in df.columns:
            df = df[df["date"].astype(str) == normalized_end_date]
        if df is None or df.empty:
            continue

        for row in df.to_dict(orient="records"):
            code = code_value(row.get("code"))
            name = str(row.get("name") or "").strip()
            rank = to_float(row.get("rank"))
            source = str(row.get("source") or path.stem).strip()
            if not code or not name or rank is None:
                continue
            rows.append(
                (
                    source,
                    normalize_date(row.get("date") or normalized_end_date),
                    int(rank),
                    code,
                    name,
                    to_float(row.get("heat") or row.get("score")),
                    json.dumps(row, ensure_ascii=False, default=str),
                )
            )
        if rows:
            break

    return rows


def fetch_eastmoney_hot_rank_direct(retries: int, sleep_seconds: float) -> list[dict[str, object]]:
    import requests  # type: ignore

    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": 100,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://guba.eastmoney.com/rank/",
        "Content-Type": "application/json",
    }
    session = requests.Session()

    data = None
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.post(
                "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
                json=payload,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_seconds * 5)
    if data is None:
        raise RuntimeError(last_error)

    items = data.get("data") or []
    if not items:
        return []

    codes = [code_value(item.get("sc")) for item in items]
    codes = [code for code in codes if code]
    quote_by_code: dict[str, dict[str, object]] = {}
    if codes:
        secids = ",".join(("0." if code.startswith(("0", "3")) else "1.") + code for code in codes)
        try:
            resp = session.get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                params={
                    "ut": "f057cbcbce2a86e2866ab8877db1d059",
                    "fltt": "2",
                    "invt": "2",
                    "fields": "f14,f3,f12,f2",
                    "secids": secids,
                },
                headers={"User-Agent": headers["User-Agent"], "Referer": headers["Referer"]},
                timeout=15,
            )
            resp.raise_for_status()
            quote_json = resp.json()
            for quote in (quote_json.get("data") or {}).get("diff") or []:
                code = code_value(quote.get("f12"))
                if code:
                    quote_by_code[code] = quote
        except Exception as exc:  # noqa: BLE001
            print(f"Popularity direct quote fallback failed: {exc}")

    rows: list[dict[str, object]] = []
    for item in items:
        code = code_value(item.get("sc"))
        if not code:
            continue
        quote = quote_by_code.get(code, {})
        rows.append(
            {
                "source": "eastmoney_hot_rank_direct",
                "rank": item.get("rk"),
                "code": code,
                "name": quote.get("f14") or code,
                "score": item.get("rc") if item.get("rc") is not None else item.get("hisRc"),
                "raw": {"rank": item, "quote": quote},
            }
        )
    return rows


def update_popularity(conn, ak, pd, end_date: str, retries: int, sleep_seconds: float, run_id: str, allow_snapshot: bool = True) -> None:
    fetchers: list[tuple[str, Callable]] = []
    has_em = hasattr(ak, "stock_hot_rank_em")
    has_wc = hasattr(ak, "stock_hot_rank_wc")
    allow_em_snapshot = allow_snapshot or (has_em and not has_wc)

    if has_em and allow_em_snapshot:
        fetchers.append(("eastmoney_hot_rank", lambda: ak.stock_hot_rank_em()))
        if not allow_snapshot:
            print("Using eastmoney_hot_rank snapshot on non-trading-day run because no dated fallback endpoint is available")
    elif has_em:
        print("Skipping eastmoney_hot_rank snapshot on non-trading-day run")
    if has_wc:
        fetchers.append(("wencai_hot_rank", lambda: ak.stock_hot_rank_wc(date=end_date)))

    if not fetchers:
        print("No supported popularity endpoint found in installed AkShare")
        return

    insert_sql = """
    INSERT OR REPLACE INTO popularity_rankings(source, date, rank, code, name, score, raw_json)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    total = 0
    for source, fetcher in fetchers:
        try:
            df = call_with_retry(fetcher, retries, sleep_seconds)
        except Exception as exc:  # noqa: BLE001
            with conn:
                insert_issue(conn, run_id, f"popularity:{source}", str(exc))
            print(f"Popularity fetch failed: {source}: {exc}")
            continue
        if df is None or df.empty:
            continue
        rows = []
        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            code = code_value(row_value(row_dict, ["代码", "股票代码", "证券代码", "code", "股票简称代码"]))
            name = row_value(row_dict, ["名称", "股票名称", "证券简称", "name"])
            if not code or not name:
                continue
            rank_raw = row_value(row_dict, ["当前排名", "排名", "序号", "rank"])
            rank = int(to_float(rank_raw) or (idx + 1))
            score = to_float(row_value(row_dict, ["人气值", "热度", "score", "排名变化"]));
            rows.append((source, normalize_date(end_date), rank, code, str(name), score, json.dumps(row_dict, ensure_ascii=False, default=str)))
        with conn:
            conn.executemany(insert_sql, rows)
        total += len(rows)
        print(f"Popularity {source}: {len(rows)} rows")

    if total == 0:
        try:
            direct_rows = fetch_eastmoney_hot_rank_direct(retries, sleep_seconds)
        except Exception as exc:  # noqa: BLE001
            with conn:
                insert_issue(conn, run_id, "popularity:eastmoney_direct", str(exc))
            print(f"Popularity direct fallback failed: {exc}")
            direct_rows = []

        if direct_rows:
            rows = []
            for row in direct_rows:
                rank = to_float(row.get("rank"))
                code = code_value(row.get("code"))
                name = str(row.get("name") or "").strip()
                if rank is None or not code or not name:
                    continue
                rows.append(
                    (
                        str(row.get("source") or "eastmoney_hot_rank_direct"),
                        normalize_date(end_date),
                        int(rank),
                        code,
                        name,
                        to_float(row.get("score")),
                        json.dumps(row.get("raw") or row, ensure_ascii=False, default=str),
                    )
                )
            if rows:
                with conn:
                    conn.executemany(insert_sql, rows)
                total += len(rows)
                print(f"Popularity eastmoney_direct: {len(rows)} rows")

    if total == 0:
        try:
            fallback_rows = load_popularity_csv_fallback(pd, Path(__file__).resolve().parent.parent, end_date)
        except Exception as exc:  # noqa: BLE001
            with conn:
                insert_issue(conn, run_id, "popularity:csv_fallback", str(exc))
            print(f"Popularity CSV fallback failed: {exc}")
            fallback_rows = []

        if fallback_rows:
            with conn:
                conn.executemany(insert_sql, fallback_rows)
            total += len(fallback_rows)
            print(f"Popularity csv_fallback: {len(fallback_rows)} rows")
    print(f"Popularity update done. rows={total}")


def update_limit_pool(conn, ak, end_date: str, retries: int, sleep_seconds: float, run_id: str) -> None:
    if not hasattr(ak, "stock_zt_pool_em"):
        print("No supported limit-up pool endpoint found in installed AkShare")
        return
    try:
        df = call_with_retry(lambda: ak.stock_zt_pool_em(date=end_date), retries, sleep_seconds)
    except Exception as exc:  # noqa: BLE001
        with conn:
            insert_issue(conn, run_id, "limit_pool:eastmoney_zt_pool", str(exc))
        print(f"Limit-up pool fetch failed: {exc}")
        return
    if df is None or df.empty:
        print("Limit-up pool returned no rows")
        return
    insert_sql = """
    INSERT OR REPLACE INTO limit_up_pool(
        source, date, code, name, reason, streak, first_limit_time,
        last_limit_time, seal_amount, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        code = code_value(row_value(row_dict, ["代码", "股票代码"]))
        name = row_value(row_dict, ["名称", "股票名称"])
        if not code or not name:
            continue
        reason = row_value(row_dict, ["涨停原因类别", "所属行业", "板块"])
        streak = to_float(row_value(row_dict, ["连板数", "涨停统计"]))
        rows.append(
            (
                "eastmoney_zt_pool",
                normalize_date(end_date),
                code,
                str(name),
                str(reason) if reason is not None else None,
                int(streak) if streak is not None else None,
                str(row_value(row_dict, ["首次封板时间"]) or ""),
                str(row_value(row_dict, ["最后封板时间"]) or ""),
                to_float(row_value(row_dict, ["封板资金", "封单资金"])),
                json.dumps(row_dict, ensure_ascii=False, default=str),
            )
        )
    with conn:
        conn.executemany(insert_sql, rows)
    print(f"Limit-up pool update done. rows={len(rows)}")


def update_market_daily(conn, ak, end_date: str, retries: int, sleep_seconds: float, run_id: str) -> None:
    """Fetch zt/dt pool counts from EastMoney and write to market_daily table."""
    date_str = normalize_date(end_date)

    # Skip if already fetched
    existing = conn.execute("SELECT zt_count FROM market_daily WHERE date = ?", (date_str,)).fetchone()
    if existing and existing["zt_count"] is not None:
        print(f"market_daily already fetched for {date_str}, skipping")
        return

    zt_count = None
    dt_count = None

    # 涨停池
    if hasattr(ak, "stock_zt_pool_em"):
        try:
            df = call_with_retry(lambda: ak.stock_zt_pool_em(date=end_date), retries, sleep_seconds)
            if df is not None and not df.empty:
                zt_count = len(df)
        except Exception as exc:  # noqa: BLE001
            insert_issue(conn, run_id, "market_daily:zt_pool", str(exc))
            print(f"market_daily zt_pool fetch failed: {exc}")

    # 跌停池
    if hasattr(ak, "stock_zt_pool_dtgc_em"):
        try:
            df = call_with_retry(lambda: ak.stock_zt_pool_dtgc_em(date=end_date), retries, sleep_seconds)
            if df is not None and not df.empty:
                dt_count = len(df)
        except Exception as exc:  # noqa: BLE001
            insert_issue(conn, run_id, "market_daily:dt_pool", str(exc))
            print(f"market_daily dt_pool fetch failed: {exc}")

    with conn:
        conn.execute(
            """
            INSERT INTO market_daily(date, zt_count, dt_count)
            VALUES(?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                zt_count = excluded.zt_count,
                dt_count = excluded.dt_count
            """,
            (date_str, zt_count, dt_count),
        )

    # Fallback: 若接口失败，用 daily_bars pct_chg 自算
    if zt_count is None or dt_count is None:
        stock_info = {
            r["code"]: (r["market"], bool(r["is_st"]))
            for r in conn.execute("SELECT code, market, is_st FROM stocks")
        }
        bars = conn.execute(
            "SELECT code, pct_chg FROM daily_bars WHERE date = ? AND pct_chg IS NOT NULL",
            (date_str,),
        ).fetchall()
        zt_calc = dt_calc = 0
        for bar in bars:
            mkt, is_st = stock_info.get(bar["code"], ("Mainboard", False))
            pct = float(bar["pct_chg"])
            if is_st:
                thr = 4.8
            elif mkt in ("ChiNext", "STAR"):
                thr = 19.8
            elif mkt == "BSE":
                thr = 29.8
            else:
                thr = 9.8
            if pct >= thr:
                zt_calc += 1
            elif pct <= -thr:
                dt_calc += 1
        if zt_count is None:
            zt_count = zt_calc
        if dt_count is None:
            dt_count = dt_calc
        with conn:
            conn.execute(
                "UPDATE market_daily SET zt_count=?, dt_count=? WHERE date=?",
                (zt_count, dt_count, date_str),
            )
        print(f"market_daily fallback calc done. date={date_str} zt={zt_count} dt={dt_count}")

    print(f"market_daily update done. date={date_str} zt={zt_count} dt={dt_count}")


def update_lhb(conn, ak, end_date: str, retries: int, sleep_seconds: float, run_id: str) -> None:
    """Fetch Dragon-Tiger list (龙虎榜) for end_date and write to lhb_records + lhb_seats."""
    if not hasattr(ak, "stock_lhb_detail_em"):
        print("stock_lhb_detail_em not available in installed AkShare")
        return

    # Check if already fetched for this date
    existing = conn.execute("SELECT COUNT(*) AS n FROM lhb_records WHERE date = ?", (normalize_date(end_date),)).fetchone()["n"]
    if existing > 0:
        print(f"LHB already fetched for {end_date}: {existing} rows, skipping")
        return

    try:
        df = call_with_retry(lambda: ak.stock_lhb_detail_em(start_date=end_date, end_date=end_date), retries, sleep_seconds)
    except Exception as exc:  # noqa: BLE001
        with conn:
            insert_issue(conn, run_id, "lhb:eastmoney_lhb_detail", str(exc))
        print(f"LHB fetch failed: {exc}")
        return
    if df is None or df.empty:
        print(f"LHB returned no rows for {end_date}")
        return

    rec_sql = """
    INSERT OR REPLACE INTO lhb_records(
        date, code, name, reason, close, pct_chg, lhb_net_buy, lhb_buy, lhb_sell,
        lhb_amount, market_amount, net_buy_ratio, amount_ratio, turnover, float_mv,
        after_1d, after_2d, after_5d, after_10d, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    seat_sql = """
    INSERT OR REPLACE INTO lhb_seats(
        date, code, direction, seat_name, buy_amount, buy_ratio, sell_amount, sell_ratio, net_amount, seat_type
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rec_rows = []
    seat_rows_all = []
    date_str = normalize_date(end_date)

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        code = code_value(row_value(row_dict, ["代码"]))
        name = row_value(row_dict, ["名称"])
        if not code or not name:
            continue
        rec_rows.append((
            date_str,
            code,
            str(name),
            str(row_value(row_dict, ["上榜原因"]) or ""),
            to_float(row_value(row_dict, ["收盘价"])),
            to_float(row_value(row_dict, ["涨跌幅"])),
            to_float(row_value(row_dict, ["龙虎榜净买额"])),
            to_float(row_value(row_dict, ["龙虎榜买入额"])),
            to_float(row_value(row_dict, ["龙虎榜卖出额"])),
            to_float(row_value(row_dict, ["龙虎榜成交额"])),
            to_float(row_value(row_dict, ["市场总成交额"])),
            to_float(row_value(row_dict, ["净买额占总成交比"])),
            to_float(row_value(row_dict, ["成交额占总成交比"])),
            to_float(row_value(row_dict, ["换手率"])),
            to_float(row_value(row_dict, ["流通市值"])),
            to_float(row_value(row_dict, ["上榜后1日"])),
            to_float(row_value(row_dict, ["上榜后2日"])),
            to_float(row_value(row_dict, ["上榜后5日"])),
            to_float(row_value(row_dict, ["上榜后10日"])),
            json.dumps(row_dict, ensure_ascii=False, default=str),
        ))

    with conn:
        conn.executemany(rec_sql, rec_rows)
    print(f"LHB records done. count={len(rec_rows)}")

    # Fetch seat details per stock — one API call per (stock, direction)
    codes_in_date = [r[1] for r in rec_rows]
    date_compact = date_str.replace("-", "")
    for code in codes_in_date:
        time.sleep(sleep_seconds)
        for direction in ("买入", "卖出"):
            try:
                sdf = call_with_retry(
                    lambda c=code, flag=direction: _call_with_hard_timeout(
                        lambda: ak.stock_lhb_stock_detail_em(
                            symbol=c, date=date_compact, flag=flag
                        ),
                        timeout_seconds=45,
                    ),
                    retries,
                    sleep_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"LHB seat detail failed: code={code} direction={direction} error={exc}")
                continue
            if sdf is None or sdf.empty:
                continue
            for _, srow in sdf.iterrows():
                sd = srow.to_dict()
                seat_name = sd.get("交易营业部名称", "")
                seat_rows_all.append((
                    date_str,
                    code,
                    direction,
                    str(seat_name),
                    to_float(sd.get("买入金额")),
                    to_float(sd.get("买入金额-占总成交比例")),
                    to_float(sd.get("卖出金额")),
                    to_float(sd.get("卖出金额-占总成交比例")),
                    to_float(sd.get("净额")),
                    str(sd.get("类型") or ""),
                ))

    if seat_rows_all:
        with conn:
            conn.executemany(seat_sql, seat_rows_all)
    print(f"LHB seats done. count={len(seat_rows_all)}")
    print("update_lhb return")


def date_chunks(start_date: str, end_date: str, chunk_days: int) -> list[tuple[str, str]]:
    """Split [start_date, end_date] into chunks of at most chunk_days calendar days.

    Returns list of (chunk_start, chunk_end) pairs in chronological order.
    Dates are YYYYMMDD strings.
    """
    if chunk_days <= 0:
        return [(start_date, end_date)]
    start = datetime.strptime(compact_date(start_date), "%Y%m%d")
    end = datetime.strptime(compact_date(end_date), "%Y%m%d")
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cur = chunk_end + timedelta(days=1)
    return chunks


def main() -> None:
    args = parse_args()
    configure_socket_timeout(args.socket_timeout)
    ak, pd = import_deps()
    conn = connect(args.db)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    requested_end_date = normalize_date(args.end_date)
    effective_end_date, non_trading_run = resolve_effective_end_date(conn, ak, requested_end_date, args.retries, args.sleep)
    args.end_date = compact_date(effective_end_date)

    if not args.skip_daily:
        latest_daily = conn.execute("SELECT MAX(date) AS date FROM daily_bars").fetchone()["date"]
        if non_trading_run and latest_daily and latest_daily >= effective_end_date and not args.backfill_history:
            print(f"Daily bars already current through {latest_daily}; skipping daily update")
        else:
            prefer_cache = non_trading_run and not args.backfill_history
            stocks = fetch_stock_list(conn, ak, args.retries, args.sleep, prefer_cache=prefer_cache)
            chunks = date_chunks(args.start_date, args.end_date, args.date_chunk_days)
            if len(chunks) > 1:
                print(f"Date range split into {len(chunks)} chunks of up to {args.date_chunk_days} days each")
            for chunk_idx, (chunk_start, chunk_end) in enumerate(chunks, start=1):
                if len(chunks) > 1:
                    print(f"--- Chunk {chunk_idx}/{len(chunks)}: {chunk_start} -> {chunk_end} ---")
                chunk_args = argparse.Namespace(**vars(args))
                chunk_args.start_date = chunk_start
                chunk_args.end_date = chunk_end
                update_daily_bars(conn, ak, stocks, chunk_args, run_id)
    if not args.skip_popularity:
        update_popularity(conn, ak, pd, args.end_date, args.retries, args.sleep, run_id, allow_snapshot=not non_trading_run)
    if not args.skip_limit_pool:
        update_limit_pool(conn, ak, args.end_date, args.retries, args.sleep, run_id)
    update_market_daily(conn, ak, args.end_date, args.retries, args.sleep, run_id)
    if not args.skip_lhb:
        update_lhb(conn, ak, args.end_date, args.retries, args.sleep, run_id)


if __name__ == "__main__":
    main()
