# A股量化统一计划（唯一计划文件）

更新时间：2026-03-19

## 1. 总目标
- 基于 A 股历史数据，推测：
- 大盘涨跌幅
- 热门板块涨跌幅
- 热门个股涨跌幅
- 进行多种策略组合尝试并比较效果。
- 自动生成各方案 Markdown 报告。
- 通过 GitHub Pages 持续发布并可访问。

## 2. 阶段路线
1. 数据补全与校验
2. 特征构建与更新
3. 组合实验与回测
4. 报告生成与发布
5. 部署监控与修复

## 3. 当前优先级（按顺序执行）
1. 数据补全（优先）
2. 数据审计（每轮补数后）
3. 特征重建
4. 组合实验
5. 报告发布与 Pages 验证

## 4. 行动任务看板
1. 部署链路检查（workflow、发布脚本、忽略规则）  
状态：已完成
2. 修复 `reports/generated` 版本控制与发布路径问题  
状态：已完成
3. 修复“无实验时覆盖 `reports/latest.md`”问题  
状态：已完成
4. 本地与线上部署可访问性验证  
状态：已完成
5. 数据补全续跑（以 `2026-03-18` 为当前审计锚点）  
状态：进行中（个股热度数据已到最新，继续补齐行情覆盖）
6. 每日任务与进度记录统一沉淀到本文件  
状态：进行中
7. 历史热度前100导出与网页筛选发布  
状态：已完成（CSV + 可筛选HTML已生成并接入Pages）

## 5. 已落地修复（部署相关）
1. `.gitignore` 已放开 `reports/generated/*.md`
2. `scripts/publish_latest_experiment_to_reports.py` 已修复：
- 无实验目录时保留已有 `reports/latest.md`
- 发布新实验前清理 `reports/generated/*.md`
3. `.github/workflows/static.yml` 已修复：
- 创建 `public/generated`
- 复制 `reports/generated/*.md` 到 `public/generated`

## 6. 每日任务更新（持续追加）
### 2026-03-19
1. 已完成部署链路体检与关键修复。
2. 已确认最新 Pages workflow 为成功状态。
3. 已确认站点可访问（首页和 `latest.html` 返回 200）。
4. 已确认个股热度数据已拉取到最新。
5. 已新增历史热度前100导出脚本，并生成：
- `reports/hot_rank_top100_history.csv`
- `reports/hot_rank_top100_explorer.html`
6. 已更新 Pages workflow 首页入口，支持网页筛选浏览。
7. 已统一为热度历史前100，并重构页面为“按交易日榜单 + 个股历史排名”双栏视图。
8. 已去除前端二次加载依赖（数据内嵌 HTML），避免页面停留在“正在加载数据...”。
9. 已在 Pages workflow 中加入自动重建步骤：部署前自动生成热度前100 `csv+html`，确保数据更新后网页自动同步。
10. 已新增 `scripts/build_pages_local.sh`，可本地一键复现与 CI 一致的 `public/` 发布产物。
11. 已补充 `docs/LOCAL_REPRODUCTION.md` 与 `reports/strategies/README.md`，方便新成员快速理解与复现。
12. 下一动作：按文档执行一次策略回测全链路并补充对比报告。
13. 已补充“每策略详细说明 + 对应买卖记录入口”，并新增统一交易发布脚本。
14. 已重构 Pages 首页布局（卡片式导航），提升策略说明与交易记录可达性。
15. 已为四个策略生成固定名称的最新交易记录页面（drop7/rise2/top20_newentry/first_top10）。
16. 已修复交易记录 HTML 的 `code` 展示（统一 6 位，保留前导 0），并同步覆盖四个策略页面。
17. 已统一金额/价格类字段显示为两位小数（收益率等比例字段保留原精度），避免页面阅读噪音。
18. 已将收益率比例字段（含 `pct`）统一为四位小数，交易页展示口径一致。
19. 已同步非交易表页面脚本格式规范：热度历史页面代码统一 6 位，并支持查询输入自动补零。
20. 已同步 `generate_trades_html.py` 的金额/价格展示口径（金额两位小数、代码前导零保留）。

### 2026-03-19（补充：交易页显示修复）
1. 执行 `python3 scripts/publish_strategy_trades.py` 重新生成四个策略交易页。
2. 校验 `reports/trades/*_trades_latest.html` 的首列代码展示为 6 位字符串。
3. 校验金额/价格类字段统一为两位小数后，准备随下一次 Pages 发布上线。
4. 已补充：收益率比例字段统一四位小数并完成四策略页面重建。


## 8. 大任务执行跟踪（策略全量复现）
### 2026-03-19（已完成）
1. 目标：复现已跑通策略（drop7 / rise2 / top20_newentry / first_top10）。
2. 步骤：
- 逐个执行策略脚本并记录日志
- 生成/更新交易与报告产物
- 重新构建本地 Pages 产物并校验入口
3. 执行结果：
- 四个策略均已成功复现（含交易明细与组合净值产物）。
- 已新增复现报告：
  - `reports/reproduce_summary_20260319.md`
  - `reports/reproduce_drop7_20260319.md`
  - `reports/reproduce_rise2_20260319.md`
  - `reports/reproduce_top20_newentry_20260319.md`
  - `reports/reproduce_first_top10_20260319.md`
- `reports/latest.md` 已更新为本次复现入口页。
- 为兼容历史特征缺失列，已修复 `scripts/backtest_hot_rank_strategy.py` 的向后兼容逻辑（缺列不再中断）。

## 7. 下一步执行清单
1. 运行一轮 `scripts/update_daily_incremental.py`（低并发）。
2. 运行 `scripts/audit_data_integrity.py`，记录覆盖变化。
3. 若覆盖达到预期，执行 `scripts/prepare_features.py`。
4. 运行组合实验并发布到 `reports/latest.md`。
5. push 后跟踪 Pages 日志，失败即修复。
