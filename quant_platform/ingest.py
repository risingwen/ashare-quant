from __future__ import annotations

import json
from datetime import UTC, datetime
from collections import defaultdict
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import text

from .db import engine
from .providers.base import ProviderResult
from .providers.replay import ReplayProvider


def _pick(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def _numeric(value: Any) -> Any:
    return None if value in (None, "", "--") else value


def _wan_to_yuan(value: Any) -> Any:
    value = _numeric(value)
    if value is None:
        return None
    numeric = float(value)
    return numeric * 10000 if abs(numeric) < 10_000_000 else numeric


def _documented_wan_to_yuan(value: Any) -> Any:
    """Convert fields whose upstream contract explicitly declares 万元 to yuan."""
    value = _numeric(value)
    return None if value is None else float(value) * 10000


def normalize_popularity(result: ProviderResult, trade_date: str) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(result.rows, 1):
        symbol = str(_pick(row, "ts_code", "code", "股票代码") or "").split(".")[0].zfill(6)
        rank = _pick(row, "rank", "排名", "当前排名")
        if not symbol.isdigit() or not rank:
            continue
        normalized.append({
            "symbol": symbol, "name": str(_pick(row, "ts_name", "name", "股票名称") or symbol),
            "rank": int(rank or index), "heat": _pick(row, "hot", "heat", "score"),
            "rank_change": _pick(row, "rank_change", "排名变化"), "rank_reason": _pick(row, "rank_reason", "上榜原因"),
            "concept": _pick(row, "concept", "概念"), "is_new": str(_pick(row, "is_new") or "").upper() in {"Y", "1", "TRUE"},
            "rank_time": _pick(row, "rank_time", "排名时间"),
            "raw": json.dumps(row, ensure_ascii=False, default=str), "trade_date": trade_date,
        })
    return normalized


def select_latest_popularity_snapshot(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Some historical is_new=Y responses contain several recent frames."""
    # Rows are ordered by rank, not frame. Select the newest candidate for each
    # rank independently; when timestamps tie, heat resolves stale duplicates.
    candidates_by_rank: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        candidates_by_rank[int(item["rank"])].append(item)
    selected: list[dict[str, Any]] = []
    used_symbols: set[str] = set()
    for rank in sorted(candidates_by_rank):
        candidates = sorted(candidates_by_rank[rank],
                            key=lambda item: (str(item.get("rank_time") or ""), float(item.get("heat") or -1)),
                            reverse=True)
        candidate = next((item for item in candidates if item["symbol"] not in used_symbols), None)
        if candidate is not None:
            selected.append(candidate)
            used_symbols.add(candidate["symbol"])
    return selected


def ingest_popularity(provider: ReplayProvider, endpoint: str, trade_date: str) -> dict[str, Any]:
    result = provider.fetch_popularity(endpoint, trade_date)
    items = select_latest_popularity_snapshot(normalize_popularity(result, trade_date)) if result.status == "success" else []
    status = result.status
    if result.status == "success" and len(items) < 20:
        status = "quarantined"
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch(provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,finished_at)
          VALUES (:provider,:dataset,:requested,:as_of,:status,:count,:hash,:error_code,:error_message,now()) RETURNING id"""),
          {"provider": result.provider, "dataset": endpoint, "requested": result.requested_at, "as_of": result.source_as_of,
           "status": status, "count": len(items), "hash": result.raw_hash, "error_code": result.error_code, "error_message": result.error_message}).scalar_one()
        if status == "quarantined":
            conn.execute(text("INSERT INTO ops.data_issue(batch_id,severity,code,message,details) VALUES (:batch,'error','popularity_too_few_rows',:message,'{}')"), {"batch": batch_id, "message": f"normalized rows {len(items)} < 20"})
        if status == "success":
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            # is_new=Y is one official final list. THS rank_time describes
            # individual row updates, so it must not split that list into frames.
            final_snapshot_time = f"{trade_date} 22:30:00"
            for item in items:
                item.pop("rank_time", None)
                grouped[final_snapshot_time].append(item)
            for rank_time, snapshot_items in sorted(grouped.items()):
                candidate = str(rank_time).replace("Z", "+00:00")
                try:
                    parsed = datetime.fromisoformat(candidate)
                    snapshot_time = parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                except ValueError:
                    snapshot_time = datetime.fromisoformat(f"{trade_date}T22:30:00").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                snapshot_id = conn.execute(text("""INSERT INTO popularity.snapshot(provider,endpoint,category,trade_date,snapshot_time,status,row_count,batch_id,raw_hash)
                  VALUES (:provider,:endpoint,:category,:trade_date,:snapshot_time,'success',:count,:batch,:hash)
                  ON CONFLICT(provider,endpoint,market,category,snapshot_time) DO UPDATE SET row_count=excluded.row_count,batch_id=excluded.batch_id
                  RETURNING id"""), {"provider": result.provider, "endpoint": endpoint, "category": "人气榜" if endpoint == "dc_hot" else "热股", "trade_date": trade_date, "snapshot_time": snapshot_time, "count": len(snapshot_items), "batch": batch_id, "hash": result.raw_hash}).scalar_one()
                conn.execute(text("""INSERT INTO popularity.snapshot_item(snapshot_id,symbol,name,rank,heat,rank_change,rank_reason,concept,is_new,raw)
                  VALUES (:snapshot_id,:symbol,:name,:rank,:heat,:rank_change,:rank_reason,:concept,:is_new,CAST(:raw AS jsonb))
                  ON CONFLICT(snapshot_id,symbol) DO UPDATE SET rank=excluded.rank,heat=excluded.heat,raw=excluded.raw"""), [{**item, "snapshot_id": snapshot_id} for item in snapshot_items])
    return {"endpoint": endpoint, "status": status, "rows": len(items), "snapshots": len(grouped) if status == "success" else 0, "batch_id": batch_id}


def refresh_popularity_view() -> None:
    with engine.begin() as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY popularity.daily_close"))


def ingest_daily_market(provider: Any, trade_date: str) -> dict[str, Any]:
    result = provider.fetch_daily_market(trade_date)
    normalized = []
    for row in result.rows:
        symbol = str(_pick(row, "ts_code", "code", "代码") or "").split(".")[0].zfill(6)
        values = {
            "open": _pick(row, "open", "今开"), "high": _pick(row, "high", "最高"), "low": _pick(row, "low", "最低"),
            "close": _pick(row, "close", "最新价"), "vol": _pick(row, "vol", "成交量"), "amount": _pick(row, "amount", "成交额"),
            "pct_chg": _pick(row, "pct_chg", "涨跌幅"), "turnover_rate": _pick(row, "turnover_rate", "换手率"),
        }
        if not symbol.isdigit() or any(values[key] is None for key in ("open", "high", "low", "close", "vol", "amount")):
            continue
        normalized.append({"symbol": symbol, "trade_date": trade_date, "open": values["open"], "high": values["high"], "low": values["low"], "close": values["close"], "volume": values["vol"], "amount": values["amount"], "pct_change": values["pct_chg"], "turnover": values["turnover_rate"], "provider": result.provider})
    status = result.status if result.status != "success" or len(normalized) >= 4000 else "quarantined"
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch(provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,finished_at)
          VALUES (:provider,'daily_market',:requested,:as_of,:status,:count,:hash,:error_code,:error_message,now()) RETURNING id"""),
          {"provider": result.provider, "requested": result.requested_at, "as_of": result.source_as_of, "status": status, "count": len(normalized), "hash": result.raw_hash, "error_code": result.error_code, "error_message": result.error_message}).scalar_one()
        if status == "success":
            known = set(conn.execute(text("SELECT symbol FROM market.instrument WHERE symbol=ANY(:symbols)"), {"symbols": [r["symbol"] for r in normalized]}).scalars())
            missing = sorted({r["symbol"] for r in normalized} - known)
            if missing:
                conn.execute(text("INSERT INTO market.instrument(symbol,name,exchange) VALUES (:symbol,:symbol,'UNKNOWN') ON CONFLICT DO NOTHING"), [{"symbol": symbol} for symbol in missing])
            conn.execute(text("""INSERT INTO market.daily_bar(symbol,trade_date,open,high,low,close,volume,amount,pct_change,turnover,provider,batch_id)
              VALUES (:symbol,:trade_date,:open,:high,:low,:close,:volume,:amount,:pct_change,:turnover,:provider,:batch_id)
              ON CONFLICT(symbol,trade_date) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,amount=excluded.amount,pct_change=excluded.pct_change,turnover=excluded.turnover,provider=excluded.provider,batch_id=excluded.batch_id"""), [{**row, "batch_id": batch_id} for row in normalized])
        elif result.status == "success":
            conn.execute(text("INSERT INTO ops.data_issue(batch_id,severity,code,message) VALUES (:batch,'error','daily_market_too_few_rows',:message)"), {"batch": batch_id, "message": f"normalized rows {len(normalized)} < 4000"})
    return {"status": status, "rows": len(normalized), "batch_id": batch_id}


def ingest_lhb(provider: ReplayProvider, endpoint: str, trade_date: str) -> dict[str, Any]:
    result = provider.fetch_lhb(endpoint, trade_date)
    rows = result.rows if result.status == "success" else []
    status = result.status
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch(provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,finished_at)
          VALUES (:provider,:dataset,:requested,:as_of,:status,:count,:hash,:error_code,:error_message,now()) RETURNING id"""),
          {"provider": result.provider, "dataset": endpoint, "requested": result.requested_at, "as_of": result.source_as_of, "status": status, "count": len(rows), "hash": result.raw_hash, "error_code": result.error_code, "error_message": result.error_message}).scalar_one()
        if status == "success" and endpoint == "top_list":
            deduped = {}
            for r in rows:
                key = (str(r.get("ts_code") or "").split(".")[0].zfill(6), r.get("reason") or "未说明")
                score = sum(r.get(field) not in (None, "", "--") for field in ("turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate", "amount_rate"))
                previous = deduped.get(key)
                previous_score = sum(previous.get(field) not in (None, "", "--") for field in ("turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate", "amount_rate")) if previous else -1
                if score > previous_score:
                    deduped[key] = r
            conn.execute(text("""INSERT INTO market.lhb_record(trade_date,symbol,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,l_amount,net_amount,net_rate,amount_rate,float_values,reason,provider,batch_id,raw)
              VALUES (:trade_date,:symbol,:name,:close,:pct_change,:turnover_rate,:amount,:l_sell,:l_buy,:l_amount,:net_amount,:net_rate,:amount_rate,:float_values,:reason,:provider,:batch_id,CAST(:raw AS jsonb))
              ON CONFLICT(trade_date,symbol,reason) DO UPDATE SET close=excluded.close,pct_change=excluded.pct_change,net_amount=excluded.net_amount,batch_id=excluded.batch_id,raw=excluded.raw"""),
              [{"trade_date": trade_date, "symbol": key[0], "name": r.get("name") or "", "close": _numeric(r.get("close")), "pct_change": _numeric(r.get("pct_change")), "turnover_rate": _numeric(r.get("turnover_rate")), "amount": _wan_to_yuan(r.get("amount")), "l_sell": _wan_to_yuan(r.get("l_sell")), "l_buy": _wan_to_yuan(r.get("l_buy")), "l_amount": _wan_to_yuan(r.get("l_amount")), "net_amount": _wan_to_yuan(r.get("net_amount")), "net_rate": _numeric(r.get("net_rate")), "amount_rate": _numeric(r.get("amount_rate")), "float_values": _wan_to_yuan(r.get("float_values")), "reason": key[1], "provider": result.provider, "batch_id": batch_id, "raw": json.dumps(r, ensure_ascii=False, default=str)} for key, r in deduped.items()])
        elif status == "success" and endpoint == "top_inst":
            deduped = {}
            for r in rows:
                key = (str(r.get("ts_code") or "").split(".")[0].zfill(6), r.get("exalter") or "未知席位", str(r.get("side") or "0"), r.get("reason") or "未说明")
                score = sum(r.get(field) not in (None, "", "--") for field in ("buy", "buy_rate", "sell", "sell_rate", "net_buy"))
                previous = deduped.get(key)
                previous_score = sum(previous.get(field) not in (None, "", "--") for field in ("buy", "buy_rate", "sell", "sell_rate", "net_buy")) if previous else -1
                if score > previous_score:
                    deduped[key] = r
            conn.execute(text("""INSERT INTO market.lhb_seat(trade_date,symbol,seat_name,side,buy,buy_rate,sell,sell_rate,net_buy,reason,provider,batch_id,raw)
              VALUES (:trade_date,:symbol,:seat_name,:side,:buy,:buy_rate,:sell,:sell_rate,:net_buy,:reason,:provider,:batch_id,CAST(:raw AS jsonb))
              ON CONFLICT(trade_date,symbol,seat_name,side,reason) DO UPDATE SET buy=excluded.buy,sell=excluded.sell,net_buy=excluded.net_buy,batch_id=excluded.batch_id,raw=excluded.raw"""),
              [{"trade_date": trade_date, "symbol": key[0], "seat_name": key[1], "side": key[2], "buy": _numeric(r.get("buy")), "buy_rate": _numeric(r.get("buy_rate")), "sell": _numeric(r.get("sell")), "sell_rate": _numeric(r.get("sell_rate")), "net_buy": _numeric(r.get("net_buy")), "reason": key[3], "provider": result.provider, "batch_id": batch_id, "raw": json.dumps(r, ensure_ascii=False, default=str)} for key, r in deduped.items()])
    return {"endpoint": endpoint, "status": status, "rows": len(rows), "batch_id": batch_id}


def ingest_moneyflow(provider: ReplayProvider, endpoint: str, trade_date: str) -> dict[str, Any]:
    """Persist standardized Eastmoney stock/sector flow amounts in yuan."""
    if endpoint not in {"moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc"}:
        raise ValueError("unsupported moneyflow endpoint")
    result = provider.fetch_moneyflow(endpoint, trade_date)
    source_rows = result.rows if result.status == "success" else []
    minimum = 4000 if endpoint == "moneyflow_dc" else 50 if endpoint == "moneyflow_ind_dc" else 1
    status = result.status if result.status != "success" or len(source_rows) >= minimum else "quarantined"
    expected_date = trade_date.replace("-", "")
    returned_dates = {str(row.get("trade_date") or "").replace("-", "") for row in source_rows}
    returned_dates.discard("")
    date_mismatch = result.status == "success" and returned_dates != {expected_date}
    if date_mismatch:
        status = "quarantined"
    amount_fields = ("net_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount")
    normalized = []
    for row in source_rows:
        if endpoint == "moneyflow_mkt_dc":
            continue
        code = str(row.get("ts_code") or "")
        symbol = code.split(".")[0].zfill(6) if endpoint == "moneyflow_dc" else code
        if not symbol or not row.get("trade_date"):
            continue
        item = {
            "trade_date": trade_date,
            "code": symbol,
            "name": str(row.get("name") or symbol),
            "content_type": row.get("content_type"),
            "rank": _numeric(row.get("rank")),
            "close": _numeric(row.get("close")),
            "pct_change": _numeric(row.get("pct_change")),
            "net_amount_rate": _numeric(row.get("net_amount_rate")),
            "buy_elg_amount_rate": _numeric(row.get("buy_elg_amount_rate")),
            "buy_lg_amount_rate": _numeric(row.get("buy_lg_amount_rate")),
            "buy_md_amount_rate": _numeric(row.get("buy_md_amount_rate")),
            "buy_sm_amount_rate": _numeric(row.get("buy_sm_amount_rate")),
            "lead_stock": row.get("buy_sm_amount_stock") or row.get("lead_stock"),
            "provider": result.provider,
            "raw": json.dumps(row, ensure_ascii=False, default=str),
        }
        # moneyflow_dc documents 万元; moneyflow_ind_dc Replay already returns yuan.
        item.update({field: (_documented_wan_to_yuan(row.get(field)) if endpoint == "moneyflow_dc" else _numeric(row.get(field))) for field in amount_fields})
        normalized.append(item)
    with engine.begin() as conn:
        batch_id = conn.execute(text("""INSERT INTO ops.data_batch(provider,dataset,requested_at,source_as_of,status,row_count,raw_hash,error_code,error_message,finished_at)
          VALUES (:provider,:dataset,:requested,:as_of,:status,:count,:hash,:error_code,:error_message,now()) RETURNING id"""),
          {"provider": result.provider, "dataset": endpoint, "requested": result.requested_at, "as_of": result.source_as_of,
           "status": status, "count": len(source_rows), "hash": result.raw_hash, "error_code": result.error_code, "error_message": result.error_message}).scalar_one()
        if status == "success" and endpoint == "moneyflow_dc":
            conn.execute(text("""INSERT INTO market.stock_moneyflow(trade_date,symbol,name,close,pct_change,net_amount,net_amount_rate,
              buy_elg_amount,buy_elg_amount_rate,buy_lg_amount,buy_lg_amount_rate,buy_md_amount,buy_md_amount_rate,buy_sm_amount,buy_sm_amount_rate,provider,batch_id,raw)
              VALUES (:trade_date,:code,:name,:close,:pct_change,:net_amount,:net_amount_rate,:buy_elg_amount,:buy_elg_amount_rate,
              :buy_lg_amount,:buy_lg_amount_rate,:buy_md_amount,:buy_md_amount_rate,:buy_sm_amount,:buy_sm_amount_rate,:provider,:batch_id,CAST(:raw AS jsonb))
              ON CONFLICT(trade_date,symbol) DO UPDATE SET name=excluded.name,close=excluded.close,pct_change=excluded.pct_change,
              net_amount=excluded.net_amount,net_amount_rate=excluded.net_amount_rate,buy_elg_amount=excluded.buy_elg_amount,
              buy_lg_amount=excluded.buy_lg_amount,buy_md_amount=excluded.buy_md_amount,buy_sm_amount=excluded.buy_sm_amount,batch_id=excluded.batch_id,raw=excluded.raw"""),
              [{**item, "batch_id": batch_id} for item in normalized])
        elif status == "success" and endpoint == "moneyflow_ind_dc":
            conn.execute(text("""INSERT INTO market.sector_moneyflow(trade_date,sector_code,name,content_type,rank,close,pct_change,net_amount,net_amount_rate,
              buy_elg_amount,buy_elg_amount_rate,buy_lg_amount,buy_lg_amount_rate,buy_md_amount,buy_md_amount_rate,buy_sm_amount,buy_sm_amount_rate,lead_stock,provider,batch_id,raw)
              VALUES (:trade_date,:code,:name,:content_type,:rank,:close,:pct_change,:net_amount,:net_amount_rate,:buy_elg_amount,:buy_elg_amount_rate,
              :buy_lg_amount,:buy_lg_amount_rate,:buy_md_amount,:buy_md_amount_rate,:buy_sm_amount,:buy_sm_amount_rate,:lead_stock,:provider,:batch_id,CAST(:raw AS jsonb))
              ON CONFLICT(trade_date,sector_code) DO UPDATE SET name=excluded.name,content_type=excluded.content_type,rank=excluded.rank,
              close=excluded.close,pct_change=excluded.pct_change,net_amount=excluded.net_amount,net_amount_rate=excluded.net_amount_rate,
              buy_elg_amount=excluded.buy_elg_amount,buy_lg_amount=excluded.buy_lg_amount,buy_md_amount=excluded.buy_md_amount,
              buy_sm_amount=excluded.buy_sm_amount,lead_stock=excluded.lead_stock,batch_id=excluded.batch_id,raw=excluded.raw"""),
              [{**item, "batch_id": batch_id} for item in normalized])
        if status == "quarantined":
            code = "moneyflow_date_mismatch" if date_mismatch else "moneyflow_too_few_rows"
            message = (f"{endpoint} requested {expected_date}, returned dates {sorted(returned_dates)}"
                       if date_mismatch else f"{endpoint} rows {len(source_rows)} < {minimum}")
            conn.execute(text("INSERT INTO ops.data_issue(batch_id,severity,code,message) VALUES (:batch,'error',:code,:message)"),
                         {"batch": batch_id, "code": code, "message": message})
    return {"endpoint": endpoint, "status": status, "rows": len(normalized), "batch_id": batch_id}
