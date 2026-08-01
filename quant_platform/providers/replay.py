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
        data = payload.get("data") or {}
        fields = data.get("fields") or []
        items = data.get("items") or payload.get("items") or []
        rows = [dict(zip(fields, row, strict=False)) for row in items] if fields and items and isinstance(items[0], list) else items
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        return ProviderResult(self.name, endpoint, requested, requested, "success" if rows else "empty", rows, digest)

    def healthcheck(self) -> ProviderResult:
        return self._get("catalog", {})

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

    def fetch_moneyflow(self, endpoint: str, trade_date: str) -> ProviderResult:
        if endpoint not in {"moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc"}:
            raise ValueError("unsupported moneyflow endpoint")
        limit = 6000 if endpoint == "moneyflow_dc" else 5000 if endpoint == "moneyflow_ind_dc" else 100
        return self._get(endpoint, {"trade_date": trade_date.replace("-", ""), "limit": limit})
