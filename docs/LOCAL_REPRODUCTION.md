# 本地复现指南

本文档记录当前推荐的本地复现方式。旧 GitHub Pages 发布链路已经移除，生产发布以 Oracle Cloud 部署为准。

## 环境准备

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 测试入口

测试收集只走 `tests/`：

```bash
python -m pytest --collect-only -q
```

外部数据源集成测试会访问 AkShare/东方财富，网络或代理异常时可能被跳过：

```bash
python -m pytest -q tests/integration --tb=short
python -m pytest -q -m "integration and network"
```

## 数据更新复现

本地不建议提交数据库或行情快照。需要复现数据更新时，使用本地 `data/quant.db`：

```bash
python src/update_sqlite_data.py --db data/quant.db --daily-source sina --workers 4
python src/update_etf.py --db data/quant.db --spot-only --skip-holdings
```

如果只想验证脚本参数和依赖是否可用，先运行：

```bash
python src/update_sqlite_data.py --help
python src/update_etf.py --help
python src/generate_report.py --help
```

## 报告生成

本地报告输出到 `reports/`，该目录是运行产物，默认不提交：

```bash
python src/generate_report.py --db data/quant.db --report-dir reports --start-date 2025-01-01
```

生成后可本地预览：

```bash
python -m http.server 8080 --directory reports/latest
```

浏览器访问：

```text
http://127.0.0.1:8080/
```

## 策略回测

策略配置位于 `config/strategies/`：

```bash
python scripts/backtest_hot_rank_strategy.py --config config/strategies/hot_rank_drop7.yaml
python scripts/backtest_hot_rank_rise2_strategy.py --config config/strategies/hot_rank_rise2.yaml
python scripts/backtest_hot_rank_top10_open_strategy.py --config config/strategies/hot_rank_top10_open.yaml
python scripts/backtest_hot_rank_first_top10_strategy.py --config config/strategies/hot_rank_first_top10_rise2_or_gapdown.yaml
```

## 生产部署关系

GitHub `master` push 触发 `.github/workflows/deploy.yml`，通过 SSH 登录 Oracle 服务器并执行：

```bash
cd /data/quant_research
RESTART_API=1 RUN_FULL_PIPELINE=0 bash deploy/scripts/deploy_oracle.sh
```

生产状态以以下接口为准：

```bash
curl http://140.245.53.52:8080/api/health
```
