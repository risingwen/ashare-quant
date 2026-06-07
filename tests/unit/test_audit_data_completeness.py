from __future__ import annotations

from pathlib import Path

from audit_data_completeness import (
    audit_daily_bars,
    audit_market_daily,
    audit_table_freshness,
    fallback_weekdays,
    load_audit_config,
)
from quant_db import connect


def test_fallback_weekdays_excludes_weekends() -> None:
    assert fallback_weekdays("2026-06-05", "2026-06-08") == ["2026-06-05", "2026-06-08"]


def test_audit_daily_bars_detects_missing_and_thin_days(tmp_path: Path) -> None:
    conn = connect(tmp_path / "quant.db")
    conn.executemany(
        """
        INSERT INTO daily_bars(code, date, open, close, high, low, volume, amount, amplitude, pct_chg, change_amount, turnover)
        VALUES (?, ?, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0)
        """,
        [("000001", "2026-06-01"), ("000002", "2026-06-01")],
    )
    conn.commit()

    results = {result.name: result for result in audit_daily_bars(conn, ["2026-06-01", "2026-06-02"], 3)}

    assert results["daily_bars_duplicates"].status == "ok"
    assert results["daily_bars_coverage"].status == "error"
    assert results["daily_bars_coverage"].stats["missing_days"] == ["2026-06-02"]
    assert results["daily_bars_coverage"].stats["thin_days"] == [{"date": "2026-06-01", "rows": 2}]


def test_audit_market_daily_and_freshness(tmp_path: Path) -> None:
    conn = connect(tmp_path / "quant.db")
    conn.execute("INSERT INTO market_daily(date, zt_count, dt_count) VALUES ('2026-06-01', 10, 1)")
    conn.execute("INSERT INTO etf_daily(date, code, name) VALUES ('2026-06-01', '510050', 'ETF')")
    conn.commit()

    market_result = audit_market_daily(conn, ["2026-06-01", "2026-06-02"])
    fresh_result = audit_table_freshness(conn, "etf_daily", "2026-06-01", 1)

    assert market_result.status == "error"
    assert market_result.stats["missing_days"] == ["2026-06-02"]
    assert fresh_result.status == "ok"


def test_load_audit_config(tmp_path: Path) -> None:
    config_path = tmp_path / "audit.yaml"
    config_path.write_text("lookback_days: 7\nmin_daily_bars: 10\n", encoding="utf-8")

    assert load_audit_config(config_path) == {"lookback_days": 7, "min_daily_bars": 10}
