#!/usr/bin/env python3
"""Build multi-source hot-rank CSV/HTML pages from latest experiment output."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT_ROOT = PROJECT_ROOT / "data" / "experiments" / "hot_rank_multi_source"
REPORTS_DIR = PROJECT_ROOT / "reports"
CSV_LAST30_PATH = REPORTS_DIR / "hot_rank_wencai_last30_normalized.csv"
CSV_SNAPSHOT_PATH = REPORTS_DIR / "hot_rank_multi_source_snapshot_latest.csv"
HTML_PATH = REPORTS_DIR / "hot_rank_multi_source_explorer.html"
SUMMARY_JSON_PATH = REPORTS_DIR / "hot_rank_multi_source_summary.json"
TOPN = 100


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>多源热度看板（最近30天）</title>
  <style>
    :root { --bg:#f3f7f9; --card:#fff; --line:#d6e0e6; --text:#183044; --muted:#5f7587; --accent:#0b7285; }
    body { margin:0; font-family:"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif; background:linear-gradient(135deg,#eef7fb 0,#f3f7f9 45%,#f9fbfc 100%); color:var(--text); }
    .wrap { max-width:1240px; margin:20px auto; padding:0 12px 20px; }
    h1 { margin:0 0 8px 0; font-size:28px; }
    .meta { color:var(--muted); font-size:13px; margin-bottom:12px; }
    .panel { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; margin-bottom:12px; }
    .controls { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }
    label { display:block; font-size:12px; color:var(--muted); margin-bottom:4px; }
    input, select, button { width:100%; box-sizing:border-box; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:#fff; }
    button { cursor:pointer; background:#edf9ff; font-weight:600; }
    .grid { display:grid; grid-template-columns: 1.2fr 1fr; gap:12px; }
    .tbl { border:1px solid var(--line); border-radius:10px; max-height:68vh; overflow:auto; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th,td { border-bottom:1px solid var(--line); padding:8px; text-align:left; white-space:nowrap; }
    th { background:#ecf6fb; position:sticky; top:0; z-index:1; }
    tr:hover { background:#f8fcff; }
    .rank { color:var(--accent); font-weight:700; }
    .hint { color:var(--muted); font-size:12px; margin-top:8px; }
    @media (max-width:900px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>多源热度看板（最近30天）</h1>
    <div class="meta" id="summary"></div>

    <div class="panel controls">
      <div><label>日期</label><select id="dateSelect"></select></div>
      <div><label>来源</label><select id="sourceSelect"><option value="">全部</option></select></div>
      <div><label>代码/名称筛选</label><input id="keywordInput" placeholder="如 600519 / 贵州茅台" /></div>
      <div><label>查看个股历史</label><input id="codeInput" placeholder="如 000001" /></div>
      <div><label>操作</label><button id="queryCode">查询历史</button></div>
    </div>

    <div class="grid">
      <div class="panel">
        <h3 id="dayTitle">当日榜单</h3>
        <div class="tbl">
          <table>
            <thead><tr><th>来源</th><th>排名</th><th>代码</th><th>名称</th><th>热度值</th></tr></thead>
            <tbody id="dayBody"></tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <h3 id="codeTitle">个股历史</h3>
        <div class="tbl">
          <table>
            <thead><tr><th>日期</th><th>来源</th><th>排名</th><th>名称</th><th>热度值</th></tr></thead>
            <tbody id="codeBody"></tbody>
          </table>
        </div>
        <div class="hint">点击左表代码可自动带入查询。</div>
      </div>
    </div>
  </div>

  <script id="data-json" type="application/json">__DATA_JSON__</script>
  <script>
    const rows = JSON.parse(document.getElementById('data-json').textContent);
    const dateSelect = document.getElementById('dateSelect');
    const sourceSelect = document.getElementById('sourceSelect');
    const keywordInput = document.getElementById('keywordInput');
    const codeInput = document.getElementById('codeInput');
    const dayBody = document.getElementById('dayBody');
    const codeBody = document.getElementById('codeBody');

    const dates = [...new Set(rows.map(r => r.date))].sort();
    const sources = [...new Set(rows.map(r => r.source))].sort();
    for (const d of dates) {
      const op = document.createElement('option'); op.value = d; op.textContent = d; dateSelect.appendChild(op);
    }
    for (const s of sources) {
      const op = document.createElement('option'); op.value = s; op.textContent = s; sourceSelect.appendChild(op);
    }
    dateSelect.value = dates[dates.length - 1] || '';
    document.getElementById('summary').textContent = `共 ${rows.length.toLocaleString()} 条记录，${dates.length} 个日期，${sources.length} 个来源。`;

    function normalizeCode(raw) {
      const s = (raw || '').trim();
      if (/^\\d{1,6}$/.test(s)) return s.padStart(6, '0');
      return s;
    }

    function renderDay() {
      const d = dateSelect.value;
      const src = sourceSelect.value;
      const kw = keywordInput.value.trim();
      let list = rows.filter(r => r.date === d);
      if (src) list = list.filter(r => r.source === src);
      if (kw) list = list.filter(r => (r.code || '').includes(kw) || (r.name || '').includes(kw));
      list.sort((a, b) => (a.source === b.source) ? (a.rank - b.rank) : a.source.localeCompare(b.source));
      document.getElementById('dayTitle').textContent = `当日榜单：${d}（${list.length} 条）`;
      dayBody.innerHTML = list.map(r =>
        `<tr><td>${r.source}</td><td class="rank">${r.rank}</td><td><a href="#" data-code="${r.code}">${r.code}</a></td><td>${r.name || ''}</td><td>${r.heat ?? ''}</td></tr>`
      ).join('');
      dayBody.querySelectorAll('a[data-code]').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          codeInput.value = a.dataset.code;
          renderCode();
        });
      });
    }

    function renderCode() {
      const code = normalizeCode(codeInput.value);
      codeInput.value = code;
      if (!code) {
        codeBody.innerHTML = '';
        document.getElementById('codeTitle').textContent = '个股历史';
        return;
      }
      const list = rows.filter(r => r.code === code)
        .sort((a, b) => (a.date === b.date) ? a.rank - b.rank : (a.date < b.date ? 1 : -1));
      document.getElementById('codeTitle').textContent = `个股历史：${code}（${list.length} 条）`;
      codeBody.innerHTML = list.map(r =>
        `<tr><td>${r.date}</td><td>${r.source}</td><td class="rank">${r.rank}</td><td>${r.name || ''}</td><td>${r.heat ?? ''}</td></tr>`
      ).join('');
    }

    dateSelect.addEventListener('change', renderDay);
    sourceSelect.addEventListener('change', renderDay);
    keywordInput.addEventListener('input', renderDay);
    document.getElementById('queryCode').addEventListener('click', renderCode);
    codeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') renderCode(); });
    renderDay();
  </script>
</body>
</html>
"""


def _latest_run_dir() -> Path | None:
    if not EXPERIMENT_ROOT.exists():
        return None
    candidates = [p for p in EXPERIMENT_ROOT.iterdir() if p.is_dir() and (p / "attempt_summary.csv").exists()]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _normalize_code(raw: object) -> str:
    s = str(raw).strip()
    if "." in s:
        s = s.split(".")[0]
    if s.isdigit():
        return s.zfill(6)
    return s


def _extract_rank_from_row(row: pd.Series) -> tuple[float | None, float | None]:
    qd = str(row.get("query_date", "")).replace("-", "")
    rank_col = f"个股热度排名[{qd}]"
    heat_col = f"个股热度[{qd}]"
    rank = row.get(rank_col)
    heat = row.get(heat_col)
    return rank, heat


def _build_last30_df(run_dir: Path) -> pd.DataFrame:
    f = run_dir / "wencai_hot_rank_last30d_pywencai.csv"
    if not f.exists():
        return pd.DataFrame(columns=["date", "source", "code", "name", "rank", "heat"])
    df = pd.read_csv(f)
    if df.empty:
        return pd.DataFrame(columns=["date", "source", "code", "name", "rank", "heat"])

    rows: list[dict] = []
    for _, row in df.iterrows():
        rank, heat = _extract_rank_from_row(row)
        if pd.isna(rank):
            continue
        rank_num = int(rank)
        if rank_num < 1 or rank_num > TOPN:
            continue
        rows.append(
            {
                "date": str(row.get("query_date", "")),
                "source": "pywencai_ths",
                "code": _normalize_code(row.get("股票代码", row.get("code", ""))),
                "name": str(row.get("股票简称", "")),
                "rank": rank_num,
                "heat": float(heat) if pd.notna(heat) else None,
            }
        )
    return pd.DataFrame(rows)


def _build_snapshot_df(run_dir: Path, date_str: str) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []

    kp = run_dir / "kaipanla_hot_rank_snapshot_pywencai.csv"
    if kp.exists():
        df = pd.read_csv(kp)
        if not df.empty:
            rank_col = next((c for c in df.columns if str(c).startswith("个股热度排名[")), None)
            heat_col = next((c for c in df.columns if str(c).startswith("个股热度[")), None)
            kp_date = date_str
            if rank_col:
                m = re.search(r"\[(\d{8})\]", str(rank_col))
                if m:
                    kp_date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
            tmp = pd.DataFrame(
                {
                    "date": kp_date,
                    "source": "pywencai_kaipanla",
                    "code": df.get("股票代码", "").map(_normalize_code),
                    "name": df.get("股票简称", ""),
                    "rank": pd.to_numeric(df.get(rank_col) if rank_col else None, errors="coerce"),
                    "heat": pd.to_numeric(df.get(heat_col) if heat_col else None, errors="coerce"),
                }
            )
            chunks.append(tmp)

    ths = run_dir / "ths_hot_rank_100_snapshot_adata.csv"
    if ths.exists():
        df = pd.read_csv(ths)
        if not df.empty:
            if "fetch_time" in df.columns and pd.notna(df["fetch_time"].iloc[0]):
                date_str = str(df["fetch_time"].iloc[0])[:10]
            name_col = "short_name" if "short_name" in df.columns else "stock_name"
            heat_col = "hot_value" if "hot_value" in df.columns else ("hot" if "hot" in df.columns else None)
            tmp = pd.DataFrame(
                {
                    "date": date_str,
                    "source": "adata_ths",
                    "code": df.get("stock_code", "").map(_normalize_code),
                    "name": df.get(name_col, ""),
                    "rank": pd.to_numeric(df.get("rank"), errors="coerce"),
                    "heat": pd.to_numeric(df.get(heat_col) if heat_col else None, errors="coerce"),
                }
            )
            chunks.append(tmp)

    if not chunks:
        return pd.DataFrame(columns=["date", "source", "code", "name", "rank", "heat"])
    out = pd.concat(chunks, ignore_index=True)
    out = out[out["rank"].between(1, TOPN, inclusive="both")]
    out["rank"] = out["rank"].astype(int)
    return out


def main() -> int:
    run_dir = _latest_run_dir()
    if run_dir is None:
        print(f"skip: no valid run under {EXPERIMENT_ROOT}")
        return 0

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = run_time[:10]

    last30_df = _build_last30_df(run_dir)
    snap_df = _build_snapshot_df(run_dir, date_str)

    last30_df.to_csv(CSV_LAST30_PATH, index=False, encoding="utf-8")
    snap_df.to_csv(CSV_SNAPSHOT_PATH, index=False, encoding="utf-8")

    merged = pd.concat([last30_df, snap_df], ignore_index=True)
    if merged.empty:
        print("skip: no normalized rows to build html")
        return 0

    merged = merged.dropna(subset=["date", "source", "code", "rank"]).copy()
    merged["code"] = merged["code"].map(_normalize_code)
    merged["rank"] = pd.to_numeric(merged["rank"], errors="coerce")
    merged = merged[merged["rank"].between(1, TOPN, inclusive="both")]
    merged["rank"] = merged["rank"].astype(int)
    merged = merged.sort_values(["date", "source", "rank", "code"], ascending=[False, True, True, True])
    rows = merged.to_dict(orient="records")

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(rows, ensure_ascii=False))
    HTML_PATH.write_text(html, encoding="utf-8")

    SUMMARY_JSON_PATH.write_text(
        json.dumps(
            {
                "run_time": run_time,
                "source_run_dir": str(run_dir.relative_to(PROJECT_ROOT)),
                "rows_total": len(rows),
                "rows_last30": int(len(last30_df)),
                "rows_snapshot": int(len(snap_df)),
                "topn": TOPN,
                "csv_last30": str(CSV_LAST30_PATH.relative_to(PROJECT_ROOT)),
                "csv_snapshot": str(CSV_SNAPSHOT_PATH.relative_to(PROJECT_ROOT)),
                "html": str(HTML_PATH.relative_to(PROJECT_ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"source_run_dir={run_dir}")
    print(f"rows_total={len(rows)}")
    print(f"html={HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
