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
10. 下一动作：继续按数据补全节奏推进，并观察自动同步发布效果。

## 7. 下一步执行清单
1. 运行一轮 `scripts/update_daily_incremental.py`（低并发）。
2. 运行 `scripts/audit_data_integrity.py`，记录覆盖变化。
3. 若覆盖达到预期，执行 `scripts/prepare_features.py`。
4. 运行组合实验并发布到 `reports/latest.md`。
5. push 后跟踪 Pages 日志，失败即修复。
