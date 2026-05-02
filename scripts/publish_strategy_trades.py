#!/usr/bin/env python3
"""Publish latest trade records for each strategy to reports/trades with filterable HTML."""

from __future__ import annotations

from pathlib import Path
import html
import shutil
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRADES_DIR = PROJECT_ROOT / "data" / "backtest" / "trades"
REPORTS_TRADES_DIR = PROJECT_ROOT / "reports" / "trades"

STRATEGIES = {
    "drop7": "hot_rank_drop7_smart_exit",
    "rise2": "hot_rank_rise2_smart_exit",
    "top20_newentry": "hot_rank_top20_newentry",
    "first_top10": "hot_rank_first_top10_rise2_or_gapdown",
}


def latest_file(prefix: str, suffix: str) -> Path | None:
    files = sorted(TRADES_DIR.glob(f"{prefix}*{suffix}"))
    return files[-1] if files else None


def render_html_from_csv(csv_path: Path, out_html: Path, title: str) -> None:
    # 统一按字符串读取，避免 code 前导 0 被 pandas 吞掉。
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    cols = list(df.columns)

    thead = "".join([f"<th>{html.escape(c)}</th>" for c in cols])

    rows = []
    def format_cell(col: str, val: str) -> str:
        c = col.lower()
        v = (val or "").strip()
        if v == "":
            return ""

        # 股票代码统一 6 位展示。
        if c == "code" and v.isdigit():
            return v.zfill(6)

        # 比例字段统一为 4 位小数，阅读更稳定。
        if "pct" in c:
            try:
                return f"{float(v):.4f}"
            except ValueError:
                return v

        # 分类型字段保留原样（整数或日期等）。
        plain_tokens = ("rank", "days", "shares", "date", "reason", "condition")
        if any(t in c for t in plain_tokens):
            return v

        # 其余可解析为数字的字段统一按两位小数展示（金额/价格等）。
        # 这样能覆盖 buy_exec/sell_exec/trigger_xxx/open/high/low/close 等字段。
        if c != "code":
            try:
                return f"{float(v):.2f}"
            except ValueError:
                return v

        return v

    for _, r in df.iterrows():
        cells = []
        for c in cols:
            s = format_cell(c, str(r[c]))
            cells.append(f"<td>{html.escape(s)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    html_text = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin:0; font-family:"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif; background:#f3f6f3; color:#1f2937; }}
    .wrap {{ max-width: 1400px; margin: 20px auto; padding: 0 12px 20px; }}
    h1 {{ margin: 0 0 10px; }}
    .meta {{ color:#4b5563; font-size:13px; margin-bottom:10px; }}
    .panel {{ background:#fff; border:1px solid #d7e0d7; border-radius:10px; padding:10px; margin-bottom:12px; }}
    input {{ width:320px; max-width:100%; padding:8px 10px; border:1px solid #cdd8cd; border-radius:8px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ border-bottom:1px solid #e5e7eb; padding:6px 8px; text-align:left; white-space:nowrap; }}
    th {{ background:#eef4ef; position:sticky; top:0; cursor:pointer; }}
    tr:hover {{ background:#f7faf8; }}
    .tbl {{ overflow:auto; max-height:72vh; border:1px solid #d7e0d7; border-radius:8px; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{html.escape(title)}</h1>
    <div class=\"meta\">记录条数：{len(df)}，列数：{len(cols)}，来源：{html.escape(csv_path.name)}</div>
    <div class=\"panel\">
      <input id=\"q\" placeholder=\"输入代码/日期/字段内容进行筛选\" />
    </div>
    <div class=\"tbl\">
      <table id=\"tbl\">
        <thead><tr>{thead}</tr></thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>
  </div>
<script>
const q = document.getElementById('q');
const tbl = document.getElementById('tbl');
const tbody = tbl.querySelector('tbody');
const allRows = Array.from(tbody.querySelectorAll('tr'));

q.addEventListener('input', () => {{
  const kw = q.value.trim().toLowerCase();
  allRows.forEach(r => {{
    const ok = !kw || r.textContent.toLowerCase().includes(kw);
    r.style.display = ok ? '' : 'none';
  }});
}});

let sortCol = -1;
let sortAsc = true;
Array.from(tbl.querySelectorAll('th')).forEach((th, idx) => {{
  th.addEventListener('click', () => {{
    if (sortCol === idx) sortAsc = !sortAsc;
    else {{ sortCol = idx; sortAsc = true; }}
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a,b) => {{
      const va = (a.children[idx]?.textContent || '').trim();
      const vb = (b.children[idx]?.textContent || '').trim();
      const na = Number(va.replace(/,/g,''));
      const nb = Number(vb.replace(/,/g,''));
      if (!Number.isNaN(na) && !Number.isNaN(nb) && va !== '' && vb !== '') return sortAsc ? na-nb : nb-na;
      return sortAsc ? va.localeCompare(vb, 'zh') : vb.localeCompare(va, 'zh');
    }});
    rows.forEach(r => tbody.appendChild(r));
  }});
}});
</script>
</body>
</html>
"""
    out_html.write_text(html_text, encoding="utf-8")


def publish() -> None:
    REPORTS_TRADES_DIR.mkdir(parents=True, exist_ok=True)

    for key, prefix in STRATEGIES.items():
        csv_src = latest_file(prefix, "_trades.csv")
        parquet_src = latest_file(prefix, "_trades.parquet")

        csv_dst = REPORTS_TRADES_DIR / f"{key}_trades_latest.csv"
        html_dst = REPORTS_TRADES_DIR / f"{key}_trades_latest.html"

        if csv_src is not None:
            shutil.copy2(csv_src, csv_dst)
        elif parquet_src is not None:
            df = pd.read_parquet(parquet_src)
            df.to_csv(csv_dst, index=False, encoding="utf-8-sig")
        else:
            print(f"skip {key}: no trades file found")
            continue

        render_html_from_csv(csv_dst, html_dst, f"{key} 策略买卖记录")
        print(f"published {key}: {csv_dst.name}, {html_dst.name}")


if __name__ == "__main__":
    publish()
