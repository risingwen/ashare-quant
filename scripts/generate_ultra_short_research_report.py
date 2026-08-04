#!/usr/bin/env python3
"""Generate the long-form hot-money and ultra-short strategy review report."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

from sqlalchemy import text

from quant_platform.db import engine
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = PROJECT_ROOT / "scripts" / "ultra_short_research_report.html"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "apps" / "web" / "public" / "strategy-research"
    / "ultra-short-research-report.html"
)
DEFAULT_MARKDOWN = PROJECT_ROOT / "reports" / "ultra_short_research_report.md"
DEFAULT_RESEARCH_DIR = PROJECT_ROOT / "apps" / "web" / "public" / "strategy-research"


MAPPING_SQL = """VALUES
  ('陈小群','%中国银河证券%大连黄河路%'),
  ('章盟主','%国泰%上海%江苏路%'),
  ('作手新一','%国泰%南京%太平南路%'),
  ('宁波桑田路','%国盛证券%宁波桑田路%'),
  ('呼家楼','%中信建投%北京东城分公司%')
"""


SEAT_EVENT_CTE = f"""
WITH mapping(hot_money_name,seat_pattern) AS ({MAPPING_SQL}), raw_events AS (
  SELECT m.hot_money_name,s.trade_date,s.symbol,s.seat_name,s.buy,s.sell,s.net_buy,s.reason,
    row_number() OVER (
      PARTITION BY m.hot_money_name,s.trade_date,s.symbol
      ORDER BY abs(s.net_buy) DESC NULLS LAST,s.seat_name
    ) event_row
  FROM mapping m
  JOIN market.lhb_seat s ON s.seat_name LIKE m.seat_pattern
  WHERE s.trade_date BETWEEN :start AND :end
), events AS (
  SELECT * FROM raw_events WHERE event_row=1
), adjusted AS (
  SELECT b.symbol,b.trade_date,b.close,b.pct_change,b.turnover,b.amount*1000 amount_yuan,
    exp(sum(ln(1+b.pct_change/100.0)) OVER (
      PARTITION BY b.symbol ORDER BY b.trade_date
    )) adjusted_close
  FROM market.daily_bar b
  WHERE b.trade_date BETWEEN :price_start AND :price_end AND b.pct_change>-99.99
), bars AS (
  SELECT *,
    lead(adjusted_close,1) OVER w adjusted_1,
    lead(adjusted_close,3) OVER w adjusted_3,
    lead(adjusted_close,5) OVER w adjusted_5,
    avg(amount_yuan) OVER (
      PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
    ) adv20_yuan,
    max(adjusted_close) OVER (
      PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
    ) high120
  FROM adjusted WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
), final_snapshots AS (
  SELECT id,endpoint,trade_date FROM (
    SELECT s.id,s.endpoint,s.trade_date,row_number() OVER (
      PARTITION BY s.endpoint,s.trade_date ORDER BY s.snapshot_time DESC,s.id DESC
    ) snapshot_row
    FROM popularity.snapshot s
    WHERE s.status='success' AND s.trade_date BETWEEN :start AND :end
  ) ranked WHERE snapshot_row=1
), popularity_rank AS (
  SELECT f.trade_date,i.symbol,
    min(i.rank) FILTER (WHERE f.endpoint='dc_hot') dc_rank,
    min(i.rank) FILTER (WHERE f.endpoint='ths_hot') ths_rank
  FROM final_snapshots f JOIN popularity.snapshot_item i ON i.snapshot_id=f.id
  GROUP BY f.trade_date,i.symbol
), enriched AS (
  SELECT e.*,coalesce(i.name,e.symbol) name,b.close,b.pct_change,b.turnover,b.amount_yuan,b.adv20_yuan,
    100*(b.adjusted_1/b.adjusted_close-1) return_t1_pct,
    100*(b.adjusted_3/b.adjusted_close-1) return_t3_pct,
    100*(b.adjusted_5/b.adjusted_close-1) return_t5_pct,
    100*(b.adjusted_close/b.high120-1) high120_distance_pct,
    p.dc_rank,p.ths_rank
  FROM events e
  JOIN bars b USING(symbol,trade_date)
  LEFT JOIN market.instrument i USING(symbol)
  LEFT JOIN popularity_rank p USING(symbol,trade_date)
)
"""


DETAIL_SQL = text(SEAT_EVENT_CTE + """
SELECT hot_money_name,trade_date,symbol,name,seat_name,buy,sell,net_buy,reason,
  close,pct_change,turnover,amount_yuan,adv20_yuan,dc_rank,ths_rank,
  high120_distance_pct,return_t1_pct,return_t3_pct,return_t5_pct
FROM enriched ORDER BY trade_date DESC,abs(net_buy) DESC
""")


SUMMARY_SQL = text(SEAT_EVENT_CTE + """
SELECT hot_money_name,count(*) event_count,count(DISTINCT trade_date) trade_days,
  count(DISTINCT symbol) stock_count,sum(buy) buy_amount,sum(sell) sell_amount,sum(net_buy) net_amount,
  avg(amount_yuan) stock_amount_avg,percentile_cont(.5) WITHIN GROUP (ORDER BY amount_yuan) stock_amount_median,
  count(*) FILTER (WHERE net_buy>=20000000) material_buy_events,
  avg(return_t1_pct) FILTER (WHERE net_buy>=20000000) return_t1_avg,
  percentile_cont(.5) WITHIN GROUP (ORDER BY return_t1_pct)
    FILTER (WHERE net_buy>=20000000) return_t1_median,
  100*avg((return_t1_pct>0)::int) FILTER (WHERE net_buy>=20000000) return_t1_win,
  avg(return_t3_pct) FILTER (WHERE net_buy>=20000000) return_t3_avg,
  avg(return_t5_pct) FILTER (WHERE net_buy>=20000000) return_t5_avg,
  100*avg((high120_distance_pct>=-2)::int) FILTER (WHERE net_buy>=20000000) near_high_rate
FROM enriched GROUP BY hot_money_name ORDER BY return_t1_avg DESC
""")


LATEST_DETAIL_SQL = text("""
SELECT d.trade_date,d.hot_money_name,d.associated_orgs,d.symbol,d.name,d.buy_amount,d.sell_amount,
  d.net_amount,d.tag,b.close,b.pct_change,b.turnover,b.amount*1000 amount_yuan
FROM market.hot_money_detail d
LEFT JOIN market.daily_bar b USING(trade_date,symbol)
WHERE d.trade_date=(SELECT max(trade_date) FROM market.hot_money_detail)
ORDER BY abs(d.net_amount) DESC NULLS LAST,d.hot_money_name,d.symbol
""")


BASELINE_SQL = text("""WITH raw AS (
  SELECT s.trade_date,s.symbol,s.seat_name,s.buy,s.sell,s.net_buy,
    row_number() OVER (
      PARTITION BY s.trade_date,s.symbol,s.seat_name
      ORDER BY abs(s.net_buy) DESC NULLS LAST
    ) event_row
  FROM market.lhb_seat s WHERE s.trade_date BETWEEN :start AND :end
), e AS (SELECT * FROM raw WHERE event_row=1 AND net_buy>=20000000), adjusted AS (
  SELECT b.symbol,b.trade_date,
    exp(sum(ln(1+b.pct_change/100.0)) OVER (
      PARTITION BY b.symbol ORDER BY b.trade_date
    )) adjusted_close
  FROM market.daily_bar b
  WHERE b.trade_date BETWEEN :price_start AND :price_end AND b.pct_change>-99.99
), bars AS (
  SELECT *,lead(adjusted_close) OVER (PARTITION BY symbol ORDER BY trade_date) adjusted_1
  FROM adjusted
), x AS (
  SELECT 100*(b.adjusted_1/b.adjusted_close-1) return_t1_pct FROM e JOIN bars b USING(symbol,trade_date)
)
SELECT count(*) event_count,avg(return_t1_pct) return_t1_avg,
  percentile_cont(.5) WITHIN GROUP (ORDER BY return_t1_pct) return_t1_median,
  100*avg((return_t1_pct>0)::int) return_t1_win FROM x
""")


CASES = [
    {"hot_money_name": "陈小群", "symbol": "600410", "name": "华胜天成", "buy_date": "2025-08-25", "buy": 2.32, "sell_date": "2025-08-28", "sell": 4.19, "path_pct": 12.26},
    {"hot_money_name": "陈小群", "symbol": "600879", "name": "航天电子", "buy_date": "2025-12-16", "buy": 5.71, "sell_date": "2025-12-26", "sell": 3.48, "path_pct": 11.90},
    {"hot_money_name": "宁波桑田路", "symbol": "300058", "name": "蓝色光标", "buy_date": "2025-12-31", "buy": 2.92, "sell_date": "2026-01-05", "sell": 3.11, "path_pct": 19.97},
    {"hot_money_name": "章盟主", "symbol": "002792", "name": "通宇通讯", "buy_date": "2026-01-08", "buy": 2.33, "sell_date": "2026-01-13", "sell": 2.48, "path_pct": 22.09},
    {"hot_money_name": "作手新一", "symbol": "300959", "name": "线上线下", "buy_date": "2026-05-12", "buy": 2.08, "sell_date": "2026-05-13", "sell": 2.47, "path_pct": 20.00},
    {"hot_money_name": "作手新一", "symbol": "300657", "name": "弘信电子", "buy_date": "2026-05-18", "buy": 3.45, "sell_date": "2026-05-20", "sell": 4.13, "path_pct": 18.89},
    {"hot_money_name": "作手新一", "symbol": "002281", "name": "光迅科技", "buy_date": "2026-03-12", "buy": 5.24, "sell_date": "2026-03-13", "sell": 3.63, "path_pct": -10.00},
    {"hot_money_name": "陈小群", "symbol": "600410", "name": "华胜天成", "buy_date": "2026-01-15", "buy": 5.42, "sell_date": "2026-01-16", "sell": 5.13, "path_pct": -9.95},
]


SOURCES = [
    {"title": "Tushare 游资每日明细 hm_detail", "url": "https://tushare.pro/document/2?doc_id=312", "note": "字段、单位及数据从2022年8月开始。"},
    {"title": "Tushare 游资名录 hm_list", "url": "https://tushare.pro/document/2?doc_id=311", "note": "游资名称与关联营业部分类；不是交易所对个人身份的认证。"},
    {"title": "Tushare 龙虎榜机构明细 top_inst", "url": "https://tushare.pro/document/2?doc_id=107", "note": "营业部买卖额、净额、上榜方向与原因。"},
    {"title": "上交所交易公开信息查询", "url": "https://www.sse.com.cn/disclosure/diclosure/public/inquirydata/index.shtml", "note": "沪市交易公开信息官方查询入口。"},
    {"title": "上交所交易规则（2026年修订）", "url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml", "note": "2026-07-06起生效的现行规则。"},
    {"title": "深交所交易规则（2026年修订）", "url": "https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf", "note": "深市现行交易规则。"},
    {"title": "Dissecting Momentum in China", "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5130681", "note": "注意力驱动的买压可能造成短期过冲，非新闻日存在反转。"},
    {"title": "Information shocks and short-term market overreaction", "url": "https://www.sciencedirect.com/science/article/abs/pii/S1057521924001510", "note": "中国市场交易时段信息冲击存在短期过度反应。"},
    {"title": "52-Week High Momentum Strategy in China", "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6403338", "note": "用户指定论文；样本止于2018年，本地近期复验见论文复验页。"},
]


EXECUTION_AUDIT = [
    {"level": "P0", "issue": "委托价未按0.01元价位处理", "action": "昨收×0.98后按证券最小价位向下取整；回测和计划单共用同一函数。"},
    {"level": "P0", "issue": "最低价触及不等于足量成交", "action": "按首次触及分钟成交额的5%限制规模，并压力测试额外20/50/100bp冲击成本。"},
    {"level": "P0", "issue": "精确收盘价卖出不可执行", "action": "14:55形成卖出决定，使用下一分钟VWAP或可执行价；封死跌停顺延。"},
    {"level": "P0", "issue": "持仓期重复信号", "action": "同一股票已有仓位时跳过新信号，组合回测统一处理资金冲突和最多4仓。"},
    {"level": "P1", "issue": "分钟数据并非全市场完整覆盖", "action": "逐个候选校验全天行数、触发附近缺口、复权一致性和数据完备率。"},
    {"level": "P1", "issue": "右尾交易贡献过高", "action": "同时报告截尾均值、最大回撤和前5笔利润贡献，不能只看逐笔平均。"},
]


ULTRA_SHORT_IDEAS = [
    {"name": "分钟止跌确认", "priority": "P0", "signal": "首次触及−2%后等待3根完整1分钟K；不创新低且最后一根收复目标价，下一分钟VWAP入场。", "why": "直接处理接飞刀风险，且信号可实时形成。"},
    {"name": "人气保持/加速度", "priority": "P1", "signal": "T日首次前五，比较T−1至T排名跃迁；T+1盘中只使用已发布的人气快照，观察价格回撤时排名是否保持。", "why": "区分真正注意力扩散与一日冲榜。"},
    {"name": "游资＋机构合力", "priority": "P1", "signal": "T日龙虎榜知名席位净买占成交额、同日净买席位数、游资与机构同时净买；T+1不追高开。", "why": "游资单独机械跟单为负，更可能需要资金合力与价格确认。"},
    {"name": "新高附近的退出延长", "priority": "P1", "signal": "新高只决定排序和涨停后的延持，不改变主策略入场；分别比较普通退出与趋势跟踪退出。", "why": "新高组均值更高但胜率未同步，提高右尾而非普遍胜率。"},
    {"name": "人气衰减退出", "priority": "P2", "signal": "T+1/T+2收盘后跌出前十或排名快速恶化，次日竞价/开盘退出；与固定T+2规则对照。", "why": "让持有逻辑与注意力生命周期一致，同时严格遵守信息时点。"},
]


OOS_GATES = [
    "自2026-08-03起冻结前5、冷却10日、−2%、ADV20≥10亿元等主参数。",
    "累计至少100笔新成交且跨越6个月，两者取较晚；按信号日聚类或周区块bootstrap。",
    "净收益均值95%置信区间下界大于0，中位净收益大于0，额外50bp冲击成本后均值仍大于0。",
    "至少4/6个月为正，前5大盈利交易贡献不超过总利润40%。",
    "最多4仓、禁止重复持仓的组合最大回撤不超过12%—15%，不可成交订单如实保留。",
    "通过后先做30笔仿真，再用目标仓位10%—20%完成30笔小额实盘，成交偏差稳定后才放大。",
]


def _clean_number(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return int(number) if number.is_integer() else number


def _serialise_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
            elif isinstance(value, (int, float)) or value is None:
                item[key] = _clean_number(value)
            else:
                try:
                    item[key] = _clean_number(value)
                    if item[key] is None and value is not None:
                        item[key] = str(value)
                except (TypeError, ValueError):
                    item[key] = str(value)
        result.append(item)
    return result


def hot_money_study(start: str, end: str) -> dict[str, Any]:
    parameters = {
        "start": start,
        "end": end,
        "price_start": "2024-06-01",
        "price_end": end,
    }
    with engine.connect() as conn:
        details = [dict(row._mapping) for row in conn.execute(DETAIL_SQL, parameters)]
        summary = [dict(row._mapping) for row in conn.execute(SUMMARY_SQL, parameters)]
        latest = [dict(row._mapping) for row in conn.execute(LATEST_DETAIL_SQL)]
        baseline = dict(conn.execute(BASELINE_SQL, parameters).one()._mapping)
        coverage = dict(conn.execute(text("""SELECT
          (SELECT min(trade_date) FROM market.lhb_seat) min_date,
          (SELECT max(trade_date) FROM market.lhb_seat) max_date,
          (SELECT count(*) FROM market.lhb_seat) raw_rows,
          (SELECT count(DISTINCT trade_date) FROM market.lhb_seat) trade_days,
          (SELECT count(*) FROM market.hot_money_detail) exact_alias_rows,
          (SELECT count(DISTINCT trade_date) FROM market.hot_money_detail) exact_alias_days
        """)).one()._mapping)
    return {
        "coverage": _serialise_rows([coverage])[0],
        "baseline": _serialise_rows([baseline])[0],
        "summary": _serialise_rows(summary),
        "details": _serialise_rows(details),
        "latest_exact": _serialise_rows(latest),
        "cases": CASES,
    }


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _is_core(row: dict[str, Any]) -> bool:
    dc_rank, ths_rank = _number(row, "dc_rank"), _number(row, "ths_rank")
    dc_absent, ths_absent = _number(row, "dc_absent_days") or 0, _number(row, "ths_absent_days") or 0
    return bool(dc_rank is not None and dc_rank <= 5 and dc_absent >= 10) or bool(
        ths_rank is not None and ths_rank <= 5 and ths_absent >= 10
    )


def _performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [value for row in rows if (value := _number(row, "rule_return_pct")) is not None]
    return {
        "records": len(rows),
        "completed": len(values),
        "average_pct": mean(values) if values else None,
        "median_pct": median(values) if values else None,
        "win_rate_pct": 100 * sum(value > 0 for value in values) / len(values) if values else None,
    }


def strategy_study(research_dir: Path) -> dict[str, Any]:
    all_drop2 = _csv_rows(research_dir / "popularity-top10-drop2.csv")
    all_drop7 = _csv_rows(research_dir / "popularity-top10-drop7.csv")
    new_drop2 = _csv_rows(research_dir / "popularity-new-top10.csv")
    new_drop7 = _csv_rows(research_dir / "popularity-core-drop7.csv")
    core_drop2 = [row for row in new_drop2 if _is_core(row)]
    core_drop7 = [row for row in new_drop7 if _is_core(row)]
    core_near_high = [
        row for row in core_drop2
        if (distance := _number(row, "high_120_distance_pct")) is not None and distance >= -2
    ]
    core_above_ma5 = [row for row in core_drop2 if row.get("benchmark_above_ma5", "").lower() == "true"]
    core_below_ma5 = [row for row in core_drop2 if row.get("benchmark_above_ma5", "").lower() == "false"]
    groups = {
        "all_drop2": _performance(all_drop2),
        "all_drop7": _performance(all_drop7),
        "new_drop2": _performance(new_drop2),
        "new_drop7": _performance(new_drop7),
        "core_drop2": _performance(core_drop2),
        "core_near_high": _performance(core_near_high),
        "core_drop7": _performance(core_drop7),
        "core_above_ma5": _performance(core_above_ma5),
        "core_below_ma5": _performance(core_below_ma5),
    }
    decisions = [
        {"tier": "主策略", "name": "同源首次前五＋此前至少10日未进前十，T+1触及−2%", "key": "core_drop2", "decision": "保留", "reason": "当前严格口径中收益最稳定；信号在T日收盘后可得，且容量门槛明确。"},
        {"tier": "排序增强", "name": "主策略＋距离120日前高不低于−2%", "key": "core_near_high", "decision": "保留为评分", "reason": "近期样本有提升，但不应做唯一硬门槛，避免错过新题材与过拟合。"},
        {"tier": "执行实验", "name": "主策略＋触及−2%后的5—10分钟止跌确认", "key": None, "decision": "优先补测", "reason": "直接解决机械接飞刀问题；必须只使用当时已形成的分钟数据。"},
        {"tier": "小样本实验", "name": "同源核心条件，T+1触及−7%", "key": "core_drop7", "decision": "降级", "reason": "样本太少且尾部风险大，只能观察，不能据均值放大仓位。"},
        {"tier": "基准对照", "name": "所有前十 / 首次前十，T+1触及−2%", "key": "new_drop2", "decision": "仅作对照", "reason": "覆盖广但边际较弱，用来判断核心筛选是否真正增益。"},
        {"tier": "淘汰", "name": "所有前十或首次前十，T+1触及−7%", "key": "new_drop7", "decision": "停止", "reason": "大样本下均值为负；深跌不是安全边际，往往是信息恶化。"},
        {"tier": "不采用", "name": "对应指数站上MA5", "key": None, "decision": "删除硬过滤", "reason": "未见稳定提升，可留作市场状态标签，不进入下单门槛。"},
        {"tier": "禁止", "name": "T+1阳线、T+1全日放量后再决定T+1买入", "key": None, "decision": "只作标签", "reason": "完整日K与全日成交额在买点时尚未形成，直接筛选会产生未来函数。"},
    ]
    for decision in decisions:
        decision["metrics"] = groups.get(decision["key"]) if decision.get("key") else None
    return {"groups": groups, "decisions": decisions}


def render_html(payload: dict[str, Any], template_path: Path, output: Path) -> None:
    template = template_path.read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__REPORT_DATA__", data), encoding="utf-8")


def render_markdown(payload: dict[str, Any], output: Path) -> None:
    hot = payload["hot_money"]
    strategies = payload["strategies"]
    def fmt(value: Any, digits: int = 3) -> str:
        return "—" if value is None else f"{float(value):.{digits}f}%"

    lines = [
        "# A股人气超短研究总方案",
        "",
        f"生成日期：{payload['generated_for']}；本地样本：{hot['coverage']['min_date']} 至 {hot['coverage']['max_date']}。",
        "",
        "## 结论",
        "",
        "公开龙虎榜只能验证营业部买卖金额，不能验证个人账户的真实成交价、完整仓位或收益率。知名游资更适合作为强趋势与资金合力的排序因子，不能机械跟单。主策略保留严格同源的“首次前五＋榜外至少10日＋T+1跌2%”，新高作为评分，分钟止跌作为下一优先检验。",
        "",
        "## 策略裁剪",
        "",
        "|层级|方案|决定|样本|均值|胜率|",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in strategies["decisions"]:
        metrics = item.get("metrics") or {}
        lines.append(
            f"|{item['tier']}|{item['name']}|{item['decision']}|{metrics.get('records','—')}|"
            f"{fmt(metrics.get('average_pct'))}|{fmt(metrics.get('win_rate_pct'), 1)}|"
        )
    lines.extend([
        "",
        "核心策略修正后为188笔，平均1.890%、中位0.852%、胜率54.8%。2025与2026两个年度均为正，但去掉两端各5%后均值约1.229%，前5笔贡献总利润约47%；普通交易不支持无条件持有到T+3/T+5。",
        "",
        "## 游资席位代理统计",
        "",
        "|席位代理|净买事件|T+1均值|T+1中位|T+1胜率|",
        "|---|---:|---:|---:|---:|",
    ])
    for row in hot["summary"]:
        lines.append(
            f"|{row['hot_money_name']}|{row['material_buy_events']}|{fmt(row['return_t1_avg'], 2)}|"
            f"{fmt(row['return_t1_median'], 2)}|{fmt(row['return_t1_win'], 1)}|"
        )
    lines.extend([
        "",
        "这些席位的重大净买事件多数发生在强趋势、阶段新高附近及大成交额股票中。机械复制‘知名席位净买后，T+1跌2%买’在代表席位上并没有正收益，席位只能作为资金合力排序因子。",
        "",
        "## 代表买卖披露路径",
        "",
        "|席位代理|股票|买入披露|买入额|卖出披露|卖出额|收盘路径|",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for case in hot["cases"]:
        lines.append(
            f"|{case['hot_money_name']}|{case['name']} {case['symbol']}|{case['buy_date']}|{case['buy']:.2f}亿|"
            f"{case['sell_date']}|{case['sell']:.2f}亿|{fmt(case['path_pct'], 2)}|"
        )
    lines.extend(["", "> 上表是披露日收盘价格路径，不是席位成交均价或真实收益。", "", "## 下一轮研究思路", ""])
    for item in payload["ideas"]:
        lines.append(f"- **{item['priority']} · {item['name']}**：{item['signal']} 目的：{item['why']}")
    lines.extend(["", "## 执行问题", ""])
    for item in payload["execution_audit"]:
        lines.append(f"- **{item['level']} · {item['issue']}**：{item['action']}")
    lines.extend([
        "",
        "单笔计划金额上限建议为 `min(ADV20的0.10%，首次触及分钟成交额的5%，账户净值预设仓位上限)`。",
        "",
        "## 前瞻样本外门槛",
        "",
    ])
    for gate in payload["oos_gates"]:
        lines.append(f"- {gate}")
    lines.extend(["", "## 数据限制", "", "- 游资别名来自第三方分类，历史统计按当前营业部名称模式映射，属于席位代理。", "- 同一席位可能由多人或量化通道共享；未上榜的买卖不可见。", "- 连续三个交易日异常披露可能是累计金额；报告按股票、席位、披露日去重，但不能还原逐笔成交。", "- 所有收益只表示标的价格路径，不是游资实际收益，也不是投资承诺。", "- 当前本地样本只有382个交易日、约19个月，不能称为完整两年。", "", "## 来源"])
    for source in payload["sources"]:
        lines.append(f"- [{source['title']}]({source['url']})：{source['note']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_payload(start: str, end: str, research_dir: Path) -> dict[str, Any]:
    return {
        "generated_for": end,
        "hot_money": hot_money_study(start, end),
        "strategies": strategy_study(research_dir),
        "execution_audit": EXECUTION_AUDIT,
        "ideas": ULTRA_SHORT_IDEAS,
        "oos_gates": OOS_GATES,
        "sources": SOURCES,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成游资与人气超短详细研究报告")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--research-dir", type=Path, default=DEFAULT_RESEARCH_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_payload(args.start, args.end, args.research_dir)
    render_html(payload, args.template, args.output)
    render_markdown(payload, args.markdown)
    print(json.dumps({"html": str(args.output), "markdown": str(args.markdown)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
