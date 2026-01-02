# Data Directory

本目录用于存储 A股数据文件。

## 目录结构

```
data/
├── parquet/                    # Parquet 数据湖（被 .gitignore 忽略）
│   └── ashare_daily/          # A股日线数据
│       ├── year=2024/         # 按年分区
│       │   ├── month=01/      # 按月分区
│       │   ├── month=02/
│       │   └── ...
│       └── year=2025/
│           └── ...
├── manifest.json              # 下载进度跟踪文件（被 .gitignore 忽略）
└── README.md                  # 本文件
```

## 数据说明

### Parquet 文件
- **路径**: `data/parquet/ashare_daily/year=YYYY/month=MM/*.parquet`
- **分区策略**: 按年月分区（year_month）
- **文件格式**: Apache Parquet（使用 snappy 压缩）
- **字段**:
  - `date`: 交易日期 (date)
  - `code`: 股票代码 (string)
  - `open`: 开盘价 (float)
  - `high`: 最高价 (float)
  - `low`: 最低价 (float)
  - `close`: 收盘价 (float)
  - `volume`: 成交量 (int64)
  - `amount`: 成交额 (float)

### Manifest 文件
- **路径**: `data/manifest.json`
- **用途**: 跟踪每只股票的下载进度和状态
- **格式**: JSON
- **内容**: 股票代码、最新日期、状态、行数等

## 注意事项

1. **数据文件不提交到 Git**
   - 所有 `.parquet`、`.json`、`.duckdb` 等数据文件已被 `.gitignore` 排除
   - 仅提交代码和配置文件到版本控制

2. **数据备份**
   - 建议定期备份 `data/parquet/` 目录到云盘或外部存储
   - Manifest 文件也应该备份，以便恢复下载进度

3. **磁盘空间**
   - 约 5000 只股票，1 年日线数据，Parquet 格式约占用 300MB-600MB
   - 请确保有足够的磁盘空间

4. **查询数据**
   - 使用 DuckDB 可以直接查询 Parquet 文件，无需导入
   - 示例查询请参考项目 README.md
