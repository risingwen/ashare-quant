from __future__ import annotations

import json
import uuid
from decimal import Decimal

from sqlalchemy import text

from .db import engine
from .research.engine import Bar, DailyEngine, PortfolioState, Position, Signal


def initialize(name: str, cash: Decimal = Decimal("1000000")) -> dict:
    portfolio_id = uuid.uuid4()
    with engine.begin() as conn:
        existing = conn.execute(text("SELECT id FROM portfolio.portfolio WHERE active ORDER BY created_at LIMIT 1")).scalar()
        if existing:
            return {"id": str(existing), "reused": True}
        conn.execute(text("""INSERT INTO portfolio.portfolio(id,name,initial_cash,cash,strategy_template_key,parameters)
          VALUES (:id,:name,:cash,:cash,'popularity_breakout',CAST(:params AS jsonb))"""),
          {"id": portfolio_id, "name": name, "cash": cash, "params": json.dumps({"rank_max": 10, "max_positions": 10})})
    return {"id": str(portfolio_id), "reused": False}


def advance(trade_date: str) -> dict:
    sim = DailyEngine()
    with engine.begin() as conn:
        portfolio = conn.execute(text("SELECT * FROM portfolio.portfolio WHERE active ORDER BY created_at LIMIT 1")).mappings().first()
        if not portfolio:
            raise RuntimeError("initialize portfolio first")
        positions = conn.execute(text("SELECT * FROM portfolio.position WHERE portfolio_id=:id"), {"id": portfolio["id"]}).mappings().all()
        state = PortfolioState(Decimal(portfolio["cash"]), {r["symbol"]: Position(r["symbol"], Decimal(r["quantity"]), Decimal(r["average_cost"])) for r in positions})
        signal_date = conn.execute(text("SELECT max(trade_date) FROM research.signal WHERE trade_date<:date"), {"date": trade_date}).scalar()
        if not signal_date:
            return {"status": "empty", "fills": 0}
        signal_rows = conn.execute(text("SELECT symbol,score FROM research.signal WHERE trade_date=:date ORDER BY rank LIMIT 10"), {"date": signal_date}).mappings().all()
        bars_rows = conn.execute(text("""SELECT b.*,lag(close) OVER(PARTITION BY symbol ORDER BY trade_date) previous_close FROM market.daily_bar b
          WHERE symbol=ANY(:symbols) AND trade_date<=:date ORDER BY trade_date DESC"""), {"symbols": [r["symbol"] for r in signal_rows], "date": trade_date}).mappings().all()
        latest = {}
        for r in bars_rows:
            if r["trade_date"].isoformat() == trade_date and r["symbol"] not in latest:
                latest[r["symbol"]] = Bar(r["symbol"], trade_date, Decimal(r["open"]), Decimal(r["high"]), Decimal(r["low"]), Decimal(r["close"]), Decimal(r["previous_close"] or r["open"]))
        fills = sim.buy_equal_weight(state, latest, [Signal(r["symbol"], str(signal_date), Decimal(r["score"] or 0)) for r in signal_rows])
        for fill in fills:
            order_id = uuid.uuid4()
            conn.execute(text("INSERT INTO portfolio.\"order\"(id,portfolio_id,symbol,signal_date,scheduled_date,side,quantity,status) VALUES (:id,:portfolio,:symbol,:signal_date,:date,'buy',:quantity,'filled')"), {"id": order_id, "portfolio": portfolio["id"], "signal_date": signal_date, "date": trade_date, **fill})
            conn.execute(text("INSERT INTO portfolio.fill(order_id,trade_date,price,quantity,fees) VALUES (:id,:date,:price,:quantity,:fees)"), {"id": order_id, "date": trade_date, **fill})
        for position in state.positions.values():
            conn.execute(text("""INSERT INTO portfolio.position(portfolio_id,symbol,quantity,average_cost) VALUES (:id,:symbol,:quantity,:cost)
              ON CONFLICT(portfolio_id,symbol) DO UPDATE SET quantity=excluded.quantity,average_cost=excluded.average_cost,updated_at=now()"""), {"id": portfolio["id"], "symbol": position.symbol, "quantity": position.quantity, "cost": position.cost})
        market_value = sum(position.quantity * latest[position.symbol].close for position in state.positions.values() if position.symbol in latest)
        equity = state.cash + market_value
        conn.execute(text("UPDATE portfolio.portfolio SET cash=:cash WHERE id=:id"), {"cash": state.cash, "id": portfolio["id"]})
        conn.execute(text("""INSERT INTO portfolio.valuation(portfolio_id,trade_date,cash,market_value,equity)
          VALUES (:id,:date,:cash,:mv,:equity) ON CONFLICT(portfolio_id,trade_date) DO UPDATE SET cash=excluded.cash,market_value=excluded.market_value,equity=excluded.equity"""), {"id": portfolio["id"], "date": trade_date, "cash": state.cash, "mv": market_value, "equity": equity})
    return {"status": "success", "fills": len(fills), "equity": str(equity)}
