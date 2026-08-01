from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class ProviderResult:
    provider: str
    dataset: str
    requested_at: datetime
    source_as_of: datetime | None
    status: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class MarketDataProvider(Protocol):
    def fetch_daily_bars(self, start: str, end: str, symbols: list[str] | None = None) -> ProviderResult: ...
    def fetch_popularity(self, endpoint: str, trade_date: str) -> ProviderResult: ...
    def fetch_moneyflow(self, endpoint: str, trade_date: str) -> ProviderResult: ...
    def healthcheck(self) -> ProviderResult: ...
