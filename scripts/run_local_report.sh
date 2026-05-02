#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 src/build_sqlite_from_csv.py --csv-dir /data/akshare/Akshare/stock_data --db data/quant.db --reset
python3 src/backtest_new_high_volume.py --db data/quant.db --report-dir reports/backtests --start-date 2022-01-01
python3 src/generate_report.py --db data/quant.db --report-dir reports --start-date 2023-01-01
