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
