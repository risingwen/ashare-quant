# 快速查看数据指南

## 🎯 最简单的方法

### 方法 1: 使用项目自带工具 ⭐（最快）

```bash
python view_data.py
```

这会显示：
- ✅ 数据结构和字段类型
- ✅ 数据统计摘要
- ✅ 示例股票数据
- ✅ 成交量排行

---

## 🖥️ 使用图形化工具

### Windows 用户：ParquetViewer

**最快捷的图形化工具（无需安装）**

1. 下载：https://github.com/mukunku/ParquetViewer/releases
2. 下载 `ParquetViewer.zip`
3. 解压后双击 `ParquetViewer.exe`
4. 点击 "Open" 选择 Parquet 文件查看

📁 文件位置：`data/parquet/ashare_daily/year=2025/month=12/*.parquet`

---

### 专业用户：DBeaver ⭐（推荐）

**功能最强大的数据库客户端**

#### 下载安装
- 网址：https://dbeaver.io/download/
- 选择：DBeaver Community Edition（免费）
- 大小：约 100MB

#### 配置步骤

1. **启动 DBeaver**

2. **创建 DuckDB 连接**
   - 点击 "数据库" → "新建数据库连接"
   - 搜索并选择 "DuckDB"
   - 点击 "下一步"

3. **配置连接**
   - Path: `:memory:` （使用内存数据库）
   - 或者：`C:/Users/14737/OneDrive/06AKshare/ashare-quant/data/analysis.duckdb` （持久化）
   - 点击 "测试连接"
   - 如果提示下载驱动，点击 "下载"
   - 点击 "完成"

4. **查询数据**
   - 在 SQL 编辑器中输入：
   ```sql
   SELECT * 
   FROM read_parquet('C:/Users/14737/OneDrive/06AKshare/ashare-quant/data/parquet/ashare_daily/**/*.parquet')
   LIMIT 100;
   ```
   - 按 `Ctrl+Enter` 执行

#### 常用 SQL 示例

```sql
-- 查看特定股票
SELECT * 
FROM read_parquet('C:/Users/14737/OneDrive/06AKshare/ashare-quant/data/parquet/ashare_daily/**/*.parquet')
WHERE code = '000001'
ORDER BY date DESC;

-- 查看最新交易日数据
SELECT * 
FROM read_parquet('C:/Users/14737/OneDrive/06AKshare/ashare-quant/data/parquet/ashare_daily/**/*.parquet')
WHERE date = (
    SELECT MAX(date) 
    FROM read_parquet('C:/Users/14737/OneDrive/06AKshare/ashare-quant/data/parquet/ashare_daily/**/*.parquet')
);

-- 统计信息
SELECT 
    COUNT(*) as total_rows,
    COUNT(DISTINCT code) as stock_count,
    MIN(date) as start_date,
    MAX(date) as end_date
FROM read_parquet('C:/Users/14737/OneDrive/06AKshare/ashare-quant/data/parquet/ashare_daily/**/*.parquet');
```

---

### VS Code 用户：Parquet Viewer 扩展

1. 打开 VS Code
2. 按 `Ctrl+Shift+X` 打开扩展市场
3. 搜索 "Parquet Viewer"
4. 安装扩展
5. 在文件资源管理器中右键点击 `.parquet` 文件
6. 选择 "Open with Parquet Viewer"

---

## 📊 使用 Excel 查看（小数据集）

1. 打开 Excel
2. 数据 → 获取数据 → 从文件 → 从 Parquet
3. 选择 Parquet 文件
4. 点击 "加载"

⚠️ 注意：Excel 只能处理约 100 万行数据

---

## 🐍 使用 Python 脚本

### 快速查看
```python
import pandas as pd

# 读取单个文件
df = pd.read_parquet('data/parquet/ashare_daily/year=2025/month=12/000001_20260102_162850.parquet')
print(df)
```

### 查询所有数据
```python
import duckdb

con = duckdb.connect()
df = con.execute("""
    SELECT * FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    WHERE code = '600519'
    ORDER BY date DESC
    LIMIT 10
""").df()
print(df)
```

---

## 🆘 常见问题

### Q: 找不到数据文件？
A: 确认数据已下载：
```bash
python test_one_month.py  # 先下载一个月测试数据
```

### Q: DBeaver 连接失败？
A: 
1. 确认选择的是 DuckDB（不是 PostgreSQL 等）
2. 路径使用 `:memory:` 或绝对路径
3. 下载驱动时需要网络连接

### Q: 文件路径怎么写？
A: 
- Windows: `C:/Users/.../file.parquet` （用正斜杠 `/`）
- 或者: `C:\\Users\\...\\file.parquet` （双反斜杠）
- 通配符: `**/*.parquet` 匹配所有子目录

---

## 💡 推荐流程

1. **初次使用**: 运行 `python view_data.py` 快速查看
2. **日常查看**: 使用 ParquetViewer（Windows）或 VS Code 扩展
3. **深度分析**: 使用 DBeaver + DuckDB 进行 SQL 查询
4. **编程分析**: 使用 Python + pandas/duckdb

---

**需要帮助？** 查看完整文档：[docs/VIEWING_TOOLS.md](VIEWING_TOOLS.md)
