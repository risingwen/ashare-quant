from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from itertools import groupby
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .db import engine


def apply_schema() -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            for migration in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                cursor.execute(migration.read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()


def import_sqlite(path: Path) -> dict[str, int]:
    source = sqlite3.connect(path)
    source.row_factory = sqlite3.Row
    counts = {"instrument": 0, "daily_bar": 0, "popularity": 0}
    with engine.begin() as target:
        rows = source.execute("SELECT code,name,market,eligible FROM stocks").fetchall()
        target.execute(text("""INSERT INTO market.instrument(symbol,name,exchange,active)
          VALUES (:symbol,:name,:exchange,:active) ON CONFLICT(symbol) DO UPDATE SET name=excluded.name,active=excluded.active"""),
          [{"symbol": r["code"], "name": r["name"], "exchange": r["market"] or "UNKNOWN", "active": bool(r["eligible"])} for r in rows])
        counts["instrument"] = len(rows)
        cursor = source.execute("SELECT code,date,open,high,low,close,volume,amount,pct_chg,turnover,source FROM daily_bars ORDER BY date")
        while batch := cursor.fetchmany(5000):
            target.execute(text("""INSERT INTO market.daily_bar(symbol,trade_date,open,high,low,close,volume,amount,pct_change,turnover,provider)
              VALUES (:symbol,:trade_date,:open,:high,:low,:close,:volume,:amount,:pct_change,:turnover,:provider)
              ON CONFLICT(symbol,trade_date) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,amount=excluded.amount,pct_change=excluded.pct_change,turnover=excluded.turnover,provider=excluded.provider"""),
              [{"symbol": r["code"], "trade_date": r["date"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"], "amount": r["amount"], "pct_change": r["pct_chg"], "turnover": r["turnover"], "provider": r["source"]} for r in batch])
            counts["daily_bar"] += len(batch)
    source.close()
    return counts


def import_legacy_popularity(path: Path) -> dict[str, int]:
    """Map each legacy source/day into one close snapshot without losing provenance."""
    source = sqlite3.connect(path)
    source.row_factory = sqlite3.Row
    cursor = source.execute("SELECT source,date,rank,code,name,score,raw_json FROM popularity_rankings ORDER BY source,date,rank")
    snapshots = items_count = 0
    with engine.begin() as target:
        for (provider, trade_date), group in groupby(cursor, key=lambda row: (row["source"], row["date"])):
            items = list(group)
            snapshot_time = datetime.fromisoformat(f"{trade_date}T15:00:00").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            snapshot_id = target.execute(text("""INSERT INTO popularity.snapshot(provider,endpoint,category,trade_date,snapshot_time,status,row_count)
              VALUES (:provider,'legacy_import','legacy',:trade_date,:snapshot_time,'success',:count)
              ON CONFLICT(provider,endpoint,market,category,snapshot_time) DO UPDATE SET row_count=excluded.row_count RETURNING id"""),
              {"provider": provider, "trade_date": trade_date, "snapshot_time": snapshot_time, "count": len(items)}).scalar_one()
            def clean_raw(value: str | None) -> str:
                try:
                    parsed = json.loads(value or "{}", parse_constant=lambda _: None)
                except (TypeError, ValueError):
                    parsed = {"legacy_raw": value}
                return json.dumps(parsed, ensure_ascii=False, allow_nan=False)

            def clean_symbol(value: str) -> str:
                symbol = str(value).upper()
                if symbol.startswith(("SH", "SZ", "BJ")):
                    symbol = symbol[2:]
                return symbol.split(".")[0].zfill(6)

            target.execute(text("""INSERT INTO popularity.snapshot_item(snapshot_id,symbol,name,rank,heat,raw)
              VALUES (:snapshot_id,:symbol,:name,:rank,:heat,CAST(:raw AS jsonb))
              ON CONFLICT(snapshot_id,symbol) DO UPDATE SET rank=excluded.rank,heat=excluded.heat,raw=excluded.raw"""),
              [{"snapshot_id": snapshot_id, "symbol": clean_symbol(row["code"]), "name": row["name"], "rank": row["rank"], "heat": row["score"], "raw": clean_raw(row["raw_json"])} for row in items])
            snapshots += 1
            items_count += len(items)
    source.close()
    return {"snapshots": snapshots, "items": items_count}
