from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, UTC
from decimal import Decimal

from sqlalchemy import text

from ..db import engine


def run_popularity_breakout(start_date: str, end_date: str, rank_max: int = 10, max_positions: int = 10) -> dict:
    params = {"rank_max": rank_max, "max_positions": max_positions}
    data_version = f"daily:{end_date}:popularity:{end_date}"
    fingerprint = hashlib.sha256(json.dumps(["popularity_breakout", 1, params, data_version], sort_keys=True).encode()).hexdigest()
    run_id = uuid.uuid4()
    with engine.begin() as conn:
        existing = conn.execute(text("SELECT id,status FROM research.strategy_run WHERE fingerprint=:fp"), {"fp": fingerprint}).mappings().first()
        if existing:
            return {"id": str(existing["id"]), "status": existing["status"], "reused": True}
        conn.execute(text("""INSERT INTO research.strategy_run(id,template_key,template_version,parameters,fingerprint,data_version,start_date,end_date,status)
          VALUES (:id,'popularity_breakout',1,CAST(:params AS jsonb),:fp,:dv,:start,:end,'running')"""),
          {"id": run_id, "params": json.dumps(params), "fp": fingerprint, "dv": data_version, "start": start_date, "end": end_date})
        candidates = conn.execute(text("""WITH ranked AS (
          SELECT trade_date,symbol,min(rank) rank FROM popularity.daily_close
          WHERE endpoint='dc_hot' AND trade_date BETWEEN :start AND :end AND rank<=:rank_max GROUP BY trade_date,symbol
        ), selected AS (
          SELECT *,row_number() OVER(PARTITION BY trade_date ORDER BY rank,symbol) rn FROM ranked
        )
        SELECT s.trade_date signal_date,s.symbol,s.rank,n.trade_date entry_date,n.open entry_price,n.close exit_price,
               CASE WHEN n.open>0 THEN (n.close/n.open)-1 END return_pct
        FROM selected s JOIN LATERAL (
          SELECT trade_date,open,close FROM market.daily_bar b WHERE b.symbol=s.symbol AND b.trade_date>s.trade_date ORDER BY trade_date LIMIT 1
        ) n ON true WHERE s.rn<=:max_positions ORDER BY s.trade_date,s.rank"""),
          {"start": start_date, "end": end_date, "rank_max": rank_max, "max_positions": max_positions}).mappings().all()
        if candidates:
            conn.execute(text("INSERT INTO research.signal(run_id,trade_date,symbol,score,rank) VALUES (:run_id,:signal_date,:symbol,:score,:rank)"),
              [{"run_id": run_id, "signal_date": r["signal_date"], "symbol": r["symbol"], "score": Decimal(1) / Decimal(r["rank"]), "rank": r["rank"]} for r in candidates])
            conn.execute(text("""INSERT INTO research.backtest_trade(run_id,symbol,signal_date,entry_date,exit_date,quantity,entry_price,exit_price,pnl,return_pct,status)
              VALUES (:run_id,:symbol,:signal_date,:entry_date,:entry_date,1,:entry_price,:exit_price,:pnl,:return_pct,'closed')"""),
              [{**r, "run_id": run_id, "pnl": r["exit_price"] - r["entry_price"]} for r in candidates])
            daily: dict = {}
            for row in candidates:
                daily.setdefault(row["entry_date"], []).append(Decimal(row["return_pct"] or 0))
            equity = Decimal("1")
            peak = equity
            daily_rows = []
            for trade_date, returns in sorted(daily.items()):
                day_return = sum(returns) / Decimal(len(returns))
                equity *= Decimal("1") + day_return
                peak = max(peak, equity)
                daily_rows.append({"run_id": run_id, "date": trade_date, "equity": equity, "return": day_return, "drawdown": equity / peak - 1})
            conn.execute(text("INSERT INTO research.backtest_daily(run_id,trade_date,cash,market_value,equity,daily_return,drawdown) VALUES (:run_id,:date,0,:equity,:equity,:return,:drawdown)"), daily_rows)
            returns = [Decimal(r["return_pct"] or 0) for r in candidates]
            metrics = {"trade_count": len(returns), "win_rate": sum(r > 0 for r in returns) / len(returns), "average_return": sum(returns) / len(returns), "total_return": equity - 1, "max_drawdown": min(r["drawdown"] for r in daily_rows)}
            conn.execute(text("INSERT INTO research.performance_metric(run_id,key,value) VALUES (:run_id,:key,:value)"), [{"run_id": run_id, "key": k, "value": v} for k, v in metrics.items()])
        conn.execute(text("UPDATE research.strategy_run SET status='success',finished_at=:now WHERE id=:id"), {"id": run_id, "now": datetime.now(UTC)})
    return {"id": str(run_id), "status": "success", "trades": len(candidates), "reused": False}
