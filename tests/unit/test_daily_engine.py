from decimal import Decimal

from quant_platform.research.engine import Bar, DailyEngine, PortfolioState, Signal


def bar(symbol="600000", open_price="10", previous="10", suspended=False):
    return Bar(symbol, "2026-01-02", Decimal(open_price), Decimal(open_price), Decimal(open_price), Decimal(open_price), Decimal(previous), suspended)


def test_limit_rules_by_board():
    engine = DailyEngine()
    assert engine.limit_rate("600000") == Decimal("0.10")
    assert engine.limit_rate("300001") == Decimal("0.20")
    assert engine.limit_rate("688001") == Decimal("0.20")
    assert engine.limit_rate("830001") == Decimal("0.30")


def test_cannot_buy_limit_up_or_suspended():
    engine = DailyEngine()
    assert not engine.can_buy(bar(open_price="11"))
    assert not engine.can_buy(bar(suspended=True))
    assert engine.can_buy(bar(open_price="10.99"))


def test_equal_weight_buys_board_lots_and_charges_fee():
    engine = DailyEngine(slippage=Decimal("0"))
    state = PortfolioState(Decimal("100000"))
    fills = engine.buy_equal_weight(state, {"600000": bar()}, [Signal("600000", "2026-01-01", Decimal("1"))], max_positions=1)
    assert fills[0]["quantity"] == Decimal("9900")
    assert state.cash < Decimal("1000")
    assert state.positions["600000"].quantity == Decimal("9900")
