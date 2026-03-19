#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

python3 scripts/export_hot_rank_top100_history.py
python3 scripts/publish_latest_experiment_to_reports.py
python3 scripts/publish_strategy_trades.py

if ! python3 -c "import markdown" >/dev/null 2>&1; then
  echo "installing missing dependency: markdown"
  python3 -m pip install markdown
fi

rm -rf public
mkdir -p public/reports public/strategies public/trades public/generated

if [ -f reports/latest.md ]; then
  cp reports/latest.md public/latest.md
else
  printf '%s\n' '# Daily Quant Notes' '' '`reports/latest.md` is not found yet.' > public/latest.md
fi

cp README.md public/

if [ -f docs/STRATEGY_REQUIREMENTS.md ]; then
  cp docs/STRATEGY_REQUIREMENTS.md public/strategies/
fi

cp config/strategies/*.yaml public/strategies/ 2>/dev/null || true
cp reports/strategies/*.md public/strategies/ 2>/dev/null || true
cp reports/*.md public/reports/ 2>/dev/null || true
cp reports/*.png public/reports/ 2>/dev/null || true
cp reports/generated/*.md public/generated/ 2>/dev/null || true
cp reports/hot_rank_top100_history.csv public/ 2>/dev/null || true
cp reports/hot_rank_top100_explorer.html public/ 2>/dev/null || true

cp reports/trades/*.csv public/trades/ 2>/dev/null || true
cp reports/trades/*.md public/trades/ 2>/dev/null || true
cp reports/trades/*.html public/trades/ 2>/dev/null || true
cp data/backtest/trades/*.csv public/trades/ 2>/dev/null || true

if [ ! -f public/trades/README.md ]; then
  printf '%s\n' '# Buy/Sell Records' '' 'Put trade CSV files under `reports/trades/` to publish them.' > public/trades/README.md
fi

printf '%s\n' '# 策略配置与说明' > public/strategies/index.md
ls public/strategies >/tmp/strategies_list_local.txt
while IFS= read -r f; do
  [ "$f" = "index.md" ] && continue
  printf -- '- [%s](./%s)\n' "$f" "$f" >> public/strategies/index.md
done < /tmp/strategies_list_local.txt

printf '%s\n' '# 统计报告列表' > public/reports/index.md
ls public/reports >/tmp/reports_list_local.txt
while IFS= read -r f; do
  [ "$f" = "index.md" ] && continue
  printf -- '- [%s](./%s)\n' "$f" "$f" >> public/reports/index.md
done < /tmp/reports_list_local.txt

if [ -f reports/trades/index.md ]; then
  cp reports/trades/index.md public/trades/index.md
else
  printf '%s\n' '# 买卖记录列表' > public/trades/index.md
  ls public/trades >/tmp/trades_list_local.txt
  while IFS= read -r f; do
    [ "$f" = "index.md" ] && continue
    printf -- '- [%s](./%s)\n' "$f" "$f" >> public/trades/index.md
  done < /tmp/trades_list_local.txt
fi

COMMIT_ID=$(git rev-parse --short HEAD)
cat > public/index.html <<EOF
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>量化统计结果 v0.1</title>
  <style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:840px;margin:2rem auto;padding:0 1rem;line-height:1.6}.card{border:1px solid #e5e7eb;border-radius:10px;padding:1rem 1.2rem;margin-top:1rem}.commit-id{position:absolute;top:1rem;right:1rem;font-size:0.75rem;color:#6b7280;font-family:monospace}</style>
</head>
<body style="position:relative">
  <div class="commit-id">commit: ${COMMIT_ID}</div>
  <h1>量化统计结果（v0.1）</h1>
  <div class="card"><a href="./latest.html">最新统计</a></div>
  <div class="card"><a href="./hot_rank_top100_explorer.html">热度个股前100历史筛选</a></div>
  <div class="card"><a href="./reports/index.html">统计报告列表</a></div>
  <div class="card"><a href="./trades/index.html">买卖记录列表</a></div>
  <div class="card"><a href="./strategies/index.html">策略配置与说明</a></div>
  <div class="card"><a href="./README.html">项目说明（README）</a></div>
</body>
</html>
EOF

python3 - <<'PY'
import re
from pathlib import Path
import markdown

template = '''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
    a {{ color: #0969da; }}
    pre {{ background: #f6f8fa; padding: 1rem; overflow-x: auto; border-radius: 6px; }}
    code {{ background: #f6f8fa; padding: 0.2em 0.4em; border-radius: 3px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; text-align: left; }}
    th {{ background: #f6f8fa; }}
    h1, h2, h3 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 0.3em; }}
  </style>
</head>
<body>
{content}
</body>
</html>'''

md = markdown.Markdown(extensions=['tables', 'fenced_code'])
for mdfile in Path('public').rglob('*.md'):
    text = mdfile.read_text(encoding='utf-8')
    text = re.sub(r'\]\(([^)]+)\.md\)', r'](\1.html)', text)
    html = md.convert(text)
    md.reset()
    mdfile.with_suffix('.html').write_text(template.format(title=mdfile.stem, content=html), encoding='utf-8')
    mdfile.unlink()
print('local pages build completed -> public/')
PY

printf '%s\n' "done: public/index.html"
