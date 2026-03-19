#!/usr/bin/env python3
"""Export historical hot-rank stocks and generate a readable explorer page."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET_GLOB = PROJECT_ROOT / "data" / "parquet" / "ashare_daily" / "**" / "*.parquet"
REPORTS_DIR = PROJECT_ROOT / "reports"
CSV_PATH = REPORTS_DIR / "hot_rank_top100_history.csv"
HTML_PATH = REPORTS_DIR / "hot_rank_top100_explorer.html"
RANK_LIMIT = 100
PARQUET_ROOT = PROJECT_ROOT / "data" / "parquet" / "ashare_daily"


HTML_TEMPLATE = """<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>热度个股历史榜单（前__RANK_LIMIT__）</title>
  <style>
    :root { --bg:#f4f8f5; --card:#ffffff; --line:#d7e3db; --text:#153126; --muted:#5e7468; --accent:#1b7a4d; }
    body { margin:0; font-family:"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif; background:radial-gradient(circle at 15% 10%,#e8f5ec 0,#f4f8f5 45%); color:var(--text); }
    .wrap { max-width:1200px; margin:20px auto; padding:0 12px 20px; }
    .head { display:flex; flex-wrap:wrap; gap:10px; align-items:end; margin-bottom:12px; }
    h1 { margin:0; font-size:26px; }
    .meta { color:var(--muted); font-size:13px; }
    .panel { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; margin-bottom:12px; }
    .grid { display:grid; grid-template-columns: 1.3fr 1fr; gap:12px; }
    .controls { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; }
    label { display:block; font-size:12px; color:var(--muted); margin-bottom:4px; }
    input, select, button { width:100%; box-sizing:border-box; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:#fff; }
    button { cursor:pointer; background:#f0f8f3; font-weight:600; }
    .btns { display:flex; gap:8px; }
    .btns button { width:auto; min-width:78px; }
    .tbl { border:1px solid var(--line); border-radius:10px; max-height:66vh; overflow:auto; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th,td { border-bottom:1px solid var(--line); padding:8px; text-align:left; }
    th { background:#eef7f1; position:sticky; top:0; z-index:1; }
    tr:hover { background:#f7fcf9; }
    .rank { color:var(--accent); font-weight:700; }
    .hint { font-size:12px; color:var(--muted); margin-top:8px; }
    @media (max-width:900px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"head\">
      <h1>热度个股历史榜单（前__RANK_LIMIT__）</h1>
      <div class=\"meta\" id=\"summary\"></div>
    </div>

    <div class=\"panel controls\">
      <div>
        <label>交易日</label>
        <select id=\"dateSelect\"></select>
      </div>
      <div>
        <label>名称/代码筛选（当日）</label>
        <input id=\"dayKeyword\" placeholder=\"如 600519 或 石油\" />
      </div>
      <div>
        <label>查看个股历史（代码）</label>
        <input id=\"codeInput\" placeholder=\"如 600519\" />
      </div>
      <div>
        <label>操作</label>
        <div class=\"btns\">
          <button id=\"prevDay\">上一日</button>
          <button id=\"nextDay\">下一日</button>
          <button id=\"queryCode\">查历史</button>
        </div>
      </div>
    </div>

    <div class=\"grid\">
      <div class=\"panel\">
        <h3 id=\"dayTitle\">当日榜单</h3>
        <div class=\"tbl\">
          <table>
            <thead><tr><th>排名</th><th>代码</th><th>名称</th></tr></thead>
            <tbody id=\"dayBody\"></tbody>
          </table>
        </div>
        <div class=\"hint\">点击代码会自动填入右侧历史查询。</div>
      </div>

      <div class=\"panel\">
        <h3 id=\"codeTitle\">个股历史排名</h3>
        <div class=\"tbl\">
          <table>
            <thead><tr><th>日期</th><th>排名</th><th>名称</th></tr></thead>
            <tbody id=\"codeBody\"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <script id=\"data-json\" type=\"application/json\">__DATA_JSON__</script>
  <script>
    const rows = JSON.parse(document.getElementById('data-json').textContent);
    const byDate = new Map();
    const byCode = new Map();

    for (const r of rows) {
      if (!byDate.has(r.date)) byDate.set(r.date, []);
      byDate.get(r.date).push(r);
      if (!byCode.has(r.code)) byCode.set(r.code, []);
      byCode.get(r.code).push(r);
    }

    const dates = [...byDate.keys()].sort();
    const dateSelect = document.getElementById('dateSelect');
    const dayKeyword = document.getElementById('dayKeyword');
    const dayBody = document.getElementById('dayBody');
    const codeBody = document.getElementById('codeBody');
    const codeInput = document.getElementById('codeInput');

    document.getElementById('summary').textContent = `共 ${rows.length.toLocaleString()} 条记录，${dates.length.toLocaleString()} 个交易日。`;

    for (const d of dates) {
      const op = document.createElement('option');
      op.value = d;
      op.textContent = d;
      dateSelect.appendChild(op);
    }

    dateSelect.value = dates[dates.length - 1] || '';

    function renderDay() {
      const d = dateSelect.value;
      const kw = dayKeyword.value.trim();
      const list = (byDate.get(d) || []).slice().sort((a,b)=>a.hot_rank-b.hot_rank);
      const filtered = kw ? list.filter(x => x.code.includes(kw) || (x.name || '').includes(kw)) : list;

      document.getElementById('dayTitle').textContent = `当日榜单：${d}（${filtered.length} 条）`;
      dayBody.innerHTML = filtered.map(x => `<tr><td class=\"rank\">${x.hot_rank}</td><td><a href=\"#\" data-code=\"${x.code}\">${x.code}</a></td><td>${x.name || ''}</td></tr>`).join('');

      dayBody.querySelectorAll('a[data-code]').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          codeInput.value = a.dataset.code;
          renderCode();
        });
      });
    }

    function renderCode() {
      const code = codeInput.value.trim();
      if (!code) {
        document.getElementById('codeTitle').textContent = '个股历史排名';
        codeBody.innerHTML = '';
        return;
      }
      const list = (byCode.get(code) || []).slice().sort((a,b)=>a.date < b.date ? 1 : -1);
      document.getElementById('codeTitle').textContent = `个股历史排名：${code}（${list.length} 条）`;
      codeBody.innerHTML = list.map(x => `<tr><td>${x.date}</td><td class=\"rank\">${x.hot_rank}</td><td>${x.name || ''}</td></tr>`).join('');
    }

    function shiftDay(step) {
      const i = dates.indexOf(dateSelect.value);
      if (i < 0) return;
      const ni = Math.min(Math.max(i + step, 0), dates.length - 1);
      dateSelect.value = dates[ni];
      renderDay();
    }

    dateSelect.addEventListener('change', renderDay);
    dayKeyword.addEventListener('input', renderDay);
    document.getElementById('queryCode').addEventListener('click', renderCode);
    codeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') renderCode(); });
    document.getElementById('prevDay').addEventListener('click', () => shiftDay(-1));
    document.getElementById('nextDay').addEventListener('click', () => shiftDay(1));

    renderDay();
  </script>
</body>
</html>
"""


def load_rows(rank_limit: int):
    con = duckdb.connect()
    sql = """
    WITH base AS (
      SELECT
        CAST(date AS DATE) AS date,
        code,
        name,
        CAST(hot_rank AS INTEGER) AS hot_rank,
        ROW_NUMBER() OVER (
          PARTITION BY CAST(date AS DATE), code
          ORDER BY CAST(hot_rank AS INTEGER) ASC
        ) AS rn
      FROM read_parquet(?)
      WHERE hot_rank IS NOT NULL
        AND CAST(hot_rank AS INTEGER) BETWEEN 1 AND ?
    )
    SELECT
      strftime(date, '%Y-%m-%d') AS date,
      code,
      name,
      hot_rank
    FROM base
    WHERE rn = 1
    ORDER BY date DESC, hot_rank ASC, code ASC
    """
    df = con.execute(sql, [str(PARQUET_GLOB), rank_limit]).fetchdf()
    trade_dates = con.execute(
        "SELECT COUNT(DISTINCT CAST(date AS DATE)) FROM read_parquet(?) WHERE hot_rank IS NOT NULL",
        [str(PARQUET_GLOB)],
    ).fetchone()[0]
    return df, trade_dates


def write_csv(df) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False, encoding="utf-8")


def write_html(rows: list[dict], rank_limit: int) -> None:
    html = HTML_TEMPLATE.replace("__RANK_LIMIT__", str(rank_limit)).replace(
        "__DATA_JSON__", json.dumps(rows, ensure_ascii=False)
    )
    HTML_PATH.write_text(html, encoding="utf-8")


def main() -> int:
    # GitHub Actions 中通常不会包含本地大体积 parquet 数据，缺失时直接跳过。
    if not PARQUET_ROOT.exists() or not any(PARQUET_ROOT.rglob("*.parquet")):
        print(f"skip: no parquet files found under {PARQUET_ROOT}")
        return 0

    df, trade_dates = load_rows(RANK_LIMIT)
    write_csv(df)
    rows = df.to_dict(orient="records")
    write_html(rows, RANK_LIMIT)

    print(f"rank_limit={RANK_LIMIT}")
    print(f"rows={len(df)}")
    print(f"trade_dates={trade_dates}")
    print(f"csv={CSV_PATH}")
    print(f"html={HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
