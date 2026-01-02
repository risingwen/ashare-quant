---
agent: "copilot"
---

你是资深Python数据工程/量化工程助手。请为“AkShare 拉取A股近一年数据 + Parquet数据湖 + DuckDB分析”创建一个可运行的项目脚手架。

要求：
1. 给出目录结构（src/, scripts/, tests/, docs/），并解释每个目录用途
2. 生成 requirements.txt（或 uv/poetry 二选一，你自行判断更适合轻量项目的方案）
3. 生成 README.md：包含环境准备、OneDrive 数据目录配置、首次全量拉取、日更增量、示例查询
4. 生成配置文件：config.example.yaml（包含 OneDrive 根路径、分区粒度、并发/限流参数）

注意：
- 数据存储在项目本地目录，不放进仓库；仓库只放代码与少量样例
- 所有脚本都必须有脚本名称、命令行参数示例
