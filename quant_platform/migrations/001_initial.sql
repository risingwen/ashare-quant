CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS popularity;
CREATE SCHEMA IF NOT EXISTS research;
CREATE SCHEMA IF NOT EXISTS portfolio;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS market.instrument (
  symbol text PRIMARY KEY, name text NOT NULL, exchange text NOT NULL,
  board text, list_date date, delist_date date, active boolean NOT NULL DEFAULT true,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS market.trade_calendar (
  trade_date date PRIMARY KEY, is_open boolean NOT NULL, previous_open_date date, next_open_date date
);
CREATE TABLE IF NOT EXISTS ops.data_batch (
  id bigserial PRIMARY KEY, provider text NOT NULL, dataset text NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT now(), source_as_of timestamptz,
  status text NOT NULL CHECK (status IN ('running','success','empty','stale','unauthorized','rate_limited','failed','quarantined')),
  row_count integer NOT NULL DEFAULT 0, raw_hash text, error_code text, error_message text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb, finished_at timestamptz
);
CREATE TABLE IF NOT EXISTS ops.data_issue (
  id bigserial PRIMARY KEY, batch_id bigint REFERENCES ops.data_batch(id), severity text NOT NULL,
  code text NOT NULL, message text NOT NULL, details jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS market.daily_bar (
  symbol text NOT NULL REFERENCES market.instrument(symbol), trade_date date NOT NULL,
  open numeric(18,6) NOT NULL, high numeric(18,6) NOT NULL, low numeric(18,6) NOT NULL,
  close numeric(18,6) NOT NULL, volume numeric(24,4) NOT NULL, amount numeric(24,4) NOT NULL,
  pct_change numeric(12,6), turnover numeric(12,6), provider text NOT NULL, batch_id bigint REFERENCES ops.data_batch(id),
  PRIMARY KEY(symbol, trade_date)
) PARTITION BY RANGE (trade_date);
DO $$ BEGIN
  FOR y IN 1990..2035 LOOP
    EXECUTE format('CREATE TABLE IF NOT EXISTS market.daily_bar_%s PARTITION OF market.daily_bar FOR VALUES FROM (%L) TO (%L)', y, y||'-01-01', (y+1)||'-01-01');
  END LOOP;
END $$;
CREATE INDEX IF NOT EXISTS ix_daily_bar_date ON market.daily_bar(trade_date);
CREATE TABLE IF NOT EXISTS market.lhb_record (
  trade_date date NOT NULL, symbol text NOT NULL, name text NOT NULL, close numeric, pct_change numeric,
  turnover_rate numeric, amount numeric, l_sell numeric, l_buy numeric, l_amount numeric,
  net_amount numeric, net_rate numeric, amount_rate numeric, float_values numeric, reason text,
  provider text NOT NULL, batch_id bigint REFERENCES ops.data_batch(id), raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(trade_date,symbol,reason)
);
CREATE INDEX IF NOT EXISTS ix_lhb_record_symbol_date ON market.lhb_record(symbol,trade_date DESC);
CREATE TABLE IF NOT EXISTS market.lhb_seat (
  trade_date date NOT NULL, symbol text NOT NULL, seat_name text NOT NULL, side text NOT NULL,
  buy numeric, buy_rate numeric, sell numeric, sell_rate numeric, net_buy numeric, reason text,
  provider text NOT NULL, batch_id bigint REFERENCES ops.data_batch(id), raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(trade_date,symbol,seat_name,side,reason)
);
CREATE INDEX IF NOT EXISTS ix_lhb_seat_name_date ON market.lhb_seat(seat_name,trade_date DESC);

CREATE TABLE IF NOT EXISTS popularity.snapshot (
  id bigserial PRIMARY KEY, provider text NOT NULL, endpoint text NOT NULL, market text NOT NULL DEFAULT 'A',
  category text NOT NULL, trade_date date NOT NULL, snapshot_time timestamptz NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(), status text NOT NULL, row_count integer NOT NULL,
  batch_id bigint REFERENCES ops.data_batch(id), raw_hash text,
  UNIQUE(provider, endpoint, market, category, snapshot_time)
);
CREATE TABLE IF NOT EXISTS popularity.snapshot_item (
  snapshot_id bigint NOT NULL REFERENCES popularity.snapshot(id) ON DELETE CASCADE,
  symbol text NOT NULL, name text, rank integer NOT NULL CHECK(rank > 0), heat numeric,
  rank_change integer, rank_reason text, concept text, is_new boolean, raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(snapshot_id, symbol)
);
CREATE INDEX IF NOT EXISTS ix_popularity_item_symbol ON popularity.snapshot_item(symbol);
CREATE MATERIALIZED VIEW IF NOT EXISTS popularity.daily_close AS
SELECT DISTINCT ON (s.provider,s.endpoint,s.category,s.trade_date,i.symbol)
 s.provider,s.endpoint,s.category,s.trade_date,s.snapshot_time,i.*
FROM popularity.snapshot s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
WHERE s.status='success'
ORDER BY s.provider,s.endpoint,s.category,s.trade_date,i.symbol,s.snapshot_time DESC;
CREATE UNIQUE INDEX IF NOT EXISTS ux_popularity_daily_close ON popularity.daily_close(provider,endpoint,category,trade_date,symbol);

CREATE TABLE IF NOT EXISTS research.strategy_template (
  key text PRIMARY KEY, name text NOT NULL, version integer NOT NULL DEFAULT 1,
  parameter_schema jsonb NOT NULL, enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS research.strategy_run (
  id uuid PRIMARY KEY, template_key text REFERENCES research.strategy_template(key), template_version integer NOT NULL,
  parameters jsonb NOT NULL, fingerprint text NOT NULL UNIQUE, data_version text NOT NULL, code_version text,
  start_date date NOT NULL, end_date date NOT NULL, status text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, error text
);
CREATE TABLE IF NOT EXISTS research.signal (
  run_id uuid REFERENCES research.strategy_run(id) ON DELETE CASCADE, trade_date date NOT NULL,
  symbol text NOT NULL, score numeric, rank integer, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(run_id,trade_date,symbol)
);
CREATE TABLE IF NOT EXISTS research.backtest_trade (
  id bigserial PRIMARY KEY, run_id uuid REFERENCES research.strategy_run(id) ON DELETE CASCADE,
  symbol text NOT NULL, signal_date date NOT NULL, entry_date date, exit_date date,
  quantity numeric, entry_price numeric, exit_price numeric, fees numeric NOT NULL DEFAULT 0,
  pnl numeric, return_pct numeric, status text NOT NULL
);
CREATE TABLE IF NOT EXISTS research.backtest_daily (
  run_id uuid REFERENCES research.strategy_run(id) ON DELETE CASCADE, trade_date date NOT NULL,
  cash numeric NOT NULL, market_value numeric NOT NULL, equity numeric NOT NULL, daily_return numeric,
  drawdown numeric, PRIMARY KEY(run_id,trade_date)
);
CREATE TABLE IF NOT EXISTS research.performance_metric (
  run_id uuid REFERENCES research.strategy_run(id) ON DELETE CASCADE, key text NOT NULL, value numeric,
  PRIMARY KEY(run_id,key)
);

CREATE TABLE IF NOT EXISTS portfolio.portfolio (
  id uuid PRIMARY KEY, name text NOT NULL, initial_cash numeric NOT NULL, cash numeric NOT NULL,
  strategy_template_key text NOT NULL, parameters jsonb NOT NULL, active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS portfolio.position (
  portfolio_id uuid REFERENCES portfolio.portfolio(id), symbol text NOT NULL, quantity numeric NOT NULL,
  average_cost numeric NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(portfolio_id,symbol)
);
CREATE TABLE IF NOT EXISTS portfolio."order" (
  id uuid PRIMARY KEY, portfolio_id uuid REFERENCES portfolio.portfolio(id), symbol text NOT NULL,
  signal_date date NOT NULL, scheduled_date date NOT NULL, side text NOT NULL CHECK(side IN ('buy','sell')),
  quantity numeric, status text NOT NULL, reason text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS portfolio.fill (
  id bigserial PRIMARY KEY, order_id uuid REFERENCES portfolio."order"(id), trade_date date NOT NULL,
  price numeric NOT NULL, quantity numeric NOT NULL, fees numeric NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS portfolio.valuation (
  portfolio_id uuid REFERENCES portfolio.portfolio(id), trade_date date NOT NULL, cash numeric NOT NULL,
  market_value numeric NOT NULL, equity numeric NOT NULL, daily_return numeric, drawdown numeric,
  PRIMARY KEY(portfolio_id,trade_date)
);
CREATE TABLE IF NOT EXISTS ops.job_run (
  id uuid PRIMARY KEY, job_name text NOT NULL, status text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz, details jsonb NOT NULL DEFAULT '{}'::jsonb, error text
);
CREATE TABLE IF NOT EXISTS ops.backfill_progress (
  dataset text NOT NULL, trade_date date NOT NULL, status text NOT NULL,
  row_count integer NOT NULL DEFAULT 0, attempts integer NOT NULL DEFAULT 0,
  error text, updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(dataset,trade_date)
);
INSERT INTO research.strategy_template(key,name,version,parameter_schema) VALUES
('popularity_breakout','人气排名突破',1,'{"rank_max":{"type":"integer","default":10},"max_positions":{"type":"integer","default":10}}'),
('popularity_volume','人气量价共振',1,'{"rank_max":{"type":"integer","default":30},"min_amount":{"type":"number","default":1000000000}}'),
('new_high_strength','历史新高强势',1,'{"window":{"type":"integer","default":120},"min_amount":{"type":"number","default":1000000000}}')
ON CONFLICT(key) DO UPDATE SET name=excluded.name,parameter_schema=excluded.parameter_schema;
