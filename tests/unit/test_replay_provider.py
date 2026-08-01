from quant_platform.providers.replay import ReplayProvider


def test_missing_key_is_explicit_unauthorized():
    result = ReplayProvider(api_key="").fetch_popularity("dc_hot", "2026-01-02")
    assert result.status == "unauthorized"
    assert result.error_code == "missing_api_key"


def test_rejects_unknown_popularity_endpoint():
    provider = ReplayProvider(api_key="x")
    try:
        provider.fetch_popularity("unknown", "2026-01-02")
    except ValueError as exc:
        assert "dc_hot" in str(exc) and "ths_hot" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_ths_hot_uses_documented_market(monkeypatch):
    provider = ReplayProvider(api_key="x")
    captured = {}

    def fake_get(endpoint, params):
        captured.update({"endpoint": endpoint, **params})
        from datetime import UTC, datetime
        from quant_platform.providers.base import ProviderResult
        return ProviderResult("replay", endpoint, datetime.now(UTC), datetime.now(UTC), "success",
                              [{"rank": rank} for rank in range(1, 101)])

    monkeypatch.setattr(provider, "_get", fake_get)
    provider.fetch_popularity("ths_hot", "2026-01-02")
    assert captured["market"] == "热股"
    assert captured["is_new"] == "Y"
    assert "hot_type" not in captured


def test_accepts_direct_list_payload(monkeypatch):
    provider = ReplayProvider(api_key="x")

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"data": [{"cal_date": "20260102", "is_open": 1}]}

    monkeypatch.setattr(provider.session, "get", lambda *args, **kwargs: Response())
    result = provider.fetch_trade_calendar("2026-01-01", "2026-01-03")
    assert result.status == "success"
    assert result.rows == [{"cal_date": "20260102", "is_open": 1}]


def test_minute_request_is_scoped_to_one_stock_day(monkeypatch):
    provider = ReplayProvider(api_key="x")
    captured = {}

    def fake_get(endpoint, params):
        captured.update({"endpoint": endpoint, **params})
        from datetime import UTC, datetime
        from quant_platform.providers.base import ProviderResult
        return ProviderResult("replay", endpoint, datetime.now(UTC), datetime.now(UTC), "empty")

    monkeypatch.setattr(provider, "_get", fake_get)
    provider.fetch_minute_bars("000001.SZ", "2026-01-02")
    assert captured["endpoint"] == "stk_mins"
    assert captured["ts_code"] == "000001.SZ"
    assert captured["start_date"] == "2026-01-02 09:00:00"
    assert captured["end_date"] == "2026-01-02 15:30:00"
