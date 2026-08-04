#!/usr/bin/env python3
"""Validate 52-week-high, price/volume and popularity hypotheses on local data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd
from scipy import stats
from sqlalchemy import text

from quant_platform.db import engine
from generate_popularity_trade_dashboard import PROJECT_ROOT, build_records


DEFAULT_TEMPLATE = PROJECT_ROOT / "scripts" / "factor_validation_dashboard.html"
DEFAULT_OUTPUT = PROJECT_ROOT / "apps" / "web" / "public" / "strategy-research" / "factor-validation.html"

PAPERS = [
    {
        "title": "The 52-Week High Momentum Strategy: Evidence in Chinese Stock Market",
        "year": "2022（样本1995—2018）",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6403338",
        "claim": "上交所A股的52周新高多空组合月均收益约0.28%。",
    },
    {
        "title": "The 52-Week High and Momentum Investing",
        "year": "2004",
        "url": "https://onlinelibrary.wiley.com/doi/full/10.1111/j.1540-6261.2004.00695.x",
        "claim": "经典研究：股价接近52周高点可解释相当部分动量收益。",
    },
    {
        "title": "Investor Behavior at the 52-Week High",
        "year": "2023",
        "url": "https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/investor-behavior-at-the-52week-high/5D1C7CA21396521F3B41D91B06A25BE1",
        "claim": "家庭投资者在52周高点附近增加交易，成交量与后续动量同时增强。",
    },
    {
        "title": "February, share turnover, and momentum in China",
        "year": "2023",
        "url": "https://www.sciencedirect.com/science/article/pii/S0927538X23002445",
        "claim": "中国市场的新高动量受春节月份反转与换手影响，排除二月后才更明显。",
    },
    {
        "title": "The Momentum Effect in China’s Stock Market",
        "year": "2023（样本2009—2022）",
        "url": "https://www.scirp.org/journal/paperinformation?paperid=128095",
        "claim": "给出相反证据：52周新高和传统动量未产生显著alpha。",
    },
]


MONTHLY_FEATURE_SQL = text("""WITH base AS (
  SELECT b.symbol,b.trade_date,b.open,b.close,b.amount*1000 amount_yuan,
    exp(sum(ln(1+b.pct_change/100.0)) OVER (
      PARTITION BY b.symbol ORDER BY b.trade_date
    )) adjusted_close
  FROM market.daily_bar b
  JOIN market.instrument i USING(symbol)
  WHERE b.trade_date BETWEEN :start AND :end
    AND b.symbol ~ '^(000|001|002|003|300|301|600|601|603|605|688|689)'
    AND upper(coalesce(i.name,'')) NOT LIKE '%ST%'
    AND b.pct_change>-99.99
), features AS (
  SELECT *,
    count(*) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) observations_120,
    max(adjusted_close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) high_120,
    count(*) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) observations_250,
    max(adjusted_close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) high_250,
    avg(amount_yuan) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) amount_5,
    avg(amount_yuan) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 24 PRECEDING AND 5 PRECEDING) prior_amount_20
  FROM base
), monthly AS (
  SELECT *,row_number() OVER (
    PARTITION BY symbol,date_trunc('month',trade_date) ORDER BY trade_date DESC
  ) month_row
  FROM features
)
SELECT * FROM monthly WHERE month_row=1 ORDER BY symbol,trade_date""")


def _time_series_summary(values: pd.Series) -> dict[str, Any]:
    clean = values.dropna().astype(float)
    test = stats.ttest_1samp(clean, 0) if len(clean) > 1 else None
    return {
        "months": len(clean),
        "average_pct": clean.mean() * 100 if len(clean) else None,
        "median_pct": clean.median() * 100 if len(clean) else None,
        "positive_months": int((clean > 0).sum()),
        "p_value": float(test.pvalue) if test is not None else None,
    }


def _portfolio_study(frame: pd.DataFrame, window: int, scope: str, tail: float) -> dict[str, Any]:
    subset = frame[(frame[f"observations_{window}"] >= window) & frame["forward_1m"].notna()].copy()
    if scope == "sse":
        subset = subset[subset["symbol"].str.startswith(("600", "601", "603", "605", "688", "689"))]
    monthly = []
    for month, group in subset.groupby("month"):
        if len(group) < 100:
            continue
        lower, upper = group[f"ratio_{window}"].quantile([tail, 1 - tail])
        winners = group[group[f"ratio_{window}"] >= upper]
        losers = group[group[f"ratio_{window}"] <= lower]
        high_volume = winners[winners["volume_ratio"] >= 1.5]
        low_volume = winners[winners["volume_ratio"] < 1.5]
        bull = winners[winners["bull_candle"]]
        bear = winners[~winners["bull_candle"]]
        monthly.append({
            "month": month,
            "eligible": len(group),
            "winner_count": len(winners),
            "winner_pct": winners["forward_1m"].mean() * 100,
            "loser_pct": losers["forward_1m"].mean() * 100,
            "spread_pct": (winners["forward_1m"].mean() - losers["forward_1m"].mean()) * 100,
            "high_volume_pct": high_volume["forward_1m"].mean() * 100,
            "low_volume_pct": low_volume["forward_1m"].mean() * 100,
            "bull_pct": bull["forward_1m"].mean() * 100,
            "bear_pct": bear["forward_1m"].mean() * 100,
            "high_volume_count": len(high_volume),
            "bull_count": len(bull),
        })
    result = pd.DataFrame(monthly)
    if result.empty:
        return {"period": [], "monthly": []}
    return {
        "window": window,
        "scope": scope,
        "tail_pct": tail * 100,
        "period": [result["month"].min(), result["month"].max()],
        "winner": _time_series_summary(result["winner_pct"] / 100),
        "loser": _time_series_summary(result["loser_pct"] / 100),
        "spread": _time_series_summary(result["spread_pct"] / 100),
        "high_volume": _time_series_summary(result["high_volume_pct"] / 100),
        "low_volume": _time_series_summary(result["low_volume_pct"] / 100),
        "bull": _time_series_summary(result["bull_pct"] / 100),
        "bear": _time_series_summary(result["bear_pct"] / 100),
        "monthly": monthly,
    }


def market_validation(start: str, end: str) -> dict[str, Any]:
    with engine.connect() as conn:
        frame = pd.read_sql(MONTHLY_FEATURE_SQL, conn, params={"start": start, "end": end})
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["month"] = frame["trade_date"].dt.strftime("%Y-%m")
    frame["forward_1m"] = frame.groupby("symbol")["adjusted_close"].shift(-1) / frame["adjusted_close"] - 1
    frame["volume_ratio"] = frame["amount_5"] / frame["prior_amount_20"]
    frame["bull_candle"] = frame["close"] > frame["open"]
    for window in (120, 250):
        frame[f"ratio_{window}"] = frame["adjusted_close"] / frame[f"high_{window}"]
    studies = {}
    for window in (120, 250):
        for scope in ("all", "sse"):
            for tail in (0.1, 0.3):
                studies[f"{window}_{scope}_{int(tail * 100)}"] = _portfolio_study(
                    frame, window, scope, tail,
                )
    return {
        "data_range": [frame["trade_date"].min().date().isoformat(), frame["trade_date"].max().date().isoformat()],
        "monthly_stock_rows": len(frame),
        "studies": studies,
    }


def _event_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [row["rule_return_pct"] for row in records if row.get("rule_return_pct") is not None]
    result = {
        "records": len(records),
        "average_pct": mean(returns) if returns else None,
        "median_pct": median(returns) if returns else None,
        "win_rate_pct": sum(value > 0 for value in returns) / len(returns) * 100 if returns else None,
    }
    for offset in (2, 3, 5):
        values = [
            row["horizon"][str(offset)]["from_entry_pct"]
            for row in records if str(offset) in row.get("horizon", {})
        ]
        result[f"t{offset}_average_pct"] = mean(values) if values else None
    return result


def popularity_validation(start: str, end: str, min_adv20: float) -> dict[str, Any]:
    drop2, meta2 = build_records(start, end, min_adv20, 0.02, "new")
    drop7, meta7 = build_records(start, end, min_adv20, 0.07, "new")

    def factor(row: dict[str, Any]) -> dict[str, Any] | None:
        return row.get("high_factors", {}).get("120")

    available = [row for row in drop2 if factor(row)]
    close_break = [row for row in available if factor(row)["close_breakout"]]
    near_high = [row for row in available if factor(row)["distance_pct"] >= -2]
    def is_core(row: dict[str, Any]) -> bool:
        return bool(
            row.get("dc_new_top10")
            and row.get("dc_rank") is not None
            and row["dc_rank"] <= 5
            and row.get("dc_absent_days", 0) >= 10
        ) or bool(
            row.get("ths_new_top10")
            and row.get("ths_rank") is not None
            and row["ths_rank"] <= 5
            and row.get("ths_absent_days", 0) >= 10
        )

    core = [row for row in drop2 if is_core(row)]
    core_available = [row for row in core if factor(row)]
    core_near_high = [row for row in core_available if factor(row)["distance_pct"] >= -2]
    core_drop7 = [row for row in drop7 if is_core(row)]
    high_volume = [row for row in near_high if row.get("entry_amount_vs_adv20", 0) >= 1.5]
    low_volume = [row for row in near_high if row.get("entry_amount_vs_adv20", 0) < 1.5]
    signal_bull = [
        row for row in near_high
        if next((bar for bar in row.get("kline", []) if bar["offset"] == 0), {}).get("close", 0)
        > next((bar for bar in row.get("kline", []) if bar["offset"] == 0), {}).get("open", float("inf"))
    ]
    return {
        "audit_drop2": meta2["audit"],
        "audit_drop7": meta7["audit"],
        "groups": {
            "new_top10_drop2": _event_summary(drop2),
            "new_top10_drop7": _event_summary(drop7),
            "high_available": _event_summary(available),
            "close_break_120": _event_summary(close_break),
            "near_high_120": _event_summary(near_high),
            "core": _event_summary(core_available),
            "core_near_high_120": _event_summary(core_near_high),
            "core_drop7": _event_summary(core_drop7),
            "near_high_high_volume": _event_summary(high_volume),
            "near_high_low_volume": _event_summary(low_volume),
            "near_high_signal_bull": _event_summary(signal_bull),
        },
    }


def render(payload: dict[str, Any], template_path: Path, output: Path) -> None:
    template = template_path.read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__VALIDATION_DATA__", data), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成人气、新高和价量因子复验页面")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--min-adv20", type=float, default=1_000_000_000)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = {
        "generated_for": args.end,
        "papers": PAPERS,
        "market": market_validation(args.start, args.end),
        "popularity": popularity_validation(args.start, args.end, args.min_adv20),
    }
    render(payload, args.template, args.output)
    print(json.dumps({"output": str(args.output), "generated_for": args.end}, ensure_ascii=False))


if __name__ == "__main__":
    main()
