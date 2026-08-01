from datetime import UTC, datetime

import pytest

from quant_platform.ingest import (
    _documented_yuan,
    normalize_broker_recommendations,
    normalize_hot_money_detail,
    normalize_institutional_surveys,
)
from quant_platform.providers.base import ProviderResult
from quant_platform.providers.replay import ReplayProvider


def result(endpoint: str, rows: list[dict]) -> ProviderResult:
    now = datetime.now(UTC)
    return ProviderResult("replay", endpoint, now, now, "success" if rows else "empty", rows)


def test_institutional_survey_uses_documented_pagination(monkeypatch):
    provider = ReplayProvider(api_key="x")
    calls = []

    def fake_get(endpoint, params):
        calls.append((endpoint, params))
        return result(endpoint, [{"ts_code": "000001.SZ"}] * (100 if params["offset"] == 0 else 1))

    monkeypatch.setattr(provider, "_get", fake_get)
    monkeypatch.setattr("quant_platform.providers.replay.time.sleep", lambda _: None)
    output = provider.fetch_institutional_surveys("2026-01-01", "2026-01-31")
    assert len(output.rows) == 101
    assert [call[1]["offset"] for call in calls] == [0, 100]
    assert calls[0][1]["limit"] == 100
    assert calls[0][1]["start_date"] == "20260101"


def test_broker_recommendation_rejects_non_month():
    with pytest.raises(ValueError, match="YYYYMM"):
        ReplayProvider(api_key="x").fetch_broker_recommendations("2026-01")


def test_broker_recommendation_filters_replay_cache(monkeypatch):
    provider = ReplayProvider(api_key="x")
    captured = {}

    def fake_get(endpoint, params):
        captured.update({"endpoint": endpoint, **params})
        return result(endpoint, [
            {"month": "202607", "broker": "甲", "ts_code": "000001.SZ"},
            {"month": "202607", "broker": "甲", "ts_code": "000001.SZ"},
            {"month": "202608", "broker": "乙", "ts_code": "000002.SZ"},
        ])

    monkeypatch.setattr(provider, "_get", fake_get)
    output = provider.fetch_broker_recommendations("202607")
    assert captured == {"endpoint": "broker_recommend", "month": "202607", "limit": 7000}
    assert len(output.rows) == 1
    assert output.rows[0]["month"] == "202607"
    assert output.error_code == "replay_client_filter"


def test_pagination_rejects_repeated_full_page(monkeypatch):
    provider = ReplayProvider(api_key="x")
    monkeypatch.setattr(provider, "_get", lambda endpoint, params: result(endpoint, [{"id": index} for index in range(100)]))
    monkeypatch.setattr("quant_platform.providers.replay.time.sleep", lambda _: None)
    output = provider._fetch_paginated("example", {}, page_size=100)
    assert output.status == "failed"
    assert output.error_code == "pagination_repeated_page"


def test_normalizes_market_intelligence_contracts():
    assert _documented_yuan(999.25) == 999.25
    hot_money = normalize_hot_money_detail([{
        "trade_date": "20260801", "ts_code": "000001.SZ", "ts_name": "平安银行",
        "buy_amount": 12.5, "sell_amount": 3, "net_amount": 9.5,
        "hm_name": "示例游资", "hm_orgs": "示例营业部", "tag": "活跃",
    }])
    assert hot_money[0]["trade_date"] == "2026-08-01"
    assert hot_money[0]["buy_amount"] == 12.5

    survey_rows = normalize_institutional_surveys([{
        "ts_code": "000001.SZ", "name": "平安银行", "surv_date": "20260731",
        "fund_visitors": ["机构甲", "机构乙"], "rece_org": "机构甲", "content": "调研纪要",
    }])
    assert survey_rows[0]["symbol"] == "000001"
    assert survey_rows[0]["survey_date"] == "2026-07-31"
    assert "机构甲" in survey_rows[0]["fund_visitors"]
    assert len(survey_rows[0]["record_key"]) == 64

    broker_rows = normalize_broker_recommendations([{
        "month": "202607", "broker": "示例证券", "ts_code": "000001.SZ", "name": "平安银行",
    }])
    assert broker_rows[0]["month"] == "202607"
    assert broker_rows[0]["symbol"] == "000001"
