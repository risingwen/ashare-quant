from quant_platform.ingest import (
    normalize_adj_factors,
    normalize_daily_basic,
    normalize_limit_events,
    normalize_limit_steps,
)


def test_normalize_daily_basic_rejects_wrong_date_and_keeps_market_fields():
    rows = [
        {"ts_code": "000001.SZ", "trade_date": "20240415", "close": 10.2,
         "turnover_rate": 3.5, "volume_ratio": 1.2, "circ_mv": 123456},
        {"ts_code": "000002.SZ", "trade_date": "20240412", "close": 9.8},
    ]
    result = normalize_daily_basic(rows, "2024-04-15")
    assert result == [{
        "symbol": "000001", "trade_date": "2024-04-15", "close": 10.2,
        "turnover_rate": 3.5, "turnover_rate_f": None, "volume_ratio": 1.2,
        "pe": None, "pe_ttm": None, "pb": None, "ps": None, "ps_ttm": None,
        "dv_ratio": None, "dv_ttm": None, "total_share": None, "float_share": None,
        "free_share": None, "total_mv": None, "circ_mv": 123456,
        "raw": ('{"ts_code": "000001.SZ", "trade_date": "20240415", "close": 10.2, '
                '"turnover_rate": 3.5, "volume_ratio": 1.2, "circ_mv": 123456}'),
    }]


def test_normalize_adj_factors_requires_factor_and_requested_date():
    result = normalize_adj_factors([
        {"ts_code": "600000.SH", "trade_date": "20240415", "adj_factor": "5.25"},
        {"ts_code": "600001.SH", "trade_date": "20240415", "adj_factor": None},
    ], "2024-04-15")
    assert result == [{"symbol": "600000", "trade_date": "2024-04-15", "adj_factor": "5.25"}]


def test_normalize_limit_events_supports_up_down_and_broken_types():
    result = normalize_limit_events([
        {"ts_code": "000001.SZ", "trade_date": "20240415", "limit": "U", "pct_chg": 10.01},
        {"ts_code": "000002.SZ", "trade_date": "20240415", "limit": "D", "pct_chg": -9.98},
        {"ts_code": "000003.SZ", "trade_date": "20240415", "limit": "Z", "open_times": 2},
        {"ts_code": "000004.SZ", "trade_date": "20240415", "limit": "X"},
    ], "2024-04-15")
    assert [item["event_type"] for item in result] == ["U", "D", "Z"]
    assert result[2]["open_times"] == 2


def test_normalize_limit_steps_uses_nums_as_streak():
    result = normalize_limit_steps([
        {"ts_code": "600001.SH", "trade_date": "20240415", "name": "示例", "nums": "3"},
    ], "2024-04-15")
    assert result[0]["symbol"] == "600001"
    assert result[0]["streak"] == 3
