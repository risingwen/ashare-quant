#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成交易记录HTML页面

功能：
1. 从CSV读取交易记录
2. 按卖出日期排序计算资金余额
3. 生成可排序的HTML表格（修复日期排序问题）
4. 添加策略说明
"""

import argparse
from pathlib import Path
import pandas as pd

def generate_html(csv_path: str, output_path: str, init_cash: float = 1_000_000):
    """生成交易记录HTML页面"""
    
    # 读取CSV
    df = pd.read_csv(csv_path)
    
    # 确保日期列是datetime类型
    df['signal_date'] = pd.to_datetime(df['signal_date'])
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    df['exit_date'] = pd.to_datetime(df['exit_date'])
    
    # 按卖出日期排序，计算资金余额
    df_sorted = df.sort_values('exit_date').reset_index(drop=True)
    balance = init_cash
    balances = []
    for _, row in df_sorted.iterrows():
        # 卖出后的余额 = 之前的余额 - 买入成本 + 卖出收入
        balance = balance - row['buy_cost'] + row['sell_proceed']
        balances.append(balance)
    df_sorted['balance'] = balances
    
    # 按信号日期降序排列显示
    df_display = df_sorted.sort_values('signal_date', ascending=False).reset_index(drop=True)
    
    # 统计
    total = len(df_display)
    wins = len(df_display[df_display['net_pnl'] > 0])
    losses = len(df_display[df_display['net_pnl'] < 0])
    win_rate = wins / total * 100 if total > 0 else 0
    total_pnl = df_display['net_pnl'].sum()
    avg_pnl_pct = df_display['net_pnl_pct'].mean() * 100
    final_balance = df_display.iloc[0]['balance'] if len(df_display) > 0 else init_cash
    
    # 生成HTML
    html_parts = []
    
    # Head
    html_parts.append('''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>交易记录 - 人气首次入榜前10策略</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f5f5f5; }
h1 { color: #333; }
.strategy-box { background: #e0f2fe; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #0284c7; }
.strategy-box h2 { margin: 0 0 10px 0; color: #0369a1; font-size: 16px; }
.strategy-box ul { margin: 0; padding-left: 20px; }
.strategy-box li { margin: 5px 0; color: #334155; }
.summary { background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.summary span { margin-right: 20px; }
.positive { color: #16a34a; font-weight: bold; }
.negative { color: #dc2626; font-weight: bold; }
table { border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #e5e7eb; font-size: 13px; }
th { background: #f8fafc; cursor: pointer; position: sticky; top: 0; user-select: none; white-space: nowrap; }
th:hover { background: #e2e8f0; }
th.sort-asc::after { content: " ▲"; color: #3b82f6; }
th.sort-desc::after { content: " ▼"; color: #3b82f6; }
tr:hover { background: #f1f5f9; }
.pnl-pos { color: #16a34a; }
.pnl-neg { color: #dc2626; }
.balance { color: #7c3aed; font-weight: 500; }
</style>
</head>
<body>
<h1>交易记录 - 人气首次入榜前10策略</h1>

<div class="strategy-box">
<h2>策略说明</h2>
<ul>
<li><b>信号条件</b>：个股首次进入人气前10（T日产生信号）</li>
<li><b>买入条件</b>（T+1日满足其一）：
  <ul>
    <li>低开买入：开盘价 < T日收盘价，按开盘价买入</li>
    <li>涨2%买入：盘中触及 T日收盘价 × 1.02，按触发价买入</li>
  </ul>
</li>
<li><b>卖出条件</b>：持仓期间人气排名跌出前50（hot_rank > 50），当日收盘卖出</li>
<li><b>仓位管理</b>：初始资金100万，每笔交易使用1/3资金，最多同时持有3个仓位</li>
</ul>
</div>
''')
    
    # Summary
    pnl_class = "positive" if total_pnl >= 0 else "negative"
    avg_class = "positive" if avg_pnl_pct >= 0 else "negative"
    html_parts.append(f'''<div class="summary">
<span>总交易: <b>{total}</b></span>
<span>盈利: <b class="positive">{wins}</b></span>
<span>亏损: <b class="negative">{losses}</b></span>
<span>胜率: <b>{win_rate:.1f}%</b></span>
<span>总盈亏: <b class="{pnl_class}">{total_pnl:,.0f}</b></span>
<span>平均收益率: <b class="{avg_class}">{avg_pnl_pct:.2f}%</b></span>
<span>最终余额: <b class="balance">{final_balance:,.0f}</b></span>
</div>
''')
    
    # Table header
    html_parts.append('''<table id="tradesTable">
<thead><tr>
<th onclick="sortTable(this)">代码</th>
<th onclick="sortTable(this)">名称</th>
<th onclick="sortTable(this)">信号日</th>
<th onclick="sortTable(this)">买入日</th>
<th onclick="sortTable(this)">买入条件</th>
<th onclick="sortTable(this)">买入价</th>
<th onclick="sortTable(this)">买入股数</th>
<th onclick="sortTable(this)">买入成本</th>
<th onclick="sortTable(this)">卖出日</th>
<th onclick="sortTable(this)">卖出排名</th>
<th onclick="sortTable(this)">卖出价</th>
<th onclick="sortTable(this)">卖出收入</th>
<th onclick="sortTable(this)">持有天数</th>
<th onclick="sortTable(this)">净盈亏</th>
<th onclick="sortTable(this)">收益率%</th>
<th onclick="sortTable(this)">资金余额</th>
</tr></thead>
<tbody>
''')
    
    # Table rows
    for _, row in df_display.iterrows():
        code = str(row['code']).zfill(6) if len(str(row['code'])) < 6 else str(row['code'])
        name = row['name']
        signal_date = row['signal_date'].strftime('%Y-%m-%d')
        signal_ts = int(row['signal_date'].timestamp())
        entry_date = row['entry_date'].strftime('%Y-%m-%d')
        entry_ts = int(row['entry_date'].timestamp())
        exit_date = row['exit_date'].strftime('%Y-%m-%d')
        exit_ts = int(row['exit_date'].timestamp())
        
        condition = "低开买" if row['entry_condition'] == 'gap_down_open' else "涨2%买"
        buy_price = row['buy_price']
        buy_shares = int(row['buy_shares'])
        buy_cost = int(row['buy_cost'])
        exit_rank = int(row['exit_rank'])
        sell_price = row['sell_price']
        sell_proceed = int(row['sell_proceed'])
        hold_days = int(row['hold_days'])
        net_pnl = row['net_pnl']
        net_pnl_pct = row['net_pnl_pct'] * 100
        balance = row['balance']
        
        pnl_class = "pnl-pos" if net_pnl >= 0 else "pnl-neg"
        pnl_str = f"{net_pnl:,.0f}"
        pnl_pct_str = f"{net_pnl_pct:.2f}%"
        
        html_parts.append(f'''<tr>
<td>{code}</td>
<td>{name}</td>
<td data-sort="{signal_ts}">{signal_date}</td>
<td data-sort="{entry_ts}">{entry_date}</td>
<td>{condition}</td>
<td>{buy_price}</td>
<td>{buy_shares}</td>
<td>{buy_cost}</td>
<td data-sort="{exit_ts}">{exit_date}</td>
<td>{exit_rank}</td>
<td>{sell_price}</td>
<td>{sell_proceed}</td>
<td>{hold_days}</td>
<td class="{pnl_class}">{pnl_str}</td>
<td class="{pnl_class}">{pnl_pct_str}</td>
<td class="balance">{balance:,.0f}</td>
</tr>
''')
    
    # Close table and add script
    html_parts.append('''</tbody></table>
<script>
let sortCol = -1, sortAsc = true;
function sortTable(th) {
  const table = document.getElementById("tradesTable");
  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const idx = Array.from(th.parentNode.children).indexOf(th);
  
  if (sortCol === idx) { sortAsc = !sortAsc; } else { sortCol = idx; sortAsc = true; }
  
  document.querySelectorAll("th").forEach(t => t.classList.remove("sort-asc", "sort-desc"));
  th.classList.add(sortAsc ? "sort-asc" : "sort-desc");
  
  rows.sort((a, b) => {
    const cellA = a.children[idx];
    const cellB = b.children[idx];
    
    // 优先使用 data-sort 属性（用于日期排序）
    let va = cellA.getAttribute("data-sort") || cellA.textContent.replace(/[,%]/g, "");
    let vb = cellB.getAttribute("data-sort") || cellB.textContent.replace(/[,%]/g, "");
    
    let na = parseFloat(va), nb = parseFloat(vb);
    if (!isNaN(na) && !isNaN(nb)) { return sortAsc ? na - nb : nb - na; }
    return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
  });
  rows.forEach(r => tbody.appendChild(r));
}
</script>
</body>
</html>
''')
    
    # Write output
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', encoding='utf-8') as f:
        f.write(''.join(html_parts))
    
    print(f"Generated: {output}")
    print(f"Total trades: {total}, Wins: {wins}, Losses: {losses}, Win rate: {win_rate:.1f}%")
    print(f"Total PnL: {total_pnl:,.0f}, Avg PnL%: {avg_pnl_pct:.2f}%, Final balance: {final_balance:,.0f}")


def main():
    parser = argparse.ArgumentParser(description="Generate trades HTML report")
    parser.add_argument("--csv", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output HTML file path")
    parser.add_argument("--init-cash", type=float, default=1_000_000, help="Initial cash (default: 1000000)")
    args = parser.parse_args()
    
    generate_html(args.csv, args.output, args.init_cash)


if __name__ == "__main__":
    main()
