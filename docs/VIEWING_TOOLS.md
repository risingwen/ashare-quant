# Parquet 数据查看工具指南

本项目的数据存储在 Parquet 格式中，有多种工具可以方便地查看和分析这些数据。

## 🎯 推荐工具

### 1. **DBeaver** ⭐ 强烈推荐
**最佳选择 - 功能强大的免费数据库客户端**

- **下载**: https://dbeaver.io/download/
- **支持**: Windows, macOS, Linux
- **特点**: 
  - ✅ 免费开源
  - ✅ 可视化查询界面
  - ✅ 支持 SQL 查询
  - ✅ 数据导出
  - ✅ 数据透视表

**使用步骤**:
1. 下载安装 DBeaver Community Edition
2. 新建连接 → 选择 "DuckDB"
3. 创建内存数据库（`:memory:`）
4. 在 SQL 编辑器中查询：
```sql
SELECT * FROM read_parquet('C:/Users/14737/OneDrive/06AKshare/ashare-quant/data/parquet/ashare_daily/**/*.parquet')
LIMIT 100;
```

### 2. **VS Code 扩展** 📝
**最方便 - 如果你已经在用 VS Code**

#### a) Data Wrangler ⭐ 强烈推荐
- **安装**: 搜索 "Data Wrangler" (微软官方扩展)
- **下载量**: 最高，超过 500K+
- **特点**:
  - ✅ 微软官方开发
  - ✅ 交互式数据探索
  - ✅ 数据清洗和转换
  - ✅ 可视化图表
  - ✅ 支持 Parquet/CSV/Excel/JSON
- **使用**: 
  1. 右键点击 `.parquet` 文件
  2. 选择 "Open in Data Wrangler"
  3. 可以排序、筛选、统计、可视化

**特别优势**: 
- 可以直接生成 Python/Pandas 代码
- 内置数据质量检查
- 交互式操作，无需编写代码

#### b) Parquet Viewer
- **安装**: 搜索 "Parquet Viewer" 或 "Parquet Explorer"
- **使用**: 直接右键点击 `.parquet` 文件 → "Open with Parquet Viewer"
- **特点**: 轻量级，只读查看

#### c) Rainbow CSV + DuckDB
- **安装**: 
  - Rainbow CSV
  - DuckDB SQL Tools
- **使用**: 可以在 VS Code 中直接用 SQL 查询

### 3. **在线工具** 🌐
**最快速 - 无需安装**

#### Parquet Viewer Online
- **网址**: https://parquet-viewer-online.com/
- **使用**: 上传 Parquet 文件直接查看
- **限制**: 文件大小限制（通常 < 100MB）

⚠️ **注意**: 不要上传敏感数据到公共在线工具

### 4. **ParquetViewer (Windows)** 💻
**专用工具 - 轻量级**

- **下载**: https://github.com/mukunku/ParquetViewer/releases
- **特点**: 
  - 轻量级 Windows 应用
  - 快速加载
  - 简单直观

**使用**: 双击 .exe 文件，然后打开 Parquet 文件

### 5. **Python 脚本** 🐍
**最灵活 - 适合编程使用**

#### 方式 1: 使用项目自带工具
```bash
python view_data.py
```

#### 方式 2: Jupyter Notebook
```bash
pip install jupyter
jupyter notebook
```

然后在 Notebook 中：
```python
import pandas as pd

df = pd.read_parquet('data/parquet/ashare_daily/**/*.parquet')
df.head(20)
```

#### 方式 3: 交互式 Python
```python
import pandas as pd
import duckdb

# 方法 A: Pandas
df = pd.read_parquet('data/parquet/ashare_daily/**/*.parquet')
print(df)

# 方法 B: DuckDB (推荐，更快)
con = duckdb.connect()
df = con.execute("""
    SELECT * FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    WHERE code = '000001'
    ORDER BY date DESC
    LIMIT 10
""").df()
print(df)
```

### 6. **DuckDB CLI** 🦆
**命令行工具 - 高性能**

```bash
# 安装
pip install duckdb

# 使用
python -m duckdb

# 在 DuckDB 提示符中
D SELECT * FROM read_parquet('data/parquet/ashare_daily/**/*.parquet') LIMIT 10;
```

### 7. **Excel / Power BI** 📊
**商业分析工具**

#### Excel Power Query
1. Excel → 数据 → 获取数据 → 从文件 → 从 Parquet
2. 选择 Parquet 文件
3. 加载到 Excel

#### Power BI
1. 获取数据 → Parquet
2. 导入并可视化

⚠️ **限制**: Excel 最多只能处理约 100 万行

## 🎮 快速开始：推荐方案

### 方案 A: VS Code 用户 ⭐ 最推荐
1. 安装 **Data Wrangler** 扩展（微软官方）
2. 右键 Parquet 文件 → "Open in Data Wrangler"
3. 享受交互式数据探索和可视化

### 方案 B: 轻量级用户
1. 安装 **ParquetViewer** (Windows) 或 **Tad** (跨平台)
2. 直接打开 Parquet 文件浏览

### 方案 C: 开发者用户
1. 使用项目自带的 `python view_data.py`
2. 或在 Python 中直接操作

### 方案 D: 专业分析
1. 安装 **DBeaver**
2. 使用 SQL 进行复杂查询和分析

## 📊 常用查询示例

### 在 DBeaver / DuckDB 中

```sql
-- 查看某只股票的历史
SELECT * FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
WHERE code = '000001'
ORDER BY date DESC;

-- 查看最新交易日所有股票
WITH latest_date AS (
    SELECT MAX(date) as max_date
    FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
)
SELECT * FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
WHERE date = (SELECT max_date FROM latest_date);

-- 计算某股票的移动平均
SELECT 
    date,
    close,
    AVG(close) OVER (ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) as ma5,
    AVG(close) OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as ma20
FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
WHERE code = '600519'
ORDER BY date DESC;
```

## 🔧 我的推荐

根据不同需求：

| 需求 | 推荐工具 | 原因 |
|------|----------|------|
| **交互式探索** ⭐ | Data Wrangler (VS Code) | 微软官方，功能最全，可视化强 |
| **快速浏览** | ParquetViewer / 其他 Parquet Viewer | 简单直接，无需配置 |
| **数据分析** | DBeaver + DuckDB | 强大的 SQL 支持 |
| **编程使用** | Python + pandas/duckdb | 灵活可扩展 |
| **可视化** | Data Wrangler / Jupyter | 交互式分析和图表 |
| **大数据集** | DuckDB CLI | 高性能 |

**首选推荐**: 如果你用 VS Code 开发，直接装 **Data Wrangler**，体验最好！

## 💡 小技巧

1. **大文件处理**: 使用 DuckDB 而不是 Pandas，速度快 10-100 倍
2. **远程查看**: 可以用 Jupyter 启动服务器，浏览器访问
3. **数据导出**: 在 DBeaver 中可以导出为 CSV/Excel 格式
4. **VS Code**: 如果你已经用 VS Code 写代码，直接装扩展最方便

## 📝 项目自带工具

本项目提供了便捷的查看脚本：

```bash
# 全面数据浏览
python view_data.py

# 系统测试（包含数据样例）
python test_system.py
```

## 🆘 遇到问题？

如果工具无法打开文件：
1. 确认 Parquet 文件路径正确
2. 确认文件没有损坏
3. 尝试先用 Python 验证：
```python
import pandas as pd
df = pd.read_parquet('你的文件路径.parquet')
print(df.shape)  # 应该显示行列数
```

---

**建议**: 如果你是初次使用，推荐先用 **ParquetViewer** (Windows) 或项目自带的 `python view_data.py` 快速查看数据！
