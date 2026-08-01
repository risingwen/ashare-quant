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
