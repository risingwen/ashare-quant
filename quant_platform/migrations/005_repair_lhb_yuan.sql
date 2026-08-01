-- Tushare top_list amount fields are already denominated in yuan. An earlier
-- heuristic multiplied values below 10,000,000 by 10,000. Restore authoritative
-- numbers from the retained provider payload; non-numeric/missing fields remain
-- unchanged so the migration is idempotent.
UPDATE market.lhb_record SET
  amount = CASE WHEN raw->>'amount' ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN (raw->>'amount')::numeric ELSE amount END,
  l_sell = CASE WHEN raw->>'l_sell' ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN (raw->>'l_sell')::numeric ELSE l_sell END,
  l_buy = CASE WHEN raw->>'l_buy' ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN (raw->>'l_buy')::numeric ELSE l_buy END,
  l_amount = CASE WHEN raw->>'l_amount' ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN (raw->>'l_amount')::numeric ELSE l_amount END,
  net_amount = CASE WHEN raw->>'net_amount' ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN (raw->>'net_amount')::numeric ELSE net_amount END,
  float_values = CASE WHEN raw->>'float_values' ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$' THEN (raw->>'float_values')::numeric ELSE float_values END
WHERE provider='tushare_replay' AND jsonb_typeof(raw)='object';
