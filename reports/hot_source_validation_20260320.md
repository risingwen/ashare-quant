# 多平台人气/热度数据可用性核验（2026-03-20）

核验时间：2026-03-20 10:57:56（Asia/Shanghai）

## 结论总览

| 平台 | 当前是否可拉取 | 说明 |
|---|---|---|
| 东方财富 | 是（快照） | `ak.stock_hot_rank_em` 可返回 100 行人气榜。 |
| 同花顺 | 是（快照） | `adata.sentiment.hot.hot_rank_100_ths` 可返回 100 行，含 `hot_value`。 |
| 雪球 | 是（快照） | `ak.stock_hot_follow_xq("最热门")` 可返回 5571 行。 |
| 通达信 | 否（未打通） | 现有公开方案未拿到可用“人气榜/热度榜”表格数据。 |

## 真实性证据（接口来源）

1. 东方财富（AKShare 源码）  
   - 接口地址：`https://emappdata.eastmoney.com/stockrank/getAllCurrentList`  
   - 函数：`akshare.stock.stock_hot_rank_em.stock_hot_rank_em`

2. 同花顺（adata 源码）  
   - 接口地址：`https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?...`  
   - 函数：`adata.sentiment.hot.hot_rank_100_ths`

3. 雪球（AKShare 源码）  
   - 接口地址：`https://xueqiu.com/service/v5/stock/screener/screen`  
   - 函数：`akshare.stock_feature.stock_hot_xq.stock_hot_follow_xq`

4. 通达信（pytdx 能力边界）  
   - `pytdx` 的 `get_*` 方法仅涵盖 K 线/分时/财务等，不包含“人气/热度榜”接口。  
   - `pywencai` 关键词“通达信 人气榜 ...”返回非表格（`dict`），不可直接作为稳定数据源。

## 建议

1. 生产链路先以“东财 + 同花顺 + 雪球”为主。  
2. 通达信单列为专项攻关（客户端抓包/逆向，暂不进主流程）。  
3. 页面展示时将通达信标记为“未打通”。
