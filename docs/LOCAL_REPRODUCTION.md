# 本地复现与发布指南

本文档用于让新同学快速理解：策略如何跑、报告如何生成、Pages 如何在本地复现。

## 1. 策略清单（当前仓库）

- `hot_rank_drop7_smart_exit`：前一日人气前100，次日回撤触发买入（主板-7%，创业板/科创板-13%）
- `hot_rank_rise2_smart_exit`：前一日人气前50，次日盘中上涨+2%触发买入
- `hot_rank_top20_newentry`：首次进入前20，开盘买入，次日不涨停或人气跌破阈值卖出
- `hot_rank_first_top10_rise2_or_gapdown`：首次前10，低开或+2%触发买入，人气跌出前50卖出

对应配置文件都在 `config/strategies/*.yaml`。

## 2. 环境准备

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. 数据与策略复现命令

### 3.1 数据更新/审计

```bash
python3 scripts/update_daily_incremental.py --config config.yaml --workers 2
python3 scripts/audit_data_integrity.py --as-of 2026-03-18
```

### 3.2 策略回测（示例）

```bash
python3 scripts/backtest_hot_rank_strategy.py --config config/strategies/hot_rank_drop7.yaml
python3 scripts/backtest_hot_rank_rise2_strategy.py --config config/strategies/hot_rank_rise2.yaml
python3 scripts/backtest_hot_rank_top10_open_strategy.py --config config/strategies/hot_rank_top10_open.yaml
python3 scripts/backtest_hot_rank_first_top10_strategy.py --config config/strategies/hot_rank_first_top10_rise2_or_gapdown.yaml
```

### 3.3 报告与页面数据

```bash
python3 scripts/export_hot_rank_top100_history.py
python3 scripts/publish_latest_experiment_to_reports.py
```

## 4. 本地复现 Pages（与 CI 一致）

一条命令生成 `public/`：

```bash
./scripts/build_pages_local.sh
```

完成后可本地预览：

```bash
python3 -m http.server 8080 --directory public
# 浏览器访问 http://127.0.0.1:8080
```

## 5. 本机复现结果（2026-03-19）

已实测：

- `scripts/export_hot_rank_top100_history.py` 产出 `26,291` 条、`290` 个交易日
- `./scripts/build_pages_local.sh` 成功生成 `public/index.html`
- 热度筛选页入口：`public/hot_rank_top100_explorer.html`

## 6. 发布到 GitHub Pages

推送到 `master` 即触发 `.github/workflows/static.yml`：

```bash
git push origin master
```

工作流会在部署前自动执行热度前100导出，保证页面与最新仓库数据同步。
