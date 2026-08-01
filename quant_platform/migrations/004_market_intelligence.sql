CREATE TABLE IF NOT EXISTS market.hot_money_directory (
  hot_money_name text PRIMARY KEY,
  description text,
  associated_orgs text,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market.hot_money_detail (
  trade_date date NOT NULL,
  symbol text NOT NULL,
  name text,
  buy_amount numeric,
  sell_amount numeric,
  net_amount numeric,
  hot_money_name text NOT NULL,
  associated_orgs text NOT NULL DEFAULT '',
  tag text,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (trade_date, symbol, hot_money_name, associated_orgs)
);
CREATE INDEX IF NOT EXISTS ix_hot_money_detail_symbol_date
  ON market.hot_money_detail(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS ix_hot_money_detail_name_date
  ON market.hot_money_detail(hot_money_name, trade_date DESC);

CREATE TABLE IF NOT EXISTS research.institutional_survey (
  record_key text PRIMARY KEY,
  symbol text NOT NULL,
  name text,
  survey_date date NOT NULL,
  fund_visitors text,
  receive_place text,
  receive_mode text,
  receive_org text,
  org_type text,
  company_receivers text,
  content text,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_institutional_survey_date_symbol
  ON research.institutional_survey(survey_date DESC, symbol);

CREATE TABLE IF NOT EXISTS research.broker_recommendation (
  month char(6) NOT NULL CHECK (month ~ '^[0-9]{6}$'),
  broker text NOT NULL,
  symbol text NOT NULL,
  name text,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (month, broker, symbol)
);
CREATE INDEX IF NOT EXISTS ix_broker_recommendation_symbol_month
  ON research.broker_recommendation(symbol, month DESC);
