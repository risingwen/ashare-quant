#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/data/quant_research}"
VENV_PYTHON="${VENV_PYTHON:-/data/quant_research_venv/bin/python}"
DB_PATH="${DB_PATH:-/data/quant_research/data/quant.db}"
REPORT_DIR="${REPORT_DIR:-/data/quant_research/reports}"
SERVICE_SCRIPT="${SERVICE_SCRIPT:-/data/quant_research/logs/quant-daily-run.sh}"
START_DATE="${START_DATE:-2025-01-01}"
BRANCH="${BRANCH:-master}"
RESTART_API="${RESTART_API:-1}"
RUN_FULL_PIPELINE="${RUN_FULL_PIPELINE:-0}"
REFRESH_HOT_RANK_FALLBACK="${REFRESH_HOT_RANK_FALLBACK:-1}"

echo "========================================"
echo "deploy_oracle start: $(date '+%F %T')"
echo "REPO_DIR=${REPO_DIR}"
echo "BRANCH=${BRANCH}"
echo "SERVICE_SCRIPT=${SERVICE_SCRIPT}"
echo "RUN_FULL_PIPELINE=${RUN_FULL_PIPELINE}"
echo "RESTART_API=${RESTART_API}"
echo "REFRESH_HOT_RANK_FALLBACK=${REFRESH_HOT_RANK_FALLBACK}"
echo "========================================"

cd "${REPO_DIR}"

echo "[1/5] Fetch latest code"
git fetch origin
git pull --ff-only origin "${BRANCH}"
echo "HEAD=$(git rev-parse HEAD)"

echo "[2/6] Install systemd daily runner"
mkdir -p "$(dirname "${SERVICE_SCRIPT}")"
install -m 0755 deploy/scripts/quant-daily-run.sh "${SERVICE_SCRIPT}"
echo "SERVICE_SCRIPT_SHA=$(sha256sum "${SERVICE_SCRIPT}" | awk '{print $1}')"

if [[ "${RUN_FULL_PIPELINE}" == "1" ]]; then
  echo "[3/6] Start full quant-daily pipeline"
  sudo systemctl start quant-daily.service
  echo "Use: sudo journalctl -u quant-daily.service -f"
else
  if [[ "${REFRESH_HOT_RANK_FALLBACK}" == "1" ]]; then
    echo "[3/6] Refresh hot-rank fallback artifacts"
    "${VENV_PYTHON}" scripts/try_hot_rank_multi_source.py || true
    "${VENV_PYTHON}" scripts/export_hot_rank_multi_source_pages.py || true
  else
    echo "[3/6] Skip hot-rank fallback refresh"
  fi

  echo "[4/6] Regenerate reports and homepage assets"
  "${VENV_PYTHON}" src/generate_report.py \
    --db "${DB_PATH}" \
    --report-dir "${REPORT_DIR}" \
    --start-date "${START_DATE}"
fi

if [[ "${RESTART_API}" == "1" ]]; then
  echo "[5/6] Restart quant-api.service"
  sudo systemctl restart quant-api.service
  sudo systemctl is-active quant-api.service
else
  echo "[5/6] Skip API restart"
fi

echo "[6/6] Verify generated homepage/report files"
"${VENV_PYTHON}" - <<'PY'
from pathlib import Path
import json

report_dir = Path("/data/quant_research/reports/latest")
summary_path = report_dir / "summary.json"
index_path = report_dir / "index.html"
report_path = report_dir / "report.html"

summary = json.loads(summary_path.read_text(encoding="utf-8"))
index_text = index_path.read_text(encoding="utf-8")
report_text = report_path.read_text(encoding="utf-8")

print(f"latest_date={summary.get('latest_date')}")
print(f"data_status_entries={len(summary.get('data_status', []))}")
print(f"index_has_data_status={('数据更新情况' in index_text)}")
print(f"report_has_data_status={('数据更新状态' in report_text)}")
PY

echo "[post] Suggested remote checks"
echo "curl http://140.245.53.52:8080/api/health"
echo "curl http://140.245.53.52:8080/index.html?v=$(date +%s)"
echo "curl http://140.245.53.52:8080/report.html?v=$(date +%s)"

echo "deploy_oracle done: $(date '+%F %T')"
