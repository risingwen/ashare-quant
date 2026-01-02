---
agent: "copilot"
---

你是资深量化研究 + 数据工程助手。请用 Python 为 A 股做一个“统计回测/事件研究”（非投资建议），基于我现有的最近1年数据，评估以下策略的历史表现，并输出可复现的交易明细、组合净值、统计报告与图表，同时打印“模拟实盘风格”的操作日志。

# 0. 我已具备的数据（仅最近1年覆盖）
1) 东方财富“个股人气榜”历史数据：至少包含字段
   - trade_date（交易日，YYYY-MM-DD）
   - code（股票代码，6位字符串）
   - rank（当日排名，1..N）
   - （可选）hot_value（人气值/热度数值，如有）
   说明：策略使用“前一交易日(T-1)的人气排名”，避免未来函数。
2) 日线行情历史数据（同一时间范围）：至少包含字段
   - date, code, open, high, low, close, volume, amount
   说明：amount 为成交额，需统一单位为“元”。

# 1. 策略参数（必须全部参数化，并可用 CLI 指定）
- start_date / end_date：默认覆盖我现有最近1年
- hot_top_n：默认 100（可改 50）
- prev_amount_min：默认 1e9（10亿，单位：元）
- drop_trigger：默认 0.07（-7%）
- init_cash：默认 100000（10w）
- per_trade_cash_frac：默认 0.1（每笔 1/10 仓，即 1w 名义资金）
- fee_buy：买入佣金费率（默认 0.0002）
- fee_sell：卖出佣金费率（默认 0.0002）
- stamp_tax_sell：卖出印花税（默认 0.001，仅卖出）
- slippage_bps：滑点（默认 5 bps = 0.05%），用于成交价修正：
  buy_exec = buy_price * (1 + slippage_bps/10000)
  sell_exec = sell_price * (1 - slippage_bps/10000)

# 2. Universe（选股池）——严格用 T-1 信息
在交易日 T：
1) 读取 T-1 的人气榜，取 rank <= hot_top_n 的股票列表；
2) 过滤：amount_{T-1} >= prev_amount_min；
3) 过滤：剔除 ST/*ST/退市整理 等股票（若数据中有 is_st/name 标记则使用；若无，需实现一个“可插拔过滤器”，允许用户提供 st_list 文件或正则规则）；
4) 过滤：若 T 当日无行情或 volume==0（视为停牌/不可交易），则该股票在 T 不允许买入；
注意：所有过滤都要在报告中统计“因何原因过滤/跳过”的数量。

# 3. Entry（买入）——交易日 T 触发价成交
触发条件（仅用日线近似盘中）：
- 若 low_T <= close_{T-1} * (1 - drop_trigger)，认为当日盘中触发 -7%
成交价假设（你必须写清楚并严格执行）：
- buy_price = close_{T-1} * (1 - drop_trigger)   # 触发价成交
- buy_exec = buy_price * (1 + slippage_bps/10000)

资金规则：
- 初始资金 init_cash
- 每次触发买入名义资金 = init_cash * per_trade_cash_frac
- 当同一交易日 T 有多只触发：
  - 按 T-1 的 rank 从小到大（越热门越优先）依次下单
  - 若现金不足以覆盖下一笔名义资金（含费用），则该笔及后续当日信号跳过
- 股票数量（shares）按 A 股 100 股一手向下取整（必须实现），不足一手则跳过并记录原因

# 4. Exit（卖出）——次日收盘卖出；若次日收盘涨停则继续持有
基础退出：
- 默认在 T+1 收盘卖出：sell_price = close_{T+1}

“涨停不卖”规则（你要求的版本，必须精确定义）：
- 若 T+1 收盘价为涨停价（close_{T+1} == limit_up_{T+1}，允许按 0.01 元精度 round 后比较），则 T+1 不卖出，继续持有；
- 从 T+2 开始逐日检查：
  - 如果当日收盘价不是涨停（close_d < limit_up_d），则在该日收盘卖出（sell_price = close_d）；
  - 如果当日收盘仍为涨停（close_d == limit_up_d），继续持有到下一交易日；
- 若持仓期间遇到停牌/无行情/volume==0 导致无法卖出，则顺延到下一个可交易日再按上述规则判断并卖出；
- 每笔交易必须输出 exit_reason（例如：sell_t1_close / hold_limitup / sell_first_non_limitup_close / suspend_delay）。

涨停价计算（必须实现为函数且可配置）：
- 需要根据股票所属板块推断涨跌幅限制（例如主板10%、创业/科创20%、北交所30%等），并提供可配置映射；
- ST 的涨跌幅限制可能不同，必须做成可配置开关与映射（例如 st_limit=0.05 或其他），并在报告里打印本次回测采用的涨停规则；
- 计算方法：limit_up = round(prev_close * (1 + limit), 2)（0.01 元精度可配置）。

# 5. 回测输出（必须生成）
1) trades 明细（CSV/Parquet）字段至少包含：
   - entry_date(T), code, rank_t1, amount_t1, prev_close, low_T, trigger
   - buy_price, buy_exec, buy_shares, buy_cost, cash_after_buy
   - exit_date, exit_reason, prev_close_exit, limit_up_exit, close_exit
   - sell_price, sell_exec, sell_proceed, cash_after_sell
   - gross_pnl, net_pnl, net_pnl_pct, hold_days
2) 组合净值（按日）：
   - date, cash, position_value, nav, daily_return, exposure（持仓占用）
3) 统计报告（Markdown）：
   - 数据覆盖率：人气榜覆盖交易日比例、行情覆盖比例
   - 信号数、成交数、跳过数（资金不足/一手不足/停牌/ST过滤/缺数据等）
   - 胜率、均值/中位数/分位数收益、最大回撤、持仓天数分布
   - 分组统计：
     - 按 rank 分组（例如 1-20/21-50/51-100，需随 hot_top_n 自适应）
     - 按 amount_{T-1} 分桶（10-20亿/20-50亿/50亿+）
4) 图表（matplotlib，不用 seaborn）：
   - 单笔 net_pnl_pct 分布直方图
   - 组合净值曲线
   - 持仓天数分布（因为涨停不卖会拉长持仓）

# 6. “模拟实盘风格”日志（你特别要求，必须实现）
要求：
- 使用 logging，同时输出到控制台与 logs/ 目录文件（例如 logs/trades_YYYYMMDD.log）
- 每次事件必须打印一行结构化日志（建议 JSON 或 key=value）：
  - BUY：日期、code、rank、买入阈值、buy_exec、shares、费用、现金余额、原因（触发-7）
  - HOLD：日期、code、原因（close==limit_up，不卖）
  - SELL：日期、code、sell_exec、shares、收益、原因（T+1卖/首次非涨停收盘卖/停牌顺延卖）
- 日志要能用于“复盘回放”，即按时间排序可重现每笔交易。

# 7. 工程实现要求（必须遵守）
- 所有脚本必须有“脚本名称”、argparse 参数、用法示例；
- 支持断点续跑：数据读取优先从本地 Parquet（或 DuckDB view），回测结果可增量写入；
- 明确列名映射：如果源数据列名不同（例如中文列），必须统一到策略使用的标准列名；
- 输出中必须写清楚所有关键假设（例如：日线近似盘中触发、触发价成交、涨停判断用收盘价等）。
