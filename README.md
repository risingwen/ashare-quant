# AShare Quant - A股数据湖项目

使用 AkShare 拉取 A股近一年历史数据（OHLCV + 换手率 + 热度排名），存储到 Parquet 数据湖，并通过 DuckDB 进行快速分析。

## 核心特性

- **历史数据**: OHLCV（开高低收量额） + 换手率
- **热度排名**: 每日股票热度排名 + 粉丝占比（可选，近一年数据）
- **Parquet 格式**: 高效存储，支持增量读取
- **DuckDB 查询**: 无需数据库，直接查询 Parquet 文件
- **断点续传**: 支持中断后继续下载
- **数据校验**: 自动去重、验证数据质量

## 目录结构

```
ashare-quant/
├── src/                    # 核心库代码
│   ├── utils.py           # 通用工具函数（日志、重试、限流）
│   ├── validation.py      # 数据验证工具
│   └── manifest.py        # 进度跟踪管理
├── scripts/               # 可执行脚本
│   ├── download_ashare_3y_to_parquet.py  # 全量下载脚本
│   └── update_daily_incremental.py       # 增量更新脚本
├── tests/                 # 单元测试
├── docs/                  # 文档
├── data/                  # 本地示例数据（不含真实数据）
│   └── manifest.json      # 下载进度跟踪文件
├── .github/               # GitHub 配置和 prompts
├── config.example.yaml    # 配置文件示例
├── requirements.txt       # Python 依赖
├── .gitignore
└── README.md
```

## 快速开始

### 1. 环境准备

```bash
# 克隆仓库
git clone <repository-url>
cd ashare-quant

# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

**注意**：虚拟环境创建后会在项目根目录生成 `venv/` 文件夹，已配置在 `.gitignore` 中。

### 2. 测试系统

运行测试脚本验证环境配置：

```bash
python test_system.py
```

测试内容包括：
- AkShare API 连接
- 单只股票数据获取
- Parquet 读写
- DuckDB 查询

### 3. 配置

复制配置示例文件并根据实际情况修改：

```bash
cp config.example.yaml config.yaml
```

**重要配置项**:
- `onedrive_root`: 数据存储根目录（默认：`data/parquet`，存储在项目本地）
- `fetching.workers`: 并发下载数量（建议 3-5）
- `fetching.rate_limit`: 限流设置（建议 1-2 请求/秒）
- `adjust`: 复权类型（`qfq` 前复权 / `hfq` 后复权 / `""` 不复权）
- **`enable_popularity`: 是否采集股票热度排名（`true`/`false`，默认开启）**
  - 开启后会额外获取：热度排名、新晋粉丝占比、铁杆粉丝占比
  - 数据源：东方财富股吧 API
  - **覆盖范围：近一年历史数据（~366天）** ⚠️
  - **重要**：热度数据受API限制只能获取最近一年，如需更长历史需定期运行增量更新积累

### 4. 首次全量下载（近一年数据）

**⭐ 方式1：手动下载脚本（最简单）**

```bash
# 下载最近一年数据（默认）
python manual_download.py

# 下载最近6个月数据
python manual_download.py --months 6

# 下载最近30天数据
python manual_download.py --days 30

# 指定具体日期范围
python manual_download.py --start 2024-01-01 --end 2025-12-31

# 不下载热度排名（加快速度）
python manual_download.py --no-popularity
```

**方式2：使用快速开始脚本**

```bash
python quick_start.py
```

**方式3：直接调用下载脚本**

```bash
python scripts/download_ashare_3y_to_parquet.py \
    --start-date 2024-01-01 \
    --end-date 2026-01-02 \
    --config config.yaml
```

**参数说明**：
- `--start-date`: 开始日期（YYYY-MM-DD）
- `--end-date`: 结束日期（YYYY-MM-DD）
- `--config`: 配置文件路径
- `--workers`: 并发数（可选，默认读取配置文件）
- `--adjust`: 复权类型（可选，默认读取配置文件）

**运行时间**：全量下载约 5000 只股票，1 年数据，约需 1-2 小时（取决于网络和限流设置）

**输出位置**：
- Parquet 文件：`data/parquet/ashare_daily/year=YYYY/month=MM/*.parquet`
- 进度文件：`data/manifest.json`
- 日志文件：`logs/ashare_quant.log`

### 5. 增量更新（每日运行）

```bash
python scripts/update_daily_incremental.py --config config.yaml
```

脚本会自动：
1. 读取 manifest 找出每只股票的最新日期
2. 只拉取缺失的交易日数据
3. 去重并追加到对应的 Parquet 分区
4. 更新 manifest 和生成日报

### 6. 查看和分析数据

#### 使用项目自带工具（推荐）
```bash
# 数据浏览工具
python view_data.py
```

#### 使用图形化客户端工具 ⭐

**最推荐: VS Code Data Wrangler**
- 微软官方扩展，下载量最高
- 交互式数据探索 + 可视化 + 代码生成
- 安装: VS Code 扩展市场搜索 "Data Wrangler"
- 使用: 右键 `.parquet` 文件 → "Open in Data Wrangler"

**其他选择**:
- **DBeaver** - 功能最强大，支持 SQL 查询
- **ParquetViewer** - Windows 轻量级工具
- **其他 Parquet Viewer** - VS Code 其他扩展

详细说明请查看：
- 📘 [Data Wrangler 完整指南](docs/DATA_WRANGLER_GUIDE.md)
- 📗 [数据查看工具对比](docs/VIEWING_TOOLS.md)
- 📙 [快速查看指南](docs/QUICK_VIEW.md)

#### 使用 DuckDB 编程查询
```python
import duckdb

# 连接到内存数据库
con = duckdb.connect()

# 直接查询 Parquet 数据湖
query = """
SELECT 
    code, 
    date, 
    close, 
    volume
FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
WHERE code = '000001'
  AND date >= '2025-01-01'
ORDER BY date
"""

df = con.execute(query).df()
print(df)
```

**性能提示**：
- DuckDB 支持直接查询 Parquet，无需导入
- 使用分区剪枝可大幅提升查询速度
- 不建议将 `.duckdb` 文件放在云盘上频繁读写

## 数据字段说明

统一字段名（snake_case）：

| 字段 | 说明 | 类型 |
|------|------|------|
| date | 交易日期 | date |
| code | 股票代码 | string |
| open | 开盘价 | float |
| high | 最高价 | float |
| low | 最低价 | float |
| close | 收盘价 | float |
| volume | 成交量 | int64 |
| amount | 成交额 | float |

## 数据质量

脚本内置以下校验：
- ✅ (code, date) 去重
- ✅ 空值检测
- ✅ 负价格检测
- ✅ 失败重试（指数退避）
- ✅ 断点续跑（基于 manifest）

## 常见问题

### Q1: 下载中断了怎么办？
A: 重新运行相同命令，脚本会从 manifest 中读取进度，只下载失败或缺失的股票。

### Q2: 数据量太大怎么办？
A: Parquet 默认按 year/month 分区，查询时可以利用分区过滤。单个月文件约 50-100MB。

### Q3: 如何备份数据到云盘？
A: 数据默认存储在项目的 `data/parquet/` 目录下。如需备份到 OneDrive 或其他云盘，可以在下载完成后手动复制，或修改 `config.yaml` 中的 `onedrive_root` 路径指向云盘目录。

### Q4: 遇到 AkShare 接口错误？
A: AkShare 接口偶尔变动，检查 `akshare` 版本，必要时降级到稳定版本。查看日志了解具体错误。

### Q5: 策略回测中创业板/科创板为什么触发阈值不同？
A: 创业板（300）和科创板（688）波动率显著高于主板，使用-13%触发买入以避免正常波动中的假信号；主板和深市股票保持-7%触发。这是基于不同板块的风险特征进行的差异化设计。详见 `docs/STRATEGY_REQUIREMENTS.md`。

## 策略回测

### 人气榜-7%策略（含差异化阈值）

**策略逻辑**：
- 前一交易日人气榜前100名股票
- 次日跌破触发阈值时买入：
  - **创业板（300）、科创板（688）**：-13%触发
  - **其他股票（主板、深市）**：-7%触发
- 智能卖出：
  - 涨停日继续持有（捕捉连板行情）
  - 跌破-7%时止损卖出
  - 其他情况T+1收盘卖出

**配置文件**：`config/strategies/hot_rank_drop7.yaml`

**运行回测**：
```bash
# 生成特征数据
python scripts/prepare_features.py --version v1

# 运行回测
python scripts/backtest_hot_rank_strategy.py \
  --config config/strategies/hot_rank_drop7.yaml \
  --features data/processed/features/daily_features_v1.parquet
```

**关键参数**：
- `hot_top_n: 100` - 人气榜前N名
- `prev_amount_min: 2000000000` - 成交额下限（20亿）
- `drop_trigger: 0.07` - 主板触发阈值（-7%）
- `drop_trigger_cyb_kcb: 0.13` - 创业板/科创板触发阈值（-13%）
- `hold_on_limit_up: true` - 涨停不卖
- `exit_on_limit_down: true` - 跌停卖出

详细策略说明参见 `docs/STRATEGY_REQUIREMENTS.md`。

## 开发与贡献

### 运行测试

```bash
pytest tests/
```

### 代码规范

- 遵循 PEP 8
- 所有脚本必须有 `main()` 入口和 argparse 参数
- 关键操作必须记录日志
- 新功能需要添加测试

## 许可证

MIT License

## 致谢

- [AkShare](https://github.com/akfamily/akshare) - 开源金融数据接口
- [DuckDB](https://duckdb.org/) - 快速分析型数据库
- [Apache Parquet](https://parquet.apache.org/) - 列式存储格式
