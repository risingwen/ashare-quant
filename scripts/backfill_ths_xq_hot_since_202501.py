#!/usr/bin/env python3
"""Backfill THS/Xueqiu popularity data since 2025-01-01 (best effort)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "hot_sources"
THS_DIR = OUT_DIR / "ths"
XQ_DIR = OUT_DIR / "xueqiu"
SUMMARY_DIR = OUT_DIR / "summaries"

THS_CSV = THS_DIR / "ths_hot_rank_top100_history.csv"
THS_FAILED_CSV = THS_DIR / "ths_hot_rank_failed_dates.csv"
XQ_CSV = XQ_DIR / "xueqiu_hot_rank_snapshots.csv"


@dataclass
class BackfillSummary:
    run_time: str
    ths_existing_dates: int
    ths_new_dates: int
    ths_new_rows: int
    ths_failed_dates: int
    xq_snapshots_added: int
    xq_note: str


def disable_proxy_env() -> None:
    for k in [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ]:
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    os.environ.setdefault("NODE_NO_WARNINGS", "1")


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def normalize_code(raw: object) -> str:
    s = str(raw).strip()
    if "." in s:
        s = s.split(".")[0]
    if s.isdigit():
        return s.zfill(6)
    return s


def extract_rank_heat(row: pd.Series, d: date) -> tuple[float | None, float | None]:
    d8 = d.strftime("%Y%m%d")
    rank_col = f"个股热度排名[{d8}]"
    heat_col = f"个股热度[{d8}]"
    rank = row.get(rank_col)
    heat = row.get(heat_col)
    return rank, heat


def fetch_ths_by_date(d: date) -> pd.DataFrame:
    import pywencai  # pylint: disable=import-outside-toplevel

    q = f"{d.strftime('%Y-%m-%d')} 人气榜 股票代码 股票简称 人气排名"
    raw = pywencai.get(query=q, loop=False)
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame(columns=["date", "code", "name", "rank", "heat", "latest_price", "latest_pct", "source"])

    out_rows: list[dict] = []
    for _, row in raw.iterrows():
        rank, heat = extract_rank_heat(row, d)
        if pd.isna(rank):
            continue
        rank = int(rank)
        if rank < 1 or rank > 100:
            continue
        out_rows.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "code": normalize_code(row.get("股票代码", row.get("code", ""))),
                "name": str(row.get("股票简称", "")),
                "rank": rank,
                "heat": float(heat) if pd.notna(heat) else None,
                "latest_price": pd.to_numeric(row.get("最新价"), errors="coerce"),
                "latest_pct": pd.to_numeric(row.get("最新涨跌幅"), errors="coerce"),
                "source": "ths_pywencai",
            }
        )
    return pd.DataFrame(out_rows)


def backfill_ths(start_date: date, end_date: date) -> tuple[int, int, int, int]:
    THS_DIR.mkdir(parents=True, exist_ok=True)

    if THS_CSV.exists() and THS_CSV.stat().st_size > 0:
        old = pd.read_csv(THS_CSV)
        if "date" in old.columns and not old.empty:
            old["date"] = pd.to_datetime(old["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            existing_dates = set(old["date"].dropna().astype(str).unique().tolist())
        else:
            existing_dates = set()
    else:
        old = pd.DataFrame(columns=["date", "code", "name", "rank", "heat", "latest_price", "latest_pct", "source"])
        existing_dates = set()

    to_fetch = [
        d
        for d in daterange(start_date, end_date)
        if d.weekday() < 5 and d.strftime("%Y-%m-%d") not in existing_dates
    ]
    print(f"[ths] existing_dates={len(existing_dates)}, to_fetch={len(to_fetch)}")
    new_parts: list[pd.DataFrame] = []
    failed_dates: list[str] = []

    for i, d in enumerate(to_fetch, 1):
        if i % 20 == 0:
            print(f"[ths] progress {i}/{len(to_fetch)}")
        ok = False
        for attempt in range(1):
            try:
                df = fetch_ths_by_date(d)
                if not df.empty:
                    new_parts.append(df)
                ok = True
                break
            except Exception:
                time.sleep(0.3 + attempt * 0.2)
        if not ok:
            failed_dates.append(d.strftime("%Y-%m-%d"))
        time.sleep(0.05)

    if new_parts:
        new_df = pd.concat(new_parts, ignore_index=True)
        merged = pd.concat([old, new_df], ignore_index=True)
    else:
        new_df = pd.DataFrame(columns=old.columns)
        merged = old.copy()

    merged = merged.drop_duplicates(subset=["date", "code", "source"], keep="last")
    merged = merged.sort_values(["date", "rank", "code"], ascending=[True, True, True]).reset_index(drop=True)
    tmp_ths = THS_CSV.with_suffix(".csv.tmp")
    tmp_failed = THS_FAILED_CSV.with_suffix(".csv.tmp")
    merged.to_csv(tmp_ths, index=False, encoding="utf-8")
    pd.DataFrame({"date": failed_dates}).to_csv(tmp_failed, index=False, encoding="utf-8")
    tmp_ths.replace(THS_CSV)
    tmp_failed.replace(THS_FAILED_CSV)

    return len(existing_dates), len(new_df["date"].unique()) if not new_df.empty else 0, len(new_df), len(failed_dates)


def _xq_to_rows(df: pd.DataFrame, kind: str, fetch_time: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["fetch_time", "date", "kind", "code", "name", "value", "latest_price", "source"])

    value_col = None
    for c in ["关注", "讨论", "交易"]:
        if c in df.columns:
            value_col = c
            break
    if value_col is None:
        value_col = df.columns[2]

    out = pd.DataFrame(
        {
            "fetch_time": fetch_time,
            "date": fetch_time[:10],
            "kind": kind,
            "code": df.iloc[:, 0].map(normalize_code),
            "name": df.iloc[:, 1].astype(str),
            "value": pd.to_numeric(df[value_col], errors="coerce"),
            "latest_price": pd.to_numeric(df.get("最新价"), errors="coerce"),
            "source": "xueqiu_akshare",
        }
    )
    return out


def capture_xueqiu_snapshot() -> tuple[int, str]:
    import akshare as ak  # pylint: disable=import-outside-toplevel

    XQ_DIR.mkdir(parents=True, exist_ok=True)
    fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts: list[pd.DataFrame] = []

    try:
        parts.append(_xq_to_rows(ak.stock_hot_follow_xq("最热门"), "follow_hot", fetch_time))
        parts.append(_xq_to_rows(ak.stock_hot_follow_xq("本周新增"), "follow_7d", fetch_time))
        parts.append(_xq_to_rows(ak.stock_hot_tweet_xq("最热门"), "tweet_hot", fetch_time))
        parts.append(_xq_to_rows(ak.stock_hot_deal_xq("最热门"), "deal_hot", fetch_time))
    except Exception as exc:  # pylint: disable=broad-except
        return 0, f"failed: {type(exc).__name__}: {exc}"

    new_df = pd.concat(parts, ignore_index=True)
    if XQ_CSV.exists():
        old = pd.read_csv(XQ_CSV)
        merged = pd.concat([old, new_df], ignore_index=True)
    else:
        merged = new_df
    merged = merged.drop_duplicates(subset=["fetch_time", "kind", "code"], keep="last")
    merged = merged.sort_values(["fetch_time", "kind", "value"], ascending=[True, True, False]).reset_index(drop=True)
    tmp_xq = XQ_CSV.with_suffix(".csv.tmp")
    merged.to_csv(tmp_xq, index=False, encoding="utf-8")
    tmp_xq.replace(XQ_CSV)
    return len(new_df), "xueqiu API currently exposes snapshot ranking; historical date replay is not available in this endpoint"


def main() -> int:
    disable_proxy_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    start = date(2025, 1, 1)
    end = date.today()
    print(f"backfill range: {start} -> {end}")

    ths_existing_dates, ths_new_dates, ths_new_rows, ths_failed_dates = backfill_ths(start, end)
    xq_added, xq_note = capture_xueqiu_snapshot()

    summary = BackfillSummary(
        run_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ths_existing_dates=ths_existing_dates,
        ths_new_dates=ths_new_dates,
        ths_new_rows=ths_new_rows,
        ths_failed_dates=ths_failed_dates,
        xq_snapshots_added=xq_added,
        xq_note=xq_note,
    )
    summary_path = SUMMARY_DIR / f"ths_xq_backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_path.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    print(f"ths_csv={THS_CSV}")
    print(f"xq_csv={XQ_CSV}")
    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
