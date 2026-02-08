# hot_rank_drop7 Buy/Sell Plan

- Universe: previous-day hot rank top-N, with liquidity filters.
- Entry: intraday drop trigger (`drop_trigger`, board-aware settings).
- Exit priority: limit-down exit > hold on limit-up > normal close exit.
- Risk controls: position cap, single-position ratio, fees/slippage from strategy config.

Source configs:

- `config/strategies/hot_rank_drop7.yaml`
- `config/backtest_base.yaml`
