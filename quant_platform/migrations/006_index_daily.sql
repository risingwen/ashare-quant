CREATE TABLE IF NOT EXISTS market.index_daily (
  index_code text NOT NULL,
  index_name text NOT NULL,
  trade_date date NOT NULL,
  open numeric(18,6) NOT NULL,
  high numeric(18,6) NOT NULL,
  low numeric(18,6) NOT NULL,
  close numeric(18,6) NOT NULL,
  volume numeric(28,4),
  provider text NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (index_code, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_index_daily_date
  ON market.index_daily(trade_date);
