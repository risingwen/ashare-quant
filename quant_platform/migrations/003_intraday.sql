CREATE TABLE IF NOT EXISTS market.minute_bar (
  symbol text NOT NULL REFERENCES market.instrument(symbol),
  trade_date date NOT NULL,
  trade_time timestamptz NOT NULL,
  freq text NOT NULL CHECK (freq IN ('1min','5min','15min','30min','60min')),
  open numeric(18,6) NOT NULL,
  high numeric(18,6) NOT NULL,
  low numeric(18,6) NOT NULL,
  close numeric(18,6) NOT NULL,
  volume numeric(24,4) NOT NULL,
  amount numeric(24,4) NOT NULL,
  provider text NOT NULL,
  batch_id bigint REFERENCES ops.data_batch(id),
  PRIMARY KEY(symbol, trade_time, freq),
  CHECK (high >= open AND high >= close AND high >= low),
  CHECK (low <= open AND low <= close),
  CHECK (volume >= 0 AND amount >= 0)
);
CREATE INDEX IF NOT EXISTS ix_minute_bar_date_symbol
  ON market.minute_bar(trade_date,symbol,trade_time);

CREATE TABLE IF NOT EXISTS ops.minute_backfill_progress (
  symbol text NOT NULL,
  trade_date date NOT NULL,
  freq text NOT NULL,
  status text NOT NULL,
  row_count integer NOT NULL DEFAULT 0,
  attempts integer NOT NULL DEFAULT 0,
  error text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(symbol,trade_date,freq)
);

CREATE TABLE IF NOT EXISTS market.price_limit (
  symbol text NOT NULL REFERENCES market.instrument(symbol),
  trade_date date NOT NULL,
  pre_close numeric(18,6),
  up_limit numeric(18,6) NOT NULL,
  down_limit numeric(18,6) NOT NULL,
  provider text NOT NULL,
  batch_id bigint REFERENCES ops.data_batch(id),
  PRIMARY KEY(symbol,trade_date)
);
CREATE INDEX IF NOT EXISTS ix_price_limit_date ON market.price_limit(trade_date);
