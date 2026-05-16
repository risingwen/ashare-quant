#!/usr/bin/env python3
"""
Script name: export_trimmed_oracle_db.py

Export a trimmed SQLite development database from the Oracle host
and copy it into the local repository data directory.

Usage:
    python scripts/export_trimmed_oracle_db.py
    python scripts/export_trimmed_oracle_db.py --start-date 2026-01-01
    python scripts/export_trimmed_oracle_db.py --output data/quant_dev.db
"""

import argparse
import logging
import shlex
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "quant_dev.db"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_remote_sql(start_date: str) -> str:
    return f"""
ATTACH '/tmp/quant_dev.db' AS dev;
CREATE TABLE dev.stocks AS SELECT * FROM stocks;
CREATE TABLE dev.daily_bars AS SELECT * FROM daily_bars WHERE date >= '{start_date}';
CREATE TABLE dev.market_daily AS SELECT * FROM market_daily WHERE date >= '{start_date}';
CREATE TABLE dev.zt_pool AS SELECT * FROM zt_pool WHERE date >= '{start_date}';
CREATE TABLE dev.lhb_records AS SELECT * FROM lhb_records WHERE date >= '{start_date}';
DETACH dev;
""".strip()


def run_command(command: list[str]) -> None:
    logger.info("Running command: %s", " ".join(shlex.quote(part) for part in command))
    subprocess.run(command, check=True)


def export_remote_db(host: str, remote_db_path: str, start_date: str) -> None:
    sql = build_remote_sql(start_date)
    remote_script = (
        "set -euo pipefail; "
        "rm -f /tmp/quant_dev.db; "
        f"sqlite3 {shlex.quote(remote_db_path)} <<'SQL'\n{sql}\nSQL\n"
        "ls -lh /tmp/quant_dev.db"
    )
    run_command(["ssh", host, f"/bin/bash -lc {shlex.quote(remote_script)}"])


def copy_remote_db(host: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(["scp", f"{host}:/tmp/quant_dev.db", str(output_path)])
    logger.info("Local trimmed database ready: %s", output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a trimmed SQLite development database from Oracle host",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/export_trimmed_oracle_db.py
  python scripts/export_trimmed_oracle_db.py --start-date 2026-01-01
  python scripts/export_trimmed_oracle_db.py --host oracle-free --output data/quant_dev.db
        """,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="oracle-free",
        help="SSH host alias or user@host target (default: oracle-free)",
    )
    parser.add_argument(
        "--remote-db-path",
        type=str,
        default="/data/quant_research/data/quant.db",
        help="Remote SQLite database path on Oracle host",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2026-01-01",
        help="Trim lower bound date in YYYY-MM-DD format (default: 2026-01-01)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Local output SQLite path (default: data/quant_dev.db)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    logger.info("Exporting trimmed database from host: %s", args.host)
    logger.info("Remote database path: %s", args.remote_db_path)
    logger.info("Start date filter: %s", args.start_date)
    logger.info("Local output path: %s", args.output)

    export_remote_db(args.host, args.remote_db_path, args.start_date)
    copy_remote_db(args.host, args.output)

    logger.info("Trimmed database export completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
