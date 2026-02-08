# 策略需求补充文档

## 参数化需求（2026-01-02更新）

### 1. 动态阈值调整
**需求**：支持快速调整买入/卖出阈值进行参数敏感性测试

**实现**：
- 所有阈值参数必须在配置文件中定义
- 支持通过CLI参数覆盖配置文件
- 参数命名遵循规范：`{action}_trigger`

#### 1.1 差异化阈值（创业板/科创板）
**新增功能**（2026-01-02）：针对不同板块设置差异化买入触发阈值

**背景**：
- 创业板（300开头）和科创板（688开头）波动率较大
- 需要更大的跌幅才能确认买入机会
- 主板股票保持原有-7%触发逻辑

**实现逻辑**：
```python
# 根据股票代码选择触发阈值
if code.startswith('300') or code.startswith('688'):
    drop_trigger = 0.13  # 创业板/科创板 -13%
else:
    drop_trigger = 0.07  # 其他股票 -7%
    
buy_price = prev_close * (1 - drop_trigger)
```

**配置参数**：
```yaml
# 配置文件
params:
  drop_trigger: 0.07            # 主板/深市 -7% 买入
  drop_trigger_cyb_kcb: 0.13    # 创业板/科创板 -13% 买入
  limit_down_trigger: 0.07      # -7% 卖出
```

```bash
# CLI覆盖测试-6%
python scripts/backtest_hot_rank_strategy.py \
  --config config/strategies/hot_rank_drop7.yaml \
  --param.drop_trigger=0.06 \
  --param.limit_down_trigger=0.06
```

### 2. 选股池大小调整
**需求**：测试不同人气榜排名范围的效果（100名 vs 50名）

**实现**：
```yaml
params:
  hot_top_n: 100  # 可改为 50
```

```bash
# CLI测试前50名
python scripts/backtest_hot_rank_strategy.py \
  --config config/strategies/hot_rank_drop7.yaml \
  --param.hot_top_n=50
```

### 3. 智能卖出规则
**需求**：在"涨停不卖"基础上，增加"跌停卖出"保护机制

**背景**：
- 次日可能大幅低开至-7%（跌停附近）
- 继续持有风险过大，应及时止损

**实现逻辑**：
```python
# 伪代码
for holding in positions:
    current_date = holding.current_date
    prev_close = holding.prev_close
    
    # 优先检查跌停卖出
    if low <= prev_close * (1 - limit_down_trigger):
        sell_at_trigger_price()  # 跌停卖出
        exit_reason = "sell_limitdown"
        continue
    
    # 其次检查涨停持有
    if close == limit_up_price:
        hold_position()  # 涨停不卖
        exit_reason = "hold_limitup"
        continue
    
    # 正常情况收盘卖出
    sell_at_close()
    exit_reason = "sell_normal_close"
```

**配置参数**：
```yaml
params:
  # 涨停不卖
  hold_on_limit_up: true
  
  # 跌停卖出（新增）
  exit_on_limit_down: true
  limit_down_trigger: 0.07        # 与买入对称
  limit_down_price_method: "trigger"  # trigger或close
```

### 4. 参数对称性设计
**原则**：买入和卖出使用相同的阈值，保持策略逻辑一致性

**示例**：
- 买入触发：-7%
- 卖出触发：-7%
- 同时调整：改为-6%时，两者同步修改

**实现**：
```yaml
params:
  # 核心阈值（买卖对称）
  core_trigger: 0.07
  
  # 引用核心阈值
  drop_trigger: 0.07      # 或直接引用 ${core_trigger}
  limit_down_trigger: 0.07
```

或使用CLI统一设置：
```bash
python scripts/backtest_hot_rank_strategy.py \
  --param.core_trigger=0.06  # 同时影响买入和卖出
```

## 参数测试矩阵建议

### 单因子测试
| 参数 | 基准值 | 测试值 | 预期影响 |
|------|--------|--------|----------|
| drop_trigger | 0.07 | [0.05, 0.06, 0.08, 0.09] | 阈值越小，信号越多 |
| hot_top_n | 100 | [50, 150, 200] | 范围越大，股票池越大 |
| prev_amount_min | 1e9 | [5e8, 2e9, 5e9] | 金额越高，流动性越好 |

### 组合测试
```bash
# 测试矩阵脚本
for top_n in 50 100 150; do
  for trigger in 0.05 0.06 0.07 0.08; do
    python scripts/backtest_hot_rank_strategy.py \
      --param.hot_top_n=$top_n \
      --param.drop_trigger=$trigger \
      --param.limit_down_trigger=$trigger \
      --output-suffix="_n${top_n}_t${trigger}"
  done
done
```

## 回测结果对比

### 期望输出
```
backtest/reports/
├── hot_rank_n100_t007_report.md     # 基准策略
├── hot_rank_n50_t007_report.md      # 变化：排名范围
├── hot_rank_n100_t006_report.md     # 变化：阈值
└── comparison_matrix.md              # 参数对比矩阵
```

### 对比维度
1. **收益指标**：总收益率、年化收益、夏普比率
2. **风险指标**：最大回撤、胜率、盈亏比
3. **交易特征**：信号数、成交数、平均持仓天数
4. **跌停保护效果**：触发跌停卖出的次数、避免的损失

## 实现优先级

### P0（必须实现）
- [x] 配置文件参数化
- [x] CLI参数覆盖机制
- [x] 跌停卖出逻辑
- [x] 涨停/跌停价格计算
- [x] 创业板/科创板差异化阈值（2026-01-02新增）

### P1（建议实现）
- [ ] 参数测试矩阵脚本
- [ ] 多版本对比报告
- [ ] 参数敏感性分析图表

## 更新日志

### 2026-01-02
1. **新增：创业板/科创板差异化买入阈值**
   - 创业板（300开头）：-13%触发
   - 科创板（688开头）：-13%触发
   - 主板/深市：保持-7%触发
   - 配置参数：`drop_trigger_cyb_kcb: 0.13`

2. **原因**：
   - 创业板和科创板波动率显著高于主板
   - 需要更大的跌幅空间以确认买入信号
   - 避免在正常波动中频繁触发交易

3. **影响**：
   - 创业板/科创板交易信号减少
   - 买入价格更低，潜在收益空间增大
   - 降低假突破带来的损失

### P2（可选实现）
- [ ] 参数自动寻优（网格搜索）
- [ ] 实时参数监控面板
- [ ] 策略参数回测缓存

## 配置文件更新日志

### v1.1.0 (2026-01-02)
- 新增 `limit_down_trigger` 参数
- 新增 `exit_on_limit_down` 开关
- 新增 `limit_down_price_method` 配置
- 更新 `exit_rule` 为 "smart_exit"
- 策略名称更新为 `hot_rank_drop7_smart_exit`

### v1.0.0 (2026-01-02)
- 初始版本
- 基础参数：hot_top_n, drop_trigger
- 基础卖出逻辑：涨停不卖
