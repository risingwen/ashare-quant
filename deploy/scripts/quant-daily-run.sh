#!/usr/bin/env bash
set -euo pipefail

cd /data/quant_research

LOG_DIR="/data/quant_research/logs"
LOG_FILE="${LOG_DIR}/daily-run-$(date +%Y%m%d).log"

exec > >(tee -a "$LOG_FILE") 2>&1
export PYTHONUNBUFFERED=1

echo "========================================"
echo "quant-daily-run start: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

run_step() {
    local step_name="$1"
    shift
    echo ""
    echo "--- [$(date '+%H:%M:%S')] START: ${step_name} ---"
    if "$@"; then
        echo "--- [$(date '+%H:%M:%S')] OK:    ${step_name} ---"
    else
        echo "--- [$(date '+%H:%M:%S')] FAIL:  ${step_name} (exit $?) ---"
        return 0
    fi
}

PYTHON=/data/quant_research_venv/bin/python
DB=/data/quant_research/data/quant.db

run_step "update_sqlite_data" \
    "$PYTHON" -u src/update_sqlite_data.py \
        --db "$DB" \
        --daily-source mootdx \
        --workers 8

run_step "update_etf" \
    "$PYTHON" -u src/update_etf.py \
        --db "$DB" \
        --min-amount 5000 \
        --holdings-only \
        --max-holdings 100 \
        --holdings-workers 4 \
        --socket-timeout 15

run_step "update_shares" \
    "$PYTHON" -u src/update_shares.py \
        --db "$DB"

run_step "screener" \
    "$PYTHON" -u src/screener.py \
        --db "$DB"

run_step "backtest_new_high_volume" \
    "$PYTHON" -u src/backtest_new_high_volume.py \
        --db "$DB" \
        --report-dir /data/quant_research/reports/backtests \
        --start-date 2025-01-01

run_step "generate_report" \
    "$PYTHON" -u src/generate_report.py \
        --db "$DB" \
        --report-dir /data/quant_research/reports \
        --start-date 2025-01-01

echo ""
echo "========================================"
echo "quant-daily-run end:   $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

find "$LOG_DIR" -name "daily-run-*.log" -mtime +30 -delete
