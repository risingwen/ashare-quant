from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    trade_date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal
    suspended: bool = False


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    signal_date: str
    score: Decimal


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: Decimal
    cost: Decimal


@dataclass(slots=True)
class PortfolioState:
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)


class DailyEngine:
    """Deterministic T-close signal/T+1-open A-share simulation core."""

    def __init__(self, commission_rate: Decimal = Decimal("0.0003"), stamp_tax: Decimal = Decimal("0.0005"), slippage: Decimal = Decimal("0.001")) -> None:
        self.commission_rate = commission_rate
        self.stamp_tax = stamp_tax
        self.slippage = slippage

    @staticmethod
    def limit_rate(symbol: str) -> Decimal:
        if symbol.startswith(("300", "688")):
            return Decimal("0.20")
        if symbol.startswith(("8", "4", "9")):
            return Decimal("0.30")
        return Decimal("0.10")

    def can_buy(self, bar: Bar) -> bool:
        return not bar.suspended and bar.open < bar.previous_close * (Decimal("1") + self.limit_rate(bar.symbol))

    def can_sell(self, bar: Bar) -> bool:
        return not bar.suspended and bar.open > bar.previous_close * (Decimal("1") - self.limit_rate(bar.symbol))

    def buy_equal_weight(self, state: PortfolioState, bars: dict[str, Bar], signals: Iterable[Signal], max_positions: int = 10) -> list[dict]:
        selected = sorted(signals, key=lambda item: (-item.score, item.symbol))[:max_positions]
        slots = max(1, max_positions - len(state.positions))
        budget = state.cash / Decimal(slots)
        fills: list[dict] = []
        for signal in selected:
            if signal.symbol in state.positions or signal.symbol not in bars or not self.can_buy(bars[signal.symbol]):
                continue
            price = bars[signal.symbol].open * (Decimal("1") + self.slippage)
            # Reserve proportional commission before rounding to an A-share board lot.
            quantity = (budget / (price * (Decimal("1") + self.commission_rate)) // Decimal("100")) * Decimal("100")
            gross = price * quantity
            fee = max(Decimal("5"), gross * self.commission_rate) if quantity else Decimal("0")
            if quantity and gross + fee <= state.cash:
                state.cash -= gross + fee
                state.positions[signal.symbol] = Position(signal.symbol, quantity, (gross + fee) / quantity)
                fills.append({"symbol": signal.symbol, "side": "buy", "price": price, "quantity": quantity, "fees": fee})
        return fills
