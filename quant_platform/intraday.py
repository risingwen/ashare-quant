from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .db import engine
from .ingest import normalize_popularity
from .providers.base import ProviderResult
from .providers.replay import ReplayProvider


SHANGHAI = ZoneInfo("Asia/Shanghai")
INTRADAY_CATEGORIES = {"dc_hot": "人气榜盘中", "ths_hot": "热股盘中"}


def _parse_exchange_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    candidate = str(value).strip().replace("Z", "+00:00")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for pattern in ("%Y%m%d %H:%M:%S", "%Y%m%d%H%M%S"):
            try:
                parsed = datetime.strptime(candidate, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def to_ts_code(symbol: str) -> str:
    clean = str(symbol).upper().split(".")[0].zfill(6)
    if clean.startswith(("4", "8", "92")):
        suffix = "BJ"
    elif clean.startswith(("6", "9")):
        suffix = "SH"
    else:
        suffix = "SZ"
    return f"{clean}.{suffix}"


def group_intraday_popularity(result: ProviderResult, trade_date: str) -> dict[datetime, list[dict[str, Any]]]:
    """Group archive rows into exchange-minute snapshots and resolve duplicates."""
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for item in normalize_popularity(result, trade_date):
        rank_time = _parse_exchange_time(item.get("rank_time"))
        if rank_time is None or rank_time.date().isoformat() != trade_date:
            continue
        midnight = rank_time.replace(hour=0, minute=0, second=0, microsecond=0)
        minute_of_day = rank_time.hour * 60 + rank_time.minute
        scheduled_minute = ((minute_of_day + 15) // 30) * 30
        grouped[midnight + timedelta(minutes=scheduled_minute)].append(item)

    resolved: dict[datetime, list[dict[str, Any]]] = {}
    for snapshot_time, candidates in grouped.items():
        by_rank: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in candidates:
            by_rank[int(item["rank"])].append(item)
        selected: list[dict[str, Any]] = []
        used_symbols: set[str] = set()
        for rank in sorted(by_rank):
            ranked = sorted(
                by_rank[rank],
                key=lambda item: (float(item.get("heat") or -1), str(item.get("rank_time") or "")),
                reverse=True,
            )
            choice = next((item for item in ranked if item["symbol"] not in used_symbols), None)
            if choice is not None:
                selected.append(choice)
                used_symbols.add(choice["symbol"])
        if selected:
            resolved[snapshot_time] = selected
    return resolved


def normalize_minute_bars(
    result: ProviderResult,
    trade_date: str,
    freq: str = "1min",
    expected_symbol: str | None = None,
) -> list[dict[str, Any]]:
    rows: dict[datetime, dict[str, Any]] = {}
    for row in result.rows:
        trade_time = _parse_exchange_time(row.get("trade_time") or row.get("datetime"))
        symbol = str(row.get("ts_code") or row.get("code") or expected_symbol or "").split(".")[0].zfill(6)
        values = {key: row.get(key) for key in ("open", "high", "low", "close", "vol", "amount")}
        if (
            trade_time is None
            or trade_time.date().isoformat() != trade_date
            or not symbol.isdigit()
            or (expected_symbol is not None and symbol != expected_symbol)
            or any(value in (None, "", "--") for value in values.values())
        ):
            continue
        try:
            open_price = float(values["open"])
            high = float(values["high"])
            low = float(values["low"])
            close = float(values["close"])
            volume = float(values["vol"])
            amount = float(values["amount"])
        except (TypeError, ValueError):
            continue
        if high < max(open_price, low, close) or low > min(open_price, close) or volume < 0 or amount < 0:
            continue
        rows[trade_time] = {
            "symbol": symbol,
            "trade_date": trade_date,
            "trade_time": trade_time,
            "freq": freq,
            "open": values["open"],
            "high": values["high"],
            "low": values["low"],
            "close": values["close"],
            "volume": values["vol"],
            "amount": values["amount"],
            "provider": result.provider,
        }
    return [rows[key] for key in sorted(rows)]


def ingest_trade_calendar(provider: ReplayProvider, start: str, end: str) -> dict[str, Any]:
    padded_start = (date.fromisoformat(start) - timedelta(days=10)).isoformat()
    padded_end = (date.fromisoformat(end) + timedelta(days=10)).isoformat()
    result = provider.fetch_trade_calendar(padded_start, padded_end)
    normalized = []
    for row in result.rows:
        raw_date = str(row.get("cal_date") or row.get("trade_date") or "")
        formatted = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else raw_date[:10]
        try:
            date.fromisoformat(formatted)
        except ValueError:
            continue
        normalized.append({"trade_date": formatted, "is_open": str(row.get("is_open")) in {"1", "True", "true"}})
    status = result.status if result.status != "success" or normalized else "quarantined"
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch
          (provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,finished_at)
          VALUES (:provider,'trade_cal',:requested,:as_of,:status,:count,:hash,:error_code,:error_message,now())
          RETURNING id"""), {
            "provider": result.provider,
            "requested": result.requested_at,
            "as_of": result.source_as_of,
            "status": status,
            "count": len(normalized),
            "hash": result.raw_hash,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }).scalar_one()
        if status == "success":
            conn.execute(text("""INSERT INTO market.trade_calendar(trade_date,is_open)
              VALUES (:trade_date,:is_open) ON CONFLICT(trade_date) DO UPDATE SET is_open=excluded.is_open"""), normalized)
            conn.execute(text("""UPDATE market.trade_calendar c SET
              previous_open_date=(SELECT max(p.trade_date) FROM market.trade_calendar p
                                  WHERE p.is_open AND p.trade_date<c.trade_date),
              next_open_date=(SELECT min(n.trade_date) FROM market.trade_calendar n
                              WHERE n.is_open AND n.trade_date>c.trade_date)"""))
    return {"status": status, "rows": len(normalized), "batch_id": batch_id}


def ingest_intraday_popularity(
    provider: ReplayProvider,
    endpoint: str,
    trade_date: str,
) -> dict[str, Any]:
    result = provider.fetch_popularity_archive(endpoint, trade_date)
    frames = group_intraday_popularity(result, trade_date) if result.status == "success" else {}
    usable_frames = {key: value for key, value in frames.items() if len(value) >= 10}
    status = result.status
    if result.status == "success" and not usable_frames:
        status = "quarantined"
    row_count = sum(len(items) for items in usable_frames.values())
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch
          (provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,metadata,finished_at)
          VALUES (:provider,:dataset,:requested,:as_of,:status,:count,:hash,:error_code,:error_message,
                  CAST(:metadata AS jsonb),now()) RETURNING id"""), {
            "provider": result.provider,
            "dataset": f"{endpoint}_intraday",
            "requested": result.requested_at,
            "as_of": result.source_as_of,
            "status": status,
            "count": row_count,
            "hash": result.raw_hash,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "metadata": json.dumps({"raw_rows": len(result.rows), "frames": len(usable_frames)}),
        }).scalar_one()
        if status == "success":
            # A successful retry is a complete replacement for this source/day.
            # This also removes stale split frames created by an older grouper.
            conn.execute(text("""DELETE FROM popularity.snapshot
              WHERE provider=:provider AND endpoint=:endpoint AND category=:category AND trade_date=:trade_date"""), {
                "provider": result.provider,
                "endpoint": endpoint,
                "category": INTRADAY_CATEGORIES[endpoint],
                "trade_date": trade_date,
            })
            for snapshot_time, items in sorted(usable_frames.items()):
                snapshot_id = conn.execute(text("""INSERT INTO popularity.snapshot
                  (provider,endpoint,category,trade_date,snapshot_time,status,row_count,batch_id,raw_hash)
                  VALUES (:provider,:endpoint,:category,:trade_date,:snapshot_time,'success',:count,:batch,:hash)
                  ON CONFLICT(provider,endpoint,market,category,snapshot_time) DO UPDATE
                  SET trade_date=excluded.trade_date,status='success',row_count=excluded.row_count,
                      batch_id=excluded.batch_id,raw_hash=excluded.raw_hash RETURNING id"""), {
                    "provider": result.provider,
                    "endpoint": endpoint,
                    "category": INTRADAY_CATEGORIES[endpoint],
                    "trade_date": trade_date,
                    "snapshot_time": snapshot_time,
                    "count": len(items),
                    "batch": batch_id,
                    "hash": result.raw_hash,
                }).scalar_one()
                conn.execute(text("DELETE FROM popularity.snapshot_item WHERE snapshot_id=:snapshot_id"), {
                    "snapshot_id": snapshot_id,
                })
                conn.execute(text("""INSERT INTO popularity.snapshot_item
                  (snapshot_id,symbol,name,rank,heat,rank_change,rank_reason,concept,is_new,raw)
                  VALUES (:snapshot_id,:symbol,:name,:rank,:heat,:rank_change,:rank_reason,:concept,:is_new,
                          CAST(:raw AS jsonb))"""), [{**item, "snapshot_id": snapshot_id} for item in items])
                if len(items) < 90:
                    conn.execute(text("""INSERT INTO ops.data_issue(batch_id,severity,code,message,details)
                      VALUES (:batch,'warning','intraday_popularity_partial',:message,CAST(:details AS jsonb))"""), {
                        "batch": batch_id,
                        "message": f"{endpoint} {snapshot_time.isoformat()} has {len(items)} rows",
                        "details": json.dumps({"snapshot_time": snapshot_time.isoformat(), "rows": len(items)}),
                    })
        elif result.status == "success":
            conn.execute(text("""INSERT INTO ops.data_issue(batch_id,severity,code,message)
              VALUES (:batch,'error','intraday_popularity_no_complete_frame',:message)"""), {
                "batch": batch_id,
                "message": f"{endpoint} raw rows {len(result.rows)} yielded no frame with at least 10 ranks",
            })
    return {
        "endpoint": endpoint,
        "status": status,
        "rows": row_count,
        "raw_rows": len(result.rows),
        "snapshots": len(usable_frames),
        "batch_id": batch_id,
    }


def ingest_minute_bars(
    provider: ReplayProvider,
    symbol: str,
    trade_date: str,
    freq: str = "1min",
) -> dict[str, Any]:
    result = provider.fetch_minute_bars(to_ts_code(symbol), trade_date, freq)
    rows = normalize_minute_bars(result, trade_date, freq, symbol) if result.status == "success" else []
    status = result.status
    if result.status == "success" and len(rows) != len(result.rows):
        status = "quarantined"
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch
          (provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,metadata,finished_at)
          VALUES (:provider,:dataset,:requested,:as_of,:status,:count,:hash,:error_code,:error_message,
                  CAST(:metadata AS jsonb),now()) RETURNING id"""), {
            "provider": result.provider,
            "dataset": "stk_mins",
            "requested": result.requested_at,
            "as_of": result.source_as_of,
            "status": status,
            "count": len(rows),
            "hash": result.raw_hash,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "metadata": json.dumps({"symbol": symbol, "trade_date": trade_date, "freq": freq}),
        }).scalar_one()
        if status == "success":
            conn.execute(text("""INSERT INTO market.instrument(symbol,name,exchange)
              VALUES (:symbol,:symbol,:exchange) ON CONFLICT(symbol) DO NOTHING"""), {
                "symbol": symbol,
                "exchange": to_ts_code(symbol).split(".")[1],
            })
            conn.execute(text("""DELETE FROM market.minute_bar
              WHERE symbol=:symbol AND trade_date=:trade_date AND freq=:freq"""), {
                "symbol": symbol,
                "trade_date": trade_date,
                "freq": freq,
            })
            conn.execute(text("""INSERT INTO market.minute_bar
              (symbol,trade_date,trade_time,freq,open,high,low,close,volume,amount,provider,batch_id)
              VALUES (:symbol,:trade_date,:trade_time,:freq,:open,:high,:low,:close,:volume,:amount,:provider,:batch_id)"""), [
                {**row, "batch_id": batch_id} for row in rows
            ])
        elif status == "quarantined":
            conn.execute(text("""INSERT INTO ops.data_issue(batch_id,severity,code,message)
              VALUES (:batch,'error','minute_bar_invalid_rows',:message)"""), {
                "batch": batch_id,
                "message": f"{symbol} {trade_date}: normalized {len(rows)} of {len(result.rows)} rows",
            })
    return {"status": status, "rows": len(rows), "batch_id": batch_id}


def hot_symbols(start: str, end: str, rank_max: int = 10) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(text("""SELECT DISTINCT i.symbol FROM popularity.snapshot s
          JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
          WHERE s.status='success' AND s.trade_date BETWEEN :start AND :end
            AND s.category IN ('人气榜','热股','人气榜盘中','热股盘中') AND i.rank<=:rank_max"""), {
            "start": start,
            "end": end,
            "rank_max": rank_max,
        }).scalars())


def ingest_price_limits(
    provider: ReplayProvider,
    trade_date: str,
    symbols: set[str],
) -> dict[str, Any]:
    result = provider.fetch_price_limits(trade_date)
    normalized = []
    for row in result.rows:
        symbol = str(row.get("ts_code") or "").split(".")[0].zfill(6)
        up_limit = row.get("up_limit")
        down_limit = row.get("down_limit")
        if symbol not in symbols or up_limit in (None, "", "--") or down_limit in (None, "", "--"):
            continue
        normalized.append({
            "symbol": symbol,
            "trade_date": trade_date,
            "pre_close": row.get("pre_close") or None,
            "up_limit": up_limit,
            "down_limit": down_limit,
            "provider": result.provider,
        })
    status = result.status
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch
          (provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,metadata,finished_at)
          VALUES (:provider,'stk_limit_hot',:requested,:as_of,:status,:count,:hash,:error_code,:error_message,
                  CAST(:metadata AS jsonb),now()) RETURNING id"""), {
            "provider": result.provider,
            "requested": result.requested_at,
            "as_of": result.source_as_of,
            "status": status,
            "count": len(normalized),
            "hash": result.raw_hash,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "metadata": json.dumps({"trade_date": trade_date, "hot_universe": len(symbols)}),
        }).scalar_one()
        if status == "success" and normalized:
            existing = set(conn.execute(text("SELECT symbol FROM market.instrument WHERE symbol=ANY(:symbols)"), {
                "symbols": [row["symbol"] for row in normalized],
            }).scalars())
            missing = sorted({row["symbol"] for row in normalized} - existing)
            if missing:
                conn.execute(text("""INSERT INTO market.instrument(symbol,name,exchange)
                  VALUES (:symbol,:symbol,:exchange) ON CONFLICT(symbol) DO NOTHING"""), [{
                    "symbol": symbol,
                    "exchange": to_ts_code(symbol).split(".")[1],
                } for symbol in missing])
            conn.execute(text("""INSERT INTO market.price_limit
              (symbol,trade_date,pre_close,up_limit,down_limit,provider,batch_id)
              VALUES (:symbol,:trade_date,:pre_close,:up_limit,:down_limit,:provider,:batch_id)
              ON CONFLICT(symbol,trade_date) DO UPDATE SET pre_close=excluded.pre_close,
                up_limit=excluded.up_limit,down_limit=excluded.down_limit,provider=excluded.provider,
                batch_id=excluded.batch_id"""), [{**row, "batch_id": batch_id} for row in normalized])
    return {"status": status, "rows": len(normalized), "raw_rows": len(result.rows), "batch_id": batch_id}


def open_dates(start: str, end: str) -> list[str]:
    with engine.connect() as conn:
        return [row[0].isoformat() for row in conn.execute(text("""SELECT trade_date
          FROM market.trade_calendar WHERE is_open AND trade_date BETWEEN :start AND :end
          ORDER BY trade_date"""), {"start": start, "end": end})]


def minute_candidates(start: str, end: str, rank_max: int = 10) -> list[tuple[str, str]]:
    """Return final-list next-day and pre-open-list same-day entry stock-days."""
    with engine.connect() as conn:
        calendar = [row[0].isoformat() for row in conn.execute(text("""SELECT trade_date
          FROM market.trade_calendar WHERE is_open ORDER BY trade_date"""))]
        final_signals = list(conn.execute(text("""SELECT DISTINCT s.trade_date,i.symbol
          FROM popularity.snapshot s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
          WHERE s.status='success' AND s.category IN ('人气榜','热股')
            AND s.trade_date BETWEEN :start AND :end AND i.rank<=:rank_max"""), {
            "start": start, "end": end, "rank_max": rank_max,
        }))
        preopen_signals = list(conn.execute(text("""WITH latest AS (
            SELECT DISTINCT ON (endpoint,trade_date) id,trade_date
            FROM popularity.snapshot
            WHERE status='success' AND category IN ('人气榜盘中','热股盘中')
              AND trade_date BETWEEN :start AND :end
              AND (snapshot_time AT TIME ZONE 'Asia/Shanghai')::time < time '09:30'
            ORDER BY endpoint,trade_date,snapshot_time DESC)
          SELECT DISTINCT l.trade_date,i.symbol FROM latest l
          JOIN popularity.snapshot_item i ON i.snapshot_id=l.id WHERE i.rank<=:rank_max"""), {
            "start": start, "end": end, "rank_max": rank_max,
        }))
    position = {value: index for index, value in enumerate(calendar)}
    candidates: set[tuple[str, str]] = set()
    for signal_date, symbol in final_signals:
        index = position.get(signal_date.isoformat())
        if index is not None and index + 1 < len(calendar):
            candidates.add((calendar[index + 1], symbol))
    for signal_date, symbol in preopen_signals:
        index = position.get(signal_date.isoformat())
        if index is None:
            continue
        candidates.add((calendar[index], symbol))
    today = date.today().isoformat()
    return sorted(candidate for candidate in candidates if candidate[0] <= today)


def save_progress(symbol: str, trade_date: str, freq: str, output: dict[str, Any], error: str | None) -> None:
    status = output["status"]
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO ops.minute_backfill_progress
          (symbol,trade_date,freq,status,row_count,attempts,error)
          VALUES (:symbol,:trade_date,:freq,:status,:rows,1,:error)
          ON CONFLICT(symbol,trade_date,freq) DO UPDATE SET status=excluded.status,row_count=excluded.row_count,
            attempts=ops.minute_backfill_progress.attempts+1,error=excluded.error,updated_at=now()"""), {
            "symbol": symbol,
            "trade_date": trade_date,
            "freq": freq,
            "status": status,
            "rows": output.get("rows", 0),
            "error": error,
        })


def throttle(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
