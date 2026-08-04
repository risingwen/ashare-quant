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
        AND category='人气榜' ORDER BY trade_date DESC,snapshot_time DESC LIMIT 1) dc_snapshot_count,
      (SELECT row_count FROM popularity.snapshot WHERE endpoint='ths_hot' AND status='success'
        AND category='热股' ORDER BY trade_date DESC,snapshot_time DESC LIMIT 1) ths_snapshot_count,
      (SELECT count(*) FROM research.strategy_run) strategy_run_count""")[0]
    return {"data": summary, "generated_at": datetime.now(UTC)}


@app.get("/api/v1/data-status")
def data_status() -> dict:
    return {"data": rows("""SELECT DISTINCT ON (dataset)
      id,provider,dataset,status,row_count,source_as_of,finished_at,error_code
      FROM ops.data_batch ORDER BY dataset,id DESC""")}


@app.get("/api/v1/data-freshness")
def data_freshness() -> dict:
    data = rows("""WITH calendar AS (
        SELECT DISTINCT trade_date FROM market.daily_bar WHERE trade_date>='2024-01-01'
      ), latest_market AS (
        SELECT max(trade_date) expected_date FROM calendar
      ), datasets AS (
        SELECT 'daily' dataset,'日线' label,max(trade_date) latest_date,
          count(DISTINCT trade_date) day_count,count(*) row_count,'trading_day' coverage_mode FROM market.daily_bar
        UNION ALL SELECT 'moneyflow_dc','个股资金流',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.stock_moneyflow
        UNION ALL SELECT 'moneyflow_ind_dc','板块资金流',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.sector_moneyflow
        UNION ALL SELECT 'daily_basic','每日估值与换手',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.daily_basic
        UNION ALL SELECT 'adj_factor','复权因子',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.adj_factor
        UNION ALL SELECT 'limit_list_d','涨跌停与炸板',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.limit_event
        UNION ALL SELECT 'limit_step','连板天梯',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.limit_streak
        UNION ALL SELECT 'market_breadth','涨跌家数与冰点',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.market_breadth
        UNION ALL SELECT 'dc_hot','东财人气',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day'
          FROM popularity.snapshot WHERE endpoint='dc_hot' AND category='人气榜' AND status='success'
        UNION ALL SELECT 'ths_hot','同花顺热股',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day'
          FROM popularity.snapshot WHERE endpoint='ths_hot' AND category='热股' AND status='success'
        UNION ALL SELECT 'top_list','龙虎榜个股',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.lhb_record
        UNION ALL SELECT 'top_inst','龙虎榜席位',max(trade_date),count(DISTINCT trade_date),count(*),'trading_day' FROM market.lhb_seat
        UNION ALL SELECT 'hm_detail','游资明细',max(trade_date),count(DISTINCT trade_date),count(*),'latest_only' FROM market.hot_money_detail
        UNION ALL SELECT 'stk_surv','机构调研',max(survey_date),count(DISTINCT survey_date),count(*),'checked_range' FROM research.institutional_survey
        UNION ALL SELECT 'broker_recommend','券商金股',to_date(max(month)||'01','YYYYMMDD'),count(DISTINCT month),count(*),'monthly' FROM research.broker_recommendation
      ), coverage AS (
        SELECT 'daily' dataset,array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE d.trade_date IS NULL) missing_dates
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.daily_bar) d USING(trade_date)
        UNION ALL SELECT 'moneyflow_dc',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.stock_moneyflow) x USING(trade_date)
        UNION ALL SELECT 'moneyflow_ind_dc',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.sector_moneyflow) x USING(trade_date)
        UNION ALL SELECT 'daily_basic',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.daily_basic) x USING(trade_date)
        UNION ALL SELECT 'adj_factor',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.adj_factor) x USING(trade_date)
        UNION ALL SELECT 'limit_list_d',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL AND u.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.limit_event) x USING(trade_date)
          LEFT JOIN (SELECT trade_date FROM ops.backfill_progress WHERE dataset='limit_list_d' AND status='unavailable') u USING(trade_date)
        UNION ALL SELECT 'limit_step',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL AND u.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.limit_streak) x USING(trade_date)
          LEFT JOIN (SELECT trade_date FROM ops.backfill_progress WHERE dataset='limit_step' AND status='unavailable') u USING(trade_date)
        UNION ALL SELECT 'market_breadth',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT trade_date FROM market.market_breadth) x USING(trade_date)
        UNION ALL SELECT 'dc_hot',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL AND u.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM popularity.snapshot
            WHERE endpoint='dc_hot' AND category='人气榜' AND status='success') x USING(trade_date)
          LEFT JOIN (SELECT trade_date FROM ops.backfill_progress WHERE dataset='dc_hot' AND status='unavailable') u USING(trade_date)
        UNION ALL SELECT 'ths_hot',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL AND u.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM popularity.snapshot
            WHERE endpoint='ths_hot' AND category='热股' AND status='success') x USING(trade_date)
          LEFT JOIN (SELECT trade_date FROM ops.backfill_progress WHERE dataset='ths_hot' AND status='unavailable') u USING(trade_date)
        UNION ALL SELECT 'top_list',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.lhb_record) x USING(trade_date)
        UNION ALL SELECT 'top_inst',array_agg(c.trade_date ORDER BY c.trade_date) FILTER (WHERE x.trade_date IS NULL)
          FROM calendar c LEFT JOIN (SELECT DISTINCT trade_date FROM market.lhb_seat) x USING(trade_date)
        UNION ALL SELECT 'hm_detail',NULL::date[]
        UNION ALL SELECT 'stk_surv',NULL::date[]
        UNION ALL SELECT 'broker_recommend',NULL::date[]
      ), limitations AS (
        SELECT dataset,
          count(*) FILTER (WHERE status='unavailable') unavailable_count,
          count(*) FILTER (WHERE status='unauthorized') unauthorized_count,
          array_agg(trade_date ORDER BY trade_date)
            FILTER (WHERE status IN ('unavailable','unauthorized')) source_limited_dates
        FROM ops.backfill_progress
        WHERE status IN ('unavailable','unauthorized')
        GROUP BY dataset
      )
      SELECT d.dataset,d.label,d.latest_date,m.expected_date,d.day_count,d.row_count,d.coverage_mode,
        CASE
          WHEN coalesce(l.unavailable_count,0)+coalesce(l.unauthorized_count,0)>0 THEN 'source_limited'
          WHEN d.dataset='stk_surv' AND coalesce(nullif(b.metadata->>'end','')::date,d.latest_date)>=m.expected_date THEN 'current'
          WHEN d.dataset='broker_recommend' AND to_char(d.latest_date,'YYYYMM')>=to_char(m.expected_date,'YYYYMM') THEN 'current'
          WHEN d.latest_date>=m.expected_date THEN 'current'
          WHEN d.latest_date IS NULL THEN 'empty'
          ELSE 'lagging'
        END status,
        coalesce(cardinality(c.missing_dates),0) missing_count,c.missing_dates,
        coalesce(l.unavailable_count,0)+coalesce(l.unauthorized_count,0) source_limited_count,
        coalesce(l.unavailable_count,0) unavailable_count,
        coalesce(l.unauthorized_count,0) unauthorized_count,l.source_limited_dates,
        CASE WHEN d.dataset='stk_surv' THEN coalesce(nullif(b.metadata->>'end','')::date,d.latest_date)
          ELSE d.latest_date END checked_through,
        b.status latest_attempt_status,b.finished_at latest_attempt_at,b.error_code
      FROM datasets d CROSS JOIN latest_market m LEFT JOIN coverage c USING(dataset)
      LEFT JOIN limitations l USING(dataset)
      LEFT JOIN LATERAL (
        SELECT status,finished_at,error_code,metadata FROM ops.data_batch
        WHERE dataset=CASE WHEN d.dataset='daily' THEN 'daily_market' ELSE d.dataset END ORDER BY id DESC LIMIT 1
      ) b ON true ORDER BY d.dataset""")
    jobs = rows("""SELECT id,job_name,status,started_at,finished_at,details,error FROM ops.job_run
      WHERE job_name IN ('moneyflow_sync','popularity_sync','market_intelligence_sync','sentiment_sync')
      ORDER BY started_at DESC LIMIT 30""")
    return {"data": data, "jobs": jobs, "generated_at": datetime.now(UTC)}


@app.get("/api/v1/instruments")
def instruments(q: str = "", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    return {"data": rows("SELECT symbol,name,exchange,board,list_date,delist_date,active FROM market.instrument WHERE (:q='' OR symbol ILIKE :like OR name ILIKE :like) ORDER BY symbol LIMIT :limit OFFSET :offset", {"q": q, "like": f"%{q}%", "limit": limit, "offset": offset})}


@app.get("/api/v1/bars/{symbol}")
def bars(symbol: str, start: str = "2025-01-01", end: str = "9999-12-31") -> dict:
    return {"data": rows("SELECT * FROM market.daily_bar WHERE symbol=:symbol AND trade_date BETWEEN :start AND :end ORDER BY trade_date", {"symbol": symbol, "start": start, "end": end})}


@app.get("/api/v1/popularity/rankings")
def rankings(trade_date: str, source: Literal["dc_hot", "ths_hot"] = "dc_hot", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    final_category = "人气榜" if source == "dc_hot" else "热股"
    data = rows("""WITH latest AS (
        SELECT DISTINCT ON (provider,endpoint,category) id,provider,endpoint,category,trade_date,snapshot_time
        FROM popularity.snapshot WHERE endpoint=:source AND category=:category
          AND status='success' AND trade_date=:trade_date
        ORDER BY provider,endpoint,category,snapshot_time DESC
      )
      SELECT s.provider,s.endpoint,s.category,s.trade_date,s.snapshot_time,i.symbol,i.name,i.rank,i.heat,
        i.rank_change,i.rank_reason,i.concept,b.close base_close,
        future.next_trade_date,future.day_3_trade_date,future.day_5_trade_date,
        round(100 * (future.next_close / nullif(b.close,0) - 1), 4) next_day_return,
        round(100 * (future.day_3_close / nullif(b.close,0) - 1), 4) day_3_return,
        round(100 * (future.day_5_close / nullif(b.close,0) - 1), 4) day_5_return
      FROM latest s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
      LEFT JOIN market.daily_bar b ON b.symbol=i.symbol AND b.trade_date=s.trade_date
      LEFT JOIN LATERAL (
        SELECT max(trade_date) FILTER (WHERE sequence=1) next_trade_date,
          max(trade_date) FILTER (WHERE sequence=3) day_3_trade_date,
          max(trade_date) FILTER (WHERE sequence=5) day_5_trade_date,
          max(close) FILTER (WHERE sequence=1) next_close,
          max(close) FILTER (WHERE sequence=3) day_3_close,
          max(close) FILTER (WHERE sequence=5) day_5_close
        FROM (
          SELECT trade_date,close,row_number() OVER (ORDER BY trade_date) sequence
          FROM market.daily_bar
          WHERE symbol=i.symbol AND trade_date>s.trade_date
          ORDER BY trade_date LIMIT 5
        ) observations
      ) future ON true
      ORDER BY s.provider,i.rank LIMIT :limit OFFSET :offset""",
      {"trade_date": trade_date, "source": source, "category": final_category, "limit": limit, "offset": offset})
    source_label = "东方财富" if source == "dc_hot" else "同花顺"
    return {"data": data, "limit": limit, "offset": offset, "coverage": {
        "scope": "published_top_100", "rank_limit": 100,
        "description": f"{source_label} {source} 每日最终发布的前100名，不代表全市场全部股票",
    }, "source": source, "source_label": source_label}


@app.get("/api/v1/popularity/dates")
def popularity_dates(source: Literal["dc_hot", "ths_hot"] = "dc_hot") -> dict:
    final_category = "人气榜" if source == "dc_hot" else "热股"
    return {"data": rows("""SELECT trade_date,provider,endpoint,count(*) snapshot_count,
      (array_agg(row_count ORDER BY snapshot_time DESC))[1] row_count,max(snapshot_time) latest_snapshot_time
      FROM popularity.snapshot WHERE endpoint=:source AND category=:category AND status='success'
      GROUP BY trade_date,provider,endpoint ORDER BY trade_date DESC,provider LIMIT 1000""", {
        "source": source, "category": final_category,
      }),
      "source": source, "source_label": "东方财富" if source == "dc_hot" else "同花顺"}


@app.get("/api/v1/popularity/history/{symbol}")
def popularity_history(symbol: str, source: Literal["dc_hot", "ths_hot"] = "dc_hot", limit: int = Query(200, ge=1, le=500)) -> dict:
    final_category = "人气榜" if source == "dc_hot" else "热股"
    return {"data": rows("""SELECT provider,endpoint,category,trade_date,snapshot_time,rank,heat,rank_change
      FROM popularity.daily_close WHERE endpoint=:source AND category=:category AND symbol=:symbol
      ORDER BY trade_date DESC,snapshot_time DESC LIMIT :limit""", {
        "source": source, "category": final_category, "symbol": symbol, "limit": limit,
    })}


@app.get("/api/v1/popularity/detail/{symbol}")
def popularity_detail(
    symbol: str,
    source: Literal["dc_hot", "ths_hot"] = "dc_hot",
    end_date: str = "9999-12-31",
    days: int = Query(30, ge=5, le=120),
) -> dict:
    try:
        date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="end_date 必须是 YYYY-MM-DD 格式") from exc
    final_category = "人气榜" if source == "dc_hot" else "热股"
    bars_data = rows("""WITH ordered AS (
        SELECT trade_date,open,high,low,close,volume,amount,pct_change,
          row_number() OVER (ORDER BY trade_date) sequence,count(*) OVER () total_rows
        FROM market.daily_bar WHERE symbol=:symbol
      ), anchor AS (
        SELECT max(sequence) anchor_sequence,max(total_rows) total_rows
        FROM ordered WHERE trade_date<=:end_date
      ), bounds AS (
        SELECT greatest(1,least(anchor_sequence-:before_days,greatest(total_rows-:days+1,1))) start_sequence,
          total_rows FROM anchor WHERE anchor_sequence IS NOT NULL
      )
      SELECT trade_date,open,high,low,close,volume,amount,pct_change
      FROM ordered CROSS JOIN bounds
      WHERE ordered.sequence BETWEEN bounds.start_sequence
        AND least(bounds.start_sequence+:days-1,bounds.total_rows)
      ORDER BY trade_date""", {
        "symbol": symbol, "end_date": end_date, "days": days, "before_days": days // 2,
    })
    window_start = bars_data[0]["trade_date"] if bars_data else end_date
    window_end = bars_data[-1]["trade_date"] if bars_data else end_date
    rank_data = rows("""SELECT provider,endpoint,trade_date,snapshot_time,rank,heat,rank_change
      FROM popularity.daily_close
      WHERE endpoint=:source AND category=:category AND symbol=:symbol
        AND trade_date BETWEEN :window_start AND :window_end
      ORDER BY trade_date,snapshot_time""", {
        "source": source, "category": final_category, "symbol": symbol,
        "window_start": window_start, "window_end": window_end,
    })
    name_data = rows("""SELECT name FROM popularity.daily_close
      WHERE endpoint=:source AND category=:category AND symbol=:symbol AND trade_date<=:end_date
      ORDER BY trade_date DESC LIMIT 1""", {
        "source": source, "category": final_category, "symbol": symbol, "end_date": end_date,
      })
    return {
        "data": {"bars": bars_data, "ranks": rank_data},
        "symbol": symbol,
        "name": name_data[0]["name"] if name_data else symbol,
        "source": source,
        "source_label": "东方财富" if source == "dc_hot" else "同花顺",
        "end_date": end_date,
        "days": days,
        "window": {
            "start_date": window_start,
            "end_date": window_end,
            "anchor_date": end_date,
            "trade_day_count": len(bars_data),
        },
    }


@app.get("/api/v1/popularity/intraday")
def popularity_intraday(trade_date: str, source: Literal["dc_hot", "ths_hot"] = "dc_hot", symbol: str | None = None) -> dict:
    snapshots = rows("""SELECT snapshot_time,row_count FROM popularity.snapshot
      WHERE endpoint=:source AND category LIKE '%盘中' AND trade_date=:date AND status='success'
      ORDER BY snapshot_time""", {"date": trade_date, "source": source})
    trajectory = []
    if symbol:
        trajectory = rows("""SELECT s.snapshot_time,i.symbol,i.name,i.rank,i.heat,i.rank_change,i.rank_reason
          FROM popularity.snapshot s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
          WHERE s.endpoint=:source AND s.category LIKE '%盘中' AND s.trade_date=:date
            AND s.status='success' AND i.symbol=:symbol
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
      r.l_sell,r.l_buy,r.l_amount,coalesce(r.net_amount,s.net_amount) net_amount,r.net_rate,
      r.amount_rate,r.float_values,r.reason,coalesce(s.seat_count,0) seat_count,
      coalesce(s.institution_count,0) institution_count,coalesce(s.business_seat_count,0) business_seat_count
      FROM market.lhb_record r LEFT JOIN (
        SELECT trade_date,symbol,sum(net_buy) net_amount,count(*) seat_count,
          count(*) FILTER (WHERE seat_name LIKE '%机构专用%') institution_count,
          count(*) FILTER (WHERE seat_name NOT LIKE '%机构专用%') business_seat_count
        FROM market.lhb_seat GROUP BY trade_date,symbol
      ) s USING(trade_date,symbol) WHERE r.trade_date=:date
      ORDER BY coalesce(r.net_amount,s.net_amount) DESC NULLS LAST LIMIT :limit OFFSET :offset""", {"date": trade_date, "limit": limit, "offset": offset})}


@app.get("/api/v1/lhb/seats")
def lhb_seats(trade_date: str, symbol: str, limit: int = Query(100, ge=1, le=500)) -> dict:
    data = rows("""SELECT seat_name,side,
      CASE side WHEN '0' THEN '买入前五' WHEN '1' THEN '卖出前五' ELSE side END side_label,
      CASE WHEN seat_name LIKE '%机构专用%' THEN '机构' ELSE '营业部' END seat_type,
      buy,buy_rate,sell,sell_rate,net_buy,reason
      FROM market.lhb_seat WHERE trade_date=:date AND symbol=:symbol
      ORDER BY side,abs(net_buy) DESC NULLS LAST LIMIT :limit""", {
        "date": trade_date, "symbol": symbol, "limit": limit,
    })
    institution_count = sum(item["seat_type"] == "机构" for item in data)
    business_count = len(data) - institution_count
    coverage_status = "mixed" if business_count else "institution_only" if institution_count else "missing"
    return {"data": data, "coverage": {
        "status": coverage_status,
        "seat_count": len(data),
        "institution_count": institution_count,
        "business_seat_count": business_count,
        "description": "同时含机构与普通营业部席位；仅表示类型覆盖，不保证上游全量" if coverage_status == "mixed" else
          "上游目前只返回机构专用席位，不能视为完整席位" if coverage_status == "institution_only" else
          "上游未返回该股票席位明细",
    }}


@app.get("/api/v1/lhb/history/{symbol}")
def lhb_history(symbol: str, limit: int = Query(200, ge=1, le=500)) -> dict:
    return {"data": rows("""SELECT trade_date,symbol,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,
      l_amount,net_amount,net_rate,amount_rate,float_values,reason FROM market.lhb_record
      WHERE symbol=:symbol ORDER BY trade_date DESC LIMIT :limit""", {"symbol": symbol, "limit": limit})}


@app.get("/api/v1/lhb/detail/{symbol}")
def lhb_detail(
    symbol: str,
    trade_date: str,
    days: int = Query(30, ge=5, le=120),
) -> dict:
    try:
        date.fromisoformat(trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="trade_date 必须是 YYYY-MM-DD 格式") from exc
    bars_data = rows("""SELECT * FROM (
        SELECT trade_date,open,high,low,close,volume,amount,pct_change
        FROM market.daily_bar WHERE symbol=:symbol AND trade_date<=:date
        ORDER BY trade_date DESC LIMIT :days
      ) selected ORDER BY trade_date""", {"symbol": symbol, "date": trade_date, "days": days})
    history_data = rows("""SELECT trade_date,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,l_amount,
      net_amount,net_rate,amount_rate,float_values,reason FROM market.lhb_record
      WHERE symbol=:symbol AND trade_date<=:date ORDER BY trade_date DESC LIMIT 50""", {
        "symbol": symbol, "date": trade_date,
    })
    flow_data = rows("""SELECT trade_date,close,pct_change,net_amount,net_amount_rate,buy_elg_amount,
      buy_lg_amount,buy_md_amount,buy_sm_amount FROM market.stock_moneyflow
      WHERE symbol=:symbol AND trade_date<=:date ORDER BY trade_date DESC LIMIT :days""", {
        "symbol": symbol, "date": trade_date, "days": days,
    })
    hot_money_data = rows("""SELECT d.trade_date,d.hot_money_name,d.associated_orgs,d.buy_amount,d.sell_amount,
      d.net_amount,d.tag,h.description FROM market.hot_money_detail d
      LEFT JOIN market.hot_money_directory h USING(hot_money_name)
      WHERE d.symbol=:symbol AND d.trade_date<=:date
      ORDER BY d.trade_date DESC,abs(d.net_amount) DESC NULLS LAST LIMIT 100""", {
        "symbol": symbol, "date": trade_date,
    })
    return {"data": {
        "bars": bars_data,
        "history": history_data,
        "moneyflow": flow_data,
        "hot_money": hot_money_data,
    }, "symbol": symbol, "trade_date": trade_date, "days": days}


@app.get("/api/v1/research/survey-dates")
def survey_dates() -> dict:
    return {"data": rows("""SELECT survey_date,count(*) row_count,count(DISTINCT symbol) symbol_count
      FROM research.institutional_survey GROUP BY survey_date ORDER BY survey_date DESC LIMIT 1000""")}


@app.get("/api/v1/research/surveys")
def institutional_surveys(
    survey_date: str | None = None,
    q: str = "",
    sort_by: Literal["symbol", "name", "receive_org", "org_type"] = "symbol",
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    if survey_date:
        try:
            date.fromisoformat(survey_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="survey_date 必须是 YYYY-MM-DD 格式") from exc
    effective = survey_date or rows("SELECT max(survey_date) survey_date FROM research.institutional_survey")[0]["survey_date"]
    survey_sort_columns = {
        "symbol": "s.symbol", "name": "coalesce(s.name,i.name,s.symbol)",
        "receive_org": "s.receive_org", "org_type": "s.org_type",
    }
    order_column = survey_sort_columns[sort_by]
    direction = sort_dir.upper()
    data = rows(f"""SELECT s.record_key,s.symbol,coalesce(s.name,i.name,s.symbol) name,s.survey_date,
      s.fund_visitors,s.receive_place,s.receive_mode,s.receive_org,s.org_type,s.company_receivers,s.content
      FROM research.institutional_survey s LEFT JOIN market.instrument i ON i.symbol=s.symbol
      WHERE s.survey_date=:date AND (:q='' OR s.symbol ILIKE :like OR s.name ILIKE :like OR i.name ILIKE :like
        OR s.receive_org ILIKE :like OR s.fund_visitors ILIKE :like)
      ORDER BY {order_column} {direction} NULLS LAST,s.symbol,s.receive_org NULLS LAST LIMIT :limit OFFSET :offset""", {
        "date": effective, "q": q, "like": f"%{q}%", "limit": limit, "offset": offset,
    }) if effective else []
    return {"data": data, "effective_date": effective, "sort_by": sort_by,
            "sort_dir": sort_dir, "limit": limit, "offset": offset}


@app.get("/api/v1/research/broker-months")
def broker_months() -> dict:
    return {"data": rows("""SELECT month,count(*) row_count,count(DISTINCT broker) broker_count,
      count(DISTINCT symbol) symbol_count FROM research.broker_recommendation
      GROUP BY month ORDER BY month DESC LIMIT 120""")}


@app.get("/api/v1/research/broker-recommendations")
def broker_recommendations(
    month: str | None = None,
    q: str = "",
    sort_by: Literal["symbol", "name", "broker", "recommendation_count"] = "recommendation_count",
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    if month and (len(month) != 6 or not month.isdigit()):
        raise HTTPException(status_code=422, detail="month 必须是 YYYYMM 格式")
    effective = month or rows("SELECT max(month) month FROM research.broker_recommendation")[0]["month"]
    broker_sort_columns = {
        "symbol": "symbol", "name": "name", "broker": "broker",
        "recommendation_count": "recommendation_count",
    }
    order_column = broker_sort_columns[sort_by]
    direction = sort_dir.upper()
    data = rows(f"""SELECT * FROM (
        SELECT b.month,b.broker,b.symbol,coalesce(b.name,i.name,b.symbol) name,
          count(*) OVER (PARTITION BY b.symbol) recommendation_count
        FROM research.broker_recommendation b LEFT JOIN market.instrument i ON i.symbol=b.symbol
        WHERE b.month=:month AND (:q='' OR b.broker ILIKE :like OR b.symbol ILIKE :like
          OR b.name ILIKE :like OR i.name ILIKE :like)
      ) recommendations
      ORDER BY {order_column} {direction} NULLS LAST,symbol,broker LIMIT :limit OFFSET :offset""", {
        "month": effective, "q": q, "like": f"%{q}%", "limit": limit, "offset": offset,
    }) if effective else []
    return {"data": data, "effective_month": effective, "sort_by": sort_by,
            "sort_dir": sort_dir, "limit": limit, "offset": offset}


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
