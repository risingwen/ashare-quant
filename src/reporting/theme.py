"""Shared HTML theme for static report pages."""

from __future__ import annotations


PAGES = [
    ("index.html", "首页"),
    ("report.html", "综合报告"),
    ("screener.html", "选股信号"),
    ("lianban.html", "连板晋级"),
    ("hot_rank_iframe.html", "人气热榜"),
    ("longhu.html", "龙虎榜"),
    ("etf.html", "ETF雷达"),
    ("emotion.html", "市场温度"),
    ("monitor.html", "运行监控"),
    ("docs.html", "文档"),
]


def navbar(active: str, latest_date: str) -> str:
    links = "\n".join(
        f'    <a href="{href}"{" class=\"active\"" if href == active else ""}>{label}</a>'
        for href, label in PAGES
    )
    return f"""<nav class="navbar">
  <a class="navbar-brand" href="index.html">📊 A股量化平台</a>
  <div class="navbar-links">
{links}
  </div>
  <div class="navbar-date">{latest_date}</div>
</nav>"""


BASE_STYLE = """* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #0d1117; color: #e6edf3; min-height: 100vh; font-size: 14px; line-height: 1.7;
}
.navbar {
  background: #161b22; border-bottom: 1px solid #30363d;
  padding: 0 32px; display: flex; align-items: center;
  min-height: 60px; gap: 24px; position: sticky; top: 0; z-index: 100; flex-wrap: wrap;
}
.navbar-brand { font-size: 16px; font-weight: 700; color: #58a6ff; text-decoration: none; white-space: nowrap; }
.navbar-links { display: flex; gap: 2px; flex-wrap: wrap; }
.navbar-links a {
  color: #8b949e; text-decoration: none; padding: 5px 10px;
  border-radius: 6px; font-size: 13px; transition: all .15s;
}
.navbar-links a:hover { color: #e6edf3; background: #21262d; }
.navbar-links a.active { color: #e6edf3; background: #21262d; }
.navbar-date { margin-left: auto; font-size: 12px; color: #484f58; }
.page { max-width: 1500px; margin: 0 auto; padding: 32px 24px 80px; }
h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
.subtitle { color: #8b949e; font-size: 13px; margin-bottom: 28px; }
.section { margin-bottom: 40px; }
.section-title {
  font-size: 15px; font-weight: 600; color: #8b949e;
  padding-left: 12px; border-left: 3px solid #58a6ff; margin-bottom: 16px;
}
table {
  width: 100%; border-collapse: collapse; font-size: 13px;
  background: #161b22; border: 1px solid #30363d; border-radius: 12px; overflow: hidden;
}
thead th {
  text-align: left; padding: 9px 10px; font-size: 12px;
  color: #8b949e; border-bottom: 1px solid #30363d; white-space: nowrap;
  background: #21262d; font-weight: 600;
}
tbody td { padding: 8px 10px; border-bottom: 1px solid #30363d; color: #c9d1d9; }
tbody tr:hover td { background: #1c2128; color: #e6edf3; }
.up   { color: #e84c3d; }
.down { color: #07a071; }
.flat { color: #8b949e; }
.badge {
  display: inline-block; padding: 1px 7px; border-radius: 20px;
  font-size: 11px; font-weight: 600;
}
.badge-streak-1 { background:#1c2333; color:#8b949e; border:1px solid #30363d; }
.badge-streak-2 { background:#2d2208; color:#ffa657; border:1px solid #9e6a03; }
.badge-streak-3 { background:#1a1f3a; color:#79c0ff; border:1px solid #1f6feb; }
.badge-streak-4 { background:#2d0f0f; color:#ff7b72; border:1px solid #6e1a1a; }
.badge-streak-5 { background:#3d1f00; color:#ffac5c; border:1px solid #9a4f00; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px,1fr)); gap: 12px; margin-bottom: 24px; }
.card { background:#161b22; border:1px solid #30363d; border-radius:14px; padding:16px; text-align:center; box-shadow:0 8px 24px #0003; }
.card .val { font-size: 26px; font-weight: 700; color: #e6edf3; }
.card .lbl { font-size: 12px; color: #8b949e; margin-top: 4px; }
.tab-bar { display:flex; gap:4px; margin-bottom:16px; }
.tab-btn {
  padding: 5px 14px; border-radius: 6px; border: 1px solid #30363d;
  background: transparent; color: #8b949e; font-size: 13px; cursor: pointer;
}
.tab-btn.active { background: #21262d; color: #e6edf3; border-color: #58a6ff44; }
.filter-row { display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; align-items:center; }
.filter-row select, .filter-row input {
  background: #161b22; border: 1px solid #30363d; color: #e6edf3;
  padding: 5px 10px; border-radius: 6px; font-size: 13px; min-width: 120px;
}
.no-data { color: #484f58; padding: 32px; text-align: center; }
@media (max-width: 760px) {
  .navbar { padding: 10px 16px; align-items: flex-start; }
  .navbar-date { margin-left: 0; width: 100%; }
  .page { padding: 24px 14px 56px; }
  thead th, tbody td { padding: 8px 9px; font-size: 12px; }
}
"""
