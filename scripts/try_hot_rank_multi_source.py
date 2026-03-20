#!/usr/bin/env python3
"""Try multiple popularity data sources and export last-30d/snapshot results."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import akshare as ak
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = PROJECT_ROOT / "data" / "experiments" / "hot_rank_multi_source"


@dataclass
class AttemptResult:
    source: str
    method: str
    status: str
    rows: int = 0
    file: str = ""
    note: str = ""
    error: str = ""


def disable_proxy_env() -> None:
    for key in [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ]:
        os.environ.pop(key, None)
    os.environ.setdefault("NODE_NO_WARNINGS", "1")


def safe_try(
    source: str,
    method: str,
    fn: Callable[[], pd.DataFrame],
    out_file: Path,
    note: str = "",
    retries: int = 2,
    retry_wait_sec: float = 1.5,
) -> AttemptResult:
    try:
        df = call_with_retry(fn, retries=retries, wait_sec=retry_wait_sec)
        if not isinstance(df, pd.DataFrame):
            return AttemptResult(
                source=source,
                method=method,
                status="failed",
                note=note,
                error=f"non-DataFrame return: {type(df)}",
            )
        df.to_csv(out_file, index=False, encoding="utf-8-sig")
        return AttemptResult(
            source=source,
            method=method,
            status="ok",
            rows=len(df),
            file=str(out_file.relative_to(PROJECT_ROOT)),
            note=note,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return AttemptResult(
            source=source,
            method=method,
            status="failed",
            note=note,
            error=f"{type(exc).__name__}: {exc}",
        )


def call_with_retry(
    fn: Callable[[], pd.DataFrame],
    retries: int = 2,
    wait_sec: float = 1.5,
) -> pd.DataFrame:
    last_exc: Exception | None = None
    total = max(1, retries + 1)
    for idx in range(total):
        try:
            return fn()
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
            if idx + 1 >= total:
                break
            time.sleep(wait_sec * (idx + 1))
    assert last_exc is not None
    raise last_exc


def fetch_eastmoney_last_30d(out_dir: Path, topn: int = 50) -> AttemptResult:
    rank_df = call_with_retry(lambda: ak.stock_hot_rank_em(), retries=3, wait_sec=2.0)
    rank_df["代码"] = rank_df["代码"].astype(str)
    rank_df.to_csv(out_dir / "eastmoney_rank_snapshot.csv", index=False, encoding="utf-8-sig")

    codes = rank_df["代码"].head(topn).tolist()
    start_date = (datetime.now() - timedelta(days=30)).date()

    chunks: list[pd.DataFrame] = []
    for code in codes:
        symbol = f"SZ{code}" if code.startswith(("0", "3")) else f"SH{code}"
        try:
            df = ak.stock_hot_rank_detail_em(symbol=symbol)
            if df is None or df.empty:
                continue
            # Expected columns after akshare mapping: 日期, 排名, 新晋粉丝, 铁杆粉丝.
            tmp = df.copy()
            tmp.columns = [str(c) for c in tmp.columns]
            if "日期" in tmp.columns:
                tmp["date"] = pd.to_datetime(tmp["日期"], errors="coerce").dt.date
            elif "时间" in tmp.columns:
                tmp["date"] = pd.to_datetime(tmp["时间"], errors="coerce").dt.date
            else:
                continue
            tmp["code"] = code
            tmp = tmp[tmp["date"] >= start_date]
            if not tmp.empty:
                chunks.append(tmp)
        except Exception:
            continue

    if not chunks:
        return AttemptResult(
            source="eastmoney",
            method="stock_hot_rank_detail_em",
            status="failed",
            note=f"topn={topn}, last30d",
            error="no detail rows collected",
        )

    merged = pd.concat(chunks, ignore_index=True)
    out_file = out_dir / "eastmoney_hot_rank_detail_last30d.csv"
    merged.to_csv(out_file, index=False, encoding="utf-8-sig")
    return AttemptResult(
        source="eastmoney",
        method="stock_hot_rank_detail_em",
        status="ok",
        rows=len(merged),
        file=str(out_file.relative_to(PROJECT_ROOT)),
        note=f"topn={topn}, unique_codes={merged['code'].nunique()}",
    )


def fetch_pywencai_last_30d(out_dir: Path, days: int = 30) -> AttemptResult:
    import pywencai  # pylint: disable=import-outside-toplevel

    end_date = datetime.now().date()
    days = max(1, days)
    start_date = end_date - timedelta(days=days - 1)
    all_rows: list[pd.DataFrame] = []
    success_dates = 0
    nonempty_dates = 0
    failed_dates: list[str] = []

    for i in range((end_date - start_date).days + 1):
        day = start_date + timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        query = f"{day_str} 人气榜 股票代码 股票简称 人气排名"
        try:
            df = call_with_retry(
                lambda q=query: pywencai.get(query=q, loop=False),
                retries=0,
                wait_sec=1.5,
            )
            success_dates += 1
            if isinstance(df, pd.DataFrame) and not df.empty:
                tmp = df.copy()
                tmp.insert(0, "query_date", day_str)
                all_rows.append(tmp)
                nonempty_dates += 1
        except Exception:
            failed_dates.append(day_str)
            continue

    if not all_rows:
        return AttemptResult(
            source="tonghuashun",
            method="pywencai.get(last30d)",
            status="failed",
            note=f"calendar_days={days}, success_dates={success_dates}, failed_dates={len(failed_dates)}",
            error=f"no non-empty rows in last{days}d queries",
        )

    merged = pd.concat(all_rows, ignore_index=True)
    out_file = out_dir / "wencai_hot_rank_last30d_pywencai.csv"
    merged.to_csv(out_file, index=False, encoding="utf-8-sig")
    failed_text = ",".join(failed_dates[:10]) if failed_dates else ""
    note = (
        f"calendar_days={days}, success_dates={success_dates}, nonempty_dates={nonempty_dates}, "
        f"failed_dates={len(failed_dates)}"
    )
    if failed_text:
        note += f", failed_samples={failed_text}"
    return AttemptResult(
        source="tonghuashun",
        method="pywencai.get(last30d)",
        status="ok",
        rows=len(merged),
        file=str(out_file.relative_to(PROJECT_ROOT)),
        note=note,
    )


def main() -> int:
    disable_proxy_env()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[AttemptResult] = []
    fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1) 东方财富（最近30天明细）
    try:
        results.append(fetch_eastmoney_last_30d(out_dir=out_dir, topn=50))
    except Exception as exc:  # pylint: disable=broad-except
        results.append(
            AttemptResult(
                source="eastmoney",
                method="stock_hot_rank_detail_em",
                status="failed",
                note="topn=50, last30d",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    # 2) 雪球快照
    for method, fn in [
        ("stock_hot_follow_xq_最热门", lambda: ak.stock_hot_follow_xq("最热门")),
        ("stock_hot_follow_xq_本周新增", lambda: ak.stock_hot_follow_xq("本周新增")),
        ("stock_hot_tweet_xq_最热门", lambda: ak.stock_hot_tweet_xq("最热门")),
        ("stock_hot_deal_xq_最热门", lambda: ak.stock_hot_deal_xq("最热门")),
    ]:
        file = out_dir / f"xueqiu_{method}.csv"
        ret = safe_try("xueqiu", method, fn, file, note="snapshot only")
        if ret.status == "ok":
            df = pd.read_csv(file)
            df.insert(0, "fetch_time", fetch_time)
            df.to_csv(file, index=False, encoding="utf-8-sig")
        results.append(ret)

    # 3) adata: 同花顺热股100 + 东财人气100
    try:
        import adata  # pylint: disable=import-outside-toplevel

        ret = safe_try(
            "tonghuashun",
            "adata.sentiment.hot.hot_rank_100_ths",
            lambda: adata.sentiment.hot.hot_rank_100_ths(),
            out_dir / "ths_hot_rank_100_snapshot_adata.csv",
            note="snapshot only",
            retries=1,
        )
        if ret.status == "ok":
            df = pd.read_csv(out_dir / "ths_hot_rank_100_snapshot_adata.csv")
            df.insert(0, "fetch_time", fetch_time)
            df.to_csv(out_dir / "ths_hot_rank_100_snapshot_adata.csv", index=False, encoding="utf-8-sig")
        results.append(ret)

        ret = safe_try(
            "eastmoney",
            "adata.sentiment.hot.pop_rank_100_east",
            lambda: adata.sentiment.hot.pop_rank_100_east(),
            out_dir / "eastmoney_pop_rank_100_snapshot_adata.csv",
            note="snapshot only",
            retries=1,
        )
        if ret.status == "ok":
            df = pd.read_csv(out_dir / "eastmoney_pop_rank_100_snapshot_adata.csv")
            df.insert(0, "fetch_time", fetch_time)
            df.to_csv(
                out_dir / "eastmoney_pop_rank_100_snapshot_adata.csv",
                index=False,
                encoding="utf-8-sig",
            )
        results.append(ret)
    except Exception as exc:  # pylint: disable=broad-except
        results.append(
            AttemptResult(
                source="adata",
                method="import",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    # 4) 问财方案: pywencai / qqhsx-wencai
    try:
        results.append(fetch_pywencai_last_30d(out_dir=out_dir))
    except Exception as exc:  # pylint: disable=broad-except
        results.append(
            AttemptResult(
                source="tonghuashun",
                method="pywencai.get(last30d)",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        import pywencai  # pylint: disable=import-outside-toplevel

        query = "2026-03-18 人气榜 股票代码 股票简称 人气排名"
        ret = safe_try(
            "tonghuashun",
            "pywencai.get",
            lambda: pywencai.get(query=query, loop=True),
            out_dir / "wencai_hot_rank_snapshot_pywencai.csv",
            note=f"query={query}",
            retries=1,
        )
        if ret.status == "ok":
            df = pd.read_csv(out_dir / "wencai_hot_rank_snapshot_pywencai.csv")
            df.insert(0, "fetch_time", fetch_time)
            df.to_csv(out_dir / "wencai_hot_rank_snapshot_pywencai.csv", index=False, encoding="utf-8-sig")
        results.append(ret)
    except Exception as exc:  # pylint: disable=broad-except
        results.append(
            AttemptResult(
                source="tonghuashun",
                method="pywencai.get",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        import wencai  # pylint: disable=import-outside-toplevel

        q = "同花顺人气榜"

        def _wencai_search() -> pd.DataFrame:
            res = wencai.search(q)
            if isinstance(res, pd.DataFrame):
                return res
            if isinstance(res, list):
                return pd.DataFrame(res)
            if isinstance(res, dict):
                return pd.DataFrame([res])
            raise TypeError(f"unsupported return type: {type(res)}")

        results.append(
            safe_try(
                "tonghuashun",
                "wencai.search",
                _wencai_search,
                out_dir / "wencai_hot_rank_snapshot_qqhsx.csv",
                note=f"query={q}",
            )
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.append(
            AttemptResult(
                source="tonghuashun",
                method="wencai.search",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    # 5) 开盘啦/通达信尝试
    try:
        import pywencai  # pylint: disable=import-outside-toplevel

        query = "开盘啦 人气榜 股票代码 股票简称 人气排名"
        ret = safe_try(
            "kaipanla",
            "pywencai.get",
            lambda: pywencai.get(query=query, loop=True),
            out_dir / "kaipanla_hot_rank_snapshot_pywencai.csv",
            note=f"query={query}",
            retries=1,
        )
        results.append(ret)

        query = "通达信 人气榜 股票代码 股票简称 人气排名"
        ret = safe_try(
            "tongdaxin",
            "pywencai.get",
            lambda: pywencai.get(query=query, loop=True),
            out_dir / "tongdaxin_hot_rank_snapshot_pywencai.csv",
            note=f"query={query}",
            retries=1,
        )
        results.append(ret)
    except Exception as exc:  # pylint: disable=broad-except
        results.append(
            AttemptResult(
                source="kaipanla/tongdaxin",
                method="pywencai.get",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    # summary
    summary = {
        "run_time": fetch_time,
        "out_dir": str(out_dir.relative_to(PROJECT_ROOT)),
        "results": [asdict(x) for x in results],
    }
    (out_dir / "attempt_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pd.DataFrame([asdict(x) for x in results]).to_csv(
        out_dir / "attempt_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    ok_cnt = sum(1 for x in results if x.status == "ok")
    print(f"out_dir={out_dir}")
    print(f"ok={ok_cnt}/{len(results)}")
    for item in results:
        print(f"[{item.status}] {item.source} | {item.method} | rows={item.rows} | {item.error or item.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
