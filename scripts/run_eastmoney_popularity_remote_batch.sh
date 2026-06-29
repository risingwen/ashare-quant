#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/data/quant_research}"
PYTHON="${PYTHON:-/data/quant_research_venv/bin/python}"
DB_PATH="${DB_PATH:-${PROJECT_ROOT}/data/quant.db}"
REMOTE_HOST="${REMOTE_HOST:-aws}"
REMOTE_PYTHON="${REMOTE_PYTHON:-python3}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/eastmoney_popularity_fetch}"
START_DATE="${START_DATE:-2025-06-27}"
END_DATE="${END_DATE:-2026-06-26}"
SOURCE="${SOURCE:-eastmoney_hot_rank_detail_em_all}"
RANK_LIMIT="${RANK_LIMIT:-10000}"
BATCH_SIZE="${BATCH_SIZE:-50}"
SLEEP_SECONDS="${SLEEP_SECONDS:-3}"
RETRIES="${RETRIES:-2}"
TIMEOUT="${TIMEOUT:-20}"
LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOCAL_WORK_DIR="/tmp/eastmoney_remote_${REMOTE_HOST}_${RUN_ID}"
LOG_FILE="${LOG_DIR}/eastmoney_popularity_remote_${REMOTE_HOST}_${RUN_ID}.log"

mkdir -p "${LOG_DIR}" "${LOCAL_WORK_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "run_id=${RUN_ID}"
echo "remote=${REMOTE_HOST} source=${SOURCE} range=${START_DATE}..${END_DATE} batch=${BATCH_SIZE}"

cd "${PROJECT_ROOT}"

sqlite3 "${DB_PATH}" "
CREATE TABLE IF NOT EXISTS popularity_backfill_progress (
  source TEXT NOT NULL,
  code TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  rank_limit INTEGER NOT NULL,
  status TEXT NOT NULL,
  rows INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (source, code, start_date, end_date, rank_limit)
);
"

CODES_FILE="${LOCAL_WORK_DIR}/codes.csv"
DATES_FILE="${LOCAL_WORK_DIR}/dates.txt"
sqlite3 -header -csv "${DB_PATH}" "
WITH active AS (
  SELECT code
  FROM popularity_backfill_progress
  WHERE source='${SOURCE}'
    AND start_date='${START_DATE}'
    AND end_date='${END_DATE}'
    AND rank_limit=${RANK_LIMIT}
    AND (
      status='ok'
      OR (status='running' AND datetime(updated_at) >= datetime('now', 'localtime', '-12 hours'))
    )
)
SELECT s.code, s.name
FROM stocks s
LEFT JOIN active a ON a.code = s.code
WHERE a.code IS NULL
ORDER BY s.code
LIMIT ${BATCH_SIZE};
" > "${CODES_FILE}"

CODE_COUNT="$(( $(wc -l < "${CODES_FILE}" | tr -d ' ') - 1 ))"
if (( CODE_COUNT <= 0 )); then
  echo "nothing to do"
  exit 0
fi
echo "selected_codes=${CODE_COUNT}"
tail -n +2 "${CODES_FILE}" | cut -d, -f1 | head -10

while IFS=, read -r code _; do
  [[ -z "${code}" ]] && continue
  sqlite3 "${DB_PATH}" "
  INSERT INTO popularity_backfill_progress(
    source, code, start_date, end_date, rank_limit, status, rows, error, updated_at
  )
  VALUES ('${SOURCE}', '${code}', '${START_DATE}', '${END_DATE}', ${RANK_LIMIT}, 'running', 0, NULL, datetime('now', 'localtime'))
  ON CONFLICT(source, code, start_date, end_date, rank_limit)
  DO UPDATE SET status='running', rows=0, error=NULL, updated_at=datetime('now', 'localtime');
  "
done < <(tail -n +2 "${CODES_FILE}")

sqlite3 -noheader "${DB_PATH}" "
SELECT DISTINCT date
FROM daily_bars
WHERE date BETWEEN '${START_DATE}' AND '${END_DATE}'
ORDER BY date;
" > "${DATES_FILE}"

ssh "${REMOTE_HOST}" "bash -lc 'mkdir -p ${REMOTE_DIR}'"
scp -q "${PROJECT_ROOT}/scripts/fetch_eastmoney_popularity_csv.py" "${REMOTE_HOST}:${REMOTE_DIR}/fetch_eastmoney_popularity_csv.py"
scp -q "${CODES_FILE}" "${REMOTE_HOST}:${REMOTE_DIR}/codes_${RUN_ID}.csv"
scp -q "${DATES_FILE}" "${REMOTE_HOST}:${REMOTE_DIR}/dates_${RUN_ID}.txt"

REMOTE_OUT="${REMOTE_DIR}/eastmoney_${RUN_ID}.csv"
REMOTE_PROGRESS="${REMOTE_DIR}/eastmoney_${RUN_ID}.progress.csv"
set +e
ssh "${REMOTE_HOST}" "bash -lc 'cd ${REMOTE_DIR} && ${REMOTE_PYTHON} fetch_eastmoney_popularity_csv.py --codes-file codes_${RUN_ID}.csv --dates-file dates_${RUN_ID}.txt --start-date ${START_DATE} --end-date ${END_DATE} --source ${SOURCE} --rank-limit ${RANK_LIMIT} --sleep ${SLEEP_SECONDS} --retries ${RETRIES} --timeout ${TIMEOUT} --output ${REMOTE_OUT} --progress-output ${REMOTE_PROGRESS}'"
REMOTE_RC=$?
set -e
echo "remote_rc=${REMOTE_RC}"

LOCAL_OUT="${LOCAL_WORK_DIR}/eastmoney_${RUN_ID}.csv"
LOCAL_PROGRESS="${LOCAL_WORK_DIR}/eastmoney_${RUN_ID}.progress.csv"
scp -q "${REMOTE_HOST}:${REMOTE_OUT}" "${LOCAL_OUT}" || true
scp -q "${REMOTE_HOST}:${REMOTE_PROGRESS}" "${LOCAL_PROGRESS}" || true

if [[ -s "${LOCAL_OUT}" ]]; then
  "${PYTHON}" "${PROJECT_ROOT}/scripts/import_popularity_rankings_csv.py" \
    --db "${DB_PATH}" \
    --stock-progress-csv "${LOCAL_PROGRESS}" \
    "${LOCAL_OUT}"
else
  echo "no output csv returned"
fi

sqlite3 "${DB_PATH}" "
SELECT source, COUNT(*) rows, COUNT(DISTINCT date) dates, COUNT(DISTINCT code) codes, MIN(date), MAX(date)
FROM popularity_rankings
WHERE source='${SOURCE}'
GROUP BY source;
SELECT status, COUNT(*) codes, SUM(rows) rows
FROM popularity_backfill_progress
WHERE source='${SOURCE}'
GROUP BY status;
"

exit "${REMOTE_RC}"
