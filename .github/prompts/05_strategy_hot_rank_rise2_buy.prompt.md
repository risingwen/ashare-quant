---
agent: "copilot"
---

你是资深量化研究 + 数据工程助手。请用 Python 为 A 股做一个"统计回测/事件研究"（非投资建议），基于我现有的最近1年数据，评估以下策略的历史表现，并输出可复现的交易明细、组合净值、统计报告，同时打印"模拟实盘风格"的操作日志。

# 0. 策略概述
**策略名称**: 人气榜+2%追涨策略 (hot_rank_rise2)

**核心思想**: 追涨强势股。当人气榜热门股票次日股价上涨到+2%时买入，捕捉强势股的延续动量。

**与原策略的区别**:
| 维度 | 原策略 (hot_rank_drop7) | 新策略 (hot_rank_rise2) |
|------|------------------------|------------------------|
| 买入逻辑 | 下跌-7%时抄底 | 上涨+2%时追涨 |
| 选股范围 | 人气前100 | 人气前50（更严格） |
| 成交额门槛 | 20亿 | 20亿（相同） |
| 交易风格 | 逆势抄底 | 顺势追涨 |

# 1. 项目架构说明
请严格遵循现有项目架构：
- **特征数据**: `data/processed/features/daily_features_v1.parquet`
- **回测结果**: `data/backtest/trades/` 和 `data/backtest/portfolio/`
- **策略配置**: `config/strategies/hot_rank_rise2.yaml`
- **回测脚本**: `scripts/backtest_hot_rank_rise2_strategy.py`

# 2. Universe（选股池）——严格用 T-1 信息
在交易日 T：
1. 读取 T-1 的人气榜，取 **rank <= 50** 的股票列表；
2. 过滤：**amount_{T-1} >= 20亿**；
3. 过滤：剔除 ST/*ST/退市整理 等股票；
4. 过滤：若 T 当日无行情或 volume==0（停牌/不可交易），则跳过；
5. 过滤：前3日人气排名需在50以内（max_hot_rank_3d <= 50）；
6. 过滤：剔除一字涨停（无法买入）；
7. **过滤：T-1日必须涨停（is_limit_up = True）**；
   - 追涨涨停板股票，捕捉连板行情
   - 这是追涨策略的核心条件

# 3. Entry（买入）——追涨+2%策略

## 3.1 触发条件（核心逻辑，必须同时满足）
```
条件1: high_T >= prev_close × (1 + rise_trigger)
       即：当日最高价涨到了+2%以上，说明盘中曾经过+2%价位

条件2: low_T <= prev_close × (1 + rise_trigger)  
       即：当日最低价不高于+2%，确保+2%价格是可成交的
       （如果开盘就跳空高开超过+2%，则low_T > +2%价，此时无法以+2%买入，应跳过）
```

**图解说明**:
```
情况1: 可以买入 ✓
  开盘价 < +2% < 最高价，最低价 < +2%
  价格线: ----[low]----[open]----[+2%]----[high]----
  
情况2: 可以买入 ✓  
  开盘价 > +2%，但最低价 <= +2%（回踩到+2%）
  价格线: ----[low]----[+2%]----[open]----[high]----

情况3: 无法买入 ✗
  跳空高开，最低价 > +2%
  价格线: ----[+2%]----[low]----[open]----[high]----
  此时即使high >= +2%，但low > +2%，无法以+2%成交
  
情况4: 无法买入 ✗
  当日最高价 < +2%（全天未涨到+2%）
  价格线: ----[low]----[open]----[high]----[+2%]----
```

## 3.2 成交价假设
```python
trigger_price = prev_close × (1 + rise_trigger)  # +2%价格
buy_price = trigger_price
buy_exec = buy_price × (1 + slippage_bps/10000)  # 加滑点
```

## 3.3 资金规则
- 初始资金 init_cash = 100,000
- 每次触发买入名义资金 = init_cash × per_trade_cash_frac (10%)
- 同一交易日有多只触发时，按 T-1 的 rank 从小到大依次下单
- 股票数量按 100 股一手向下取整

# 4. Exit（卖出）——与原策略相同

## 4.1 基础退出规则
- 默认在 T+1 收盘卖出：sell_price = close_{T+1}

## 4.2 涨停不卖规则
- 若 T+1 收盘价为涨停价，则继续持有
- 从 T+2 开始逐日检查，首个非涨停日收盘卖出

## 4.3 跌停卖出规则
- 若持仓期间 low <= prev_close × (1 - limit_down_trigger)，触发跌停卖出
- limit_down_trigger = 0.07（-7%）

## 4.4 exit_reason 标记
- `sell_t1_close`: T+1正常收盘卖出
- `hold_limitup`: 涨停持有
- `sell_drop7`: 跌停-7%卖出
- `sell_first_non_limitup`: 首个非涨停日收盘卖出
- `sell_max_hold_days`: 达到最大持仓天数

# 5. 策略参数（配置文件）

```yaml
# config/strategies/hot_rank_rise2.yaml
params:
  # === 选股池参数 ===
  hot_top_n: 50                    # 人气榜前50名
  prev_amount_min: 2000000000      # 成交额>=20亿（单位：元）
  max_hot_rank_3d: 50              # 前3日人气需在50以内
  
  # === 买入参数 ===
  rise_trigger: 0.02               # 触发买入阈值（+2%）
  entry_price_method: "trigger"    # 成交价=触发价
  
  # === 卖出参数 ===
  hold_on_limit_up: true           # 涨停不卖
  exit_on_limit_down: true         # 跌停卖出
  limit_down_trigger: 0.07         # 跌停阈值（-7%）
  base_exit_day: 1                 # T+1卖出
  max_hold_days: 30                # 最大持仓天数
  
  # === 仓位管理 ===
  per_trade_cash_frac: 0.1         # 每笔10%资金
  max_positions: 10                # 最大持仓数
```

# 6. 回测输出

## 6.1 trades 明细（CSV格式）
必须包含字段：
- entry_date, code, name
- rank_t, rank_t1, rank_t2（T/T-1/T-2人气排名）
- amount_t, amount_t1, amount_t2（T/T-1/T-2成交额）
- prev_close, trigger_high（触发最高价）, trigger_low（触发最低价）
- buy_price, buy_exec, buy_shares, buy_cost
- exit_date, exit_reason, hold_days
- sell_price, sell_exec, sell_proceed
- net_pnl, net_pnl_pct

## 6.2 统计报告
- 信号数、成交数、跳过数（资金不足/一手不足/跳空高开无法买入等）
- 胜率、平均收益、最大回撤
- 分组统计：按rank分组（1-10/11-25/26-50）、按成交额分组

## 6.3 "模拟实盘风格"日志
- BUY: 日期、code、rank、+2%触发价、买入价、股数、费用、现金余额
- HOLD: 日期、code、原因（涨停持有）
- SELL: 日期、code、卖出价、收益、原因

# 7. 实现要点

## 7.1 check_entry_signal 函数（核心修改）
```python
def check_entry_signal(self, row_today: pd.Series, row_prev: pd.Series) -> bool:
    """
    检查买入信号（+2%追涨策略）
    
    买入条件（必须同时满足）：
    1. 当日最高价 >= 前收盘 × (1 + rise_trigger) -- 涨到过+2%
    2. 当日最低价 <= 前收盘 × (1 + rise_trigger) -- 确保+2%可成交
    """
    trigger_price = row_prev['close'] * (1 + self.rise_trigger)
    
    # 条件1: 最高价涨到过触发价
    condition1 = row_today['high'] >= trigger_price
    
    # 条件2: 最低价不高于触发价（确保可成交）
    condition2 = row_today['low'] <= trigger_price
    
    return condition1 and condition2
```

## 7.2 execute_buy 函数（买入价改为+2%）
```python
def execute_buy(self, ...):
    # 计算买入价格（基于昨日收盘价 +2%）
    buy_price = row_prev['close'] * (1 + self.rise_trigger)
    buy_exec = buy_price * (1 + self.slippage_bps / 10000)
    # ... 其余逻辑与原策略相同
```

## 7.3 统计信息（新增）
- `skip_gap_up`: 跳空高开无法买入的次数（low > trigger_price）
- `skip_not_reach`: 最高价未涨到+2%的次数（high < trigger_price）

# 8. 预期行为对比

| 市场环境 | 原策略(抄底) | 新策略(追涨) |
|---------|-------------|-------------|
| 强势上涨 | 可能错过（等不到-7%） | 容易触发 |
| 震荡市场 | 触发较多 | 触发较多 |
| 弱势下跌 | 容易触发（可能亏损） | 较难触发 |
| 跳空高开 | 可能触发 | 无法买入 |
| 跳空低开 | 触发买入 | 可能错过 |

# 9. 风险提示
- 追涨策略在弱势市场可能表现不佳
- +2%买入成本较高，需要更大涨幅才能盈利
- 跳空高开时无法买入，可能错过部分强势股

---

# Changelog

## 2026-01-04

### Fixed
- **[Critical] 修复买入条件检查逻辑缺陷**
  - **问题**: `check_entry_signal` 函数只检查 `condition2 (low <= trigger_price)`, 缺少 `condition1 (high >= trigger_price)` 检查
  - **影响**: 跳空低开场景下, 回测会尝试在"不存在的价格"买入
    - 例: 603618 在 2025-09-24, 最高价 11.57, 却尝试在触发价 12.4746 买入
    - 前日涨停 12.23 → 次日跳空低开 -10% → 错误买入导致 -20.8% 亏损
  - **修复**: 在 `check_entry_signal` 中增加 `condition1` 检查, 确保买入价格真实可达
  - **效果**: 
    - 买入次数: 290 → 239 (减少 51 笔, 17.6%)
    - 最终净值: 保持不变 124,215.18
    - 被过滤的都是跳空低开无效交易, 不影响策略整体表现
  - **意义**: 保证回测真实性, 符合实盘交易逻辑

### Added
- **前一日振幅过滤 (≤15%)**
  - **原因**: 避免选入极端波动股票, 降低策略风险
  - **规则**: T-1 日振幅 (high - low) / low * 100 必须 ≤ 15%
  - **位置**: 在极端波动过滤 (30%) 之后追加的更严格过滤
  - **效果**: 
    - 过滤信号: 305 笔
    - 买入次数: 239 → 223 (-16 笔, -6.7%)
    - 最终净值: 124,215 → 127,298 (+3,082, +2.5%)
  - **预期**: 过滤掉日内震荡剧烈的股票, 提高持仓稳定性

- **资金分配策略优化**
  - **原因**: 降低单笔风险, 提高资金利用效率
  - **规则**: 
    - 10 万资金分为 2 份, 每份 5 万 (50%)
    - 同时最多持有 2 只股票
    - 按前一日 hot_rank 排序, 优先买入人气更高的股票 (rank 数字越小越优先)
  - **实现**: 
    - 修改 `nominal_cash = init_cash * 0.5`
    - 增加 `max_positions = 2` 限制
    - 选股池按 `hot_rank` 升序排序后遍历买入
  - **预期**: 集中火力买入最强势股票, 提高胜率

## 2026-01-03

### Changed
- **新股过滤条件**: 从 `days_since_listing > 10` 调整为 `days_since_listing > 5`
  - 原因: 数据集仅包含2025年数据，部分1月上市新股在10天过滤下会被排除过多交易机会
  - 影响: 允许上市第6天起参与交易，增加新股追涨机会

### Fixed
- **max_hot_rank_3d计算**: 从预计算改为动态计算
  - 问题: 预计算使用pandas rolling+shift在遇到缺失日期时会跨越空档期取历史旧值
  - 解决: 在回测时使用T-1和T-2 DataFrame直接merge计算，仅看连续两天的实际人气值
  - 影响: 过滤精度提升，避免因旧数据导致的误过滤

- **涨停阈值**: 从 `>= 10%` 调整为 `>= 9.9%`
  - 原因: 实际交易中9.97%等接近10%的涨幅应被识别为涨停
  - 影响: 更准确识别涨停板，减少漏选
