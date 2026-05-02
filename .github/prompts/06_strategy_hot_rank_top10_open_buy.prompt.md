---
agent: "copilot"
---

你是资深量化研究 + 数据工程助手。请用 Python 为 A 股做一个"统计回测/事件研究"（非投资建议），基于我现有的最近1年数据，评估以下策略的历史表现，并输出可复现的交易明细、组合净值、统计报告，同时打印"模拟实盘风格"的操作日志。

# 0. 策略概述
**策略名称**: 人气榜TOP10开盘买入策略 (hot_rank_top10_open)

**核心思想**: 每日开盘买入人气排名前10的强势股，利用市场情绪和人气聚集效应，追踪最热门股票的短期表现。

**策略特点**:
| 维度 | 本策略 (hot_rank_top10_open) |
|------|------------------------------|
| 买入时机 | 开盘价买入 |
| 选股范围 | 人气前10名（极度严格） |
| 买入限制 | 一字涨停不买（无法成交） |
| 卖出条件 | 次日不涨停 OR 人气跌破50 |
| 资金管理 | 10万分2份（可配置1/3/4份） |
| 交易风格 | 追热点、快进快出 |

**与现有策略的区别**:
| 维度 | 原策略 (hot_rank_drop7) | rise2策略 | 本策略 (top10_open) |
|------|------------------------|-----------|---------------------|
| 买入逻辑 | 下跌-7%抄底 | 上涨+2%追涨 | 开盘直接买入 |
| 选股范围 | 人气前100 | 人气前50 | 人气前10 |
| 买入价格 | 触发价(-7%) | 触发价(+2%) | 开盘价 |
| 卖出条件 | 涨停不卖+跌停卖 | 涨停不卖+跌停卖 | 不涨停或人气跌破50 |

# 1. 项目架构说明
请严格遵循现有项目架构：
- **特征数据**: `data/processed/features/daily_features_v1.parquet`
- **回测结果**: `data/backtest/trades/` 和 `data/backtest/portfolio/`
- **策略配置**: `config/strategies/hot_rank_top10_open.yaml`
- **回测脚本**: `scripts/backtest_hot_rank_top10_open_strategy.py`

# 2. Universe（选股池）——严格用 T-1 信息
在交易日 T：
1. 读取 T-1 的人气榜，取 **rank <= 10** 的股票列表；
2. 过滤：剔除 ST/*ST/退市整理 等股票；
3. 过滤：若 T 当日无行情或 volume==0（停牌/不可交易），则跳过；
4. **过滤：剔除一字涨停（open == high == low == close 且涨停）**；
   - 一字涨停无法买入，必须跳过
   - 判断条件：`open == high == low` 且 `open >= prev_close * (1 + limit_pct - 0.001)`

# 3. Entry（买入）——开盘价买入

## 3.1 触发条件
```
条件1: T-1 人气排名 <= 10
条件2: 非一字涨停（可以成交）
条件3: 非停牌（volume > 0）
```

满足以上全部条件即触发买入。

## 3.2 成交价假设
```python
buy_price = open_T           # 当日开盘价买入
buy_exec = buy_price * (1 + slippage_bps/10000)  # 加滑点
```

## 3.3 资金规则
- 初始资金 init_cash = 100,000
- **资金分份数 cash_splits = 2**（可配置为1/2/3/4）
- 每份资金 = init_cash / cash_splits = 50,000
- 同一交易日有多只触发时，按 T-1 的 rank 从小到大依次下单（rank越小越优先）
- 股票数量按 100 股一手向下取整
- 最大同时持仓数 = cash_splits

# 4. Exit（卖出）——次日不涨停或人气跌破50

## 4.1 卖出条件（满足任一即卖出）

**条件A: 次日不涨停**
```python
# 在 T+1 检查
is_limit_up_t1 = close_T1 >= prev_close_T1 * (1 + limit_pct - 0.001)
if not is_limit_up_t1:
    # 卖出，exit_reason = "not_limit_up"
```

**条件B: 人气跌破50**
```python
# 在 T+1 检查
if hot_rank_T1 > 50:  # 人气排名>50表示跌出前50
    # 卖出，exit_reason = "rank_drop_below_50"
```

## 4.2 持有条件
只有同时满足以下两个条件才继续持有：
1. 次日涨停（close == limit_up_price）
2. 人气排名仍在前50（hot_rank <= 50）

## 4.3 卖出执行
```python
# 在满足卖出条件的当日收盘卖出
sell_price = close
sell_exec = sell_price * (1 - slippage_bps/10000)  # 减滑点
```

## 4.4 最大持仓天数
- max_hold_days = 30（防止极端情况无限持有）
- 达到最大持仓天数强制卖出，exit_reason = "max_hold_days"

## 4.5 exit_reason 标记
- `not_limit_up`: 次日不涨停，收盘卖出
- `rank_drop_below_50`: 人气跌破50，收盘卖出
- `not_limit_up_and_rank_drop`: 同时满足两个条件
- `max_hold_days`: 达到最大持仓天数
- `suspend_resume`: 停牌恢复后卖出

## 4.6 持有期间的检查逻辑（每日）
```
T日买入（开盘价）
T+1日检查：
  - 若人气排名 > 50 → 卖出（人气下降）
  - 若收盘不涨停 → 卖出（动能减弱）
  - 若涨停 AND 人气<=50 → 继续持有
T+2日检查（如果T+1持有）：
  - 同上逻辑
...
直到满足卖出条件或达到最大持仓天数
```

# 5. 策略参数（配置文件）

```yaml
# config/strategies/hot_rank_top10_open.yaml
params:
  # === 选股池参数 ===
  hot_top_n: 10                    # 人气榜前10名
  
  # === 买入参数 ===
  entry_price_method: "open"       # 开盘价买入
  skip_limit_up_open: true         # 跳过一字涨停
  
  # === 卖出参数 ===
  sell_if_not_limit_up: true       # 不涨停则卖出
  rank_threshold: 50               # 人气跌破此阈值则卖出
  max_hold_days: 30                # 最大持仓天数
  
  # === 仓位管理 ===
  init_cash: 100000                # 初始资金
  cash_splits: 2                   # 资金分份数（1/2/3/4）
  max_positions: 2                 # 最大持仓数（= cash_splits）
  
  # === 交易成本 ===
  fee_buy: 0.0003                  # 买入佣金
  fee_sell: 0.0003                 # 卖出佣金
  stamp_tax_sell: 0.001            # 印花税（卖出）
  slippage_bps: 5                  # 滑点（基点）
```

# 6. 回测输出

## 6.1 trades 明细（CSV格式）
必须包含字段：
- entry_date, code, name
- rank_t1（T-1人气排名，用于买入决策）
- open_T, high_T, low_T, close_T（买入日价格）
- is_limit_up_open（是否一字涨停，布尔）
- buy_price, buy_exec, buy_shares, buy_cost
- exit_date, exit_reason, hold_days
- rank_exit（卖出日人气排名）
- close_exit, is_limit_up_exit（卖出日是否涨停）
- sell_price, sell_exec, sell_proceed
- net_pnl, net_pnl_pct

## 6.2 统计报告
- 信号数、成交数、跳过数（一字涨停/资金不足/一手不足）
- 胜率、平均收益、最大回撤
- 分组统计：
  - 按rank分组（1-3/4-6/7-10）
  - 按exit_reason分组
  - 按hold_days分组
- 资金分份对比：1份/2份/3份/4份的表现差异

## 6.3 "模拟实盘风格"日志
- BUY: 日期、code、rank、开盘价、买入价、股数、费用、现金余额
- HOLD: 日期、code、原因（涨停且人气在前50）
- SELL: 日期、code、卖出价、收益、原因（不涨停/人气跌破50）

# 7. 实现要点

## 7.1 一字涨停判断函数
```python
def is_limit_up_board(row: pd.Series, prev_close: float, limit_pct: float = 0.10) -> bool:
    """
    判断是否一字涨停（无法买入）
    
    一字涨停特征：
    1. 开盘价 = 最高价 = 最低价（一字板）
    2. 价格达到涨停价
    """
    is_flat = (row['open'] == row['high'] == row['low'])
    limit_up_price = round(prev_close * (1 + limit_pct), 2)
    is_at_limit = row['open'] >= limit_up_price - 0.01  # 允许0.01误差
    return is_flat and is_at_limit
```

## 7.2 check_exit_signal 函数（核心逻辑）
```python
def check_exit_signal(self, row_today: pd.Series, prev_close: float) -> tuple[bool, str]:
    """
    检查卖出信号
    
    卖出条件（满足任一）：
    1. 收盘不涨停
    2. 人气排名 > 50
    
    Returns:
        (should_exit, exit_reason)
    """
    # 检查涨停
    limit_up_price = round(prev_close * (1 + self.limit_pct), 2)
    is_limit_up = row_today['close'] >= limit_up_price - 0.01
    
    # 检查人气排名
    rank = row_today['hot_rank']
    rank_ok = rank <= self.rank_threshold  # 默认50
    
    if not is_limit_up and not rank_ok:
        return True, "not_limit_up_and_rank_drop"
    elif not is_limit_up:
        return True, "not_limit_up"
    elif not rank_ok:
        return True, "rank_drop_below_50"
    else:
        return False, "hold_limit_up_rank_ok"
```

## 7.3 资金分份测试（后续扩展）
```python
# 在回测脚本中支持批量测试不同分份
for cash_splits in [1, 2, 3, 4]:
    params['cash_splits'] = cash_splits
    params['max_positions'] = cash_splits
    result = run_backtest(params)
    results[f"splits_{cash_splits}"] = result

# 输出对比报告
generate_comparison_report(results)
```

# 8. 预期行为分析

| 市场环境 | 策略表现预期 |
|---------|-------------|
| 连板行情 | 收益较高（涨停持有）|
| 人气轮动快 | 频繁换手（人气跌破50）|
| 一字板多 | 信号减少（无法买入）|
| 热点分散 | 收益平稳（分散持仓）|

# 9. 风险提示
- 人气排名靠前的股票波动较大，风险较高
- 开盘买入可能面临高开低走风险
- 人气数据可能有延迟，实盘需注意
- 本策略仅用于研究学习，不构成投资建议

# 10. 后续优化方向
1. 测试不同资金分份（1/2/3/4）的表现差异
2. 测试不同人气阈值（30/40/50/60）的影响
3. 增加成交额过滤条件
4. 增加市场整体情绪指标作为开关

---

# Changelog

## 2026-01-05

### Added
- **初始版本**: 人气榜TOP10开盘买入策略
  - 核心逻辑: 开盘买入人气前10，次日不涨停或人气跌破50卖出
  - 资金管理: 10万分2份，优先买入排名靠前的股票
  - 过滤条件: 一字涨停不买入
  - 后续计划: 测试1/3/4份资金分配的表现差异
