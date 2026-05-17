# 快速参考 - 手动下载数据

## 前置条件

1. **确保已安装依赖**：
```bash
pip install -r requirements.txt
```

2. **确保已配置 config.yaml**：
```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml 根据需要调整设置
```

## 手动下载命令

### 最简单的方式（推荐）

```bash
# 下载最近一年数据（默认）
python manual_download.py
```

执行后会显示下载范围并要求确认，输入 `y` 开始下载。

### 常用场景

```bash
# 下载最近6个月数据
python manual_download.py --months 6

# 下载最近30天数据
python manual_download.py --days 30

# 下载最近一年数据
python manual_download.py --months 12

# 指定具体日期范围
python manual_download.py --start 2024-01-01 --end 2025-12-31

# 不下载热度排名数据（加快速度）
python manual_download.py --no-popularity

# 使用更多并发加快速度
python manual_download.py --workers 10
```

### 组合使用

```bash
# 下载最近3个月，不要热度数据，10个并发
python manual_download.py --months 3 --no-popularity --workers 10
```

## 下载完成后

### 1. 查看数据
```bash
# 使用命令行工具
python view_parquet_simple.py

# 或使用交互式工具
python view_data.py
```

### 2. 使用 VS Code Data Wrangler
- 打开 VS Code
- 在 `data/parquet/ashare_daily/` 目录中找到任意 `.parquet` 文件
- 右键 → "Open in Data Wrangler"

### 3. 使用 Python 分析
```python
import pandas as pd

# 读取所有数据
df = pd.read_parquet('data/parquet/ashare_daily/**/*.parquet')

# 查看基本信息
print(df.head())
print(df.info())

# 查看特定股票
stock_df = df[df['code'] == '000001'].sort_values('date')
print(stock_df.tail(10))
```

## 注意事项

### 关于热度排名数据

⚠️ **重要限制**：
- 热度排名数据**只能获取最近一年**（约366天）
- 这是东方财富股吧API的限制
- 如果下载超过一年的数据，超出范围的热度字段会为空（`NaN`）

**解决方案**：
- 如需更长历史，请定期运行增量更新：
  ```bash
  python scripts/update_daily_incremental.py --config config.yaml
  ```
- 每日/每周运行一次增量更新，逐步积累热度历史数据

### 下载时间估计

| 数据范围 | 股票数 | 预计时间 | 数据大小 |
|---------|--------|---------|---------|
| 1个月 | ~5000 | 5-15分钟 | ~50MB |
| 3个月 | ~5000 | 15-30分钟 | ~150MB |
| 6个月 | ~5000 | 30-60分钟 | ~300MB |
| 1年 | ~5000 | 1-2小时 | ~600MB |


*实际时间取决于网络速度和限流设置*

### 如何加快下载速度

1. **减少并发数**（避免被限流）：
   ```bash
   python manual_download.py --workers 3
   ```

2. **调整配置文件中的限流设置**：
   ```yaml
   fetching:
     rate_limit: 2  # 每秒请求数，增加可加快速度但可能被封IP
   ```

3. **跳过热度数据**：
   ```bash
   python manual_download.py --no-popularity
   ```

## 常见问题

**Q: 下载中断了怎么办？**
A: 重新运行相同命令即可，脚本会自动断点续传（基于 `data/manifest.json` 记录）。

**Q: 如何更新已有数据？**
A: 使用增量更新脚本：
```bash
python scripts/update_daily_incremental.py --config config.yaml
```

**Q: 下载失败怎么办？**
A: 检查：
1. 网络连接是否正常
2. AkShare 版本是否最新：`pip install --upgrade akshare`
3. 查看日志文件：`logs/ashare_quant.log`

**Q: 如何只下载某几只股票？**
A: 目前不支持单独下载，如有需要可以：
1. 先全量下载
2. 使用 DuckDB 或 Pandas 过滤需要的股票

**Q: 数据存在哪里？**
A: 
- Parquet 文件：`data/parquet/ashare_daily/year=YYYY/month=MM/*.parquet`
- 进度文件：`data/manifest.json`
- 日志：`logs/ashare_quant.log`
