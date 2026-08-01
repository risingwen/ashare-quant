from datetime import UTC, datetime

from quant_platform.ingest import normalize_popularity, select_latest_popularity_snapshot
from quant_platform.providers.base import ProviderResult


def test_normalizes_replay_popularity_shape():
    result = ProviderResult("replay", "dc_hot", datetime.now(UTC), datetime.now(UTC), "success", [
        {"ts_code": "600000.SH", "ts_name": "浦发银行", "rank": 3, "hot": 88}
    ])
    rows = normalize_popularity(result, "2026-01-02")
    assert rows[0]["symbol"] == "600000"
    assert rows[0]["rank"] == 3
    assert rows[0]["heat"] == 88


def test_normalizes_ths_popularity_fields():
    result = ProviderResult("replay", "ths_hot", datetime.now(UTC), datetime.now(UTC), "success", [
        {"ts_code": "000001.SZ", "ts_name": "平安银行", "rank": 2, "hot": 99,
         "concept": "银行", "rank_reason": "热度上升", "rank_time": "2026-01-02 15:00:05"}
    ])
    rows = normalize_popularity(result, "2026-01-02")
    assert rows[0]["symbol"] == "000001"
    assert rows[0]["concept"] == "银行"
    assert rows[0]["rank_reason"] == "热度上升"


def test_selects_only_latest_frame_from_historical_final_response():
    items = [
        {"symbol": "000001", "rank": 1, "rank_time": "2025-08-08 21:30:01"},
        {"symbol": "000002", "rank": 1, "rank_time": "2025-08-08 22:30:01"},
        {"symbol": "000003", "rank": 2, "rank_time": "2025-08-08 22:30:42"},
    ]
    selected = select_latest_popularity_snapshot(items)
    assert [item["symbol"] for item in selected] == ["000002", "000003"]


def test_deduplicates_conflicting_ths_rank_by_heat():
    items = [
        {"symbol": "000001", "rank": 14, "heat": 10, "rank_time": "2025-08-19 22:42:54"},
        {"symbol": "000002", "rank": 14, "heat": 30, "rank_time": "2025-08-19 22:42:54"},
    ]
    selected = select_latest_popularity_snapshot(items)
    assert [item["symbol"] for item in selected] == ["000002"]
