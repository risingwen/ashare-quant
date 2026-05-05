#!/usr/bin/env bash
set -euo pipefail

for path in /data/quant_research/reports/latest/index.html /data/quant_research/reports/2026-04-30/index.html; do
  [ -f "$path" ] || continue
  sed -i '/index-responsive.css/d' "$path"
  sed -i '/<link rel=" stylesheet href=index-responsive.css>/d' "$path"
  sed -i '/<\/head>/i <link rel="stylesheet" href="index-responsive.css">' "$path"
done
