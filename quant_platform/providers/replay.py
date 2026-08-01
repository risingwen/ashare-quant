from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

import requests

from ..config import settings
from .base import ProviderResult


class ReplayProvider:
    name = "tushare_replay"

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or settings.tushare_replay_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.tushare_replay_api_key
        self.session = requests.Session()
        self.session.trust_env = False

    def _get(self, endpoint: str, params: dict[str, Any]) -> ProviderResult:
        requested = datetime.now(UTC)
        if not self.api_key:
            return ProviderResult(self.name, endpoint, requested, None, "unauthorized", error_code="missing_api_key")
        response = None
        last_error = None
        for attempt in range(3):
            try:
                response = self.session.get(
                    f"{self.base_url}/{endpoint}", headers={"X-API-Key": self.api_key}, params=params, timeout=(5, 40)
                )
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
            except requests.RequestException as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
        if response is None:
            return ProviderResult(self.name, endpoint, requested, None, "failed", error_code="network", error_message=str(last_error))
        if response.status_code in {401, 403}:
            return ProviderResult(self.name, endpoint, requested, None, "unauthorized", error_code=f"http_{response.status_code}")
        if response.status_code == 429:
            return ProviderResult(self.name, endpoint, requested, None, "rate_limited", error_code="http_429")
        if response.status_code >= 400:
            return ProviderResult(self.name, endpoint, requested, None, "failed", error_code=f"http_{response.status_code}", error_message=response.text[:300])
        payload = response.json()
        data = payload.get("data")
        if isinstance(data, dict):
            fields = data.get("fields") or []
            items = data.get("items") or payload.get("items") or []
            rows = (
                [dict(zip(fields, row, strict=False)) for row in items]
                if fields and items and isinstance(items[0], list)
                else items
            )
        elif isinstance(data, list):
            # Some Replay endpoints (notably trade calendar and price limits)
            # return a list directly instead of Tushare's fields/items envelope.
            rows = data
        else:
            rows = payload.get("items") or []
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        return ProviderResult(self.name, endpoint, requested, requested, "success" if rows else "empty", rows, digest)

    def healthcheck(self) -> ProviderResult:
        return self._get("catalog", {})

    def _fetch_paginated(
        self,
        endpoint: str,
        params: dict[str, Any],
        page_size: int,
        max_pages: int = 200,
    ) -> ProviderResult:
        """Fetch standard Tushare offset pages without exceeding endpoint limits."""
        combined: list[dict[str, Any]] = []
        first: ProviderResult | None = None
        seen_pages: set[str] = set()
        for page_number in range(max_pages):
            page = self._get(endpoint, {**params, "limit": page_size, "offset": page_number * page_size})
            first = first or page
            if page.status == "empty":
                break
            if page.status != "success":
                return page
            page_hash = hashlib.sha256(
                json.dumps(page.rows, sort_keys=True, ensure_ascii=False, default=str).encode()
            ).hexdigest()
            if page_hash in seen_pages:
                return ProviderResult(
                    self.name,
                    endpoint,
                    first.requested_at,
                    first.source_as_of,
                    "failed",
                    error_code="pagination_repeated_page",
                    error_message=f"endpoint repeated a full page at offset {page_number * page_size}",
                )
            seen_pages.add(page_hash)
            combined.extend(page.rows)
            if len(page.rows) < page_size:
                break
            time.sleep(0.15)
        else:
            assert first is not None
            return ProviderResult(
                self.name,
                endpoint,
                first.requested_at,
                first.source_as_of,
                "failed",
                error_code="pagination_page_limit",
                error_message=f"endpoint exceeded {max_pages} pages",
            )
        if not combined:
            assert first is not None
            return first
        assert first is not None
        digest = hashlib.sha256(
            json.dumps(combined, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()
        return ProviderResult(
            self.name,
            endpoint,
            first.requested_at,
            first.source_as_of,
            "success",
            combined,
            digest,
        )

    def _fetch_popularity_archive(self, endpoint: str, params: dict[str, Any]) -> ProviderResult:
        combined: list[dict[str, Any]] = []
        first: ProviderResult | None = None
        for page_number in range(10):
            page = self._get(endpoint, {**params, "is_new": "N", "limit": 2000, "offset": page_number * 2000})
            first = first or page
            if page.status == "empty":
                break
            if page.status != "success":
                return page
            combined.extend(page.rows)
            if len(page.rows) < 2000:
                break
            time.sleep(0.15)
        if not combined:
            return first  # type: ignore[return-value]
        digest = hashlib.sha256(json.dumps(combined, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        return ProviderResult(self.name, endpoint, first.requested_at, first.source_as_of, "success", combined, digest)

    def fetch_popularity(self, endpoint: str, trade_date: str) -> ProviderResult:
        if endpoint not in {"dc_hot", "ths_hot"}:
            raise ValueError("endpoint must be dc_hot or ths_hot")
        # The product only needs the official final Top100. One request per
        # source/date is faster and avoids storing redundant intraday frames.
        params = {"trade_date": trade_date.replace("-", ""), "is_new": "Y", "limit": 2000}
        if endpoint == "dc_hot":
            params.update({"market": "A股市场", "hot_type": "人气榜"})
        else:
            params.update({"market": "热股"})
        result = self._get(endpoint, params)
        published_ranks = {int(row["rank"]) for row in result.rows if str(row.get("rank") or "").isdigit()}
        if result.status == "empty" or (result.status == "success" and len(published_ranks) < 90):
            # Rare historical THS dates omit is_new=Y while the archive exists.
            # Fetch that day once; ingestion keeps only its latest rank_time.
            archived = self._fetch_popularity_archive(endpoint, params)
            archived_ranks = {int(row["rank"]) for row in archived.rows if str(row.get("rank") or "").isdigit()}
            if archived.status == "success" and len(archived_ranks) > len(published_ranks):
                archived.error_code = "archived_final_fallback"
                archived.error_message = "final response incomplete; latest candidate per rank selected from archive"
                return archived
        return result

    def fetch_popularity_archive(self, endpoint: str, trade_date: str) -> ProviderResult:
        if endpoint not in {"dc_hot", "ths_hot"}:
            raise ValueError("endpoint must be dc_hot or ths_hot")
        params: dict[str, Any] = {"trade_date": trade_date.replace("-", "")}
        if endpoint == "dc_hot":
            params.update({"market": "A股市场", "hot_type": "人气榜"})
        else:
            params.update({"market": "热股"})
        return self._fetch_popularity_archive(endpoint, params)

    def fetch_minute_bars(self, ts_code: str, trade_date: str, freq: str = "1min") -> ProviderResult:
        if freq not in {"1min", "5min", "15min", "30min", "60min"}:
            raise ValueError("unsupported minute frequency")
        params = {
            "ts_code": ts_code,
            "freq": freq,
            "start_date": f"{trade_date} 09:00:00",
            "end_date": f"{trade_date} 15:30:00",
            "limit": 8000,
        }
        result = self._get("stk_mins", params)
        # Replay can transiently shed load as HTTP 200 with an empty list. A
        # stock-day should not become terminally unavailable on one such reply.
        for attempt in range(2):
            if result.status != "empty":
                break
            time.sleep(0.5 * (attempt + 1))
            result = self._get("stk_mins", params)
        return result

    def fetch_trade_calendar(self, start: str, end: str, exchange: str = "SSE") -> ProviderResult:
        return self._get("trade_cal", {
            "exchange": exchange,
            "start_date": start.replace("-", ""),
            "end_date": end.replace("-", ""),
            "limit": 10000,
        })

    def fetch_price_limits(self, trade_date: str) -> ProviderResult:
        return self._get("stk_limit", {"trade_date": trade_date.replace("-", ""), "limit": 10000})

    def fetch_daily_bars(self, start: str, end: str, symbols: list[str] | None = None) -> ProviderResult:
        params: dict[str, Any] = {"start_date": start.replace("-", ""), "end_date": end.replace("-", ""), "limit": 7000}
        if symbols and len(symbols) == 1:
            params["ts_code"] = symbols[0]
        return self._get("daily", params)

    def fetch_daily_market(self, trade_date: str) -> ProviderResult:
        return self._get("daily", {"trade_date": trade_date.replace("-", ""), "limit": 7000})

    def fetch_lhb(self, endpoint: str, trade_date: str) -> ProviderResult:
        if endpoint not in {"top_list", "top_inst"}:
            raise ValueError("endpoint must be top_list or top_inst")
        return self._get(endpoint, {"trade_date": trade_date.replace("-", ""), "limit": 5000})

    def fetch_hot_money_directory(self) -> ProviderResult:
        return self._get("hm_list", {"limit": 1000})

    def fetch_hot_money_detail(self, trade_date: str) -> ProviderResult:
        return self._fetch_paginated(
            "hm_detail",
            {"trade_date": trade_date.replace("-", "")},
            page_size=2000,
        )

    def fetch_institutional_surveys(
        self,
        start: str,
        end: str,
        ts_code: str | None = None,
    ) -> ProviderResult:
        params: dict[str, Any] = {
            "start_date": start.replace("-", ""),
            "end_date": end.replace("-", ""),
        }
        if ts_code:
            params["ts_code"] = ts_code
        return self._fetch_paginated("stk_surv", params, page_size=100)

    def fetch_broker_recommendations(self, month: str) -> ProviderResult:
        if len(month) != 6 or not month.isdigit():
            raise ValueError("month must use YYYYMM format")
        # The Replay proxy currently ignores offset (and may include an adjacent
        # month) for this endpoint. It does, however, return its complete cached
        # set when asked above the 5000-row server cap. Filter and de-duplicate
        # that bounded response instead of accepting repeated pages as complete.
        result = self._get("broker_recommend", {"month": month, "limit": 7000})
        if result.status != "success":
            return result
        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in result.rows:
            row_month = str(row.get("month") or "").replace("-", "")[:6]
            if row_month != month:
                continue
            key = (row_month, str(row.get("broker") or ""), str(row.get("ts_code") or ""))
            unique[key] = row
        filtered = list(unique.values())
        digest = hashlib.sha256(
            json.dumps(filtered, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()
        return ProviderResult(
            self.name,
            "broker_recommend",
            result.requested_at,
            result.source_as_of,
            "success" if filtered else "empty",
            filtered,
            digest,
            error_code="replay_client_filter",
            error_message="Replay offset is ignored; response filtered and de-duplicated by requested month",
        )

    def fetch_moneyflow(self, endpoint: str, trade_date: str) -> ProviderResult:
        if endpoint not in {"moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc"}:
            raise ValueError("unsupported moneyflow endpoint")
        limit = 6000 if endpoint == "moneyflow_dc" else 5000 if endpoint == "moneyflow_ind_dc" else 100
        return self._get(endpoint, {"trade_date": trade_date.replace("-", ""), "limit": limit})
