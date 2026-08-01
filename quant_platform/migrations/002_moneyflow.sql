CREATE TABLE IF NOT EXISTS market.stock_moneyflow (
  trade_date date NOT NULL,
  symbol text NOT NULL,
  name text,
  close numeric,
  pct_change numeric,
  net_amount numeric,
  net_amount_rate numeric,
  buy_elg_amount numeric,
  buy_elg_amount_rate numeric,
  buy_lg_amount numeric,
  buy_lg_amount_rate numeric,
  buy_md_amount numeric,
  buy_md_amount_rate numeric,
  buy_sm_amount numeric,
  buy_sm_amount_rate numeric,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (trade_date, symbol)
);
CREATE INDEX IF NOT EXISTS ix_stock_moneyflow_symbol_date ON market.stock_moneyflow(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS ix_stock_moneyflow_date_net ON market.stock_moneyflow(trade_date DESC, net_amount DESC);

CREATE TABLE IF NOT EXISTS market.sector_moneyflow (
  trade_date date NOT NULL,
  sector_code text NOT NULL,
  name text NOT NULL,
  content_type text,
  rank integer,
  close numeric,
  pct_change numeric,
  net_amount numeric,
  net_amount_rate numeric,
  buy_elg_amount numeric,
  buy_elg_amount_rate numeric,
  buy_lg_amount numeric,
  buy_lg_amount_rate numeric,
  buy_md_amount numeric,
  buy_md_amount_rate numeric,
  buy_sm_amount numeric,
  buy_sm_amount_rate numeric,
  lead_stock text,
  provider text NOT NULL DEFAULT 'tushare_replay',
  batch_id bigint REFERENCES ops.data_batch(id),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (trade_date, sector_code)
);
CREATE INDEX IF NOT EXISTS ix_sector_moneyflow_code_date ON market.sector_moneyflow(sector_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS ix_sector_moneyflow_date_net ON market.sector_moneyflow(trade_date DESC, net_amount DESC);
