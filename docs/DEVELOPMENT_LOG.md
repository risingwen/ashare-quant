# 开发记录

本文档用于记录“做过什么、为什么做、如何验证、后续还欠什么”。新增功能、重构、部署修复和重要排查完成后，都应该追加一条记录，避免只靠聊天记录或个人记忆。

## 记录规则

- 每次记录以日期开头，标题使用“日期 + 主题”。
- 必须写清楚改动范围、验证命令和后续动作。
- 如果涉及线上状态，只记录 commit、路径、服务名和 secret 名称，不记录私钥、token、密码。
- 事故类问题同时补到 [事故记录](INCIDENT_LOG.md)，架构决策同时补到 `docs/adr/`。

## 模板

```markdown
## YYYY-MM-DD 标题

- 背景：
- 改动：
- 验证：
- 影响：
- 后续：
```

## 2026-05-17 运行监控与日更稳定化

- 背景：线上页面只能看到“最新数据”日期，无法判断每个数据模块是否更新成功，也无法确认当前页面对应哪个 Git commit。
- 改动：新增 `/api/health`、`monitor.html`、`summary.json` Git 元数据；日更日志固定到 `/data/quant_research/logs/daily-run-YYYYMMDD.log`；首页展示 Git commit。
- 改动：ETF 日更主链路改为 `src/update_etf.py --spot-only --skip-holdings`，避免 ETF 持仓回补阻塞每日快照。
- 改动：人气榜更新增加东方财富 direct fallback，AkShare 接口异常时仍尽量写入当日 Top100。
- 验证：`curl http://140.245.53.52:8080/api/health` 返回 `status=ok`，最新有效交易日为 `2026-05-15`。
- 影响：线上监控从“只有日期”提升为“模块级状态 + 日志路径 + Git 版本”。
- 后续：新增数据模块必须进入 `/api/health.modules`，否则无法判断日更是否真的完整。

## 2026-05-17 工程文档补全

- 背景：部署、日更、数据源兜底和故障修复都散落在临时记录里，后续维护成本高。
- 改动：补充 [架构设计](ARCHITECTURE.md)、[数据流水线](DATA_PIPELINE.md)、[运维手册](OPERATIONS_RUNBOOK.md)、[事故记录](INCIDENT_LOG.md) 和 ADR。
- 改动：README 改为入口导航，不再承载过多细节。
- 验证：运行 `git diff --check`；检查 README 链接文件存在；检查关键路径和脚本名被文档覆盖。
- 影响：后续排查生产问题时优先看 `OPERATIONS_RUNBOOK.md` 和 `INCIDENT_LOG.md`，不用从聊天记录里翻命令。
- 后续：每次线上故障修复后补 `INCIDENT_LOG.md`；每次长期技术取舍补 ADR。

## 2026-05-17 第一轮仓库整理

- 背景：根目录堆积了一批一次性测试、导出和查看脚本，和仍在维护的生产代码混在一起，降低开发入口可读性。
- 改动：删除无文档引用、无脚本引用、且不在 pytest 当前收集范围内的一次性脚本：`export_trades_to_csv.py`、`test_fixed_logic.py`、`test_match.py`、`test_new_columns.py`、`view_test_result.py`。
- 改动：新增 [仓库清理清单](REPO_CLEANUP.md)，把已清理内容、保留原因和下一批候选分开记录。
- 验证：运行 `git diff --check`；运行 `python -m pytest --collect-only -q` 确认 pytest 收集项不减少；用 `rg` 检查被删除文件没有残留引用。
- 影响：根目录减少一次性杂项，后续清理可以按清单推进，而不是临时凭感觉删除。
- 后续：继续迁移旧 parquet 工具和旧文档。

## 2026-05-17 测试结构整理

- 背景：真正被 pytest 收集的测试文件放在根目录，且全部依赖 AkShare/东方财富等外部数据源；`test_system.py` 还会写入仓库内的 `data/test/test_000001.parquet`。
- 改动：新增 `pytest.ini`，把 pytest 收集入口限制到 `tests/`，并注册 `integration`、`network` 两个 marker。
- 改动：将 `test_hot_rank.py`、`test_popularity.py`、`test_system.py` 迁移到 `tests/integration/`，统一标记为网络集成测试。
- 改动：重构 `tests/integration/test_system.py`，用 `tmp_path` 写临时 parquet，避免测试运行污染仓库数据目录。
- 验证：运行 `python -m pytest --collect-only -q`，仍收集 8 个测试；运行 `python -m pytest -q tests/integration --tb=short`，本地结果为 `1 passed, 7 skipped`，跳过原因是外部源代理不可达。
- 影响：测试入口更清晰，根目录不再混入正式 pytest 文件；以后可以继续补 `tests/unit/`，把不依赖网络的快速测试放进去。
- 后续：把网络测试中外部源不可达与代码/schema 错误继续区分清楚。

## 2026-05-17 根目录大清理

- 背景：GitHub 根目录仍直接显示旧脚本、旧测试、`reports/`、`logs/`、`configs/`、`.specstory/` 和旧 Pages 相关文件，工程入口不清晰。
- 改动：根目录旧 parquet 工具和脚本式验证文件迁入 `archive/legacy-tools/`。
- 改动：旧下载/查看/Data Wrangler/Excel 文档迁入 `archive/legacy-docs/`，当前 `docs/` 只保留有效工程文档。
- 改动：删除已提交的 `reports/` 运行产物、`data/hot_sources/` 大 CSV、`data/test/test_000001.parquet`、`logs/.gitkeep` 和重复 `configs/`。
- 改动：删除旧 GitHub Pages workflow、旧 Pages 构建脚本和早期 `.github/prompts/`。
- 改动：迁移旧 parquet 更新/导出脚本和旧 `scripts/generate_report.py`，避免与当前 SQLite 主链路混淆。
- 改动：重写 `.gitignore` 和 `data/README.md`，明确 `data/`、`reports/`、`logs/` 都是运行时目录。
- 验证：运行 `git diff --check`；运行 `python -m pytest --collect-only -q`；用 `rg` 检查非 archive 范围内没有旧根目录入口命令残留。
- 影响：GitHub 根目录将只剩工程入口和核心目录；运行产物不再污染代码审阅。
- 后续：继续评估 `archive/diagnostics/`、`archive/reports/` 和 `scripts/prepare_features.py` 是否仍需保留。
