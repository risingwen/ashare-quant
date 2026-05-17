# 仓库清理清单

本文档记录仓库结构约束、已经完成的清理动作和后续候选项。目标是让根目录成为工程入口，而不是历史脚本和运行产物堆场。

## 最终结构目标

| 路径 | 职责 | 规则 |
| --- | --- | --- |
| `src/` | 生产数据更新、报告生成、API、健康检查 | 保留 |
| `scripts/` | 可复用 CLI 和生产辅助脚本 | 保留，避免放一次性排查 |
| `deploy/` | Oracle 部署、systemd、nginx 配置 | 保留 |
| `config/` | 当前 YAML 配置和策略模板 | 保留 |
| `tests/` | pytest 测试入口 | 保留 |
| `docs/` | 当前有效工程文档 | 保留，过时文档迁到 `archive/legacy-docs/` |
| `archive/` | 历史脚本、旧文档、一次性诊断材料 | 只读参考，不作为主开发入口 |
| `data/` | 本地/生产运行时数据 | 只提交 `README.md` 和占位文件 |
| `reports/` | 运行时报告输出 | 不提交 |
| `logs/` | 运行时日志 | 不提交 |

## 2026-05-17 已删除

| 内容 | 原因 |
| --- | --- |
| `export_trades_to_csv.py` | 一次性交易导出脚本，硬编码旧回测产物路径，无引用 |
| `test_fixed_logic.py` | 一次性板块判断验证脚本，不是 pytest 稳定测试，无引用 |
| `test_match.py` | 一次性字符串匹配验证脚本，不是 pytest 稳定测试，无引用 |
| `test_new_columns.py` | 一次性字段顺序验证脚本，不是 pytest 稳定测试，无引用 |
| `view_test_result.py` | 旧回测结果查看脚本，硬编码历史目录结构，无文档引用 |
| `configs/` | 旧 JSON 示例配置，与 `config/` 和 `config.example.yaml` 重复 |
| `.github/workflows/static.yml` | 旧 GitHub Pages 发布链路，当前生产只走 Oracle deploy |
| `.github/prompts/` | 早期实现提示词，不属于当前工程入口 |
| `.github/copilot-instructions.md` | 过时且与当前结构不一致，统一以 `AGENTS.md` 为准 |
| `.specstory/` | 本地工具目录，不应提交 |
| `logs/.gitkeep` | 日志目录是运行时目录，不在仓库占位 |
| `reports/` 已提交产物 | 历史报告、HTML、CSV、交易导出均属于运行产物 |
| `data/hot_sources/` | 大体积热榜回补 CSV，属于运行时数据 |
| `data/test/test_000001.parquet` | 测试样本改用 `tmp_path`，不再固定写仓库 |
| `scripts/build_pages_local.sh` | 旧 GitHub Pages 本地构建脚本，发布链路已移除 |
| `scripts/publish_latest_experiment_to_reports.py` | 旧 Pages 报告发布脚本，运行产物不再入库 |

## 2026-05-17 已迁移

| 原路径 | 新路径 | 处理 |
| --- | --- | --- |
| `test_hot_rank.py` | `tests/integration/test_hot_rank.py` | 加 `integration`、`network` marker |
| `test_popularity.py` | `tests/integration/test_popularity.py` | 加 `integration`、`network` marker |
| `test_system.py` | `tests/integration/test_system.py` | parquet 写入改用 `tmp_path` |
| `manual_download.py` | `archive/legacy-tools/manual_download.py` | 旧 parquet 下载入口，退出根目录 |
| `quick_start.py` | `archive/legacy-tools/quick_start.py` | 旧 parquet 快速下载入口，退出根目录 |
| `view_data.py` | `archive/legacy-tools/view_data.py` | 旧 parquet 查看工具，退出根目录 |
| `view_parquet_simple.py` | `archive/legacy-tools/view_parquet_simple.py` | 旧 parquet 查看工具，退出根目录 |
| `test_one_month.py` | `archive/legacy-tools/test_one_month.py` | 旧大批量下载验证脚本，退出根目录 |
| `test_hot_rank_combinations.py` | `archive/legacy-tools/test_hot_rank_combinations.py` | 旧回测组合排查脚本，退出根目录 |
| `test_position_allocation.py` | `archive/legacy-tools/test_position_allocation.py` | 旧仓位排查脚本，退出根目录 |
| `plan.md` | `archive/legacy-tools/plan.md` | 早期运营计划，退出根目录 |
| `docs/QUICK_DOWNLOAD.md` | `archive/legacy-docs/QUICK_DOWNLOAD.md` | 旧 parquet 下载文档 |
| `docs/QUICK_VIEW.md` | `archive/legacy-docs/QUICK_VIEW.md` | 旧 parquet 查看文档 |
| `docs/VIEWING_TOOLS.md` | `archive/legacy-docs/VIEWING_TOOLS.md` | 旧查看工具文档 |
| `docs/DATA_WRANGLER_GUIDE.md` | `archive/legacy-docs/DATA_WRANGLER_GUIDE.md` | 旧 Data Wrangler 文档 |
| `docs/DATA_FIELDS.md` | `archive/legacy-docs/DATA_FIELDS.md` | 旧 parquet 字段文档 |
| `docs/EXCEL_GUIDE.md` | `archive/legacy-docs/EXCEL_GUIDE.md` | 旧 Excel 查看文档 |
| `scripts/download_ashare_3y_to_parquet.py` | `archive/legacy-tools/download_ashare_3y_to_parquet.py` | 旧 parquet 下载主脚本 |
| `scripts/update_daily_incremental.py` | `archive/legacy-tools/update_daily_incremental.py` | 旧 parquet 增量更新入口 |
| `scripts/export_hot_rank_top100_history.py` | `archive/legacy-tools/export_hot_rank_top100_history.py` | 旧 Pages/Parquet 热榜导出 |
| `scripts/generate_report.py` | `archive/legacy-tools/generate_report.py` | 旧回测报告生成器，避免与 `src/generate_report.py` 混淆 |

## 当前保留的清理候选

| 内容 | 原因 | 建议 |
| --- | --- | --- |
| `archive/diagnostics/` | 历史排查脚本较多 | 后续按是否仍有复现价值继续删除 |
| `archive/reports/` | 历史报告较多 | 后续只保留最终结论，删除中间图表 |
| `docs/IMPLEMENTATION_PLAN.md` | 早期计划文档可能与当前状态重复 | 合并有效内容到架构/数据流水线后归档 |
| `scripts/prepare_features.py` | 仍服务旧 parquet 特征链路 | 确认策略回测是否仍依赖后再决定归档 |

## 每次清理的验证命令

```bash
git diff --check
python -m pytest --collect-only -q
rg -n "被删除或迁移的入口名" . -g "!archive/**" -g "!data/**" -g "!reports/**"
```
