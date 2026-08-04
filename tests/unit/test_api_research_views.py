from quant_platform import api


def test_popularity_rankings_requests_forward_trading_day_returns(monkeypatch):
    captured = {}

    def fake_rows(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return [{"symbol": "000001", "rank": 1, "next_day_return": 1.2, "day_3_return": 2.3, "day_5_return": 3.4}]

    monkeypatch.setattr(api, "rows", fake_rows)
    response = api.rankings("2026-07-31", "dc_hot", 100, 0)
    assert response["data"][0]["day_5_return"] == 3.4
    assert "sequence=5" in captured["sql"]
    assert "trade_date>s.trade_date" in captured["sql"]
    assert "category=:category" in captured["sql"]
    assert captured["params"]["trade_date"] == "2026-07-31"
    assert captured["params"]["category"] == "人气榜"


def test_lhb_seat_coverage_marks_institution_only(monkeypatch):
    monkeypatch.setattr(api, "rows", lambda *_args, **_kwargs: [{
        "seat_name": "机构专用", "side": "0", "side_label": "买入前五", "seat_type": "机构",
        "buy": 1, "buy_rate": 1, "sell": 0, "sell_rate": 0, "net_buy": 1, "reason": "测试",
    }])
    response = api.lhb_seats("2026-07-31", "000001", 100)
    assert response["coverage"]["status"] == "institution_only"
    assert "不能视为完整" in response["coverage"]["description"]


def test_popularity_detail_centers_window_and_aligns_rank_query(monkeypatch):
    calls = []

    def fake_rows(sql, params=None):
        calls.append((sql, params))
        if "WITH ordered AS" in sql:
            return [
                {"trade_date": "2026-06-10", "close": 10},
                {"trade_date": "2026-07-01", "close": 11},
                {"trade_date": "2026-07-22", "close": 12},
            ]
        if "BETWEEN :window_start AND :window_end" in sql:
            return [{"trade_date": "2026-07-01", "rank": 50}]
        return [{"name": "测试股票"}]

    monkeypatch.setattr(api, "rows", fake_rows)
    response = api.popularity_detail("000001", "dc_hot", "2026-07-01", 30)

    assert calls[0][1]["before_days"] == 15
    assert calls[1][1]["window_start"] == "2026-06-10"
    assert calls[1][1]["window_end"] == "2026-07-22"
    assert response["window"] == {
        "start_date": "2026-06-10",
        "end_date": "2026-07-22",
        "anchor_date": "2026-07-01",
        "trade_day_count": 3,
    }


def test_research_sorting_uses_whitelisted_columns_and_instrument_name(monkeypatch):
    captured = {}

    def fake_rows(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return [{"symbol": "000001", "name": "平安银行"}]

    monkeypatch.setattr(api, "rows", fake_rows)
    response = api.institutional_surveys("2026-07-28", "", "name", "desc", 10, 0)

    assert response["sort_by"] == "name"
    assert "LEFT JOIN market.instrument" in captured["sql"]
    assert "coalesce(s.name,i.name,s.symbol) DESC" in captured["sql"]


def test_freshness_separates_current_date_from_historical_gaps(monkeypatch):
    sql_calls = []

    def fake_rows(sql, _params=None):
        sql_calls.append(sql)
        return []

    monkeypatch.setattr(api, "rows", fake_rows)
    api.data_freshness()

    assert "WHEN d.latest_date>=m.expected_date THEN 'current'" in sql_calls[0]
    assert "'stk_surv','机构调研'" in sql_calls[0]
    assert "THEN 'source_limited'" in sql_calls[0]
    assert "source_limited_count" in sql_calls[0]
    assert "coalesce(cardinality(c.missing_dates),0)=0" not in sql_calls[0]
