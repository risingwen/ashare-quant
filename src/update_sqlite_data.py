#!/usr/bin/env python3
"""Update daily bars, real popularity rankings, and limit-up pools into SQLite."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--daily-source", choices=["em", "sina"], default="sina", help="Daily data source; sina is more stable for bulk refresh")
    parser.add_argument("--backfill-history", action="store_true", help="Fetch data before each stock's first stored date")
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


def fetch_stock_list(conn, ak, retries: int, sleep_seconds: float) -> list[dict[str, str]]:
    try:
        if hasattr(ak, "stock_info_a_code_name"):
            df = call_with_retry(lambda: ak.stock_info_a_code_name(), retries, sleep_seconds)
            stocks = [{"code": str(row["code"]).zfill(6), "name": str(row["name"])} for _, row in df.iterrows()]
        else:
            df = call_with_retry(lambda: ak.stock_zh_a_spot_em(), retries, sleep_seconds)
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
        rows = conn.execute("SELECT code, name FROM stocks ORDER BY code").fetchall()
        if not rows:
            raise SystemExit(f"Failed to fetch stock list and database has no cache: {exc}") from exc
        print(f"Using database stock cache: {len(rows)}; live stock-list error: {exc}")
        return [{"code": row["code"], "name": row["name"]} for row in rows]


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


def fetch_daily_df(ak, code: str, start_date: str, end_date: str, source: str):
    if source == "em":
        return ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq"), "em"
    return ak.stock_zh_a_daily(symbol=symbol_with_exchange(code), start_date=start_date, end_date=end_date, adjust="qfq"), "sina"


def update_daily_bars(conn, ak, stocks: list[dict[str, str]], args: argparse.Namespace, run_id: str) -> None:
    insert_sql = """
    INSERT OR REPLACE INTO daily_bars(
        code, date, open, close, high, low, volume, amount, amplitude,
        pct_chg, change_amount, turnover, source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'akshare')
    """
    created = 0
    updated = 0
    skipped = 0
    failed = 0
    selected = stocks[: args.max_symbols] if args.max_symbols else stocks

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
        tasks.append({"code": code, "name": name, "last": last, "start_date": start_date, "end_date": end_date})

    def fetch_one(task: dict[str, object]) -> tuple[dict[str, object], list[tuple] | None, str | None]:
        code = str(task["code"])
        start_date = str(task["start_date"])
        end_date = str(task["end_date"])
        time.sleep(args.sleep)
        try:
            df, source = call_with_retry(
                lambda: fetch_daily_df(ak, code, start_date, end_date, args.daily_source),
                args.retries,
                args.sleep,
            )
        except Exception as exc:  # noqa: BLE001
            return task, None, str(exc)
        if df is None or df.empty:
            return task, [], None
        rows = df_to_daily_rows(df, code) if source == "em" else df_to_sina_daily_rows(df, code)
        return task, rows, None

    if not tasks:
        print(f"Daily update done. created={created}, updated={updated}, skipped={skipped}, failed={failed}")
        return

    workers = max(1, args.workers)
    print(f"Daily tasks to fetch: {len(tasks)}, workers={workers}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_one, task) for task in tasks]
        for completed, future in enumerate(as_completed(futures), start=1):
            task, rows, error = future.result()
            code = str(task["code"])
            name = str(task["name"])
            if completed <= 10 or completed % 100 == 0:
                print(f"[{completed}/{len(tasks)}] daily {code} {name}: {task['start_date']} -> {task['end_date']}")
            if error:
                failed += 1
                with conn:
                    insert_issue(conn, run_id, f"daily:{code}", error)
                continue
            if not rows:
                skipped += 1
                continue
            with conn:
                conn.executemany(insert_sql, rows)
            if task["last"]:
                updated += 1
            else:
                created += 1
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


def update_popularity(conn, ak, pd, end_date: str, retries: int, sleep_seconds: float, run_id: str) -> None:
    fetchers: list[tuple[str, Callable]] = []
    if hasattr(ak, "stock_hot_rank_em"):
        fetchers.append(("eastmoney_hot_rank", lambda: ak.stock_hot_rank_em()))
    if hasattr(ak, "stock_hot_rank_wc"):
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
                    lambda c=code, flag=direction: ak.stock_lhb_stock_detail_em(
                        symbol=c, date=date_compact, flag=flag
                    ),
                    retries,
                    sleep_seconds,
                )
            except Exception:  # noqa: BLE001
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


def main() -> None:
    args = parse_args()
    ak, pd = import_deps()
    conn = connect(args.db)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    stocks = fetch_stock_list(conn, ak, args.retries, args.sleep)
    if not args.skip_daily:
        update_daily_bars(conn, ak, stocks, args, run_id)
    if not args.skip_popularity:
        update_popularity(conn, ak, pd, args.end_date, args.retries, args.sleep, run_id)
    if not args.skip_limit_pool:
        update_limit_pool(conn, ak, args.end_date, args.retries, args.sleep, run_id)
    if not args.skip_lhb:
        update_lhb(conn, ak, args.end_date, args.retries, args.sleep, run_id)


if __name__ == "__main__":
    main()
