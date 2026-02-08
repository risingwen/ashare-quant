# hot_rank_top10_open Buy/Sell Plan

- Universe: previous-day hot rank top10.
- Entry: buy at open when conditions pass (skip one-word limit-up open).
- Exit logic: if not limit-up or rank falls below threshold, exit next day; otherwise hold.
- Risk controls: cash split count, position cap, trading fee/slippage config.

Source configs:

- `config/strategies/hot_rank_top10_open.yaml`
- `config/backtest_base.yaml`
