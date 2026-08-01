#!/usr/bin/env python3
"""Build the public architecture and project handbook."""

from __future__ import annotations

import argparse
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]


def render(source: Path) -> str:
    body = markdown.markdown(source.read_text(encoding="utf-8"), extensions=["fenced_code", "tables", "toc"])
    sections = [
        ("overview", "项目概览"), ("product-design", "产品设计"), ("concepts", "概念说明"),
        ("architecture", "系统架构"), ("data-pipeline", "数据管线"), ("api-and-ui", "API 与页面"),
        ("operations", "部署运维"), ("progress", "项目进度"), ("roadmap", "路线图"),
        ("acceptance", "验收标准"),
    ]
    links = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in sections)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A 股量化研究平台 · 项目手册</title><style>
body{{margin:0;background:#080c11;color:#c9d1d9;font:15px/1.75 system-ui,sans-serif}}
.layout{{max-width:1320px;margin:auto;display:grid;grid-template-columns:220px minmax(0,980px);gap:42px;padding:32px 24px 80px}}
aside{{position:sticky;top:82px;align-self:start;display:flex;flex-direction:column;border-left:1px solid #27313b;padding-left:16px}}
aside a{{padding:5px 8px;text-decoration:none;color:#8493a2;font-size:13px}}aside a:hover{{color:#45d4a2;background:#101a20}}
main{{min-width:0}}h1,h2{{color:#f0f6fc}}h2{{margin-top:42px;border-bottom:1px solid #30363d;padding-bottom:8px}}a{{color:#58a6ff}}
pre,code{{background:#161b22;border-radius:6px}}pre{{padding:16px;overflow:auto}}code{{padding:2px 5px}}
nav{{position:sticky;top:0;z-index:2;background:#0d141bdd;border-bottom:1px solid #27313b;padding:14px 24px;backdrop-filter:blur(10px)}}
nav a{{text-decoration:none;font-weight:700;color:#45d4a2}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;border-bottom:1px solid #30363d;text-align:left}}
blockquote{{margin:20px 0;padding:12px 18px;border-left:3px solid #45d4a2;background:#0d151b;color:#aebbc6}}
@media(max-width:800px){{.layout{{display:block;padding:24px 16px 70px}}aside{{position:static;flex-direction:row;overflow:auto;border:0;border-bottom:1px solid #27313b;padding:0 0 12px;margin-bottom:24px}}aside a{{white-space:nowrap}}}}
</style></head><body><nav><a href="/">← 返回平台</a>　A 股量化研究平台 · 项目手册</nav><div class="layout"><aside>{links}</aside><main>{body}</main></div></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "reports/latest/docs.html")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(ROOT / "docs/REBUILD_PLAN.md"), encoding="utf-8")


if __name__ == "__main__":
    main()
