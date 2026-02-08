# hot_rank_rise2 Buy/Sell Plan

- Universe: previous-day hot rank top-N with basic liquidity checks.
- Entry: intraday rise trigger (`rise_trigger`) to capture momentum continuation.
- Exit priority: drop-stop exit > hold on limit-up > normal close exit.
- Risk controls: max positions, per-trade cash ratio, fees/slippage from base config.

Source configs:

- `config/strategies/hot_rank_rise2.yaml`
- `config/backtest_base.yaml`
