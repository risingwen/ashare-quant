#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/data/quant_research}"
PYTHON="${PYTHON:-/data/quant_research_venv/bin/python}"
DB_PATH="${DB_PATH:-${PROJECT_ROOT}/data/quant.db}"
REMOTE_HOST="${REMOTE_HOST:-huawei}"
REMOTE_PYTHON="${REMOTE_PYTHON:-/tmp/hot_rank_venv/bin/python}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/hot_rank_fetch}"
START_DATE="${START_DATE:-2025-06-27}"
END_DATE="${END_DATE:-2026-06-26}"
RANK_LIMIT="${RANK_LIMIT:-100}"
BATCH_SIZE="${BATCH_SIZE:-10}"
SLEEP_SECONDS="${SLEEP_SECONDS:-8}"
RETRIES="${RETRIES:-2}"
MIN_ROWS="${MIN_ROWS:-80}"
LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOCAL_WORK_DIR="/tmp/hot_rank_remote_${RUN_ID}"
LOG_FILE="${LOG_DIR}/ths_popularity_remote_${RUN_ID}.log"

mkdir -p "${LOG_DIR}" "${LOCAL_WORK_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "run_id=${RUN_ID}"
echo "remote=${REMOTE_HOST} range=${START_DATE}..${END_DATE} batch=${BATCH_SIZE} sleep=${SLEEP_SECONDS}"

cd "${PROJECT_ROOT}"

MISSING_FILE="${LOCAL_WORK_DIR}/missing_dates.txt"
DATES_FILE="${LOCAL_WORK_DIR}/dates.txt"
sqlite3 -noheader "${DB_PATH}" "
WITH trading AS (
  SELECT DISTINCT date
  FROM daily_bars
  WHERE date BETWEEN '${START_DATE}' AND '${END_DATE}'
),
done AS (
  SELECT date, COUNT(*) rows
  FROM popularity_rankings
  WHERE source='ths_pywencai_hot_rank'
  GROUP BY date
  HAVING rows >= ${MIN_ROWS}
)
SELECT trading.date
FROM trading
LEFT JOIN done USING(date)
WHERE done.date IS NULL
ORDER BY trading.date DESC;
" > "${MISSING_FILE}"

MISSING_COUNT="$(wc -l < "${MISSING_FILE}" | tr -d ' ')"
echo "missing_dates=${MISSING_COUNT}"
if [[ "${MISSING_COUNT}" == "0" ]]; then
  echo "nothing to do"
  exit 0
fi

head -n "${BATCH_SIZE}" "${MISSING_FILE}" > "${DATES_FILE}"
echo "batch_dates:"
cat "${DATES_FILE}"

ssh "${REMOTE_HOST}" "bash -lc 'mkdir -p ${REMOTE_DIR}'"
scp -q "${PROJECT_ROOT}/scripts/fetch_ths_popularity_csv.py" "${REMOTE_HOST}:${REMOTE_DIR}/fetch_ths_popularity_csv.py"
scp -q "${DATES_FILE}" "${REMOTE_HOST}:${REMOTE_DIR}/dates_${RUN_ID}.txt"

REMOTE_OUT="${REMOTE_DIR}/ths_${RUN_ID}.csv"
REMOTE_FAILED="${REMOTE_DIR}/ths_${RUN_ID}.failed.csv"
set +e
ssh "${REMOTE_HOST}" "bash -lc 'cd ${REMOTE_DIR} && NODE_NO_WARNINGS=1 ${REMOTE_PYTHON} fetch_ths_popularity_csv.py --dates-file dates_${RUN_ID}.txt --rank-limit ${RANK_LIMIT} --sleep ${SLEEP_SECONDS} --retries ${RETRIES} --min-rows ${MIN_ROWS} --output ${REMOTE_OUT} --failed-output ${REMOTE_FAILED}'"
REMOTE_RC=$?
set -e
echo "remote_rc=${REMOTE_RC}"

LOCAL_OUT="${LOCAL_WORK_DIR}/ths_${RUN_ID}.csv"
LOCAL_FAILED="${LOCAL_WORK_DIR}/ths_${RUN_ID}.failed.csv"
scp -q "${REMOTE_HOST}:${REMOTE_OUT}" "${LOCAL_OUT}" || true
scp -q "${REMOTE_HOST}:${REMOTE_FAILED}" "${LOCAL_FAILED}" || true

if [[ -s "${LOCAL_OUT}" ]]; then
  "${PYTHON}" "${PROJECT_ROOT}/scripts/import_popularity_rankings_csv.py" \
    --db "${DB_PATH}" \
    --mark-date-progress \
    --rank-limit "${RANK_LIMIT}" \
    "${LOCAL_OUT}"
else
  echo "no output csv returned"
fi

echo "failed_rows:"
cat "${LOCAL_FAILED}" 2>/dev/null || true

sqlite3 "${DB_PATH}" "
SELECT 'coverage', COUNT(DISTINCT p.date), (SELECT COUNT(DISTINCT date) FROM daily_bars WHERE date BETWEEN '${START_DATE}' AND '${END_DATE}')
FROM popularity_rankings p
WHERE p.source='ths_pywencai_hot_rank'
  AND p.date BETWEEN '${START_DATE}' AND '${END_DATE}'
  AND p.date IN (SELECT date FROM daily_bars WHERE date BETWEEN '${START_DATE}' AND '${END_DATE}')
GROUP BY p.source;
SELECT source, COUNT(*) rows, COUNT(DISTINCT date) dates, MIN(date), MAX(date)
FROM popularity_rankings
WHERE source='ths_pywencai_hot_rank'
GROUP BY source;
"

exit 0
