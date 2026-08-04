#!/usr/bin/env python3
"""Build the standalone strategy-review pages used by the web application."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from statistics import mean

from sqlalchemy import text

from quant_platform.db import engine
from generate_popularity_trade_dashboard import (
    DEFAULT_TEMPLATE,
    PROJECT_ROOT,
    build_records,
    render_html,
    write_csv,
)


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "apps" / "web" / "public" / "strategy-research"


PAGES = {
    "popularity-top10-drop2.html": {
        "scope": "all",
        "discount": 0.02,
        "title": "人气前十 · T+1 跌2%成交档案",
        "description": "T日收盘位于东方财富或同花顺最终榜前十，T+1相对昨收跌2%入场；逐笔查看成交时间、价量、K线和后续人气。",
        "defaults": {"absentMin": 0},
    },
    "popularity-top10-drop7.html": {
        "scope": "all",
        "discount": 0.07,
        "title": "人气前十 · T+1 跌7%成交档案",
        "description": "与跌2%策略使用完全相同的信号、流动性、成本和卖出规则，只把T+1触发价改为昨收下方7%。",
        "defaults": {"absentMin": 0},
    },
    "popularity-new-top10.html": {
        "scope": "new",
        "discount": 0.02,
        "title": "首次进入前十 · T+1 跌2%成交档案",
        "description": "T日收盘首次进入任一最终榜前十，T+1相对昨收跌2%入场；后续人气、收益与K线只用于复盘。",
        "defaults": {"absentMin": 1},
    },
    "popularity-core-drop2.html": {
        "scope": "new",
        "discount": 0.02,
        "title": "核心人气 · 首次前五且榜外至少10日",
        "description": "当前优先条件：首次进入前五、此前至少10个完整交易日未进前十，T+1跌2%入场。",
        "defaults": {"rankMax": 5, "absentMin": 10},
    },
    "popularity-core-new-high.html": {
        "scope": "new",
        "discount": 0.02,
        "title": "核心人气 × 接近120日前高",
        "description": "核心人气条件叠加T日距离此前120日最高价不低于−2%，用于验证新高是否改善后续延续。",
        "defaults": {"rankMax": 5, "absentMin": 10, "highWindow": 120, "highState": "near2"},
    },
    "popularity-core-drop7.html": {
        "scope": "new",
        "discount": 0.07,
        "title": "核心人气 · T+1 跌7%深度回撤",
        "description": "首次进入前五且此前至少10日未进前十，只有T+1跌至昨收下方7%才成交；重点观察深跌后的延续风险。",
        "defaults": {"rankMax": 5, "absentMin": 10},
    },
}


def _latest_market_date() -> str:
    with engine.connect() as conn:
        latest = conn.execute(text("SELECT max(trade_date) FROM market.daily_bar")).scalar_one()
    if latest is None:
        raise RuntimeError("market.daily_bar is empty")
    return latest.isoformat()


def build_pages(start: str, end: str, min_adv20: float, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = {}
    generated = []
    for filename, page in PAGES.items():
        key = (page["scope"], page["discount"])
        if key not in cache:
            cache[key] = build_records(start, end, min_adv20, page["discount"], page["scope"])
        records, metadata = cache[key]
        page_metadata = deepcopy(metadata)
        presentation = {
            "title": page["title"],
            "description": page["description"],
            "defaults": page["defaults"],
        }
        output = output_dir / filename
        render_html(records, page_metadata, DEFAULT_TEMPLATE, output, presentation)
        write_csv(records, output.with_suffix(".csv"))
        completed = [row["rule_return_pct"] for row in records if row.get("rule_return_pct") is not None]
        generated.append({
            "file": filename,
            "scope": page["scope"],
            "discount_pct": page["discount"] * 100,
            "records": len(records),
            "average_rule_return_pct": mean(completed) if completed else None,
        })
    return {"start": start, "end": end, "generated": generated}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成全部人气策略复盘页面")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="latest", help="YYYY-MM-DD 或 latest")
    parser.add_argument("--min-adv20", type=float, default=1_000_000_000)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    end = _latest_market_date() if args.end == "latest" else args.end
    print(json.dumps(build_pages(args.start, end, args.min_adv20, args.output_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
