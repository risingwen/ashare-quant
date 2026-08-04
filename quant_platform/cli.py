from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from datetime import date
from decimal import Decimal

from .migrate import apply_schema, import_legacy_popularity, import_sqlite
from .providers.replay import ReplayProvider
from .ingest import (
    ingest_adj_factors,
    ingest_broker_recommendations,
    ingest_daily_basic,
    ingest_daily_market,
    ingest_hot_money_detail,
    ingest_hot_money_directory,
    ingest_institutional_surveys,
    ingest_lhb,
    ingest_limit_events,
    ingest_limit_steps,
    ingest_moneyflow,
    ingest_popularity,
    refresh_market_breadth,
    refresh_popularity_view,
)
from .intraday import (
    ingest_intraday_popularity,
    ingest_minute_bars,
    ingest_price_limits,
    ingest_trade_calendar,
    hot_symbols,
    minute_candidates,
    open_dates,
    save_progress,
    throttle,
)
from .research.runner import run_popularity_breakout
from .research.minute_analysis import run_minute_popularity_analysis
from .portfolio import advance, initialize


def main() -> None:
    parser = argparse.ArgumentParser(prog="quant")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    load = commands.add_parser("migrate-sqlite")
    load.add_argument("--source", type=Path, default=Path("data/quant.db"))
    load_popularity = commands.add_parser("migrate-popularity")
    load_popularity.add_argument("--source", type=Path, default=Path("data/quant.db"))
    replay = commands.add_parser("probe-replay")
    replay.add_argument("--date", required=True)
    ingest = commands.add_parser("ingest-popularity")
    ingest.add_argument("--date", required=True)
    popularity_backfill = commands.add_parser("backfill-popularity")
    popularity_backfill.add_argument("--start", default="2025-01-01")
    popularity_backfill.add_argument("--end", default=date.today().isoformat())
    popularity_backfill.add_argument("--sleep", type=float, default=0.15, help="Keep sustained rate below the 500 requests/minute allowance")
    popularity_backfill.add_argument("--force", action="store_true")
    strategy = commands.add_parser("run-strategy")
    strategy.add_argument("--start", required=True)
    strategy.add_argument("--end", required=True)
    strategy.add_argument("--rank-max", type=int, default=10)
    strategy.add_argument("--max-positions", type=int, default=10)
    minute_analysis = commands.add_parser("analyze-minute-popularity")
    minute_analysis.add_argument("--start", required=True)
    minute_analysis.add_argument("--end", required=True)
    minute_analysis.add_argument("--rank-max", type=int, default=10)
    minute_analysis.add_argument("--max-positions", type=int, default=10)
    minute_analysis.add_argument("--min-adv20", type=float, default=1_000_000_000)
    minute_analysis.add_argument("--buy-cost", type=float, default=0.0007)
    minute_analysis.add_argument("--sell-cost", type=float, default=0.0012)
    init_portfolio = commands.add_parser("init-portfolio")
    init_portfolio.add_argument("--name", default="官方模拟组合")
    init_portfolio.add_argument("--cash", type=Decimal, default=Decimal("1000000"))
    advance_portfolio = commands.add_parser("advance-portfolio")
    advance_portfolio.add_argument("--date", required=True)
    daily = commands.add_parser("daily")
    daily.add_argument("--date", default="today")
    flow_sync = commands.add_parser("sync-moneyflow")
    flow_sync.add_argument("--date", default="latest-market")
    sentiment_sync = commands.add_parser("sync-sentiment")
    sentiment_sync.add_argument("--date", default="latest-market")
    popularity_sync = commands.add_parser("sync-popularity")
    popularity_sync.add_argument("--date", default="latest-market")
    intelligence_sync = commands.add_parser("sync-market-intelligence")
    intelligence_sync.add_argument("--date", default="latest-market")
    intelligence_sync.add_argument("--survey-start", help="Defaults to the selected market date")
    intelligence_sync.add_argument("--month", help="Broker recommendation month in YYYYMM")
    backfill = commands.add_parser("backfill-two-years")
    backfill.add_argument("--start", default="2025-01-01")
    backfill.add_argument("--end", default=date.today().isoformat())
    backfill.add_argument("--sleep", type=float, default=0.6, help="Keep sustained rate at or below 100 requests/minute")
    backfill.add_argument("--workers", type=int, default=1, help="Parallel datasets per date; keep request rate below provider allowance")
    backfill.add_argument("--force", action="store_true")
    backfill.add_argument("--no-finalize", action="store_true")
    flow_backfill = commands.add_parser("backfill-moneyflow")
    flow_backfill.add_argument("--start", default="2025-01-01")
    flow_backfill.add_argument("--end", default=date.today().isoformat())
    flow_backfill.add_argument("--sleep", type=float, default=0.6)
    flow_backfill.add_argument("--workers", type=int, default=1)
    flow_backfill.add_argument("--force", action="store_true")
    sentiment_backfill = commands.add_parser("backfill-sentiment")
    sentiment_backfill.add_argument("--start", default="2024-01-01")
    sentiment_backfill.add_argument("--end", default=date.today().isoformat())
    sentiment_backfill.add_argument("--sleep", type=float, default=0.6)
    sentiment_backfill.add_argument("--workers", type=int, default=1)
    sentiment_backfill.add_argument("--force", action="store_true")
    intelligence_backfill = commands.add_parser("backfill-market-intelligence")
    intelligence_backfill.add_argument("--start", default="2025-01-01")
    intelligence_backfill.add_argument("--end", default=date.today().isoformat())
    intelligence_backfill.add_argument("--sleep", type=float, default=0.15)
    intelligence_backfill.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel trade dates; capped at 4 and globally throttled below the provider allowance",
    )
    intelligence_backfill.add_argument("--force", action="store_true")
    intraday_backfill = commands.add_parser("backfill-intraday-popularity")
    intraday_backfill.add_argument("--start", default="2025-01-01")
    intraday_backfill.add_argument("--end", default=date.today().isoformat())
    intraday_backfill.add_argument("--sleep", type=float, default=0.15)
    intraday_backfill.add_argument("--force", action="store_true")
    minute_backfill = commands.add_parser("backfill-hot-minutes")
    minute_backfill.add_argument("--start", default="2025-01-01")
    minute_backfill.add_argument("--end", default=date.today().isoformat())
    minute_backfill.add_argument("--rank-max", type=int, default=10)
    minute_backfill.add_argument("--freq", default="1min", choices=("1min", "5min", "15min", "30min", "60min"))
    minute_backfill.add_argument("--sleep", type=float, default=0.15)
    minute_backfill.add_argument("--workers", type=int, default=4)
    minute_backfill.add_argument("--force", action="store_true")
    minute_backfill.add_argument("--limit", type=int, help="Process only the first N candidate stock-days")
    limit_backfill = commands.add_parser("backfill-hot-limits")
    limit_backfill.add_argument("--start", default="2025-01-01")
    limit_backfill.add_argument("--end", default=date.today().isoformat())
    limit_backfill.add_argument("--rank-max", type=int, default=10)
    limit_backfill.add_argument("--sleep", type=float, default=0.15)
    limit_backfill.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "migrate":
        apply_schema()
    elif args.command == "migrate-sqlite":
        print(json.dumps(import_sqlite(args.source), ensure_ascii=False))
    elif args.command == "migrate-popularity":
        print(json.dumps(import_legacy_popularity(args.source), ensure_ascii=False))
    elif args.command == "probe-replay":
        provider = ReplayProvider()
        probe_date = date.today().isoformat() if args.date == "today" else args.date
        for endpoint in ("dc_hot", "ths_hot"):
            result = provider.fetch_popularity(endpoint, probe_date)
            print(endpoint, result.status, len(result.rows), result.error_code)
    elif args.command == "ingest-popularity":
        ingest_date = date.today().isoformat() if args.date == "today" else args.date
        provider = ReplayProvider()
        output = [ingest_popularity(provider, endpoint, ingest_date) for endpoint in ("dc_hot", "ths_hot")]
        if any(item["status"] == "success" for item in output):
            refresh_popularity_view()
        print(json.dumps(output, ensure_ascii=False, default=str))
    elif args.command == "run-strategy":
        print(json.dumps(run_popularity_breakout(args.start, args.end, args.rank_max, args.max_positions), ensure_ascii=False))
    elif args.command == "analyze-minute-popularity":
        print(json.dumps(run_minute_popularity_analysis(
            args.start,
            args.end,
            args.rank_max,
            args.max_positions,
            args.min_adv20,
            args.buy_cost,
            args.sell_cost,
        ), ensure_ascii=False, default=str))
    elif args.command == "init-portfolio":
        print(json.dumps(initialize(args.name, args.cash), ensure_ascii=False))
    elif args.command == "advance-portfolio":
        print(json.dumps(advance(args.date), ensure_ascii=False))
    elif args.command == "daily":
        run_date = date.today().isoformat() if args.date == "today" else args.date
        provider = ReplayProvider()
        daily_result = ingest_daily_market(provider, run_date)
        popularity_results = [ingest_popularity(provider, endpoint, run_date) for endpoint in ("dc_hot", "ths_hot")]
        lhb_results = [ingest_lhb(provider, endpoint, run_date) for endpoint in ("top_list", "top_inst")]
        moneyflow_results = [ingest_moneyflow(provider, endpoint, run_date) for endpoint in ("moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc")]
        sentiment_results = [
            ingest_daily_basic(provider, run_date),
            ingest_adj_factors(provider, run_date),
            ingest_limit_events(provider, run_date),
            ingest_limit_steps(provider, run_date),
        ]
        breadth_result = refresh_market_breadth(run_date)
        if any(item["status"] == "success" for item in popularity_results):
            refresh_popularity_view()
        strategy_result = run_popularity_breakout(f"{int(run_date[:4]) - 1}{run_date[4:]}", run_date)
        portfolio_result = advance(run_date)
        print(json.dumps({"daily": daily_result, "popularity": popularity_results, "lhb": lhb_results,
                          "moneyflow": moneyflow_results, "sentiment": sentiment_results,
                          "market_breadth": breadth_result, "strategy": strategy_result,
                          "portfolio": portfolio_result}, ensure_ascii=False, default=str))
    elif args.command == "sync-sentiment":
        from sqlalchemy import text
        from .db import engine
        if args.date == "latest-market":
            with engine.connect() as conn:
                latest_market = conn.execute(text("SELECT max(trade_date) FROM market.daily_bar")).scalar_one()
            if latest_market is None:
                raise SystemExit("daily_bar is empty; cannot resolve latest market date")
            run_date = latest_market.isoformat()
        else:
            run_date = date.today().isoformat() if args.date == "today" else args.date
        job_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ops.job_run(id,job_name,status,details)
              VALUES (:id,'sentiment_sync','running',CAST(:details AS jsonb))"""), {
                "id": job_id, "details": json.dumps({"trade_date": run_date}),
            })
        try:
            provider = ReplayProvider()
            outputs = [
                ingest_daily_basic(provider, run_date),
                ingest_adj_factors(provider, run_date),
                ingest_limit_events(provider, run_date),
                ingest_limit_steps(provider, run_date),
            ]
            failures = [item for item in outputs if item["status"] not in {"success", "empty"}]
            breadth = refresh_market_breadth(run_date)
            if breadth["status"] != "success":
                failures.append({"endpoint": "market_breadth", "status": breadth["status"]})
            status = "failed" if failures else "success"
            details = {"trade_date": run_date, "datasets": outputs, "market_breadth": breadth}
            with engine.begin() as conn:
                conn.execute(text("""UPDATE ops.job_run SET status=:status,finished_at=now(),
                  details=CAST(:details AS jsonb),error=:error WHERE id=:id"""), {
                    "id": job_id, "status": status, "details": json.dumps(details),
                    "error": None if not failures else ", ".join(
                        f"{item['endpoint']}={item['status']}" for item in failures
                    ),
                })
            print(json.dumps({"job_id": str(job_id), "status": status, **details}, ensure_ascii=False, default=str))
            if failures:
                raise SystemExit(2)
        except SystemExit:
            raise
        except Exception as exc:
            with engine.begin() as conn:
                conn.execute(text("""UPDATE ops.job_run SET status='failed',finished_at=now(),error=:error
                  WHERE id=:id"""), {"id": job_id, "error": str(exc)[:2000]})
            raise
    elif args.command == "sync-popularity":
        from sqlalchemy import text
        from .db import engine
        if args.date == "latest-market":
            with engine.connect() as conn:
                latest_market = conn.execute(text("SELECT max(trade_date) FROM market.daily_bar")).scalar_one()
            if latest_market is None:
                raise SystemExit("daily_bar is empty; cannot resolve latest market date")
            run_date = latest_market.isoformat()
        else:
            run_date = date.today().isoformat() if args.date == "today" else args.date
        job_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO ops.job_run(id,job_name,status,details) VALUES (:id,'popularity_sync','running',CAST(:details AS jsonb))"),
                         {"id": job_id, "details": json.dumps({"trade_date": run_date})})
        try:
            provider = ReplayProvider()
            outputs = [ingest_popularity(provider, endpoint, run_date) for endpoint in ("dc_hot", "ths_hot")]
            failures = [item for item in outputs if item["status"] != "success"]
            if not failures:
                refresh_popularity_view()
            status = "failed" if failures else "success"
            details = {"trade_date": run_date, "datasets": outputs}
            with engine.begin() as conn:
                conn.execute(text("UPDATE ops.job_run SET status=:status,finished_at=now(),details=CAST(:details AS jsonb),error=:error WHERE id=:id"),
                             {"id": job_id, "status": status, "details": json.dumps(details),
                              "error": None if not failures else ", ".join(f"{item['endpoint']}={item['status']}" for item in failures)})
            print(json.dumps({"job_id": str(job_id), "status": status, **details}, ensure_ascii=False, default=str))
            if failures:
                raise SystemExit(2)
        except SystemExit:
            raise
        except Exception as exc:
            with engine.begin() as conn:
                conn.execute(text("UPDATE ops.job_run SET status='failed',finished_at=now(),error=:error WHERE id=:id"),
                             {"id": job_id, "error": str(exc)[:2000]})
            raise
    elif args.command == "sync-market-intelligence":
        from sqlalchemy import text
        from .db import engine
        if args.date == "latest-market":
            with engine.connect() as conn:
                latest_market = conn.execute(text("SELECT max(trade_date) FROM market.daily_bar")).scalar_one()
            if latest_market is None:
                raise SystemExit("daily_bar is empty; cannot resolve latest market date")
            run_date = latest_market.isoformat()
        else:
            run_date = date.today().isoformat() if args.date == "today" else args.date
        survey_start = args.survey_start or run_date
        month = args.month or run_date[:7].replace("-", "")
        job_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO ops.job_run(id,job_name,status,details)
              VALUES (:id,'market_intelligence_sync','running',CAST(:details AS jsonb))"""), {
                "id": job_id,
                "details": json.dumps({"trade_date": run_date, "survey_start": survey_start, "month": month}),
            })
        try:
            provider = ReplayProvider()
            outputs = [
                ingest_hot_money_directory(provider),
                ingest_hot_money_detail(provider, run_date),
                ingest_institutional_surveys(provider, survey_start, run_date),
                ingest_broker_recommendations(provider, month),
            ]
            failures = [item for item in outputs if item["status"] not in {"success", "empty"}]
            status = "failed" if failures else "success"
            details = {"trade_date": run_date, "survey_start": survey_start, "month": month, "datasets": outputs}
            with engine.begin() as conn:
                conn.execute(text("""UPDATE ops.job_run SET status=:status,finished_at=now(),
                  details=CAST(:details AS jsonb),error=:error WHERE id=:id"""), {
                    "id": job_id, "status": status, "details": json.dumps(details),
                    "error": None if not failures else ", ".join(
                        f"{item['endpoint']}={item['status']}" for item in failures
                    ),
                })
            print(json.dumps({"job_id": str(job_id), "status": status, **details}, ensure_ascii=False, default=str))
            if failures:
                raise SystemExit(2)
        except SystemExit:
            raise
        except Exception as exc:
            with engine.begin() as conn:
                conn.execute(text("""UPDATE ops.job_run SET status='failed',finished_at=now(),error=:error
                  WHERE id=:id"""), {"id": job_id, "error": str(exc)[:2000]})
            raise
    elif args.command == "sync-moneyflow":
        from sqlalchemy import text
        from .db import engine
        if args.date == "latest-market":
            with engine.connect() as conn:
                latest_market = conn.execute(text("SELECT max(trade_date) FROM market.daily_bar")).scalar_one()
            if latest_market is None:
                raise SystemExit("daily_bar is empty; cannot resolve latest market date")
            run_date = latest_market.isoformat()
        else:
            run_date = date.today().isoformat() if args.date == "today" else args.date
        job_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO ops.job_run(id,job_name,status,details) VALUES (:id,'moneyflow_sync','running',CAST(:details AS jsonb))"),
                         {"id": job_id, "details": json.dumps({"trade_date": run_date})})
        try:
            provider = ReplayProvider()
            outputs = [ingest_moneyflow(provider, endpoint, run_date) for endpoint in ("moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc")]
            failures = [item for item in outputs if item["status"] != "success"]
            status = "failed" if failures else "success"
            details = {"trade_date": run_date, "datasets": outputs}
            with engine.begin() as conn:
                conn.execute(text("UPDATE ops.job_run SET status=:status,finished_at=now(),details=CAST(:details AS jsonb),error=:error WHERE id=:id"),
                             {"id": job_id, "status": status, "details": json.dumps(details),
                              "error": None if not failures else ", ".join(f"{item['endpoint']}={item['status']}" for item in failures)})
            print(json.dumps({"job_id": str(job_id), "status": status, **details}, ensure_ascii=False, default=str))
            if failures:
                raise SystemExit(2)
        except SystemExit:
            raise
        except Exception as exc:
            with engine.begin() as conn:
                conn.execute(text("UPDATE ops.job_run SET status='failed',finished_at=now(),error=:error WHERE id=:id"),
                             {"id": job_id, "error": str(exc)[:2000]})
            raise
    elif args.command == "backfill-popularity":
        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        with engine.connect() as conn:
            dates = [row[0].isoformat() for row in conn.execute(text("""SELECT trade_date FROM (
                SELECT trade_date FROM market.trade_calendar WHERE is_open AND trade_date BETWEEN :start AND :end
                UNION SELECT DISTINCT trade_date FROM market.daily_bar WHERE trade_date BETWEEN :start AND :end
              ) dates ORDER BY trade_date"""), {"start": args.start, "end": args.end})]
            done = set() if args.force else {(row[0], row[1].isoformat()) for row in conn.execute(text("""
              SELECT dataset,trade_date FROM ops.backfill_progress
              WHERE dataset IN ('dc_hot','ths_hot') AND status IN ('success','unavailable')
              UNION
              SELECT endpoint,trade_date FROM popularity.snapshot
              WHERE endpoint IN ('dc_hot','ths_hot') AND status='success'
            """))}
        failures = 0
        changed = False
        for index, run_date in enumerate(dates, 1):
            outputs = {}
            for dataset in ("dc_hot", "ths_hot"):
                if (dataset, run_date) in done:
                    continue
                try:
                    output = ingest_popularity(provider, dataset, run_date)
                    status, error = output["status"], None
                except Exception as exc:
                    output = {"status": "failed", "rows": 0}
                    status, error = "failed", str(exc)[:1000]
                outputs[dataset] = output
                changed = changed or status == "success"
                failures += int(status not in {"success", "unavailable"})
                with engine.begin() as conn:
                    conn.execute(text("""INSERT INTO ops.backfill_progress(dataset,trade_date,status,row_count,attempts,error)
                      VALUES (:dataset,:date,:status,:rows,1,:error) ON CONFLICT(dataset,trade_date) DO UPDATE
                      SET status=excluded.status,row_count=excluded.row_count,attempts=ops.backfill_progress.attempts+1,
                          error=excluded.error,updated_at=now()"""),
                      {"dataset": dataset, "date": run_date, "status": status, "rows": output.get("rows", 0), "error": error})
                time.sleep(args.sleep)
            if outputs:
                print(json.dumps({"progress": f"{index}/{len(dates)}", "date": run_date, "results": outputs}, ensure_ascii=False), flush=True)
        if changed:
            refresh_popularity_view()
        if failures:
            raise SystemExit(2)
    elif args.command == "backfill-moneyflow":
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        with engine.connect() as conn:
            dates = [row[0].isoformat() for row in conn.execute(text("""SELECT trade_date FROM (
                SELECT trade_date FROM market.trade_calendar WHERE is_open AND trade_date BETWEEN :start AND :end
                UNION SELECT DISTINCT trade_date FROM market.daily_bar WHERE trade_date BETWEEN :start AND :end
              ) dates ORDER BY trade_date"""), {"start": args.start, "end": args.end})]
            done = set() if args.force else {(row[0], row[1].isoformat()) for row in conn.execute(text("SELECT dataset,trade_date FROM ops.backfill_progress WHERE dataset IN ('moneyflow_dc','moneyflow_ind_dc') AND status='success'"))}
        failures = 0
        for index, run_date in enumerate(dates, 1):
            outputs = {}
            pending = [dataset for dataset in ("moneyflow_dc", "moneyflow_ind_dc")
                       if (dataset, run_date) not in done]

            def execute_flow(dataset: str) -> tuple[str, dict, str, str | None]:
                task_provider = provider if args.workers <= 1 else ReplayProvider()
                try:
                    output = ingest_moneyflow(task_provider, dataset, run_date)
                    status, error = output["status"], None
                except Exception as exc:
                    output = {"status": "failed", "rows": 0}
                    status, error = "failed", str(exc)[:1000]
                time.sleep(args.sleep)
                return dataset, output, status, error

            if args.workers <= 1:
                task_results = [execute_flow(dataset) for dataset in pending]
            else:
                with ThreadPoolExecutor(max_workers=min(max(args.workers, 1), 2)) as executor:
                    task_results = list(executor.map(execute_flow, pending))
            for dataset, output, status, error in task_results:
                outputs[dataset] = output
                failures += int(status != "success")
                with engine.begin() as conn:
                    conn.execute(text("""INSERT INTO ops.backfill_progress(dataset,trade_date,status,row_count,attempts,error)
                      VALUES (:dataset,:date,:status,:rows,1,:error) ON CONFLICT(dataset,trade_date) DO UPDATE
                      SET status=excluded.status,row_count=excluded.row_count,attempts=ops.backfill_progress.attempts+1,error=excluded.error,updated_at=now()"""),
                      {"dataset": dataset, "date": run_date, "status": status, "rows": output.get("rows", 0), "error": error})
            print(json.dumps({"progress": f"{index}/{len(dates)}", "date": run_date, "results": outputs}, ensure_ascii=False), flush=True)
        if failures:
            raise SystemExit(2)
    elif args.command == "backfill-sentiment":
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        datasets = ("daily_basic", "adj_factor", "limit_list_d", "limit_step")
        with engine.connect() as conn:
            dates = [row[0].isoformat() for row in conn.execute(text("""SELECT trade_date FROM (
                SELECT trade_date FROM market.trade_calendar WHERE is_open AND trade_date BETWEEN :start AND :end
                UNION SELECT DISTINCT trade_date FROM market.daily_bar WHERE trade_date BETWEEN :start AND :end
              ) dates ORDER BY trade_date"""), {"start": args.start, "end": args.end})]
            done = set() if args.force else {(row[0], row[1].isoformat()) for row in conn.execute(text("""
              SELECT dataset,trade_date FROM ops.backfill_progress
              WHERE dataset=ANY(:datasets) AND status IN ('success','unavailable')"""), {
                  "datasets": list(datasets),
              })}
        failures = 0
        for index, run_date in enumerate(dates, 1):
            outputs = {}
            pending = [dataset for dataset in datasets if (dataset, run_date) not in done]

            def execute_sentiment(dataset: str) -> tuple[str, dict, str | None]:
                task_provider = provider if args.workers <= 1 else ReplayProvider()
                error = None
                try:
                    if dataset == "daily_basic":
                        output = ingest_daily_basic(task_provider, run_date)
                    elif dataset == "adj_factor":
                        output = ingest_adj_factors(task_provider, run_date)
                    elif dataset == "limit_list_d":
                        output = ingest_limit_events(task_provider, run_date)
                    else:
                        output = ingest_limit_steps(task_provider, run_date)
                except Exception as exc:
                    output = {"endpoint": dataset, "status": "failed", "rows": 0}
                    error = str(exc)[:1000]
                time.sleep(args.sleep)
                return dataset, output, error

            if args.workers <= 1:
                task_results = [execute_sentiment(dataset) for dataset in pending]
            else:
                with ThreadPoolExecutor(max_workers=min(max(args.workers, 1), 4)) as executor:
                    task_results = list(executor.map(execute_sentiment, pending))
            for dataset, output, error in task_results:
                progress_status = "unavailable" if output["status"] == "empty" else output["status"]
                outputs[dataset] = {**output, "progress_status": progress_status}
                failures += int(progress_status not in {"success", "unavailable"})
                with engine.begin() as conn:
                    conn.execute(text("""INSERT INTO ops.backfill_progress(dataset,trade_date,status,row_count,attempts,error)
                      VALUES (:dataset,:date,:status,:rows,1,:error)
                      ON CONFLICT(dataset,trade_date) DO UPDATE SET status=excluded.status,
                        row_count=excluded.row_count,attempts=ops.backfill_progress.attempts+1,
                        error=excluded.error,updated_at=now()"""), {
                            "dataset": dataset, "date": run_date, "status": progress_status,
                            "rows": output.get("rows", 0), "error": error,
                        })
            breadth = refresh_market_breadth(run_date)
            failures += int(breadth["status"] != "success")
            print(json.dumps({"progress": f"{index}/{len(dates)}", "date": run_date,
                              "results": outputs, "market_breadth": breadth},
                             ensure_ascii=False, default=str), flush=True)
        if failures:
            raise SystemExit(2)
    elif args.command == "backfill-market-intelligence":
        from concurrent.futures import ThreadPoolExecutor

        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        directory_output = ingest_hot_money_directory(provider)
        with engine.connect() as conn:
            dates = [row[0].isoformat() for row in conn.execute(text("""SELECT DISTINCT trade_date
              FROM market.daily_bar WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date"""), {
                "start": args.start, "end": args.end,
            })]
            done = set() if args.force else {(row[0], row[1].isoformat()) for row in conn.execute(text("""
              SELECT dataset,trade_date FROM ops.backfill_progress
              WHERE dataset IN ('hm_detail','stk_surv','broker_recommend')
                AND status IN ('success','unavailable')"""))}

        def save_intelligence_progress(dataset: str, progress_date: str, output: dict, error: str | None) -> str:
            progress_status = "unavailable" if output["status"] == "empty" else output["status"]
            with engine.begin() as conn:
                conn.execute(text("""INSERT INTO ops.backfill_progress(dataset,trade_date,status,row_count,attempts,error)
                  VALUES (:dataset,:date,:status,:rows,1,:error)
                  ON CONFLICT(dataset,trade_date) DO UPDATE SET status=excluded.status,row_count=excluded.row_count,
                    attempts=ops.backfill_progress.attempts+1,error=excluded.error,updated_at=now()"""), {
                    "dataset": dataset, "date": progress_date, "status": progress_status,
                    "rows": output.get("rows", 0), "error": error,
                })
            return progress_status

        failures = 0
        months = sorted({run_date[:7].replace("-", "") for run_date in dates})
        for month in months:
            progress_date = f"{month[:4]}-{month[4:]}-01"
            if ("broker_recommend", progress_date) in done:
                continue
            error = None
            try:
                output = ingest_broker_recommendations(provider, month)
            except Exception as exc:
                output = {"status": "failed", "rows": 0}
                error = str(exc)[:1000]
            status = save_intelligence_progress("broker_recommend", progress_date, output, error)
            failures += int(status not in {"success", "unavailable"})
            time.sleep(args.sleep)
        def process_intelligence_date(item: tuple[int, str]) -> tuple[int, str, dict, int]:
            index, run_date = item
            task_provider = ReplayProvider()
            outputs = {}
            tasks = (
                ("hm_detail", lambda d=run_date: ingest_hot_money_detail(task_provider, d)),
                ("stk_surv", lambda d=run_date: ingest_institutional_surveys(task_provider, d, d)),
            )
            date_failures = 0
            for dataset, task in tasks:
                if (dataset, run_date) in done:
                    continue
                error = None
                try:
                    output = task()
                except Exception as exc:
                    output = {"status": "failed", "rows": 0}
                    error = str(exc)[:1000]
                status = save_intelligence_progress(dataset, run_date, output, error)
                date_failures += int(status not in {"success", "unavailable"})
                outputs[dataset] = {**output, "progress_status": status}
                time.sleep(args.sleep)
            return index, run_date, outputs, date_failures

        items = list(enumerate(dates, 1))
        if args.workers <= 1:
            date_results = map(process_intelligence_date, items)
        else:
            executor = ThreadPoolExecutor(max_workers=min(max(args.workers, 1), 4))
            date_results = executor.map(process_intelligence_date, items)
        try:
            for index, run_date, outputs, date_failures in date_results:
                failures += date_failures
                if outputs:
                    print(json.dumps({"progress": f"{index}/{len(dates)}", "date": run_date,
                                      "directory": directory_output if index == 1 else None,
                                      "results": outputs}, ensure_ascii=False, default=str), flush=True)
        finally:
            if args.workers > 1:
                executor.shutdown(wait=True)
        if failures:
            raise SystemExit(2)
    elif args.command == "backfill-intraday-popularity":
        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        calendar_output = ingest_trade_calendar(provider, args.start, args.end)
        if calendar_output["status"] != "success":
            print(json.dumps({"calendar": calendar_output}, ensure_ascii=False), flush=True)
            raise SystemExit(2)
        dates = open_dates(args.start, args.end)
        with engine.connect() as conn:
            done = set() if args.force else {(row[0], row[1].isoformat()) for row in conn.execute(text("""
              SELECT dataset,trade_date FROM ops.backfill_progress
              WHERE dataset IN ('dc_hot_intraday','ths_hot_intraday')
                AND status IN ('success','unavailable')"""))}
        failures = 0
        for index, run_date in enumerate(dates, 1):
            outputs = {}
            for endpoint in ("dc_hot", "ths_hot"):
                dataset = f"{endpoint}_intraday"
                if (dataset, run_date) in done:
                    continue
                error = None
                try:
                    output = ingest_intraday_popularity(provider, endpoint, run_date)
                except Exception as exc:
                    output = {"status": "failed", "rows": 0, "snapshots": 0}
                    error = str(exc)[:1000]
                status = output["status"]
                failures += int(status not in {"success", "empty"})
                outputs[endpoint] = output
                with engine.begin() as conn:
                    conn.execute(text("""INSERT INTO ops.backfill_progress(dataset,trade_date,status,row_count,attempts,error)
                      VALUES (:dataset,:date,:status,:rows,1,:error) ON CONFLICT(dataset,trade_date) DO UPDATE
                      SET status=excluded.status,row_count=excluded.row_count,
                          attempts=ops.backfill_progress.attempts+1,error=excluded.error,updated_at=now()"""), {
                        "dataset": dataset,
                        "date": run_date,
                        "status": status,
                        "rows": output.get("rows", 0),
                        "error": error,
                    })
                throttle(args.sleep)
            if outputs:
                print(json.dumps({"progress": f"{index}/{len(dates)}", "date": run_date,
                                  "results": outputs}, ensure_ascii=False), flush=True)
        if failures:
            raise SystemExit(2)
    elif args.command == "backfill-hot-minutes":
        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        calendar_output = ingest_trade_calendar(provider, args.start, args.end)
        if calendar_output["status"] != "success":
            print(json.dumps({"calendar": calendar_output}, ensure_ascii=False), flush=True)
            raise SystemExit(2)
        candidates = minute_candidates(args.start, args.end, args.rank_max)
        with engine.connect() as conn:
            done = set() if args.force else {(row[0].isoformat(), row[1]) for row in conn.execute(text("""
              SELECT trade_date,symbol FROM ops.minute_backfill_progress
              WHERE freq=:freq AND status IN ('success','unavailable')"""), {"freq": args.freq})}
        pending = [item for item in candidates if item not in done]
        total_pending = len(pending)
        if args.limit is not None:
            pending = pending[:args.limit]
        print(json.dumps({"candidate_stock_days": len(candidates), "already_done": len(candidates) - total_pending,
                          "pending_this_run": len(pending)}, ensure_ascii=False), flush=True)
        failures = 0
        rows_written = 0
        from concurrent.futures import ThreadPoolExecutor
        from threading import local
        thread_state = local()

        def download(candidate):
            run_date, symbol = candidate
            if not hasattr(thread_state, "provider"):
                thread_state.provider = ReplayProvider()
            error = None
            try:
                output = ingest_minute_bars(thread_state.provider, symbol, run_date, args.freq)
            except Exception as exc:
                output = {"status": "failed", "rows": 0}
                error = str(exc)[:1000]
            save_progress(symbol, run_date, args.freq, output, error)
            throttle(args.sleep)
            return run_date, symbol, output

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            outputs = executor.map(download, pending)
            for index, (run_date, symbol, output) in enumerate(outputs, 1):
                status = output["status"]
                failures += int(status not in {"success", "empty"})
                rows_written += output.get("rows", 0)
                if index == 1 or index % 25 == 0 or index == len(pending):
                    print(json.dumps({"progress": f"{index}/{len(pending)}", "date": run_date, "symbol": symbol,
                                      "status": status, "rows_written": rows_written,
                                      "failures": failures}, ensure_ascii=False), flush=True)
        if failures:
            raise SystemExit(2)
    elif args.command == "backfill-hot-limits":
        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        calendar_output = ingest_trade_calendar(provider, args.start, args.end)
        if calendar_output["status"] != "success":
            print(json.dumps({"calendar": calendar_output}, ensure_ascii=False), flush=True)
            raise SystemExit(2)
        symbols = hot_symbols(args.start, args.end, args.rank_max)
        dates = open_dates(args.start, min(args.end, date.today().isoformat()))
        with engine.connect() as conn:
            done = set() if args.force else {row[0].isoformat() for row in conn.execute(text("""
              SELECT trade_date FROM ops.backfill_progress
              WHERE dataset='stk_limit_hot' AND status IN ('success','unavailable')"""))}
        pending = [run_date for run_date in dates if run_date not in done]
        failures = 0
        rows_written = 0
        print(json.dumps({"hot_symbols": len(symbols), "pending_dates": len(pending)}, ensure_ascii=False), flush=True)
        for index, run_date in enumerate(pending, 1):
            error = None
            try:
                output = ingest_price_limits(provider, run_date, symbols)
            except Exception as exc:
                output = {"status": "failed", "rows": 0}
                error = str(exc)[:1000]
            status = "unavailable" if output["status"] == "empty" else output["status"]
            failures += int(status not in {"success", "unavailable"})
            rows_written += output.get("rows", 0)
            with engine.begin() as conn:
                conn.execute(text("""INSERT INTO ops.backfill_progress(dataset,trade_date,status,row_count,attempts,error)
                  VALUES ('stk_limit_hot',:date,:status,:rows,1,:error)
                  ON CONFLICT(dataset,trade_date) DO UPDATE SET status=excluded.status,row_count=excluded.row_count,
                    attempts=ops.backfill_progress.attempts+1,error=excluded.error,updated_at=now()"""), {
                    "date": run_date,
                    "status": status,
                    "rows": output.get("rows", 0),
                    "error": error,
                })
            if index == 1 or index % 20 == 0 or index == len(pending):
                print(json.dumps({"progress": f"{index}/{len(pending)}", "date": run_date,
                                  "status": status, "rows_written": rows_written,
                                  "failures": failures}, ensure_ascii=False), flush=True)
            throttle(args.sleep)
        if failures:
            raise SystemExit(2)
    elif args.command == "backfill-two-years":
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import text
        from .db import engine
        provider = ReplayProvider()
        with engine.begin() as conn:
            dates = [row[0].isoformat() for row in conn.execute(text("""SELECT trade_date FROM (
                SELECT trade_date FROM market.trade_calendar WHERE is_open AND trade_date BETWEEN :start AND :end
                UNION SELECT DISTINCT trade_date FROM market.daily_bar WHERE trade_date BETWEEN :start AND :end
              ) dates ORDER BY trade_date"""), {"start": args.start, "end": args.end})]
            # A provider-confirmed empty result is terminal after repeated attempts.  Keep it
            # visible as unavailable instead of retrying forever or inventing market rows.
            conn.execute(text("""UPDATE ops.backfill_progress SET status='unavailable',
              error=COALESCE(error,'Replay returned no archived rows after repeated retries'),updated_at=now()
              WHERE status='empty' AND attempts>=5"""))
            done = set() if args.force else {(row[0], row[1].isoformat()) for row in conn.execute(text("SELECT dataset,trade_date FROM ops.backfill_progress WHERE status IN ('success','unavailable')"))}
        popularity_changed = False
        for index, run_date in enumerate(dates, 1):
            outputs = {}
            pending = [dataset for dataset in ("daily", "dc_hot", "ths_hot", "top_list", "top_inst")
                       if (dataset, run_date) not in done]

            def execute(dataset: str) -> tuple[str, dict, str, str | None]:
                task_provider = provider if args.workers <= 1 else ReplayProvider()
                try:
                    if dataset == "daily":
                        output = ingest_daily_market(task_provider, run_date)
                    elif dataset in {"dc_hot", "ths_hot"}:
                        output = ingest_popularity(task_provider, dataset, run_date)
                    else:
                        output = ingest_lhb(task_provider, dataset, run_date)
                    status = output["status"]
                    error = None
                except Exception as exc:
                    output = {"status": "failed", "rows": 0}
                    status, error = "failed", str(exc)[:1000]
                time.sleep(args.sleep)
                return dataset, output, status, error

            if args.workers <= 1:
                task_results = [execute(dataset) for dataset in pending]
            else:
                with ThreadPoolExecutor(max_workers=min(max(args.workers, 1), 5)) as executor:
                    task_results = list(executor.map(execute, pending))
            for dataset, output, status, error in task_results:
                outputs[dataset] = output
                popularity_changed = popularity_changed or (
                    dataset in {"dc_hot", "ths_hot"} and status == "success"
                )
                with engine.begin() as conn:
                    conn.execute(text("""INSERT INTO ops.backfill_progress(dataset,trade_date,status,row_count,attempts,error)
                      VALUES (:dataset,:date,:status,:rows,1,:error) ON CONFLICT(dataset,trade_date) DO UPDATE
                      SET status=excluded.status,row_count=excluded.row_count,attempts=ops.backfill_progress.attempts+1,error=excluded.error,updated_at=now()"""),
                      {"dataset": dataset, "date": run_date, "status": status, "rows": output.get("rows", 0), "error": error})
            print(json.dumps({"progress": f"{index}/{len(dates)}", "date": run_date, "results": outputs}, ensure_ascii=False), flush=True)
        if popularity_changed:
            refresh_popularity_view()
        if args.no_finalize:
            return
        with engine.begin() as conn:
            missing = conn.execute(text("""SELECT count(*) FROM (
              WITH dates AS (SELECT trade_date FROM market.trade_calendar
                             WHERE is_open AND trade_date BETWEEN :start AND :end)
              SELECT d.trade_date,x.dataset FROM dates d
              CROSS JOIN (VALUES ('daily'),('dc_hot'),('ths_hot'),('top_list'),('top_inst')) x(dataset)
              LEFT JOIN ops.backfill_progress p ON p.trade_date=d.trade_date AND p.dataset=x.dataset AND p.status IN ('success','unavailable')
              WHERE p.dataset IS NULL) gaps"""), {"start": args.start, "end": args.end}).scalar_one()
            if missing == 0:
                conn.execute(text("DELETE FROM market.daily_bar WHERE trade_date<:start"), {"start": args.start})
                conn.execute(text("DELETE FROM market.daily_bar WHERE provider<>'tushare_replay'"))
                conn.execute(text("DELETE FROM popularity.snapshot WHERE provider<>'tushare_replay'"))
                conn.execute(text("REFRESH MATERIALIZED VIEW popularity.daily_close"))
                print(json.dumps({"finalized": True, "legacy_sources_removed": True}, ensure_ascii=False), flush=True)
            else:
                print(json.dumps({"finalized": False, "remaining_dataset_days": missing}, ensure_ascii=False), flush=True)
                raise SystemExit(2)


if __name__ == "__main__":
    main()
