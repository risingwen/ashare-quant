from datetime import UTC, datetime

from quant_platform.intraday import group_intraday_popularity, normalize_minute_bars, to_ts_code
from quant_platform.providers.base import ProviderResult


def result(endpoint, rows):
    now = datetime.now(UTC)
    return ProviderResult("replay", endpoint, now, now, "success", rows)


def test_groups_row_level_ths_times_into_one_minute_frame():
    grouped = group_intraday_popularity(result("ths_hot", [
        {"ts_code": "000001.SZ", "rank": 1, "hot": 30, "rank_time": "2026-01-02 10:00:03"},
        {"ts_code": "600000.SH", "rank": 2, "hot": 20, "rank_time": "2026-01-02 10:00:48"},
    ]), "2026-01-02")
    assert len(grouped) == 1
    assert [item["rank"] for item in next(iter(grouped.values()))] == [1, 2]


def test_merges_rows_that_straddle_a_scheduled_half_hour():
    grouped = group_intraday_popularity(result("ths_hot", [
        {"ts_code": "000001.SZ", "rank": 1, "rank_time": "2026-01-02 16:30:58"},
        {"ts_code": "600000.SH", "rank": 2, "rank_time": "2026-01-02 16:31:02"},
    ]), "2026-01-02")
    assert len(grouped) == 1
    assert next(iter(grouped)).strftime("%H:%M") == "16:30"


def test_minute_normalization_rejects_bad_ohlc_and_wrong_day():
    rows = normalize_minute_bars(result("stk_mins", [
        {"ts_code": "000001.SZ", "trade_time": "2026-01-02 09:31:00",
         "open": 10, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1000},
        {"ts_code": "000001.SZ", "trade_time": "2026-01-02 09:32:00",
         "open": 10, "high": 9.8, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1000},
        {"ts_code": "000001.SZ", "trade_time": "2026-01-03 09:31:00",
         "open": 10, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1000},
    ]), "2026-01-02", expected_symbol="000001")
    assert len(rows) == 1
    assert rows[0]["trade_time"].isoformat() == "2026-01-02T09:31:00+08:00"


def test_infers_exchange_suffixes():
    assert to_ts_code("600000") == "600000.SH"
    assert to_ts_code("300750") == "300750.SZ"
    assert to_ts_code("920000") == "920000.BJ"
