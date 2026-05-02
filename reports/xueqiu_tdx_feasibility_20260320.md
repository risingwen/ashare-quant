# 雪球上限与通达信可行性调研（2026-03-20）

## 1. 雪球：当前最多能获取多少

基于实测脚本 `scripts/probe_xueqiu_capacity.py`，结论如下：

1. A股分类（`category=CN`）下，四类榜单总量一致：`count=5571`  
   - `follow`（关注）  
   - `follow7d`（本周新增关注）  
   - `tweet`（讨论）  
   - `deal`（交易）
2. 单页 `size` 最大有效值是 `200`；`size=500/1000` 仍只返回 200 行。
3. 需要分页抓取，共 `28` 页（按 200/页）。
4. 以我们当前四次快照累计文件统计：  
   `data/hot_sources/xueqiu/xueqiu_hot_rank_snapshots.csv`  
   - 总行数：`88,086`  
   - 覆盖唯一股票：`5,571`
5. 历史日期参数（如 `date=2025-01-02` 或 `begin/end`）返回 `count=0`，即该接口不支持历史回放。

对应探针结果文件：`reports/xueqiu_capacity_probe.json`

## 2. 通达信：网上常见思路与可行性

### 2.1 可确认事实

1. `pytdx`定位为“标准行情/扩展行情/本地文件读取”，并未提供“人气榜/热度榜”接口。  
   参考：<https://github.com/peter159/pytdx-1>
2. 通达信App侧存在“热搜/问小达”相关功能入口（说明平台内部有热度内容展示）。  
   参考：<https://jingyan.baidu.com/article/8275fc8620f8d507a13cf64f.html>  
   参考：<https://apps.apple.com/cn/app/%E9%80%9A%E8%BE%BE%E4%BF%A1/id907323628>
3. 通过破解/篡改券商交易接口获取数据存在明显合规与刑事风险，不建议。  
   参考：<https://www.jcrb.com/rmjc/YAJJ/202206/t20220622_4979515.html>  
   参考：<https://m.fx361.com/news/2025/0520/27610153.html>

### 2.2 可执行路线（按优先级）

1. **合规优先：App可见数据抓取路线**  
   - 目标：仅抓“通达信App已公开展示的人气/热搜榜”  
   - 方法：Android模拟器 + 抓包（mitmproxy/charles） + API回放
2. **次选：页面自动化/OCR路线**  
   - 若接口存在证书固定或签名难复现，改为页面截图+OCR提取榜单
3. **不建议：逆向破解交易接口路线**  
   - 风险高、边界不清，不纳入本项目默认方案

## 3. 下一步建议

1. 雪球：继续日更快照累计（当前上限已明确为 5571/榜单/次）。  
2. 通达信：启动“App热搜榜抓取POC”，先打通“单日TopN落地CSV”。  
3. 打通后再接入现有 Pages 筛选页与日更任务。
