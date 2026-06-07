#!/usr/bin/env bash
set -euo pipefail

cd /data/quant_research

LOG_DIR="/data/quant_research/logs"
LOG_FILE="${LOG_DIR}/daily-run-$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1
export PYTHONUNBUFFERED=1

echo "========================================"
echo "quant-daily-run start: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

run_step() {
    local step_name="$1"
    shift
    local rc=0
    echo ""
    echo "--- [$(date '+%H:%M:%S')] START: ${step_name} ---"
    if "$@"; then
        echo "--- [$(date '+%H:%M:%S')] OK:    ${step_name} ---"
    else
        rc=$?
        echo "--- [$(date '+%H:%M:%S')] FAIL:  ${step_name} (exit ${rc}) ---"
        return "$rc"
    fi
}

PYTHON=/data/quant_research_venv/bin/python
DB=/data/quant_research/data/quant.db

run_step "update_sqlite_data" \
    "$PYTHON" -u src/update_sqlite_data.py \
        --db "$DB" \
        --daily-source mootdx \
        --socket-timeout 20 \
        --workers 8 \
        --stock-batch-size 500 \
        --date-chunk-days 30

run_step "update_etf" \
    "$PYTHON" -u src/update_etf.py \
        --db "$DB" \
        --min-amount 5000 \
        --spot-only \
        --skip-holdings \
        --socket-timeout 15

run_step "update_shares" \
    "$PYTHON" -u src/update_shares.py \
        --db "$DB"

run_step "update_zt_pool" \
    "$PYTHON" -u src/update_zt_pool.py \
        --db "$DB"

run_step "health_check" \
    "$PYTHON" -u src/health_check.py \
        --db "$DB" \
        --lookback-days 20 \
        --socket-timeout 20

run_step "audit_data_completeness" \
    "$PYTHON" -u src/audit_data_completeness.py \
        --db "$DB" \
        --lookback-days 20 \
        --record-issues \
        --socket-timeout 20

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
