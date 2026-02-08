# 项目目标
- 用 AkShare 拉取 A股近一年日线数据（可扩展到复权、成交额、人气等）
- 数据落地到项目本地目录，方便访问
- 分析用 DuckDB（本机），优先"查询 Parquet 数据湖文件"，避免频繁读写数据库文件

# 数据口径（默认）
- 频率：daily
- 日期：交易日（以数据源返回为准）
- 股票范围：沪深京 A 股（后续可增加过滤：ST、退市、北交所等）
- 字段：date, code, open, high, low, close, volume, amount（以 AkShare 返回字段为准，统一重命名为 snake_case）

# 工程规范
- 所有脚本必须给出“脚本名称”，并提供 main() 入口与 argparse 参数
- 日志使用 logging，关键步骤打印清晰英文提示（不使用 emoji）
- 必须实现：断点续跑、失败重试、限流保护、数据校验（行数/重复/空值/日期连续性）
- 目录结构要清晰：src/ tests/ data/（data 只存少量示例，真实数据在 OneDrive 路径）
- Git commit 信息使用中文，简洁明了描述改动内容和原因

# 文档规范
- 策略文档（.github/prompts/）需要包含完整的策略逻辑、参数说明、实现要点
- 每次策略逻辑或参数调整后，必须在文档末尾添加 Changelog 章节
- Changelog 格式：日期 + 分类（Changed/Fixed/Added/Removed）+ 详细说明（包含原因和影响）