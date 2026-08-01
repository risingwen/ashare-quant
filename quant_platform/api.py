from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import engine, ping


app = FastAPI(title="A股量化研究平台", version="0.1.0", docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=[settings.public_origin], allow_methods=["GET"], allow_headers=["*"])


def rows(sql: str, params: dict | None = None) -> list[dict]:
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok" if ping() else "error", "generated_at": datetime.now(UTC)}


@app.get("/api/v1/overview")
def overview() -> dict:
    summary = rows("""SELECT (SELECT max(trade_date) FROM market.daily_bar) latest_date,
      (SELECT count(DISTINCT trade_date) FROM market.daily_bar WHERE trade_date>='2025-01-01') trade_day_count,
      (SELECT count(*) FROM market.instrument WHERE active) instrument_count,
      (SELECT row_count FROM popularity.snapshot WHERE endpoint='dc_hot' AND status='success'
        ORDER BY trade_date DESC,snapshot_time DESC LIMIT 1) dc_snapshot_count,
      (SELECT row_count FROM popularity.snapshot WHERE endpoint='ths_hot' AND status='success'
        ORDER BY trade_date DESC,snapshot_time DESC LIMIT 1) ths_snapshot_count,
      (SELECT count(*) FROM research.strategy_run) strategy_run_count""")[0]
    return {"data": summary, "generated_at": datetime.now(UTC)}


@app.get("/api/v1/data-status")
def data_status() -> dict:
    return {"data": rows("SELECT id,provider,dataset,status,row_count,source_as_of,finished_at,error_code FROM ops.data_batch ORDER BY id DESC LIMIT 50")}


@app.get("/api/v1/data-freshness")
def data_freshness() -> dict:
    data = rows("""WITH calendar AS (
        SELECT trade_date FROM market.daily_bar
        UNION SELECT trade_date FROM market.stock_moneyflow
        UNION SELECT trade_date FROM market.sector_moneyflow
      ), latest_market AS (
        SELECT max(trade_date) expected_date FROM calendar
      ), datasets AS (
        SELECT 'daily' dataset,max(trade_date) latest_date FROM market.daily_bar
        UNION ALL SELECT 'moneyflow_dc',max(trade_date) FROM market.stock_moneyflow
        UNION ALL SELECT 'moneyflow_ind_dc',max(trade_date) FROM market.sector_moneyflow
        UNION ALL SELECT 'dc_hot',max(trade_date) FROM popularity.snapshot WHERE endpoint='dc_hot'
        UNION ALL SELECT 'ths_hot',max(trade_date) FROM popularity.snapshot WHERE endpoint='ths_hot'
        UNION ALL SELECT 'top_list',max(trade_date) FROM market.lhb_record
        UNION ALL SELECT 'top_inst',max(trade_date) FROM market.lhb_seat
      ), coverage AS (
        SELECT 'daily' dataset,array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE d.trade_date IS NULL) missing_dates
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.daily_bar) d USING(trade_date)
        UNION ALL SELECT 'moneyflow_dc',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.stock_moneyflow) x USING(trade_date)
        UNION ALL SELECT 'moneyflow_ind_dc',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.sector_moneyflow) x USING(trade_date)
        UNION ALL SELECT 'dc_hot',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL AND u.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM popularity.snapshot WHERE endpoint='dc_hot') x USING(trade_date)
          LEFT JOIN (SELECT trade_date FROM ops.backfill_progress WHERE dataset='dc_hot' AND status='unavailable') u USING(trade_date)
        UNION ALL SELECT 'ths_hot',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL AND u.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM popularity.snapshot WHERE endpoint='ths_hot') x USING(trade_date)
          LEFT JOIN (SELECT trade_date FROM ops.backfill_progress WHERE dataset='ths_hot' AND status='unavailable') u USING(trade_date)
        UNION ALL SELECT 'top_list',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.lhb_record) x USING(trade_date)
        UNION ALL SELECT 'top_inst',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.lhb_seat) x USING(trade_date)
      )
      SELECT d.dataset,d.latest_date,m.expected_date,
        CASE WHEN d.latest_date>=m.expected_date AND coalesce(cardinality(c.missing_dates),0)=0 THEN 'current' ELSE 'stale' END status,
        coalesce(cardinality(c.missing_dates),0) missing_count,c.missing_dates,
        b.status latest_attempt_status,b.finished_at latest_attempt_at,b.error_code
      FROM datasets d CROSS JOIN latest_market m LEFT JOIN coverage c USING(dataset)
      LEFT JOIN LATERAL (
        SELECT status,finished_at,error_code FROM ops.data_batch
        WHERE dataset=CASE WHEN d.dataset='daily' THEN 'daily_market' ELSE d.dataset END ORDER BY id DESC LIMIT 1
      ) b ON true ORDER BY d.dataset""")
    jobs = rows("SELECT id,job_name,status,started_at,finished_at,details,error FROM ops.job_run WHERE job_name IN ('moneyflow_sync','popularity_sync') ORDER BY started_at DESC LIMIT 20")
    return {"data": data, "jobs": jobs, "generated_at": datetime.now(UTC)}


@app.get("/api/v1/instruments")
def instruments(q: str = "", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    return {"data": rows("SELECT symbol,name,exchange,board,list_date,delist_date,active FROM market.instrument WHERE (:q='' OR symbol ILIKE :like OR name ILIKE :like) ORDER BY symbol LIMIT :limit OFFSET :offset", {"q": q, "like": f"%{q}%", "limit": limit, "offset": offset})}


@app.get("/api/v1/bars/{symbol}")
def bars(symbol: str, start: str = "2025-01-01", end: str = "9999-12-31") -> dict:
    return {"data": rows("SELECT * FROM market.daily_bar WHERE symbol=:symbol AND trade_date BETWEEN :start AND :end ORDER BY trade_date", {"symbol": symbol, "start": start, "end": end})}


@app.get("/api/v1/popularity/rankings")
def rankings(trade_date: str, source: Literal["dc_hot", "ths_hot"] = "dc_hot", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    data = rows("""WITH latest AS (
        SELECT DISTINCT ON (provider,endpoint,category) id,provider,endpoint,category,trade_date,snapshot_time
        FROM popularity.snapshot WHERE endpoint=:source AND status='success' AND trade_date=:trade_date
        ORDER BY provider,endpoint,category,snapshot_time DESC
      )
      SELECT s.provider,s.endpoint,s.category,s.trade_date,s.snapshot_time,i.symbol,i.name,i.rank,i.heat,
        i.rank_change,i.rank_reason,i.concept
      FROM latest s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
      ORDER BY s.provider,i.rank LIMIT :limit OFFSET :offset""",
      {"trade_date": trade_date, "source": source, "limit": limit, "offset": offset})
    source_label = "东方财富" if source == "dc_hot" else "同花顺"
    return {"data": data, "limit": limit, "offset": offset, "coverage": {
        "scope": "published_top_100", "rank_limit": 100,
        "description": f"{source_label} {source} 每日最终发布的前100名，不代表全市场全部股票",
    }, "source": source, "source_label": source_label}


@app.get("/api/v1/popularity/dates")
def popularity_dates(source: Literal["dc_hot", "ths_hot"] = "dc_hot") -> dict:
    return {"data": rows("""SELECT trade_date,provider,endpoint,count(*) snapshot_count,
      (array_agg(row_count ORDER BY snapshot_time DESC))[1] row_count,max(snapshot_time) latest_snapshot_time
      FROM popularity.snapshot WHERE endpoint=:source AND status='success'
      GROUP BY trade_date,provider,endpoint ORDER BY trade_date DESC,provider LIMIT 1000""", {"source": source}),
      "source": source, "source_label": "东方财富" if source == "dc_hot" else "同花顺"}


@app.get("/api/v1/popularity/history/{symbol}")
def popularity_history(symbol: str, source: Literal["dc_hot", "ths_hot"] = "dc_hot", limit: int = Query(200, ge=1, le=500)) -> dict:
    return {"data": rows("SELECT provider,endpoint,category,trade_date,snapshot_time,rank,heat,rank_change FROM popularity.daily_close WHERE endpoint=:source AND symbol=:symbol ORDER BY trade_date DESC,snapshot_time DESC LIMIT :limit", {"source": source, "symbol": symbol, "limit": limit})}


@app.get("/api/v1/popularity/intraday")
def popularity_intraday(trade_date: str, source: Literal["dc_hot", "ths_hot"] = "dc_hot", symbol: str | None = None) -> dict:
    snapshots = rows("""SELECT snapshot_time,row_count FROM popularity.snapshot
      WHERE endpoint=:source AND trade_date=:date AND status='success' ORDER BY snapshot_time""", {"date": trade_date, "source": source})
    trajectory = []
    if symbol:
        trajectory = rows("""SELECT s.snapshot_time,i.symbol,i.name,i.rank,i.heat,i.rank_change,i.rank_reason
          FROM popularity.snapshot s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
          WHERE s.endpoint=:source AND s.trade_date=:date AND s.status='success' AND i.symbol=:symbol
          ORDER BY s.snapshot_time""", {"date": trade_date, "source": source, "symbol": symbol})
    return {"data": {"snapshots": snapshots, "trajectory": trajectory}, "trade_date": trade_date,
            "source": source, "source_label": "东方财富" if source == "dc_hot" else "同花顺", "symbol": symbol}


@app.get("/api/v1/lhb/dates")
def lhb_dates() -> dict:
    return {"data": rows("""SELECT r.trade_date,count(*) row_count,max(s.net_amount) net_amount
      FROM market.lhb_record r LEFT JOIN (SELECT trade_date,sum(net_buy) net_amount FROM market.lhb_seat GROUP BY trade_date) s USING(trade_date)
      GROUP BY r.trade_date ORDER BY r.trade_date DESC LIMIT 500""")}


@app.get("/api/v1/lhb/records")
def lhb_records(trade_date: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    return {"data": rows("""SELECT r.trade_date,r.symbol,r.name,r.close,r.pct_change,r.turnover_rate,r.amount,
      coalesce(r.net_amount,s.net_amount) net_amount,r.net_rate,r.reason
      FROM market.lhb_record r LEFT JOIN (
        SELECT trade_date,symbol,sum(net_buy) net_amount FROM market.lhb_seat GROUP BY trade_date,symbol
      ) s USING(trade_date,symbol) WHERE r.trade_date=:date
      ORDER BY coalesce(r.net_amount,s.net_amount) DESC NULLS LAST LIMIT :limit OFFSET :offset""", {"date": trade_date, "limit": limit, "offset": offset})}


@app.get("/api/v1/lhb/seats")
def lhb_seats(trade_date: str, symbol: str, limit: int = Query(100, ge=1, le=500)) -> dict:
    return {"data": rows("SELECT seat_name,side,buy,buy_rate,sell,sell_rate,net_buy,reason FROM market.lhb_seat WHERE trade_date=:date AND symbol=:symbol ORDER BY abs(net_buy) DESC NULLS LAST LIMIT :limit", {"date": trade_date, "symbol": symbol, "limit": limit})}


@app.get("/api/v1/lhb/history/{symbol}")
def lhb_history(symbol: str, limit: int = Query(200, ge=1, le=500)) -> dict:
    return {"data": rows("SELECT trade_date,symbol,name,pct_change,amount,net_amount,net_rate,reason FROM market.lhb_record WHERE symbol=:symbol ORDER BY trade_date DESC LIMIT :limit", {"symbol": symbol, "limit": limit})}


@app.get("/api/v1/moneyflow/dates")
def moneyflow_dates() -> dict:
    return {"data": rows("""WITH stock AS (
        SELECT trade_date,count(*) stock_count FROM market.stock_moneyflow GROUP BY trade_date
      ), sector AS (
        SELECT trade_date,count(*) sector_count FROM market.sector_moneyflow GROUP BY trade_date
      )
      SELECT coalesce(stock.trade_date,sector.trade_date) trade_date,
        coalesce(stock_count,0) stock_count,coalesce(sector_count,0) sector_count
      FROM stock FULL JOIN sector USING(trade_date)
      ORDER BY trade_date DESC LIMIT 500""")}


@app.get("/api/v1/moneyflow/streaks")
def moneyflow_streaks(
    scope: Literal["stock", "sector"] = "stock",
    end_date: str | None = None,
    days: int = Query(5, ge=2, le=20),
    min_inflow_days: int = Query(5, ge=1, le=20),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    min_days = min(min_inflow_days, days)
    table = "market.stock_moneyflow" if scope == "stock" else "market.sector_moneyflow"
    code = "symbol" if scope == "stock" else "sector_code"
    latest = rows(f"SELECT max(trade_date) latest_date FROM {table}")[0]["latest_date"]
    if latest is None:
        raise HTTPException(status_code=404, detail={"message": "资金流数据集为空", "scope": scope})

    if end_date is None:
        effective_end_date = latest
    else:
        try:
            requested_date = date.fromisoformat(end_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"message": "end_date 必须是 YYYY-MM-DD 格式", "end_date": end_date}) from exc
        available = rows(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE trade_date=:date) available", {"date": requested_date})[0]["available"]
        if not available:
            raise HTTPException(status_code=404, detail={
                "message": "所选日期没有资金流数据，请选择数据日期列表中的交易日",
                "requested_end_date": end_date,
                "latest_available_date": latest.isoformat(),
                "scope": scope,
            })
        effective_end_date = requested_date

    window_dates = rows(f"""SELECT DISTINCT trade_date FROM {table}
      WHERE trade_date<=:end_date ORDER BY trade_date DESC LIMIT :days""",
      {"end_date": effective_end_date, "days": days})
    data = rows(f"""WITH dates AS (
        SELECT DISTINCT trade_date FROM {table} WHERE trade_date<=:end_date ORDER BY trade_date DESC LIMIT :days
      ), selected AS (SELECT * FROM {table} WHERE trade_date IN (SELECT trade_date FROM dates))
      SELECT {code} code,(array_agg(name ORDER BY trade_date DESC))[1] name,
        count(*) FILTER (WHERE net_amount>0) inflow_days,count(*) observed_days,
        sum(net_amount) net_amount_sum,avg(net_amount_rate) avg_net_amount_rate,
        (array_agg(net_amount ORDER BY trade_date DESC))[1] latest_net_amount,
        (array_agg(pct_change ORDER BY trade_date DESC))[1] latest_pct_change,
        min(trade_date) first_date,max(trade_date) last_date
      FROM selected GROUP BY {code}
      HAVING count(*)=:days AND count(*) FILTER (WHERE net_amount>0)>=:min_days
      ORDER BY inflow_days DESC,net_amount_sum DESC NULLS LAST LIMIT :limit OFFSET :offset""",
      {"end_date": effective_end_date, "days": days, "min_days": min_days, "limit": limit, "offset": offset})
    return {
        "data": data,
        "scope": scope,
        "days": days,
        "min_inflow_days": min_days,
        "requested_end_date": end_date,
        "effective_end_date": effective_end_date,
        "latest_available_date": latest,
        "window_dates": [item["trade_date"] for item in window_dates],
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/v1/moneyflow/history/{code}")
def moneyflow_history(code: str, scope: Literal["stock", "sector"] = "stock", limit: int = Query(20, ge=1, le=250)) -> dict:
    if scope == "stock":
        sql = "SELECT trade_date,symbol code,name,close,pct_change,net_amount,net_amount_rate,buy_elg_amount,buy_lg_amount,buy_md_amount,buy_sm_amount FROM market.stock_moneyflow WHERE symbol=:code ORDER BY trade_date DESC LIMIT :limit"
    else:
        sql = "SELECT trade_date,sector_code code,name,close,pct_change,net_amount,net_amount_rate,buy_elg_amount,buy_lg_amount,buy_md_amount,buy_sm_amount FROM market.sector_moneyflow WHERE sector_code=:code ORDER BY trade_date DESC LIMIT :limit"
    return {"data": rows(sql, {"code": code, "limit": limit}), "scope": scope}


@app.get("/api/v1/strategies")
def strategies() -> dict:
    return {"data": rows("SELECT key,name,version,parameter_schema FROM research.strategy_template WHERE enabled ORDER BY key")}


@app.get("/api/v1/strategy-runs")
def strategy_runs(limit: int = Query(50, ge=1, le=200)) -> dict:
    return {"data": rows("SELECT * FROM research.strategy_run ORDER BY started_at DESC LIMIT :limit", {"limit": limit})}


@app.get("/api/v1/strategy-runs/{run_id}")
def strategy_run(run_id: str) -> dict:
    run = rows("SELECT * FROM research.strategy_run WHERE id=:id", {"id": run_id})
    metrics = rows("SELECT key,value FROM research.performance_metric WHERE run_id=:id ORDER BY key", {"id": run_id})
    return {"data": run[0] if run else None, "metrics": metrics}


@app.get("/api/v1/strategy-runs/{run_id}/signals")
def strategy_signals(run_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    return {"data": rows("SELECT * FROM research.signal WHERE run_id=:id ORDER BY trade_date DESC,rank LIMIT :limit OFFSET :offset", {"id": run_id, "limit": limit, "offset": offset})}


@app.get("/api/v1/strategy-runs/{run_id}/equity")
def strategy_equity(run_id: str) -> dict:
    return {"data": rows("SELECT * FROM research.backtest_daily WHERE run_id=:id ORDER BY trade_date", {"id": run_id})}


@app.get("/api/v1/portfolio")
def portfolio() -> dict:
    return {"data": rows("SELECT * FROM portfolio.portfolio WHERE active ORDER BY created_at DESC")}


@app.get("/api/v1/portfolio/positions")
def portfolio_positions() -> dict:
    return {"data": rows("SELECT p.name,x.symbol,x.quantity,x.average_cost,x.updated_at FROM portfolio.position x JOIN portfolio.portfolio p ON p.id=x.portfolio_id WHERE p.active ORDER BY x.symbol")}


@app.get("/api/v1/portfolio/orders")
def portfolio_orders(limit: int = Query(100, ge=1, le=200)) -> dict:
    return {"data": rows("SELECT o.* FROM portfolio.\"order\" o JOIN portfolio.portfolio p ON p.id=o.portfolio_id WHERE p.active ORDER BY o.created_at DESC LIMIT :limit", {"limit": limit})}


@app.get("/api/v1/jobs")
def jobs() -> dict:
    return {"data": rows("SELECT * FROM ops.job_run ORDER BY started_at DESC LIMIT 100")}


@app.get("/api/v1/backfill-status")
def backfill_status() -> dict:
    return {"data": rows("""SELECT dataset,status,count(*) day_count,sum(row_count) row_count,min(trade_date) first_date,max(trade_date) last_date,max(updated_at) updated_at
      FROM ops.backfill_progress GROUP BY dataset,status ORDER BY dataset,status""")}
