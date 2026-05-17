# data 目录

`data/` 是本地和生产运行时数据目录，不是源码目录。真实行情数据、SQLite 数据库、热榜回补 CSV、实验输出和测试样本都不提交到 Git。

## 当前约定

| 路径 | 用途 | 是否提交 |
| --- | --- | --- |
| `data/quant.db` | 本地 SQLite 数据库 | 否 |
| `data/parquet/` | 旧 parquet 数据湖 | 否 |
| `data/hot_sources/` | 同花顺/雪球热榜回补数据 | 否 |
| `data/experiments/` | 本地实验和探针输出 | 否 |
| `data/README.md` | 本说明文件 | 是 |

## 原则

- 需要复现的数据通过脚本重新生成，不把快照塞进仓库。
- 生产数据库位于 `/data/quant_research/data/quant.db`。
- 需要临时测试样本时使用 pytest 的 `tmp_path` 或本机临时目录，不写入仓库内固定文件。
- 如果确实需要长期保存一份小型样例数据，先在 `docs/REPO_CLEANUP.md` 记录原因和大小上限。
