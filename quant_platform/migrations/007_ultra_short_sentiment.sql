CREATE TABLE IF NOT EXISTS market.daily_basic (
  symbol text NOT NULL REFERENCES market.instrument(symbol),
  trade_date date NOT NULL,
  close numeric,
  turnover_rate numeric,
  turnover_rate_f numeric,
  volume_ratio numeric,
  pe numeric,
  pe_ttm numeric,
  pb numeric,
  ps numeric,
  ps_ttm numeric,
  dv_ratio numeric,
  dv_ttm numeric,
  total_share numeric,
  float_share numeric,
  free_share numeric,
  total_mv numeric,
  circ_mv numeric,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_daily_basic_date_turnover
  ON market.daily_basic(trade_date DESC, turnover_rate DESC);

CREATE TABLE IF NOT EXISTS market.adj_factor (
  symbol text NOT NULL REFERENCES market.instrument(symbol),
  trade_date date NOT NULL,
  adj_factor numeric NOT NULL,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  PRIMARY KEY (symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_adj_factor_date ON market.adj_factor(trade_date DESC);

CREATE TABLE IF NOT EXISTS market.limit_event (
  trade_date date NOT NULL,
  symbol text NOT NULL,
  event_type text NOT NULL CHECK (event_type IN ('U', 'D', 'Z')),
  name text,
  industry text,
  close numeric,
  pct_change numeric,
  amount numeric,
  limit_amount numeric,
  float_mv numeric,
  total_mv numeric,
  turnover_ratio numeric,
  fd_amount numeric,
  first_time text,
  last_time text,
  open_times integer,
  up_stat text,
  limit_times integer,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (trade_date, symbol, event_type)
);
CREATE INDEX IF NOT EXISTS ix_limit_event_symbol_date
  ON market.limit_event(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS ix_limit_event_date_type
  ON market.limit_event(trade_date DESC, event_type);

CREATE TABLE IF NOT EXISTS market.limit_streak (
  trade_date date NOT NULL,
  symbol text NOT NULL,
  name text,
  streak integer NOT NULL,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (trade_date, symbol)
);
CREATE INDEX IF NOT EXISTS ix_limit_streak_date_streak
  ON market.limit_streak(trade_date DESC, streak DESC);

CREATE TABLE IF NOT EXISTS market.market_breadth (
  trade_date date PRIMARY KEY,
  up_num integer NOT NULL,
  down_num integer NOT NULL,
  flat_num integer NOT NULL,
  traded_num integer NOT NULL,
  limit_up_num integer NOT NULL DEFAULT 0,
  limit_down_num integer NOT NULL DEFAULT 0,
  broken_limit_num integer NOT NULL DEFAULT 0,
  total_amount numeric,
  is_ice boolean NOT NULL,
  provider text NOT NULL DEFAULT 'computed_from_tushare_replay',
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_market_breadth_ice_date
  ON market.market_breadth(is_ice, trade_date DESC);
