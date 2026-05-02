# A-share Quant Research

这是一个干净的新量化研究目录，不修改旧的 `/data/akshare/Akshare` 脚本和 CSV 数据。

## 数据层

CSV 已不再作为主数据层。当前流程是：

1. 旧 CSV 只作为一次性导入源。
2. 日线、人气榜、涨停池统一写入 `data/quant.db`。
3. 报告和策略回测只读取 SQLite。

当前数据库已回补到 `1991-01-14`，最新到 `2026-04-30`，2024-2026 年样本已可用于策略统计。

## 环境

本机可用 uv 环境：

```bash
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python
```

如需重建：

```bash
uv venv /LocalRun/xiwen.xing/01_envs/quant_research --python python3.12
uv pip install --python /LocalRun/xiwen.xing/01_envs/quant_research/bin/python -r requirements.txt
```

## 常用命令

生成 2024-2026 策略回测和报告：

```bash
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/backtest_new_high_volume.py --db data/quant.db --report-dir reports/backtests --start-date 2024-01-01
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/generate_report.py --db data/quant.db --report-dir reports --start-date 2024-01-01
```

更新最新日线、人气榜、涨停池：

```bash
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/update_sqlite_data.py --db data/quant.db --daily-source sina --workers 8
```

历史回补：

```bash
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/update_sqlite_data.py --db data/quant.db --start-date 19900101 --daily-source sina --workers 8 --backfill-history --skip-popularity --skip-limit-pool
```

## 主要输出

- `data/quant.db`
- `reports/latest/report.html`
- `reports/latest/report.md`
- `reports/latest/summary.json`
- `reports/latest/new_high_volume_backtests.csv`
- `reports/backtests/new_high_volume_backtest.md`
- `reports/latest/latest_popularity_rankings.csv`
- `reports/latest/latest_external_limit_up_pool.csv`

## 三套历史新高放量策略

- `HH_VOL_MA5_BASE`：可用历史收盘新高，近 20 日均量 2 倍以上，成交额不低于 5 亿，次日开盘买入，收盘跌破 5 日线卖出，最多持有 20 日。
- `HH_VOL_MA5_WARM_CYCLE`：历史新高，近 20 日均量 1.5 倍以上，成交额不低于 8 亿，当日涨幅 2%-9.5%，市场暖/强周期，跌破 5 日线卖出，最多持有 20 日。
- `HH_VOL_MA5_HOT_LEADER`：历史新高，近 60 日均量 1.2 倍以上，成交额不低于 10 亿，换手率不低于 3%，当日涨幅不低于 5%，市场强周期，跌破 5 日线卖出，最多持有 30 日。

回测区间：`2024-01-01` 到 `2026-04-30`。

当前结果：

- `HH_VOL_MA5_BASE`：2505 笔，胜率 34.65%，单笔均值 0.61%，批次复利收益 3389.13%，最大回撤 -97.58%。
- `HH_VOL_MA5_WARM_CYCLE`：1088 笔，胜率 34.28%，单笔均值 0.42%，批次复利收益 -58.25%，最大回撤 -93.24%。
- `HH_VOL_MA5_HOT_LEADER`：526 笔，胜率 35.74%，单笔均值 0.65%，批次复利收益 68.08%，最大回撤 -61.95%。

回测说明：不包含手续费、滑点、涨停无法买入、跌停无法卖出和持仓重叠资金占用。当前最值得继续优化的是 `HH_VOL_MA5_HOT_LEADER`，因为收益为正且回撤相对小于基础版。

## 打包迁移

```bash
cd /home/xiwen.xing/quant_research
bash scripts/package_project.sh
```
